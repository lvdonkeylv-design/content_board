# -*- coding: utf-8 -*-
"""
docx_to_clipboard.py
====================
将 docx 文件转换为剪贴板数据文件夹，格式与 save_clipboard.py 输出完全兼容，
可直接由 restore_clipboard.py 恢复。

Usage:
    python docx_to_clipboard.py <docx_file> [output_dir]

如果不指定 output_dir，默认生成 content_{yyyyMMdd} 文件夹（与 docx 同目录）。
"""

import os
import sys
import json
import zipfile
import struct
import html as html_mod
from datetime import datetime
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# docx XML namespace
# ---------------------------------------------------------------------------
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


# ---------------------------------------------------------------------------
# Step 1: Parse docx → structured paragraphs
# ---------------------------------------------------------------------------
def parse_docx(docx_path):
    """Parse a docx file and return a list of paragraph dicts."""
    with zipfile.ZipFile(docx_path, "r") as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)

    root = tree.getroot()
    body = root.find(".//w:body", NS)
    paragraphs = []

    for p in body.findall(".//w:p", NS):
        # --- paragraph-level properties ---
        pPr = p.find("w:pPr", NS)
        p_style = ""
        p_jc = ""
        if pPr is not None:
            pStyle_el = pPr.find("w:pStyle", NS)
            if pStyle_el is not None:
                p_style = pStyle_el.get(f"{{{W_NS}}}val", "")
            jc_el = pPr.find("w:jc", NS)
            if jc_el is not None:
                p_jc = jc_el.get(f"{{{W_NS}}}val", "")

        # --- extract runs ---
        runs = []
        all_bold = True
        has_runs = False
        for r in p.findall(".//w:r", NS):
            rPr = r.find("w:rPr", NS)
            r_bold = False
            r_sz = None
            r_color = None
            if rPr is not None:
                b_el = rPr.find("w:b", NS)
                if b_el is not None:
                    val = b_el.get(f"{{{W_NS}}}val", None)
                    # w:b with no val attribute or val="true"/"1" → bold
                    r_bold = val is None or val in ("true", "1", "")
                else:
                    r_bold = False
                sz_el = rPr.find("w:sz", NS)
                if sz_el is not None:
                    r_sz = sz_el.get(f"{{{W_NS}}}val", None)
                color_el = rPr.find("w:color", NS)
                if color_el is not None:
                    r_color = color_el.get(f"{{{W_NS}}}val", None)

            texts = []
            for t in r.findall("w:t", NS):
                if t.text:
                    texts.append(t.text)
            run_text = "".join(texts)

            if run_text or r.findall("w:br", NS):
                has_runs = True
                if not r_bold:
                    all_bold = False

            runs.append({
                "text": run_text,
                "bold": r_bold,
                "size_half_pt": r_sz,  # half-points string, e.g. "28"
                "color": r_color,
                "has_break": bool(r.findall("w:br", NS)),
            })

        full_text = "".join(r["text"] for r in runs)

        # Determine size from runs
        sizes = set()
        for r in runs:
            if r["size_half_pt"]:
                sizes.add(r["size_half_pt"])

        paragraphs.append({
            "text": full_text,
            "runs": runs,
            "style": p_style,
            "jc": p_jc,
            "all_bold": all_bold and has_runs,
            "sizes_half_pt": sizes,
        })

    return paragraphs


# ---------------------------------------------------------------------------
# Step 2: Classify paragraphs → type (title / heading / body / empty)
# ---------------------------------------------------------------------------
def classify_paragraphs(paragraphs):
    """
    Classify each paragraph as: title, heading, body, or empty.
    Rules (designed to match the docx → Xiumi mapping):
      - First bold paragraph with largest font → title
      - Bold paragraphs with subheading-sized font (or shorter text + bold) → heading
      - Empty paragraphs → empty
      - Everything else → body
    """
    # Find the maximum font size (title candidate)
    max_size = 0
    for p in paragraphs:
        for s in p["sizes_half_pt"]:
            try:
                max_size = max(max_size, int(s))
            except ValueError:
                pass

    title_found = False
    for p in paragraphs:
        text = p["text"].strip()
        if not text:
            p["type"] = "empty"
            continue

        is_bold = p["all_bold"]
        has_large_font = any(
            int(s) >= max_size for s in p["sizes_half_pt"] if s
        ) if p["sizes_half_pt"] else False
        has_heading_font = any(
            int(s) >= 24 for s in p["sizes_half_pt"] if s
        ) if p["sizes_half_pt"] else False

        if is_bold and has_large_font and not title_found:
            p["type"] = "title"
            title_found = True
        elif is_bold and has_heading_font:
            p["type"] = "heading"
        elif is_bold and not title_found and len(text) < 40:
            # Short bold text before any title → treat as title
            p["type"] = "title"
            title_found = True
        elif is_bold and len(text) < 30:
            # Short bold text → heading
            p["type"] = "heading"
        else:
            p["type"] = "body"

    return paragraphs


# ---------------------------------------------------------------------------
# Step 3: Build config.json (editable) and HTML
# ---------------------------------------------------------------------------
def build_config(paragraphs):
    """
    Build a config list where each entry is editable.
    Users can modify: text, type, html_override.
    """
    config = []
    for i, p in enumerate(paragraphs):
        entry = {
            "index": i,
            "type": p["type"],
            "text": p["text"],
            "html_override": "",  # if set, this HTML replaces auto-generated HTML
        }
        if p["type"] == "body":
            # Preserve per-run formatting info for body paragraphs
            entry["runs"] = [
                {
                    "text": r["text"],
                    "bold": r["bold"],
                }
                for r in p["runs"]
                if r["text"] or r.get("has_break")
            ]
        config.append(entry)
    return config


# --- Xiumi-style HTML generators ---

def _escape(text):
    """HTML-escape text."""
    return html_mod.escape(text)


def html_title(text):
    return (
        '<section style="text-align: center; margin-top: 10px; margin-bottom: 10px; '
        'box-sizing: border-box;">'
        '<p style="margin: 0px; padding: 0px; box-sizing: border-box; '
        f'font-size: 24px; font-weight: bold;">{_escape(text)}</p>'
        '</section>'
    )


def html_heading(text):
    return (
        '<section style="text-align: center; margin-top: 10px; margin-bottom: 10px; '
        'box-sizing: border-box;">'
        '<p style="margin: 0px; padding: 0px; box-sizing: border-box; '
        f'font-size: 18px; font-weight: bold;">{_escape(text)}</p>'
        '</section>'
    )


def html_body(paragraph_entry):
    """Generate HTML for a body paragraph, preserving per-run bold."""
    runs = paragraph_entry.get("runs", [])
    if not runs:
        # Fallback: plain text
        return (
            '<section style="box-sizing: border-box;">'
            '<p style="white-space: normal; margin: 0px; padding: 0px; '
            f'box-sizing: border-box; font-size: 16px;">{_escape(paragraph_entry["text"])}</p>'
            '</section>'
        )

    inner = ""
    for r in runs:
        if r.get("has_break") and not r["text"]:
            inner += '<br style="box-sizing: border-box;">'
        elif r["bold"]:
            inner += f'<strong style="box-sizing: border-box;">{_escape(r["text"])}</strong>'
        else:
            inner += _escape(r["text"])

    return (
        '<section style="box-sizing: border-box;">'
        '<p style="white-space: normal; margin: 0px; padding: 0px; '
        f'box-sizing: border-box; font-size: 16px;">{inner}</p>'
        '</section>'
    )


def html_empty():
    return (
        '<section style="box-sizing: border-box;">'
        '<p style="white-space: normal; margin: 0px; padding: 0px; '
        'box-sizing: border-box;"><br style="box-sizing: border-box;"></p>'
        '</section>'
    )


def generate_html_from_config(config):
    """Generate the full HTML fragment from config entries."""
    parts = []
    for entry in config:
        # If user provided html_override, use it directly
        if entry.get("html_override", "").strip():
            parts.append(entry["html_override"])
            continue

        ptype = entry["type"]
        if ptype == "title":
            parts.append(html_title(entry["text"]))
        elif ptype == "heading":
            parts.append(html_heading(entry["text"]))
        elif ptype == "empty":
            parts.append(html_empty())
        else:  # body
            parts.append(html_body(entry))

    # Wrap in the Xiumi-style outer section
    outer_style = (
        "padding: 0px 30px; box-sizing: border-box; "
        "font-style: normal; font-weight: 400; text-align: justify; "
        "font-size: 16px; color: rgb(62, 62, 62);"
    )
    fragment = f'<section style="{outer_style}">' + "".join(parts) + "</section>"
    return fragment


# ---------------------------------------------------------------------------
# Step 4: Build Windows Clipboard HTML Format binary
# ---------------------------------------------------------------------------
def build_clipboard_html(fragment_html):
    """
    Wrap an HTML fragment in the Windows clipboard HTML format:
      Version:0.9
      StartHTML:xxxxxxxxxx
      EndHTML:xxxxxxxxxx
      StartFragment:xxxxxxxxxx
      EndFragment:xxxxxxxxxx
      <html><body>
      <!--StartFragment-->...fragment...<!--EndFragment-->
      </body></html>
    """
    prefix = "<html>\r\n<body>\r\n<!--StartFragment-->"
    suffix = "<!--EndFragment-->\r\n</body>\r\n</html>"

    # We'll build a template header, then calculate offsets
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_frag:010d}\r\n"
        "EndFragment:{end_frag:010d}\r\n"
    )

    # First pass: estimate header size
    dummy_header = header_template.format(
        start_html=0, end_html=0, start_frag=0, end_frag=0
    )
    header_len = len(dummy_header.encode("utf-8"))

    start_html = header_len
    start_frag = start_html + len(prefix.encode("utf-8"))
    frag_bytes = fragment_html.encode("utf-8")
    end_frag = start_frag + len(frag_bytes)
    end_html = end_frag + len(suffix.encode("utf-8"))

    # Second pass: build real header (size might differ due to digit count)
    real_header = header_template.format(
        start_html=start_html,
        end_html=end_html,
        start_frag=start_frag,
        end_frag=end_frag,
    )
    real_header_bytes = real_header.encode("utf-8")

    # Recalculate if header length changed
    if len(real_header_bytes) != header_len:
        header_len = len(real_header_bytes)
        start_html = header_len
        start_frag = start_html + len(prefix.encode("utf-8"))
        end_frag = start_frag + len(frag_bytes)
        end_html = end_frag + len(suffix.encode("utf-8"))
        real_header = header_template.format(
            start_html=start_html,
            end_html=end_html,
            start_frag=start_frag,
            end_frag=end_frag,
        )
        real_header_bytes = real_header.encode("utf-8")

    return real_header_bytes + prefix.encode("utf-8") + frag_bytes + suffix.encode("utf-8")


# ---------------------------------------------------------------------------
# Step 5: Build all clipboard binary files
# ---------------------------------------------------------------------------
def build_clipboard_data(html_bin, plain_text, output_dir):
    """Write all .bin files and manifest.json."""
    os.makedirs(output_dir, exist_ok=True)
    manifest = []

    def save(fmt_id, fmt_name, data):
        safe = fmt_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        fname = f"{fmt_id:05d}_{safe}.bin"
        fpath = os.path.join(output_dir, fname)
        with open(fpath, "wb") as f:
            f.write(data)
        manifest.append({
            "format_id": fmt_id,
            "format_name": fmt_name,
            "file": fname,
            "size": len(data),
        })

    # 1) HTML Format
    save(49393, "HTML Format", html_bin)

    # 2) CF_UNICODETEXT  (UTF-16LE + null terminator)
    utext = plain_text.encode("utf-16-le") + b"\x00\x00"
    save(13, "CF_UNICODETEXT", utext)

    # 3) CF_LOCALE (2052 = zh-CN)
    save(16, "CF_LOCALE", struct.pack("<I", 2052))

    # 4) CF_TEXT (UTF-8 → then encode as ANSI/CP936 for Windows, fallback to UTF-8)
    try:
        ansi = plain_text.encode("cp936") + b"\x00"
    except UnicodeEncodeError:
        ansi = plain_text.encode("utf-8") + b"\x00"
    save(1, "CF_TEXT", ansi)

    # 5) CF_OEMTEXT (same as CF_TEXT for our purposes)
    save(7, "CF_OEMTEXT", ansi)

    # Write manifest
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return manifest


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def run(docx_path, output_dir=None):
    if not os.path.isfile(docx_path):
        print(f"[ERROR] File not found: {docx_path}")
        sys.exit(1)

    if output_dir is None:
        date_str = datetime.now().strftime("%Y%m%d")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, f"content_{date_str}")

    print(f"[INFO] Input docx:  {docx_path}")
    print(f"[INFO] Output dir:  {output_dir}")

    # 1) Parse
    paragraphs = parse_docx(docx_path)
    print(f"[INFO] Parsed {len(paragraphs)} paragraphs.")

    # 2) Classify
    paragraphs = classify_paragraphs(paragraphs)
    type_counts = {}
    for p in paragraphs:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1
    print(f"[INFO] Classification: {type_counts}")

    # 3) Build config
    config = build_config(paragraphs)

    # 4) Generate HTML
    fragment = generate_html_from_config(config)
    html_bin = build_clipboard_html(fragment)

    # 5) Build plain text (for CF_UNICODETEXT etc.)
    plain_text = "\r\n\r\n".join(
        p["text"] for p in paragraphs if p["text"].strip()
    )

    # 6) Write clipboard data
    manifest = build_clipboard_data(html_bin, plain_text, output_dir)

    # 7) Save config.json (for editing)
    config_path = os.path.join(output_dir, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n[DONE] Generated clipboard data with {len(manifest)} format(s).")
    print(f"       Config (editable): {config_path}")
    print(f"       Manifest:          {os.path.join(output_dir, 'manifest.json')}")
    print(f"\n       Next steps:")
    print(f"       1. Edit config.json to modify text/types/html_override")
    print(f"       2. Run: python regenerate.py \"{output_dir}\"")
    print(f"       3. Run: python restore_clipboard.py \"{output_dir}\"")

    return output_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python docx_to_clipboard.py <docx_file> [output_dir]")
        sys.exit(1)

    docx_file = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None
    run(docx_file, out_dir)
