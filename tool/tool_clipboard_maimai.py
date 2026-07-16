"""
剪贴板文字追加工具
功能：
  1. 获取剪贴板纯文本内容，取前600字
     └ 或从 {input_dir}/process/_debug_clipboard_after.html 读取纯文字（如指定）
  2. 从 wx_content_list.txt 读取文章条目
  3. 第1个条目放在【展开内容如下】下面
  4. 接下来3个条目放在【其他优质内容分享】下面
  5. 拼接完成后写回剪贴板
"""

import os
import re
import sys
import time
import html as html_module
import ctypes
import ctypes.wintypes

# 本文件位于 tool/ 子目录，独立运行时需要把上层目录加入 sys.path 才能 import launch
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from launch import DIR_NAME

# Windows 剪贴板常量
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# 声明返回类型，防止64位系统指针截断
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = ctypes.c_bool
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
kernel32.GlobalFree.restype = ctypes.c_void_p
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_uint]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]


def safe_print(text):
    """Windows GBK终端安全打印"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", errors="replace").decode("gbk", errors="replace"))


def _open_clipboard(retries=5, delay=0.5):
    """带重试的打开剪贴板"""
    for i in range(retries):
        if user32.OpenClipboard(None):
            return True
        if i < retries - 1:
            time.sleep(delay)
    print(f"[ERROR] 无法打开剪贴板（重试{retries}次失败），请关闭其他占用剪贴板的程序")
    return False


def get_clipboard_text():
    """获取剪贴板纯文本内容（兼容含图片的剪贴板）"""
    if not _open_clipboard():
        return ""
    try:
        # 检查是否有纯文本
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            print("[WARN] 剪贴板不含纯文本格式（可能只有图片）")
            return ""
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        # 锁定全局内存并读取
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            # 用 c_wchar_p 从指针地址读取宽字符串
            text = ctypes.cast(ptr, ctypes.c_wchar_p).value or ""
        finally:
            kernel32.GlobalUnlock(handle)
        return text
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    """将文本写入剪贴板"""
    if not _open_clipboard():
        return
    try:
        user32.EmptyClipboard()
        # 分配全局内存 (UTF-16LE + 2字节终止符)
        data = text.encode("utf-16-le") + b"\x00\x00"
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        ret = user32.SetClipboardData(CF_UNICODETEXT, h)
        if ret:
            print("[OK] 已写入剪贴板")
        else:
            print("[ERROR] SetClipboardData 失败")
            kernel32.GlobalFree(h)
    finally:
        user32.CloseClipboard()


def html_to_plain_text(html_str):
    """将后处理过的 HTML（只含 <p>/<h1>/<h2>/<strong>/<img>/<br>）转为纯文本：
      - <br> / <br/>              → 换行
      - </p> </h1> </h2> </h3> </h4> → 段落换行（\n\n）
      - <img ...>                  → 丢弃
      - 其余标签                     → 只剥外壳，保留文字
      - HTML 实体                    → 解码（&amp; &lt; &gt; 等）
      - 多个连续空行 → 折叠为一个、首尾去空
    """
    s = html_str
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
    s = re.sub(r'</(p|h1|h2|h3|h4|div)>', '\n\n', s, flags=re.IGNORECASE)
    s = re.sub(r'<img\b[^>]*>', '', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', '', s)
    s = html_module.unescape(s)

    lines = [ln.strip() for ln in s.split('\n')]
    normalized, prev_blank = [], False
    for ln in lines:
        if not ln:
            if not prev_blank:
                normalized.append('')
            prev_blank = True
        else:
            normalized.append(ln)
            prev_blank = False
    while normalized and not normalized[0]:
        normalized.pop(0)
    while normalized and not normalized[-1]:
        normalized.pop()
    return '\n'.join(normalized)


def load_text_from_after_html(input_dir):
    """从 {project_root}\\{input_dir}\\process\\_debug_clipboard_after.html 读纯文字。
    input_dir 为空 或 文件不存在 → 返回 ''，由调用方回退到剪贴板。
    """
    if not input_dir:
        return ''
    # tool/ 目录的上一级 = 项目根
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    after_path = os.path.join(project_root, input_dir, 'process', '_debug_clipboard_after.html')
    if not os.path.isfile(after_path):
        print(f"[INFO] 未找到 after 文件，回退到剪贴板：{after_path}")
        return ''
    with open(after_path, 'r', encoding='utf-8') as f:
        html_str = f.read()
    text = html_to_plain_text(html_str)
    print(f"[OK] 从 after 文件读取纯文字 {len(text)} 字：{after_path}")
    return text


def parse_content_list(filepath):
    """
    解析 wx_content_list.txt
    文件格式：每个条目占4行（标题、空行、URL、空行）
    返回 [(title, url), ...] 列表
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n").rstrip("\r") for line in f.readlines()]

    entries = []
    i = 0
    while i < len(lines):
        # 跳过空行
        if not lines[i].strip():
            i += 1
            continue
        title = lines[i].strip()
        # 找下一个非空行作为 URL
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines):
            url = lines[j].strip()
            entries.append((title, url))
            i = j + 1
        else:
            break
    return entries


def normalize_paragraphs(text):
    """规范化段落：删除所有空白段落，段落之间统一加一个空行"""
    lines = text.split("\n")
    # 过滤掉空白行，保留有内容的段落
    paragraphs = [line for line in lines if line.strip()]
    # 段落之间用 \n\n 连接（即一个空行）
    return "\n\n".join(paragraphs)


def build_output(clipboard_text, entries, char_limit=600):
    """
    拼接输出文本：
      [前600字]......
      ---------------
      展开内容如下：
      [第1个条目]
      ---------------
      其他优质内容分享：
      [第2~4个条目]
      ---------------
    """
    # 取前 char_limit 个字
    text = clipboard_text[:char_limit] if len(clipboard_text) > char_limit else clipboard_text

    parts = [text + "......"]
    parts.append("---------------")

    # 展开内容如下：第1个条目
    parts.append("展开内容如下：")
    if len(entries) >= 1:
        parts.append(entries[0][0])
        parts.append(entries[0][1])
    parts.append("---------------")

    # 其他优质内容分享：第2~4个条目
    parts.append("其他优质内容分享：")
    for entry in entries[1:4]:
        parts.append(entry[0])
        parts.append(entry[1])
    parts.append("---------------")

    return "\n".join(parts)


def main(input_dir=None):
    # wx_content_list.txt 路径：与 tool 目录同级
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    content_file = os.path.join(tool_dir, "wx_content_list.txt")

    if not os.path.exists(content_file):
        print(f"[ERROR] 找不到文件: {content_file}")
        sys.exit(1)

    # 1. 获取文本源：优先从 after 文件读（如指定 input_dir 且文件存在），否则回退剪贴板
    clipboard_text = load_text_from_after_html(input_dir)
    source = 'after 文件'
    if not clipboard_text:
        clipboard_text = get_clipboard_text()
        source = '剪贴板'
        if not clipboard_text:
            print("[ERROR] 剪贴板为空或不包含文本")
            print("[TIP] 请先复制一篇文章的文字内容（选中文字后Ctrl+C），再运行此工具")
            sys.exit(1)

    safe_print(f"[INFO] 文本来源: {source}，长度: {len(clipboard_text)} 字")

    # 2. 解析文章列表
    entries = parse_content_list(content_file)
    safe_print(f"[INFO] 读取到 {len(entries)} 个文章条目")

    if len(entries) < 4:
        safe_print(f"[WARN] 条目不足4个（需要至少4个），实际: {len(entries)}")

    # 3. 拼接输出
    output = build_output(clipboard_text, entries)

    # 4. 规范化段落
    output = normalize_paragraphs(output)

    safe_print("\n===== 生成结果 =====")
    safe_print(output)
    safe_print("====================\n")

    # 5. 写回剪贴板
    set_clipboard_text(output)


if __name__ == "__main__":
    # 文本来源开关：
    #   input_dir = None                                   → 读剪贴板（默认行为）
    #   input_dir = fr"content_instance\content_20260708_1" → 从该目录下 process/_debug_clipboard_after.html 读纯文字
    # 想走剪贴板路径 → 把下面写死的那行注释掉；想从文件读 → 保留并改路径
    input_dir = None
    input_dir = fr"content_instance\{DIR_NAME}"
    # input_dir = fr"content_instance\content_20260708_1"  
    

    main(input_dir=input_dir)
