# -*- coding: utf-8 -*-
"""
step2_1_table_to_html.py
========================
流水线第 2 步：读取 step1 JSON 中的表格元素，
按绿色主题模板生成独立 HTML 文件。

输入：process/step1_docx_to_json.json
输出：process/table/table_{n}.html

模板文件：html_template/caicai_html_1_green_table.html
占位符：{{TABLE_PLACEHOLDER}} 会被替换为 <table> 内容。
表格第一行作为 <thead>，其余行作为 <tbody>。

可单独运行，也可通过 launch.py 串联执行。
"""

import json
import os
import sys


# ---------------------------------------------------------------------------
# 模板路径
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, 'html_template', 'caicai_html_1_green_table.html')


# ---------------------------------------------------------------------------
# HTML 生成
# ---------------------------------------------------------------------------
def load_template():
    """读取 HTML 模板文件"""
    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def generate_table_tag(table_data):
    """根据表格数据生成 <table>...</table> 片段"""
    rows = table_data['data']
    if not rows:
        return None

    header_cells = rows[0]
    body_rows = rows[1:]

    # 表头
    th_html = ''.join(
        f'<th>{cell["text"]}</th>' for cell in header_cells
    )

    # 表体
    tbody_lines = []
    for row in body_rows:
        tds = ''.join(
            f'<td{" class=\"bold\"" if cell["bold"] else ""}>{cell["text"]}</td>'
            for cell in row
        )
        tbody_lines.append(f'      <tr>{tds}</tr>')
    tbody_html = '\n'.join(tbody_lines)

    return (
        '    <table>\n'
        f'      <thead><tr>{th_html}</tr></thead>\n'
        f'      <tbody>\n{tbody_html}\n      </tbody>\n'
        '    </table>'
    )


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(json_path):
    if not os.path.isfile(json_path):
        print(f"[ERROR] JSON 文件不存在: {json_path}")
        sys.exit(1)

    # 输出目录：process/table/
    process_dir = os.path.dirname(os.path.abspath(json_path))
    table_dir = os.path.join(process_dir, 'table')
    os.makedirs(table_dir, exist_ok=True)

    # 读取 JSON
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 筛选表格元素
    tables = [e for e in data['elements'] if e['type'] == 'table']
    if not tables:
        print("[INFO] 未找到表格元素")
        return

    print(f"[INFO] 找到 {len(tables)} 个表格，开始生成 HTML...")

    # 加载模板
    template = load_template()

    for i, table in enumerate(tables, start=1):
        print(f"[INFO] 处理表格 {i}/{len(tables)} "
              f"({table['row_count']}行 x {table['col_count']}列)")

        table_tag = generate_table_tag(table)
        if not table_tag:
            print(f"[WARN] 表格 {i} 为空，跳过")
            continue

        # 模板 + 替换占位符
        html_content = template.replace('{{TABLE_PLACEHOLDER}}', table_tag)

        # 保存 HTML
        html_path = os.path.join(table_dir, f'table_{i}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"[OK]   table_{i}.html")

    print(f"[DONE] 共生成 {len(tables)} 个 HTML，输出目录: {table_dir}")


if __name__ == '__main__':
    # ---- 手动修改输入路径 ----
    json_path = r"content_instance\content_20260708_1\process\step1_3_bold_paragraphs.json"
    main(json_path)
