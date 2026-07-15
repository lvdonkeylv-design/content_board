# -*- coding: utf-8 -*-
"""
step4_upload_clipboard.py
=========================
流水线第 5 步：读取生成的 HTML，将正文内容写入 Windows 剪贴板。

输入：process/step3_json_to_html.html
输出：Windows 剪贴板（HTML Format + 纯文本 + 图片 base64 内嵌）

处理流程：
  1. 提取 <article id="clipboard-content"> 内容
  2. 展开 CSS 类（.title/.body/.hl/.empty-line）为内联样式
  3. 去除格式化空白
  4. 本地图片转 base64 data URI（支持微信公众号粘贴）
  5. 构建 Windows 剪贴板多格式数据并写入

可单独运行，也可通过 launch.py 串联执行。
"""

import os
import sys
import json
import base64
import re
import struct
import ctypes
import ctypes.wintypes as wt

from launch import DIR_NAME

# ---------------------------------------------------------------------------
# Windows API (64-bit safe)
# ---------------------------------------------------------------------------
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.OpenClipboard.restype    = wt.BOOL
user32.OpenClipboard.argtypes   = [wt.HWND]
user32.CloseClipboard.restype   = wt.BOOL
user32.CloseClipboard.argtypes  = []
user32.EmptyClipboard.restype   = wt.BOOL
user32.EmptyClipboard.argtypes  = []
user32.SetClipboardData.restype  = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
user32.RegisterClipboardFormatW.restype  = wt.UINT
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]

kernel32.GlobalAlloc.restype   = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes  = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype    = ctypes.c_void_p
kernel32.GlobalLock.argtypes   = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype  = wt.BOOL
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype    = ctypes.c_void_p
kernel32.GlobalFree.argtypes   = [ctypes.c_void_p]


def resolve_format_id(fmt_id, fmt_name):
    """Resolve a clipboard format ID at runtime."""
    if fmt_id <= 17:
        return fmt_id
    rid = user32.RegisterClipboardFormatW(fmt_name)
    if rid == 0:
        return fmt_id
    return rid


# ---------------------------------------------------------------------------
# Step 1: Parse the HTML file
# ---------------------------------------------------------------------------
def parse_html_file(html_path):
    """
    Parse the export HTML file.
    Returns:
      content_fragment: str  — HTML inside <article id="clipboard-content">
      raw_formats: list      — original binary formats from cb-raw-data
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # --- Extract content fragment ---
    pattern_content = (
        r'<article\s+id="clipboard-content"[^>]*>'
        r'(.*?)'
        r'</article>'
    )
    m = re.search(pattern_content, html, re.DOTALL)
    if not m:
        print("[ERROR] <article id=\"clipboard-content\"> not found.")
        sys.exit(1)
    content_fragment = m.group(1).strip()

    # --- Extract raw data manifest ---
    pattern_raw = (
        r'<script\s+type="application/json"\s+id="cb-raw-data"[^>]*>'
        r'(.*?)'
        r'</script>'
    )
    m = re.search(pattern_raw, html, re.DOTALL)
    raw_formats = []
    if m:
        raw_manifest = json.loads(m.group(1).strip())
        raw_formats = raw_manifest.get("formats", [])
    else:
        print("[WARN] <script id=\"cb-raw-data\"> not found, "
              "will regenerate all formats from content.")

    return content_fragment, raw_formats


# ---------------------------------------------------------------------------
# Step 1.5: Expand simplified <p class="..."> back to full Xiumi inline HTML
# ---------------------------------------------------------------------------
def expand_patterns(html_str):
    """
    Expand simplified class-based <p> tags back to the full
    inline-style Xiumi HTML that the Windows clipboard expects.

    Recognized classes:
      title       → <section font-size:24px><p><strong>TEXT</strong></p></section>
      body        → <p white-space:normal;...>TEXT</p>
      empty-line  → <p><br></p>
      hl (span)   → <span background-color><strong>TEXT</strong></span>
    """
    result = html_str

    # 1) Title: <p class="title">TEXT</p>
    result = re.sub(
        r'<p\s+class="title">(.*?)</p>',
        lambda m: (
            '<section style="font-size: 24px; box-sizing: border-box;">'
            '<p style="margin: 0px; padding: 0px; box-sizing: border-box;">'
            '<strong style="box-sizing: border-box;">'
            + m.group(1) +
            '</strong></p></section>'
        ),
        result, flags=re.DOTALL
    )

    # 2) Body: <p class="body">TEXT</p>
    result = re.sub(
        r'<p\s+class="body">(.*?)</p>',
        lambda m: (
            '<p style="white-space: normal; margin: 0px; padding: 0px; box-sizing: border-box;">'
            + m.group(1) +
            '</p>'
        ),
        result, flags=re.DOTALL
    )

    # 3) Empty line: <p class="empty-line"><br></p>
    result = re.sub(
        r'<p\s+class="empty-line">\s*<br>\s*</p>',
        '<p style="white-space: normal; margin: 0px; padding: 0px; box-sizing: border-box;">'
        '<br style="box-sizing: border-box;"></p>',
        result
    )

    # 4) Inline highlight: <span class="hl">TEXT</span>
    result = re.sub(
        r'<span\s+class="hl">(.*?)</span>',
        lambda m: (
            '<span style="background-color: rgb(235, 252, 229); box-sizing: border-box;">'
            '<strong style="box-sizing: border-box;">'
            + m.group(1) +
            '</strong></span>'
        ),
        result, flags=re.DOTALL
    )

    return result


def normalize_whitespace(html_str):
    """
    Remove formatting whitespace (newlines + indentation) between HTML tags.
    This restores the compact tag structure needed for correct clipboard output.
    """
    # Remove newline + any leading whitespace before the next HTML tag
    result = re.sub(r'\n\s*(?=<)', '', html_str)
    # Remove any trailing whitespace before a closing tag
    result = re.sub(r'\s+(?=</)', '', result)
    # Remove newline + indentation before text content (between closing tags and text)
    result = re.sub(r'\n\s+', '', result)
    # Remove spaces between consecutive closing tags
    result = re.sub(r'(</\w+>)\s+(?=</)', r'\1', result)
    return result


# ---------------------------------------------------------------------------
# Step 1.6: Embed local images as base64 data URIs
# ---------------------------------------------------------------------------
def embed_local_images(html_str, base_dir):
    """
    Find all <img src="..."> with local file paths, convert to base64 data URIs.
    This is required for clipboard HTML format — external file paths don't work.
    """
    def replace_img(match):
        full_tag = match.group(0)
        src = match.group(1)

        # Skip remote URLs and already-embedded data URIs
        if src.startswith(('http://', 'https://', 'data:')):
            return full_tag

        img_path = os.path.join(base_dir, src.replace('/', os.sep))
        if not os.path.isfile(img_path):
            print(f"  [WARN] Image not found: {img_path}")
            return full_tag

        ext = os.path.splitext(img_path)[1].lower().lstrip('.')
        if ext == 'jpg':
            ext = 'jpeg'

        with open(img_path, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode('ascii')

        print(f"  [OK] Embedded image: {src} ({len(img_data)//1024}KB)")
        return full_tag.replace(src, f'data:image/{ext};base64,{img_data}')

    return re.sub(r'<img[^>]+src="([^"]+)"', replace_img, html_str)


# ---------------------------------------------------------------------------
# Step 2: Build clipboard formats from content
# ---------------------------------------------------------------------------
def build_html_format_binary(fragment):
    """
    Build the Windows clipboard HTML Format binary from an HTML fragment.
    Includes the standard header with byte offsets.
    """
    prefix = "<html>\r\n<body>\r\n<!--StartFragment-->"
    suffix = "<!--EndFragment-->\r\n</body>\r\n</html>"

    header_tpl = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_frag:010d}\r\n"
        "EndFragment:{end_frag:010d}\r\n"
    )

    prefix_bytes = prefix.encode("utf-8")
    suffix_bytes = suffix.encode("utf-8")
    frag_bytes = fragment.encode("utf-8")

    # Iteratively calculate offsets (header length may change)
    dummy = header_tpl.format(start_html=0, end_html=0,
                              start_frag=0, end_frag=0)
    hdr_len = len(dummy.encode("utf-8"))

    for _ in range(3):
        start_html = hdr_len
        start_frag = start_html + len(prefix_bytes)
        end_frag = start_frag + len(frag_bytes)
        end_html = end_frag + len(suffix_bytes)

        real_hdr = header_tpl.format(
            start_html=start_html, end_html=end_html,
            start_frag=start_frag, end_frag=end_frag,
        )
        new_len = len(real_hdr.encode("utf-8"))
        if new_len == hdr_len:
            break
        hdr_len = new_len

    return real_hdr.encode("utf-8") + prefix_bytes + frag_bytes + suffix_bytes + b"\x00"


def extract_plain_text(html_fragment):
    """Convert HTML fragment to plain text (matching Xiumi clipboard format)."""
    text = html_fragment
    text = re.sub(r'<br\s*/?\s*>', '\n', text)
    text = re.sub(r'</(?:p|section|div|h[1-6])>', '\n\n\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    text = text.strip()
    return text


def build_all_formats(content_fragment, raw_formats):
    """
    Build the complete list of clipboard format entries to write.

    Strategy:
      - HTML Format: regenerated from content_fragment
      - CF_UNICODETEXT: regenerated from plain text extraction
      - CF_TEXT / CF_OEMTEXT: regenerated from plain text
      - CF_LOCALE and others: use original raw data if available
    """
    # Index original data by name for quick lookup
    orig = {}
    for entry in raw_formats:
        orig[entry["format_name"]] = entry

    result = []

    # 1) HTML Format (always regenerate from content)
    html_bin = build_html_format_binary(content_fragment)
    result.append({
        "format_id": 49393,
        "format_name": "HTML Format",
        "raw": html_bin,
    })

    # 2) Plain text
    plain_text = extract_plain_text(content_fragment)

    # CF_UNICODETEXT
    utext = plain_text.encode("utf-16-le") + b"\x00\x00"
    result.append({
        "format_id": 13,
        "format_name": "CF_UNICODETEXT",
        "raw": utext,
    })

    # CF_LOCALE (use original or default zh-CN)
    if "CF_LOCALE" in orig:
        locale_raw = base64.b64decode(orig["CF_LOCALE"]["data"])
    else:
        locale_raw = struct.pack("<I", 2052)  # zh-CN
    result.append({
        "format_id": 16,
        "format_name": "CF_LOCALE",
        "raw": locale_raw,
    })

    # CF_TEXT
    try:
        ansi = plain_text.encode("cp936") + b"\x00"
    except UnicodeEncodeError:
        ansi = plain_text.encode("utf-8") + b"\x00"
    result.append({
        "format_id": 1,
        "format_name": "CF_TEXT",
        "raw": ansi,
    })

    # CF_OEMTEXT
    result.append({
        "format_id": 7,
        "format_name": "CF_OEMTEXT",
        "raw": ansi,
    })

    # Other formats (Chromium internal, etc.) — use original data
    regenerated_names = {"HTML Format", "CF_UNICODETEXT", "CF_LOCALE",
                         "CF_TEXT", "CF_OEMTEXT"}
    for entry in raw_formats:
        name = entry["format_name"]
        if name not in regenerated_names:
            result.append({
                "format_id": entry["format_id"],
                "format_name": name,
                "raw": base64.b64decode(entry["data"]),
            })

    return result


# ---------------------------------------------------------------------------
# Step 3: Write to clipboard
# ---------------------------------------------------------------------------
def write_clipboard(formats):
    """Write all formats to the Windows clipboard."""
    print(f"[INFO] Writing {len(formats)} format(s) to clipboard ...")

    import time
    opened = False
    for attempt in range(5):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.3)
    if not opened:
        print("[ERROR] Cannot open clipboard after 5 attempts.")
        sys.exit(1)

    try:
        user32.EmptyClipboard()
        ok = 0

        for entry in formats:
            fmt_id   = entry["format_id"]
            fmt_name = entry["format_name"]
            raw      = entry["raw"]
            size     = len(raw)

            if size == 0:
                print(f"  [WARN] Empty data: {fmt_name}, skipping.")
                continue

            runtime_fmt = resolve_format_id(fmt_id, fmt_name)

            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
            if not h_mem:
                print(f"  [ERROR] GlobalAlloc failed: {fmt_name}")
                continue

            p = kernel32.GlobalLock(h_mem)
            if not p:
                print(f"  [ERROR] GlobalLock failed: {fmt_name}")
                kernel32.GlobalFree(h_mem)
                continue

            try:
                buf = ctypes.create_string_buffer(raw, size)
                ctypes.memmove(p, ctypes.addressof(buf), size)
            finally:
                kernel32.GlobalUnlock(h_mem)

            if not user32.SetClipboardData(runtime_fmt, h_mem):
                print(f"  [ERROR] SetClipboardData failed: {fmt_name}")
                kernel32.GlobalFree(h_mem)
                continue

            print(f"  [OK] {fmt_name:<45s}  {size:>8,} bytes")
            ok += 1

        print(f"\n[DONE] Restored {ok}/{len(formats)} format(s) to clipboard.")

    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(html_path=None):
    # 未传值 → 派生自 DIR_NAME
    if html_path is None:
        html_path = fr"content_instance\{DIR_NAME}\process\step3_json_to_html.html"

    if not os.path.isfile(html_path):
        print(f"[ERROR] File not found: {html_path}")
        sys.exit(1)

    print(f"[INFO] Reading: {html_path}")

    # 1) Parse
    content_fragment, raw_formats = parse_html_file(html_path)
    print(f"[INFO] Content fragment: {len(content_fragment):,} chars")
    print(f"[INFO] Original formats:  {len(raw_formats)}")

    # 1.5) Expand simplified class-based <p> tags back to full Xiumi inline HTML
    expanded_fragment = expand_patterns(content_fragment)

    # 1.6) Normalize: remove formatting whitespace between tags
    normalized_fragment = normalize_whitespace(expanded_fragment)
    print(f"[INFO] After expansion:   {len(normalized_fragment):,} chars")

    # 1.65) 保存内联样式 HTML 供 step6 复用（不含 base64，外部图片待 step6 上传微信）
    inline_html_path = os.path.join(
        os.path.dirname(os.path.abspath(html_path)),
        'step4_upload_clipboard.html'
    )
    with open(inline_html_path, 'w', encoding='utf-8') as f:
        f.write(normalized_fragment)
    print(f"[INFO] 已保存内联样式 HTML → {inline_html_path}")

    # 1.7) Embed local images as base64 data URIs (for clipboard compatibility)
    # base_dir 是 HTML 文件的上一级，因为 image_path 已包含 process/ 前缀
    html_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(html_path)))
    print("[INFO] Embedding local images as base64...")
    normalized_fragment = embed_local_images(normalized_fragment, html_base_dir)
    print(f"[INFO] After embedding:   {len(normalized_fragment):,} chars")

    # 2) Build all formats from content
    formats = build_all_formats(normalized_fragment, raw_formats)

    # 3) Write to clipboard
    write_clipboard(formats)


if __name__ == '__main__':
    # 默认让 main() 自行派生（fr"content_instance\{DIR_NAME}\process\step3_json_to_html.html"）
    # 若要指定别的目录/文件：保留下面显式行并改路径；不需要覆盖时把它注释掉即可
    html_path = None
    html_path = fr"content_instance\content_20260715_1\process\step3_json_to_html.html"
    main(html_path)
