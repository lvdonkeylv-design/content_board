# -*- coding: utf-8 -*-
"""
export_html.py
==============
将 clipboard_data 文件夹中的数据转换为一个结构清晰、段落分明、可直接手动
编辑的 HTML 文件。

生成的 HTML 文件：
  - 内容区域语义清晰，每个段落有明确标签包裹
  - CSS 样式在 <style> 中集中定义，便于修改
  - 剪贴板原始二进制数据以 base64 嵌入隐藏区域，保证无损还原
  - 可被 import_html.py 读取并写回 Windows 剪贴板

Usage:
    python export_html.py [clipboard_data_dir] [output.html]
"""

import os
import sys
import json
import base64
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Step 1: Load clipboard binary data
# ---------------------------------------------------------------------------
def load_clipboard_data(data_dir):
    """Load all clipboard formats from a data directory."""
    manifest_path = os.path.join(data_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"[ERROR] manifest.json not found in: {data_dir}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    formats = {}
    for entry in manifest:
        file_path = os.path.join(data_dir, entry["file"])
        if not os.path.isfile(file_path):
            print(f"  [WARN] Missing: {entry['file']}, skipping.")
            continue
        with open(file_path, "rb") as f:
            formats[entry["format_name"]] = {
                "format_id": entry["format_id"],
                "format_name": entry["format_name"],
                "raw": f.read(),
            }

    return formats


# ---------------------------------------------------------------------------
# Step 2: Parse the Windows Clipboard HTML Format
# ---------------------------------------------------------------------------
def parse_html_format(raw_bytes):
    """
    Parse Windows clipboard HTML Format binary.
    Returns (header_dict, full_html_string, fragment_string).
    """
    text = raw_bytes.decode("utf-8")
    header = {}
    header_end = 0
    for line in text.split("\r\n"):
        if ":" in line and line.split(":")[0].strip() in (
            "Version", "StartHTML", "EndHTML", "StartFragment", "EndFragment"
        ):
            key, val = line.split(":", 1)
            header[key.strip()] = val.strip()
            header_end = text.index(line) + len(line) + 2  # +2 for \r\n
        else:
            break

    # Extract fragment
    frag_start_marker = "<!--StartFragment-->"
    frag_end_marker = "<!--EndFragment-->"
    fs = text.find(frag_start_marker)
    fe = text.find(frag_end_marker)

    if fs >= 0 and fe >= 0:
        fragment = text[fs + len(frag_start_marker):fe]
    else:
        fragment = text[header_end:]

    return header, text, fragment


# ---------------------------------------------------------------------------
# Step 3: Format HTML for readability
# ---------------------------------------------------------------------------
def format_html_fragment(html_str):
    """
    Add newlines and indentation to make HTML readable and editable.
    Preserves all content exactly — only adds whitespace between tags.
    """
    # Tokenize: split on tag boundaries, keeping tags as separate tokens
    tokens = re.split(r'(<[^>]+>)', html_str)
    tokens = [t for t in tokens if t]  # remove empty strings

    # Self-closing / void elements
    void_tags = {"br", "img", "hr", "input", "meta", "link"}

    output = []
    indent = 0
    indent_str = "  "

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.startswith("</"):
            # Closing tag
            indent = max(0, indent - 1)
            output.append(indent_str * indent + token)
        elif token.startswith("<"):
            tag_name = re.match(r'<(\w+)', token)
            name = tag_name.group(1).lower() if tag_name else ""

            if name in void_tags or token.endswith("/>"):
                output.append(indent_str * indent + token)
            else:
                output.append(indent_str * indent + token)
                indent += 1
        else:
            # Text content — append to previous line if it's short
            text = token.strip()
            if text:
                if output and not output[-1].endswith("\n"):
                    # Check if previous was an opening tag
                    if output[-1].strip().startswith("<") and not output[-1].strip().startswith("</"):
                        output[-1] = output[-1] + text
                    else:
                        output.append(indent_str * indent + text)
                else:
                    output.append(indent_str * indent + text)

        i += 1

    return "\n".join(output)


# ---------------------------------------------------------------------------
# Step 3.5: Collapse recognized format patterns into single-line <p> tags
# ---------------------------------------------------------------------------
def collapse_patterns(html_str):
    """
    Collapse three recognized Xiumi format patterns into single-line <p> tags
    with semantic class names, making the HTML easier to read and edit.

    Patterns:
      1. Title (大标题): 24px bold heading
      2. Body Bold (正文加粗): 18px bold paragraph with green background
      3. Body (正文): 18px regular paragraph
      4. Empty line (空行): <br> separator
      5. Inline Highlight (内联高亮): green background + bold span
    """
    result = html_str

    # 1) Title: <section style="font-size: 24px; ..."> <p> <strong>TEXT</strong>
    #    (?:(?!</p>).)* ensures we don't cross </p> boundaries
    def _title_replace(m):
        text = m.group(1).strip()
        return f'<p class="title">{text}</p>'

    result = re.sub(
        r'<section\s+style="font-size:\s*24px;[^"]*">'
        r'\s*<p\s+style="[^"]*">\s*<strong\s+style="[^"]*">'
        r'((?:(?!</p>).)*)'
        r'</strong>\s*</p>\s*</section>',
        _title_replace, result, flags=re.DOTALL
    )

    # 2) Body Bold: <p> <span background-color><strong>TEXT</strong></span> </p>
    #    (MUST run before Body to avoid partial matches)
    #    (?:(?!</p>).)* ensures we don't cross </p> boundaries (mixed content)
    def _body_bold_replace(m):
        text = m.group(1).strip()
        return f'<p class="body-bold">{text}</p>'

    result = re.sub(
        r'<p\s+style="white-space:\s*normal;\s*margin:\s*0px;\s*padding:\s*0px;\s*box-sizing:\s*border-box;">'
        r'\s*<span\s+style="background-color:\s*rgb\(235,\s*252,\s*229\);[^"]*">'
        r'\s*<strong\s+style="[^"]*">'
        r'((?:(?!</p>).)*)'
        r'</strong>\s*</span>\s*</p>',
        _body_bold_replace, result, flags=re.DOTALL
    )

    # 3) Body: <p>TEXT</p>  (text only, no inner tags)
    def _body_replace(m):
        text = m.group(1).strip()
        return f'<p class="body">{text}</p>'

    result = re.sub(
        r'<p\s+style="white-space:\s*normal;\s*margin:\s*0px;\s*padding:\s*0px;\s*box-sizing:\s*border-box;">'
        r'([^<]+)'
        r'</p>',
        _body_replace, result
    )

    # 4) Empty line: <p><br></p>
    result = re.sub(
        r'<p\s+style="white-space:\s*normal;\s*margin:\s*0px;\s*padding:\s*0px;\s*box-sizing:\s*border-box;">'
        r'\s*<br\s+style="[^"]*">\s*'
        r'</p>',
        '<p class="empty-line"><br></p>',
        result
    )

    # 5) Inline Highlight: <span background-color><strong>TEXT</strong></span>
    #    (remaining after Body Bold has been collapsed)
    def _hl_replace(m):
        text = m.group(1).strip()
        return f'<span class="hl">{text}</span>'

    result = re.sub(
        r'<span\s+style="background-color:\s*rgb\(235,\s*252,\s*229\);[^"]*">'
        r'\s*<strong\s+style="[^"]*">'
        r'((?:(?!</span>).)*)'
        r'</strong>\s*</span>',
        _hl_replace, result, flags=re.DOTALL
    )

    return result


# ---------------------------------------------------------------------------
# Step 4: Extract plain text from HTML
# ---------------------------------------------------------------------------
def html_to_plain_text(html_fragment):
    """Convert HTML fragment to plain text (matching Xiumi clipboard format)."""
    text = html_fragment

    # Replace <br> with newline
    text = re.sub(r'<br\s*/?\s*>', '\n', text)

    # Add paragraph separator after block-level closing tags
    # Xiumi uses triple LF (\n\n\n) between paragraphs
    text = re.sub(r'</(?:p|section|div|h[1-6])>', '\n\n\n', text)

    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    # Clean up excessive newlines (keep max triple)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    text = text.strip()

    return text


# ---------------------------------------------------------------------------
# Step 5: Generate the export HTML document
# ---------------------------------------------------------------------------
def generate_export_html(formatted_fragment, plain_text, raw_formats, original_fragment=""):
    """
    Generate a well-structured, human-editable HTML document.

    Structure:
      <html>
        <head>
          <style>  — CSS for preview rendering  </style>
        </head>
        <body>
          <!-- ============ CONTENT AREA (editable) ============ -->
          <article id="clipboard-content">
            ... formatted Xiumi HTML fragment ...
          </article>

          <!-- ============ CLIPBOARD DATA (hidden) ============ -->
          <script id="cb-raw-data" type="application/json">
            ... base64 encoded binary data ...
          </script>
        </body>
      </html>
    """

    # Build raw data manifest
    raw_entries = []
    for name, info in raw_formats.items():
        raw_entries.append({
            "format_id": info["format_id"],
            "format_name": name,
            "size": len(info["raw"]),
            "data": base64.b64encode(info["raw"]).decode("ascii"),
        })

    raw_json = json.dumps({
        "version": 3,
        "source": "export_html.py",
        "original_fragment": original_fragment,
        "original_plain_text": plain_text,
        "formats": raw_entries,
    }, indent=2, ensure_ascii=False)

    # Escape text for plain-text preview
    preview_escaped = (plain_text
                       .replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))

    lines = []

    # --- Head ---
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="zh-CN">')
    lines.append("<head>")
    lines.append('  <meta charset="utf-8">')
    lines.append("  <title>Clipboard Content Export</title>")
    lines.append("  <style>")
    lines.append("    /* ===== 全局样式 (Global Styles) ===== */")
    lines.append("    body {")
    lines.append("      font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;")
    lines.append("      max-width: 820px;")
    lines.append("      margin: 40px auto;")
    lines.append("      padding: 0 24px;")
    lines.append("      background: #f7f7f7;")
    lines.append("      color: #333;")
    lines.append("    }")
    lines.append("")
    lines.append("    /* ===== 元信息栏 (Metadata Bar) ===== */")
    lines.append("    .meta-bar {")
    lines.append("      background: #fff;")
    lines.append("      border: 1px solid #e0e0e0;")
    lines.append("      border-radius: 8px;")
    lines.append("      padding: 16px 20px;")
    lines.append("      margin-bottom: 24px;")
    lines.append("      font-size: 13px;")
    lines.append("      color: #888;")
    lines.append("    }")
    lines.append("    .meta-bar h1 {")
    lines.append("      font-size: 18px;")
    lines.append("      color: #333;")
    lines.append("      margin: 0 0 8px 0;")
    lines.append("    }")
    lines.append("")
    lines.append("    /* ===== 内容区域 (Content Area) ===== */")
    lines.append("    #clipboard-content {")
    lines.append("      background: #fff;")
    lines.append("      border: 1px solid #e0e0e0;")
    lines.append("      border-radius: 8px;")
    lines.append("      padding: 24px;")
    lines.append("      margin-bottom: 24px;")
    lines.append("      overflow: hidden;")
    lines.append("    }")
    lines.append("")
    lines.append("    /* ===== 格式类型说明 (Format Classes) ===== */")
    lines.append("    /* class=\"title\"      — 大标题 (24px, 加粗, 居中) */")
    lines.append("    /* class=\"body\"       — 正文 (18px, 两端对齐) */")
    lines.append("    /* class=\"body-bold\"  — 正文加粗 (18px, 加粗, 绿色背景) */")
    lines.append("    /* class=\"empty-line\" — 空行分隔 */")
    lines.append("")
    lines.append("    .title {")
    lines.append("      font-size: 24px;")
    lines.append("      font-weight: bold;")
    lines.append("      text-align: center;")
    lines.append("      margin: 16px 0;")
    lines.append("    }")
    lines.append("    .body {")
    lines.append("      font-size: 18px;")
    lines.append("      line-height: 2;")
    lines.append("      letter-spacing: 1px;")
    lines.append("      text-align: justify;")
    lines.append("      margin: 4px 0;")
    lines.append("    }")
    lines.append("    .body-bold {")
    lines.append("      font-size: 18px;")
    lines.append("      line-height: 2;")
    lines.append("      letter-spacing: 1px;")
    lines.append("      font-weight: bold;")
    lines.append("      background-color: rgb(235, 252, 229);")
    lines.append("      text-align: justify;")
    lines.append("      margin: 4px 0;")
    lines.append("    }")
    lines.append("    .empty-line {")
    lines.append("      height: 1em;")
    lines.append("    }")
    lines.append("")
    lines.append("    /* ===== 纯文本预览 (Plain Text Preview) ===== */")
    lines.append("    #plain-text-preview {")
    lines.append("      background: #fafafa;")
    lines.append("      border: 1px solid #eee;")
    lines.append("      border-radius: 8px;")
    lines.append("      padding: 16px 20px;")
    lines.append("      margin-bottom: 24px;")
    lines.append("      font-size: 14px;")
    lines.append("      line-height: 1.8;")
    lines.append("      white-space: pre-wrap;")
    lines.append("      max-height: 400px;")
    lines.append("      overflow-y: auto;")
    lines.append("      color: #555;")
    lines.append("    }")
    lines.append("  </style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append("")

    # --- Metadata ---
    lines.append("<!-- ============ 元信息 (Metadata) ============ -->")
    lines.append('<div class="meta-bar">')
    lines.append("  <h1>Clipboard Content Export</h1>")
    lines.append('  <p>此文件由 <code>export_html.py</code> 生成。'
                 '编辑 <code>&lt;article id="clipboard-content"&gt;</code> '
                 "区域的内容后，运行 <code>import_html.py</code> 即可将修改后的内容写回剪贴板。</p>")

    format_list = ", ".join(
        f"{name} ({info['format_id']})" for name, info in raw_formats.items()
    )
    lines.append(f"  <p>包含格式: {format_list}</p>")
    lines.append("</div>")
    lines.append("")

    # --- Content Area (the main editable region) ---
    lines.append("<!-- ============================================================")
    lines.append("     内容区域 (CONTENT AREA) — 可直接编辑以下 HTML")
    lines.append("     编辑后运行 import_html.py 将内容写回剪贴板")
    lines.append("     ============================================================ -->")
    lines.append("")
    lines.append('<article id="clipboard-content">')
    lines.append("")
    lines.append(formatted_fragment)
    lines.append("")
    lines.append("</article>")
    lines.append("")

    # --- Plain Text Preview ---
    lines.append("<!-- ============ 纯文本预览 (Plain Text Preview) ============ -->")
    lines.append("<details>")
    lines.append("  <summary>纯文本预览 (点击展开)</summary>")
    lines.append('  <div id="plain-text-preview">')
    lines.append(f"    {preview_escaped}")
    lines.append("  </div>")
    lines.append("</details>")
    lines.append("")

    # --- Raw Clipboard Data (hidden) ---
    lines.append("<!-- ============================================================")
    lines.append("     剪贴板原始数据 (RAW CLIPBOARD DATA) — 请勿手动修改此区域")
    lines.append("     import_html.py 从此区域读取数据重建剪贴板")
    lines.append("     ============================================================ -->")
    lines.append("")
    lines.append('<script type="application/json" id="cb-raw-data" '
                 'style="display:none">')
    lines.append(raw_json)
    lines.append("</script>")
    lines.append("")
    lines.append("</body>")
    lines.append("</html>")

    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        data_dir = os.path.join(SCRIPT_DIR, "clipboard_data")
    else:
        data_dir = sys.argv[1]

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        output_path = os.path.join(SCRIPT_DIR, "clipboard_export.html")

    print(f"[INFO] Source:  {data_dir}")
    print(f"[INFO] Output: {output_path}")

    # 1) Load binary data
    formats = load_clipboard_data(data_dir)
    print(f"[INFO] Loaded {len(formats)} format(s): {list(formats.keys())}")

    # 2) Parse HTML Format
    if "HTML Format" in formats:
        header, full_html, fragment = parse_html_format(formats["HTML Format"]["raw"])
        print(f"[INFO] HTML fragment: {len(fragment):,} chars")
    else:
        fragment = "<p>(no HTML content)</p>"
        print("[WARN] No HTML Format found in clipboard data.")

    # 3) Format fragment for readability
    formatted = format_html_fragment(fragment)

    # 3.5) Collapse recognized patterns into single-line <p class="...">
    formatted = collapse_patterns(formatted)

    # 4) Extract plain text
    plain_text = html_to_plain_text(fragment)
    print(f"[INFO] Plain text: {len(plain_text):,} chars")

    # 5) Generate export HTML
    html_output = generate_export_html(formatted, plain_text, formats, fragment)

    # 6) Write
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_output)

    file_size = os.path.getsize(output_path)
    print(f"\n[DONE] Exported: {output_path} ({file_size:,} bytes)")
    print(f"       Restore: python import_html.py \"{output_path}\"")


if __name__ == "__main__":
    main()
