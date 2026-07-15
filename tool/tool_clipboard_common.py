# -*- coding: utf-8 -*-
"""
tool_clipboard_replace_images.py
=================================
独立工具：读取剪贴板 HTML，按 step2_table_to_image.json 中的图片顺序
替换剪贴板中的图片，再写回剪贴板。

用法：
  python tool_clipboard_replace_images.py content_instance/content_20260702_1

逻辑：
  1. 读取当前剪贴板中的 HTML Format 内容
  2. 读取指定文件夹下 process/step2_table_to_image.json 的图片列表
  3. 比较剪贴板 <img> 数量 vs JSON 图片数量，不匹配则报错退出
  4. 按顺序逐一替换为本地图片（base64 编码）
  5. 将替换后的内容写回剪贴板（保留其他格式不变）

依赖：Windows 系统（使用 ctypes 操作剪贴板）
"""

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import struct
import sys
import time
from launch import DIR_NAME

# ---------------------------------------------------------------------------
# Windows API (64-bit safe) — 与 step4 相同的剪贴板 API
# ---------------------------------------------------------------------------
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.OpenClipboard.restype = wt.BOOL
user32.OpenClipboard.argtypes = [wt.HWND]
user32.CloseClipboard.restype = wt.BOOL
user32.CloseClipboard.argtypes = []
user32.EmptyClipboard.restype = wt.BOOL
user32.EmptyClipboard.argtypes = []
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [wt.UINT]
user32.IsClipboardFormatAvailable.restype = wt.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
user32.RegisterClipboardFormatW.restype = wt.UINT
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]

kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = wt.BOOL
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]


def resolve_format_id(fmt_name):
    """通过格式名获取剪贴板 format ID"""
    rid = user32.RegisterClipboardFormatW(fmt_name)
    return rid if rid else 0


# ---------------------------------------------------------------------------
# 从剪贴板读取 HTML
# ---------------------------------------------------------------------------
def read_clipboard_html():
    """从剪贴板读取 HTML Format 内容，返回 HTML 字符串"""
    fmt_id = resolve_format_id("HTML Format")
    if fmt_id == 0:
        raise RuntimeError("无法注册 HTML Format")

    opened = False
    for _ in range(5):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.3)

    if not opened:
        raise RuntimeError("无法打开剪贴板")

    try:
        if not user32.IsClipboardFormatAvailable(fmt_id):
            raise RuntimeError("剪贴板中没有 HTML Format 数据")

        h_data = user32.GetClipboardData(fmt_id)
        if not h_data:
            raise RuntimeError("GetClipboardData 返回空")

        p = kernel32.GlobalLock(h_data)
        if not p:
            raise RuntimeError("GlobalLock 失败")

        try:
            size = kernel32.GlobalSize(h_data)
            print(f"[DEBUG] 剪贴板原始数据大小: {size} bytes")
            raw = ctypes.string_at(p, size)
            print(f"[DEBUG] 实际读取字节数: {len(raw)}")
        finally:
            kernel32.GlobalUnlock(h_data)

        # 解析 HTML Format 头部，提取 fragment 内容
        # 注意：StartFragment/EndFragment 是 **字节偏移量**，必须先解码再切片
        header_text = raw[:512].decode('utf-8', errors='replace')

        start_frag = None
        end_frag = None
        for line in header_text.split('\r\n')[:10]:
            if line.startswith('StartFragment:'):
                start_frag = int(line.split(':')[1].strip())
            elif line.startswith('EndFragment:'):
                end_frag = int(line.split(':')[1].strip())

        if start_frag is not None and end_frag is not None:
            print(f"[DEBUG] StartFragment={start_frag}, EndFragment={end_frag}")
            # 用字节偏移从 raw 中切片，再解码为字符串
            frag_bytes = raw[start_frag:end_frag]
            print(f"[DEBUG] fragment 字节大小: {len(frag_bytes)} bytes")
            fragment = frag_bytes.decode('utf-8', errors='replace')
            # 去除可能的 StartFragment / EndFragment 注释标记
            fragment = re.sub(r'<!--StartFragment-->', '', fragment)
            fragment = re.sub(r'<!--EndFragment-->', '', fragment)
            return fragment.strip()
        else:
            return raw.decode('utf-8', errors='replace').rstrip('\x00')

    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# 写入剪贴板（HTML Format + 纯文本，覆盖式）
# ---------------------------------------------------------------------------
def build_html_format_binary(fragment):
    """构建 Windows 剪贴板 HTML Format 二进制数据（含头部偏移量）"""
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
    """从 HTML 片段提取纯文本"""
    text = html_fragment
    text = re.sub(r'<br\s*/?\s*>', '\n', text)
    text = re.sub(r'</(?:p|section|div|h[1-6])>', '\n\n\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    for old, new in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                     ('&quot;', '"'), ('&#39;', "'"), ('&nbsp;', ' ')]:
        text = text.replace(old, new)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    return text.strip()


def write_clipboard(html_fragment):
    """将替换后的 HTML 写回剪贴板（HTML Format + CF_UNICODETEXT + CF_LOCALE）"""
    fmt_html = resolve_format_id("HTML Format")
    if fmt_html == 0:
        raise RuntimeError("无法注册 HTML Format")

    formats = []

    # HTML Format
    html_bin = build_html_format_binary(html_fragment)
    formats.append((fmt_html, "HTML Format", html_bin))

    # CF_UNICODETEXT (format id = 13)
    plain = extract_plain_text(html_fragment)
    utext = plain.encode("utf-16-le") + b"\x00\x00"
    formats.append((13, "CF_UNICODETEXT", utext))

    # CF_LOCALE (format id = 16, zh-CN = 2052)
    locale_raw = struct.pack("<I", 2052)
    formats.append((16, "CF_LOCALE", locale_raw))

    opened = False
    for _ in range(5):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.3)
    if not opened:
        raise RuntimeError("无法打开剪贴板写入")

    try:
        user32.EmptyClipboard()
        ok = 0

        for fmt_id, fmt_name, raw in formats:
            size = len(raw)
            if size == 0:
                print(f"  [SKIP] {fmt_name}: 空数据")
                continue

            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
            if not h_mem:
                print(f"  [FAIL] {fmt_name}: GlobalAlloc 失败")
                continue

            p = kernel32.GlobalLock(h_mem)
            if not p:
                print(f"  [FAIL] {fmt_name}: GlobalLock 失败")
                kernel32.GlobalFree(h_mem)
                continue

            try:
                buf = ctypes.create_string_buffer(raw, size)
                ctypes.memmove(p, ctypes.addressof(buf), size)
            finally:
                kernel32.GlobalUnlock(h_mem)

            ret = user32.SetClipboardData(fmt_id, h_mem)
            if not ret:
                err = ctypes.GetLastError() if hasattr(ctypes, 'GetLastError') else '?'
                print(f"  [FAIL] {fmt_name}: SetClipboardData 失败 (err={err})")
                kernel32.GlobalFree(h_mem)
                continue
            print(f"  [OK]   {fmt_name}: {size:,} bytes (handle={ret})")
            ok += 1

        print(f"[DONE] 写入 {ok}/{len(formats)} 个格式到剪贴板")
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# 从 JSON 获取图片列表（按出现顺序）
# ---------------------------------------------------------------------------
def get_image_list_from_json(json_path):
    """
    从 step2_table_to_image.json 中按顺序提取所有图片信息。
    返回: [(image_path, file_name), ...]
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    images = []
    for elem in data.get('elements', []):
        if elem.get('type') == 'image':
            images.append((
                elem.get('image_path', ''),
                elem.get('file_name', ''),
            ))
    return images


# ---------------------------------------------------------------------------
# 替换剪贴板 HTML 中的图片（base64 内嵌）
# ---------------------------------------------------------------------------
def replace_images_in_html(html_str, image_list, base_dir):
    """
    按顺序替换 HTML 中的 <img src="..."> 为本地图片的 base64。
    image_list: [(relative_path, file_name), ...]
    base_dir:   图片相对路径的根目录（content_instance/content_xxx/）
    """
    img_pattern = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
    matches = list(img_pattern.finditer(html_str))

    if len(matches) != len(image_list):
        print(f"[ERROR] 图片数量不匹配!")
        print(f"  剪贴板中: {len(matches)} 张")
        print(f"  JSON 中:  {len(image_list)} 张")
        print(f"  无法确定替换顺序，已放弃替换。")
        return None

    print(f"[INFO] 共 {len(matches)} 张图片，按顺序替换:")

    # 从后往前替换，避免偏移量变化
    result = html_str
    for i in range(len(matches) - 1, -1, -1):
        match = matches[i]
        old_src = match.group(1)
        img_rel_path, img_name = image_list[i]

        # 构建本地图片绝对路径
        img_abs_path = os.path.join(base_dir, img_rel_path.replace('/', os.sep))

        if not os.path.isfile(img_abs_path):
            print(f"  [{i+1}] [WARN] 图片不存在: {img_abs_path}，跳过")
            continue

        # 读取图片并编码为 base64
        ext = os.path.splitext(img_abs_path)[1].lower().lstrip('.')
        if ext == 'jpg':
            ext = 'jpeg'

        with open(img_abs_path, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode('ascii')

        new_src = f'data:image/{ext};base64,{img_data}'
        old_tag = match.group(0)
        new_tag = old_tag.replace(old_src, new_src)

        result = result[:match.start()] + new_tag + result[match.end():]
        print(f"  [{i+1}] {img_name} → base64 ({len(img_data) // 1024}KB)")

    return result


# ---------------------------------------------------------------------------
# HTML 后处理：清理剪贴板 HTML 中的冗余样式和结构
# ---------------------------------------------------------------------------
def postprocess_html(html_str):
    """
    对剪贴板 HTML 做六项后处理：
      1. 去除所有 background-color 声明
      2. 将所有 margin 相关属性归零为 0px
      3. 去除 <p> 内包裹 <br> 的冗余 <span> 标签
      4. 清理标签之间冗余的不可见空格（&nbsp; 实体 或 U+00A0）
      5. 将 font-size:24px 的 section 内的 <p> 转为 <h1>
      6. 在末尾追加 add_html.html 中的尾部内容（声明信息等）
    """
    result = html_str

    # 1) 去除 background-color
    bg_pattern = re.compile(r'background-color:\s*[^;"]+;\s*', re.IGNORECASE)
    bg_count = len(bg_pattern.findall(result))
    result = bg_pattern.sub('', result)
    if bg_count:
        print(f"[后处理] 去除 background-color ({bg_count} 处)")

    # 2) 所有 margin 归零（含 margin-top/right/bottom/left）
    margin_pattern = re.compile(r'margin(?:-(?:top|right|bottom|left))?:\s*[^;"]+;', re.IGNORECASE)
    margin_count = len(margin_pattern.findall(result))

    def _zero_margin(m):
        prop = m.group(0).split(':')[0]
        return f'{prop}: 0px;'

    result = margin_pattern.sub(_zero_margin, result)
    if margin_count:
        print(f"[后处理] margin → 0px ({margin_count} 处)")

    # 3) 去除 <p> 内包裹 <br> 的 <span>：
    #    <p ...><span ...><br ...></span></p>  →  <p ...><br ...></p>
    span_br_pattern = re.compile(
        r'(<p[^>]*>)\s*<span[^>]*>\s*(<br[^>]*?>)\s*</span>\s*(</p>)',
        re.IGNORECASE | re.DOTALL
    )
    span_br_count = len(span_br_pattern.findall(result))
    result = span_br_pattern.sub(r'\1\2\3', result)
    if span_br_count:
        print(f"[后处理] 去除 <span> 包裹 <br> ({span_br_count} 处)")

    # 4) 清理标签之间冗余的不可见空格（&nbsp; 实体 或 U+00A0 字符）
    #    只去除标签之间的独立空格，保留文字中间有意的空格
    NBSP = '(?:&nbsp;|\u00a0)'  # 匹配 HTML 实体或 Unicode 字符
    nbsp_between_tags = re.compile(r'(?<=>)\s*' + NBSP + r'\s*(?=<)', re.IGNORECASE)
    nbsp_standalone = re.compile(r'<p[^>]*>\s*' + NBSP + r'\s*</p>', re.IGNORECASE)
    count1 = len(nbsp_between_tags.findall(result))
    count2 = len(nbsp_standalone.findall(result))
    if count1:
        result = nbsp_between_tags.sub(lambda m: '', result)
    if count2:
        result = nbsp_standalone.sub('', result)
    total = count1 + count2
    if total:
        print(f"[后处理] 去除冗余不可见空格 ({total} 处)")

    # 5) 将 font-size:24px 的 <section> 内的 <p> 转为 <h1>
    #    秀米中 24px 的标题块结构：<section ...24px...><p ...>标题</p></section>
    h1_pattern = re.compile(
        r'<section[^>]*font-size:\s*24px[^>]*>\s*'
        r'<p[^>]*>(.*?)</p>\s*'
        r'</section>',
        re.IGNORECASE | re.DOTALL
    )
    h1_matches = list(h1_pattern.finditer(result))
    if h1_matches:
        for m in reversed(h1_matches):
            inner_content = m.group(1).strip()
            result = result[:m.start()] + f'<h1>{inner_content}</h1>' + result[m.end():]
        print(f"[后处理] 24px 标题 <p> → <h1> ({len(h1_matches)} 处)")

    # 6) 在末尾追加 add_html.html 的尾部内容
    add_html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'add_html.html')
    if os.path.isfile(add_html_path):
        with open(add_html_path, 'r', encoding='utf-8') as f:
            add_content = f.read()
        result = result + add_content
        print(f"[后处理] 追加尾部内容 (add_html.html)")
    else:
        print(f"[WARN] add_html.html 不存在: {add_html_path}")

    return result


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(input_dir=None):
    """
    input_dir: 文章实例目录，如 content_instance\\content_20260702_1
               未传值 → 默认 content_instance\\{DIR_NAME}
    """
    if input_dir is None:
        input_dir = fr"content_instance\{DIR_NAME}"

    # 验证路径
    if not os.path.isdir(input_dir):
        print(f"[ERROR] 目录不存在: {input_dir}")
        sys.exit(1)

    json_path = os.path.join(input_dir, 'process', 'step2_table_to_image.json')
    if not os.path.isfile(json_path):
        print(f"[ERROR] JSON 文件不存在: {json_path}")
        sys.exit(1)

    print(f"[INFO] 输入目录: {input_dir}")
    print(f"[INFO] JSON 文件: {json_path}")

    # 1. 读取 JSON 图片列表
    image_list = get_image_list_from_json(json_path)
    print(f"[INFO] JSON 中图片数量: {len(image_list)}")
    for i, (path, name) in enumerate(image_list):
        print(f"  [{i+1}] {name} → {path}")

    # 2. 读取剪贴板 HTML
    print(f"\n{'─'*60}")
    print("[INFO] 读取剪贴板 HTML...")
    try:
        html_fragment = read_clipboard_html()
    except Exception as e:
        print(f"[ERROR] 读取剪贴板失败: {e}")
        sys.exit(1)
    print(f"[INFO] 剪贴板 HTML: {len(html_fragment):,} chars")

    # 调试：保存原始剪贴板 HTML 到文件以便检查
    debug_dir = os.path.join(input_dir, 'process')
    debug_before = os.path.join(debug_dir, '_debug_clipboard_before.html')
    with open(debug_before, 'w', encoding='utf-8') as f:
        f.write(html_fragment)
    print(f"[DEBUG] 原始剪贴板 HTML 已保存: {debug_before}")

    # 调试：显示剪贴板中找到的 img 标签
    img_debug = re.findall(r'<img[^>]+src="([^"]{0,80})', html_fragment, re.IGNORECASE)
    print(f"[DEBUG] 剪贴板中 <img> 标签数: {len(img_debug)}")
    for i, src in enumerate(img_debug):
        label = 'base64' if src.startswith('data:') else 'url'
        print(f"  [{i+1}] ({label}) {src[:60]}...")

    # 3. 替换图片
    print(f"\n{'─'*60}")
    result = replace_images_in_html(html_fragment, image_list, input_dir)
    if result is None:
        sys.exit(1)

    # 3.5 后处理
    print(f"\n{'─'*60}")
    print("[INFO] HTML 后处理...")
    result = postprocess_html(result)

    # 4. 写回剪贴板
    print(f"\n{'─'*60}")
    print("[INFO] 写回剪贴板...")
    try:
        write_clipboard(result)
    except Exception as e:
        print(f"[ERROR] 写入剪贴板失败: {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  图片替换完成!")
    print(f"  共替换 {len(image_list)} 张图片")
    print(f"{'='*60}")

    # 验证：回读剪贴板检查图片是否真的替换了
    print(f"\n[INFO] 验证：回读剪贴板...")
    try:
        verify_html = read_clipboard_html()
        verify_imgs = re.findall(r'<img[^>]+src="([^"]{0,40})', verify_html, re.IGNORECASE)
        b64_count = sum(1 for s in verify_imgs if s.startswith('data:'))
        print(f"[DEBUG] 回读 <img> 标签数: {len(verify_imgs)}，其中 base64: {b64_count}")

        # 保存回读内容到文件
        debug_after = os.path.join(debug_dir, '_debug_clipboard_after.html')
        with open(debug_after, 'w', encoding='utf-8') as f:
            f.write(verify_html)
        print(f"[DEBUG] 回读 HTML 已保存: {debug_after}")

        if b64_count == len(image_list):
            print(f"[OK] 验证通过！剪贴板图片已替换。")
        else:
            print(f"[WARN] 验证失败！期望 {len(image_list)} 张 base64，实际 {b64_count} 张")
    except Exception as e:
        print(f"[WARN] 回读验证失败: {e}")


if __name__ == '__main__':
    # 默认让 main() 自行派生（fr"content_instance\{DIR_NAME}"）
    # 若要指定别的目录：保留 531 行并改路径；不需要覆盖时，把 531 行注释掉即可
    input_dir = None
    input_dir = fr"content_instance\content_20260715_1"
    main(input_dir)
