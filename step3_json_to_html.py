# -*- coding: utf-8 -*-
"""
step3_json_to_html.py
=====================
流水线第 4 步：读取 step2 JSON，将段落、标题、图片渲染为 HTML，
替换模板中的 {{BODY_PLACEHOLDER}} 后输出完整页面。

输入：process/step2_table_to_image.json
输出：process/step3_json_to_html.html

模板文件：html_template/caicai_html_1_green_classical.html

渲染规则：
  - heading_level 1（大标题）：跳过，不渲染
  - heading_level 2（小标题）：→ <p class="title">文字</p>
  - 连续正文段落：合并在 <section> 里，每段 <p class="body">
  - bold run：→ <span class="hl">文字</span>
  - image：→ <img src="...">（居中）
  - 元素间单行空行分隔，无连续 empty-line

可单独运行，也可通过 launch.py 串联执行。
"""

import json
import os
import sys

from launch import DIR_NAME

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, 'html_template', 'caicai_html_1_green_classical.html')

# 正文 section 的统一样式
SECTION_STYLE = 'font-size: 18px; line-height: 2; letter-spacing: 1px; box-sizing: border-box;'


# ---------------------------------------------------------------------------
# 元素 → HTML 片段
# ---------------------------------------------------------------------------
def render_runs(runs):
    """将 runs 列表渲染为内联 HTML 字符串"""
    parts = []
    for run in runs:
        text = run['text']
        if run.get('bold'):
            parts.append(f'<span class="hl">{text}</span>')
        else:
            parts.append(text)
    return ''.join(parts)


def render_body_section(paragraphs):
    """将一组连续正文段落包裹在 <section> 里"""
    lines = []
    for p in paragraphs:
        lines.append(f'    <p class="body">{render_runs(p["runs"])}</p>')
        lines.append('    <p class="empty-line"><br></p>')
    return (
        f'  <section style="{SECTION_STYLE}">\n'
        + '\n'.join(lines)
        + '\n  </section>'
    )


def render_title(text):
    """渲染标题"""
    return (
        f'  <p class="title">{text}</p>\n'
        '  <p class="empty-line"><br></p>'
    )


def render_image(image_path):
    """渲染图片（路径统一转为正斜杠）"""
    src = image_path.replace('\\', '/')
    return (
        f'  <p style="text-align: center; margin: 0; padding: 0;">'
        f'<img src="{src}" style="max-width: 90%; vertical-align: middle;"></p>\n'
        '  <p class="empty-line"><br></p>'
    )


# ---------------------------------------------------------------------------
# 正文 HTML 生成
# ---------------------------------------------------------------------------
def generate_body_html(elements):
    """将 JSON elements 转为正文区 HTML 片段"""
    parts = []
    body_group = []

    def flush_body():
        nonlocal body_group
        if body_group:
            parts.append(render_body_section(body_group))
            body_group = []

    for elem in elements:
        etype = elem['type']

        if etype == 'paragraph':
            heading = elem.get('heading_level')
            if heading == 2:
                flush_body()
                title_text = elem['runs'][0]['text'] if elem['runs'] else ''
                parts.append(render_title(title_text))
            elif heading == 1:
                # 大标题不渲染到正文
                flush_body()
            else:
                body_group.append(elem)

        elif etype == 'image':
            flush_body()
            parts.append(render_image(elem['image_path']))

    flush_body()
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(json_path=None):
    # 未传值 → 派生自 DIR_NAME
    if json_path is None:
        json_path = fr"content_instance\{DIR_NAME}\process\step2_table_to_image.json"

    if not os.path.isfile(json_path):
        print(f"[ERROR] JSON 文件不存在: {json_path}")
        sys.exit(1)

    # 输出到 JSON 同目录
    process_dir = os.path.dirname(os.path.abspath(json_path))

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        template = f.read()

    body_html = generate_body_html(data['elements'])
    html_content = template.replace('{{BODY_PLACEHOLDER}}', body_html)

    output_path = os.path.join(process_dir, 'step3_json_to_html.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"[DONE] 正文 HTML 已生成: {output_path}")


if __name__ == '__main__':
    # 默认让 main() 自行派生（fr"content_instance\{DIR_NAME}\process\step2_table_to_image.json"）
    # 若要指定别的目录/文件：保留下面显式行并改路径；不需要覆盖时把它注释掉即可
    json_path = None
    json_path = fr"content_instance\content_20260715_1\process\step2_table_to_image.json"
    main(json_path)
