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

# 本文件位于 tool/ 子目录，独立运行时需要把上层目录加入 sys.path 才能 import launch
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

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
# HTML 后处理：剪贴板 HTML “白名单极简化”
# ---------------------------------------------------------------------------
def postprocess_html(html_str, heading_level=1, douban=0):
    """
    将剪贴板 HTML 清洗到只保留以下信号的极简结构：
      文字、<strong>加粗、<img>图片、<p>段落、<h1>/<h2>标题、<br>换行
    其他一律扫除。

    步骤（默认全量执行）：
      1. font-size:24px 的 <section> → <hN>（内部只取纯文字）
      2. <b> → <strong>；剪掉 em/i/u/s/small/font/mark 等非加粗强调标签
      3. 解包 span/section/div/a（只删标签，保留内容）
      4. 剥掉所有属性；<img> 特殊：data-src 只放原 URL，src 只放 base64
      5. 全局删除所有 &nbsp; / U+00A0（不限位置）
      6. 删除所有 <br>，以及只含 <br>/空白的 <p>/<h1>/<h2>；清完后剥掉因此成为空壳的 <strong></strong> 及 <p></p>
      7. 在每个 </p>、</h1>、</h2>、<img ...> 之后插入一个 <br>（统一段间距）
      8. 末尾原样拼接 add_html.html（不做任何处理）

    参数 heading_level：仅支持 1、2 或 3。
    参数 douban：1 → 只执行步骤 1 与 8，步骤 2～7 全部跳过（适合发到豆瓣等只需高亮标题、保留原样式的平台）
    """
    if heading_level not in (1, 2, 3, 5):
        raise ValueError(f"heading_level 仅支持 1,2,3,5 收到: {heading_level}")
    heading_tag = f'h{heading_level}'

    result = html_str

    # 1) 24px section → <hN>（只取纯文字，避免标题中衍生冗余 <strong>/<span>）
    heading_pattern = re.compile(
        r'<section[^>]*font-size:\s*24px[^>]*>(.*?)</section>',
        re.IGNORECASE | re.DOTALL
    )

    def _to_heading(match):
        raw_inner = match.group(1)
        text = re.sub(r'<[^>]*>', '', raw_inner)             # 剥掉所有内部标签
        text = text.replace('&nbsp;', ' ').replace('\u00a0', ' ')
        text = text.strip()
        return f'<{heading_tag}>{text}</{heading_tag}>' if text else ''

    result, n_head = heading_pattern.subn(_to_heading, result)
    if n_head:
        print(f"[后处理] 24px section → <{heading_tag}> ({n_head} 处)")

    if douban:
        print(f"[后处理] DOUBAN=1，跳过步骤 2～7（仅保留 24px → <{heading_tag}> 与末尾拼接）")
    else:
        # 2) <b> → <strong>；剪掉非加粗强调标签（保留内部文字）
        result, n_b = re.subn(r'<(/?)b\b([^>]*)>', r'<\1strong\2>', result, flags=re.IGNORECASE)
        if n_b:
            print(f"[后处理] <b> → <strong> ({n_b} 处)")

        _NON_BOLD_INLINE = (
            r'(?:em|i|u|s|strike|small|big|sub|sup|font|mark|ins|del|'
            r'code|kbd|samp|var|abbr|cite|q|dfn|tt)'
        )
        result, n_nb = re.subn(
            r'</?' + _NON_BOLD_INLINE + r'\b[^>]*/?>', '', result,
            flags=re.IGNORECASE
        )
        if n_nb:
            print(f"[后处理] 剥掉非加粗强调标签 ({n_nb} 处)")

        # 3) 解包 span/section/div/a（标签删掉，内容保留）
        result, n_uw = re.subn(
            r'</?(?:span|section|div|a)\b[^>]*/?>', '', result,
            flags=re.IGNORECASE
        )
        if n_uw:
            print(f"[后处理] 解包 span/section/div/a ({n_uw} 处)")

        # 4) 剥掉所有属性：<img> 特殊处理，其他全部裸标签
        #    <img> 规则：data-src 仅放原 URL，src 仅放 base64；缺哪个不输出哪个
        _attr_count = [0]
        def _strip_attrs(m):
            slash = m.group(1)                # '' 或 '/'
            tag = m.group(2).lower()
            attrs_str = m.group(3)
            if slash == '/':
                return f'</{tag}>'
            if tag == 'img':
                # 注意：`\bsrc\b` 会误匹配 `data-src` 里的 src（因为 `-` 与 `s` 之间有词边界）
                # 用负向回看排除 字母/数字/下划线/连字符，保证只匹配独立的 src=
                src_match = re.search(r'(?<![\w\-])src\s*=\s*"([^"]*)"', attrs_str, re.IGNORECASE)
                dsrc_match = re.search(r'\bdata-src\s*=\s*"([^"]*)"', attrs_str, re.IGNORECASE)
                in_src = src_match.group(1) if src_match else ''
                in_dsrc = dsrc_match.group(1) if dsrc_match else ''

                # base64 候选：任一属性以 data: 开头就取为 base64
                base64_val = ''
                if in_src.startswith('data:'):
                    base64_val = in_src
                elif in_dsrc.startswith('data:'):
                    base64_val = in_dsrc

                # 原 URL 候选：优先用 data-src 的非 base64 值，其次用 src 的非 base64 值
                url_val = ''
                if in_dsrc and not in_dsrc.startswith('data:'):
                    url_val = in_dsrc
                elif in_src and not in_src.startswith('data:'):
                    url_val = in_src

                if attrs_str.strip():
                    _attr_count[0] += 1

                parts = ['<img']
                if base64_val:
                    parts.append(f'src="{base64_val}"')
                if url_val:
                    parts.append(f'data-src="{url_val}"')
                return ' '.join(parts) + '>'
            if attrs_str.strip():
                _attr_count[0] += 1
            return f'<{tag}>'
 
        tag_re = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>')
        result = tag_re.sub(_strip_attrs, result)
        if _attr_count[0]:
            print(f"[后处理] 剥掉冗余属性 ({_attr_count[0]} 处标签)")

        # 5) 全局删除所有 &nbsp; / U+00A0（不限位置）
        nbsp_pattern = re.compile(r'&nbsp;|\u00a0', re.IGNORECASE)
        n_nbsp = len(nbsp_pattern.findall(result))
        if n_nbsp:
            result = nbsp_pattern.sub('', result)
            print(f"[后处理] 删除所有 &nbsp;/U+00A0 ({n_nbsp} 处)")

        # 6) 删除所有 <br>，以及只含 <br>/空白的 <p>/<h1>/<h2>
        #    先删只包 <br>/空白的块级元素（避免丢掉有文字的段落），再删剩下的 <br>
        empty_block_pattern = re.compile(
            r'<(p|h1|h2)>\s*(?:<br>\s*)*</\1>',
            re.IGNORECASE
        )
        total_empty = 0
        while True:
            new_result, n = empty_block_pattern.subn('', result)
            if n == 0:
                break
            total_empty += n
            result = new_result
        if total_empty:
            print(f"[后处理] 删除只含 <br>/空白的 <p>/<h1>/<h2> ({total_empty} 处)")

        result, n_br = re.subn(r'<br>', '', result, flags=re.IGNORECASE)
        if n_br:
            print(f"[后处理] 删除剩余 <br> ({n_br} 处)")

        # 6.5) 删除空壳 <strong></strong>（上一步删掉被包裹的 <br> 后可能留下空强调）
        empty_strong_pattern = re.compile(r'<strong>\s*</strong>', re.IGNORECASE)
        total_es = 0
        while True:
            new_result, n = empty_strong_pattern.subn('', result)
            if n == 0:
                break
            total_es += n
            result = new_result
        if total_es:
            print(f"[后处理] 删除空壳 <strong></strong> ({total_es} 处)")

        # 6.6) 删除因上面清理新产生的只含空白的 <p></p>/<h1></h1>/<h2></h2>
        empty_block_pattern2 = re.compile(r'<(p|h1|h2)>\s*</\1>', re.IGNORECASE)
        result, n_eb2 = empty_block_pattern2.subn('', result)
        if n_eb2:
            print(f"[后处理] 删除新产生的空 <p>/<h1>/<h2> ({n_eb2} 处)")

        # 7) 在每个 </p>、</h1>、</h2>、<img ...> 之后插入一个 <br>（统一段间距）
        trailing_br_pattern = re.compile(r'(</p>|</h1>|</h2>|</h3>|</h5>|<img\b[^>]*>)', re.IGNORECASE)
        result, n_add = trailing_br_pattern.subn(r'\1<p><br></p>', result)
        if n_add:
            print(f"[后处理] 在 </p>/</h1>/</h2>/<img> 后注入 <br> ({n_add} 处)")
    
    # 8) 末尾原样拼接 add_html.html（不做任何处理）
    
    add_html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'add_html_douban.html' if douban else 'add_html.html')   
    if os.path.isfile(add_html_path):
        with open(add_html_path, 'r', encoding='utf-8') as f:
            add_content = f.read()
        result = result + add_content
        print(f"[后处理] 末尾原样拼接 ({add_html_path})")
    else:
        print(f"[WARN] html 不存在: {add_html_path}")

    return result


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(input_dir=None, heading_level=1, douban=0):
    """
    input_dir: 文章实例目录，如 content_instance\\content_20260702_1
               未传值 → 默认 content_instance\\{DIR_NAME}
    heading_level: 24px 标题块升级到的标题级别，1 → <h1>，2 → <h2>，3 → <h3>
    douban: 1 → 跳过换图片的步骤（适合发布到豆瓣等无需替换图片的平台）；0 → 正常替换
    """
    if input_dir is None:
        input_dir = fr"content_instance\{DIR_NAME}"

    # 验证路径
    if not os.path.isdir(input_dir):
        print(f"[ERROR] 目录不存在: {input_dir}")
        sys.exit(1)

    print(f"[INFO] 输入目录: {input_dir}")

    # 1. 读取 JSON 图片列表（douban 模式下跳过；无 JSON / 无图片 亦视为合法情况）
    if douban:
        print(f"[INFO] DOUBAN=1，跳过换图片步骤（不加载 JSON 图片列表）")
        image_list = []
    else:
        json_path = os.path.join(input_dir, 'process', 'step2_table_to_image.json')
        if not os.path.isfile(json_path):
            print(f"[INFO] 未找到 JSON 图片列表（{json_path}），按“无图片”处理")
            image_list = []
        else:
            print(f"[INFO] JSON 文件: {json_path}")
            image_list = get_image_list_from_json(json_path)
            print(f"[INFO] JSON 中图片数量: {len(image_list)}")
            for i, (path, name) in enumerate(image_list):
                print(f"  [{i+1}] {name} → {path}")

    # 2. 读取剪贴板 HTML
    #    若 _debug_clipboard_before.html 已存在，跳过剪贴板读取，直接复用磁盘缓存
    debug_dir = os.path.join(input_dir, 'process')
    debug_before = os.path.join(debug_dir, '_debug_clipboard_before.html')

    if os.path.isfile(debug_before):
        print(f"\n{'─'*60}")
        print(f"[INFO] 检测到已生成的 before 文件，跳过剪贴板读取")
        print(f"[INFO] 直接复用: {debug_before}")
        with open(debug_before, 'r', encoding='utf-8') as f:
            html_fragment = f.read()
        print(f"[INFO] 磁盘 HTML: {len(html_fragment):,} chars")
    else:
        print(f"\n{'─'*60}")
        print("[INFO] 读取剪贴板 HTML...")
        try:
            html_fragment = read_clipboard_html()
        except Exception as e:
            print(f"[ERROR] 读取剪贴板失败: {e}")
            sys.exit(1)
        print(f"[INFO] 剪贴板 HTML: {len(html_fragment):,} chars")

        # 调试：保存原始剪贴板 HTML 到文件以便检查
        os.makedirs(debug_dir, exist_ok=True)
        with open(debug_before, 'w', encoding='utf-8') as f:
            f.write(html_fragment)
        print(f"[DEBUG] 原始剪贴板 HTML 已保存: {debug_before}")

    # 调试：显示剪贴板中找到的 img 标签
    img_debug = re.findall(r'<img[^>]+src="([^"]{0,80})', html_fragment, re.IGNORECASE)
    print(f"[DEBUG] 剪贴板中 <img> 标签数: {len(img_debug)}")
    for i, src in enumerate(img_debug):
        label = 'base64' if src.startswith('data:') else 'url'
        print(f"  [{i+1}] ({label}) {src[:60]}...")

    # 3. 替换图片（douban 模式 或 无图片时跳过）
    print(f"\n{'─'*60}")
    if douban:
        print(f"[INFO] DOUBAN=1，跳过图片替换步骤")
        result = html_fragment
    elif not image_list:
        # 文章无图片（如纯文字文章）：JSON 未生成 或 JSON 中 image 元素为 0
        # 预期剪贴板中也没有 <img>，直接跳到后处理
        clip_img_count = len(re.findall(r'<img\b', html_fragment, re.IGNORECASE))
        if clip_img_count == 0:
            print(f"[INFO] 无图片可替换（JSON=0, 剪贴板=0），跳过替换直接进入后处理")
        else:
            print(f"[WARN] JSON 图片列表为空，但剪贴板中发现 {clip_img_count} 个 <img> 标签；本次不做替换，直接进入后处理")
        result = html_fragment
    else:
        result = replace_images_in_html(html_fragment, image_list, input_dir)
        if result is None:
            sys.exit(1)

    # 3.5 后处理
    print(f"\n{'─'*60}")
    print("[INFO] HTML 后处理...")
    result = postprocess_html(result, heading_level=heading_level, douban=douban)

    # 4. 写回剪贴板
    print(f"\n{'─'*60}")
    print("[INFO] 写回剪贴板...")
    try:
        write_clipboard(result)
    except Exception as e:
        print(f"[ERROR] 写入剪贴板失败: {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    if douban:
        print(f"  剪贴板已更新（DOUBAN 模式，未替换图片）")
    elif not image_list:
        print(f"  剪贴板已更新（无图片，未执行替换）")
    else:
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

        if douban:
            print(f"[OK] 剪贴板已写入（DOUBAN 模式，跳过图片替换校验）")
        elif not image_list:
            print(f"[OK] 剪贴板已写入（无图片，无需校验）")
        elif b64_count == len(image_list):
            print(f"[OK] 验证通过！剪贴板图片已替换。")
        else:
            print(f"[WARN] 验证失败！期望 {len(image_list)} 张 base64，实际 {b64_count} 张")
    except Exception as e:
        print(f"[WARN] 回读验证失败: {e}")

    # 打印 step1_1_titles.txt 内容（方便发布时直接复制标题）
    titles_path = os.path.join(input_dir, 'process', 'step1_1_titles.txt')
    print(f"\n{'='*60}")
    if os.path.isfile(titles_path):
        with open(titles_path, 'r', encoding='utf-8') as f:
            titles_content = f.read()
        print(f"[大标题] {titles_path}")
        print(f"{'─'*60}")
        print(titles_content)
    else:
        print(f"[INFO] 未找到大标题文件: {titles_path}")
    print(f"{'='*60}")


if __name__ == '__main__':
    # 默认让 main() 自行派生（fr"content_instance\{DIR_NAME}"）
    # 若要指定别的目录：保留下面显式行并改路径；不需要覆盖时把它注释掉即可
    input_dir = None
    input_dir = fr"content_instance\content_20260710_1"

    # # 正常
    # DOUBAN = 0
    # heading_level = 1

    # # 豆瓣
    # DOUBAN = 1
    # heading_level = 3

    # 网易
    DOUBAN = 0
    heading_level = 5

    main(input_dir, heading_level=heading_level, douban=DOUBAN)
