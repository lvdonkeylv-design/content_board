# -*- coding: utf-8 -*-
"""
step1_docx_to_json.py
=====================
流水线第 1 步：解析 Word 文档（.docx），提取段落、表格、图片，
输出结构化 JSON。

输入：Word 文件路径（.docx）
输出：process/step1_docx_to_json.json
      process/images/image_{n}.png

段落结构：{ type, heading_level, runs: [{text, bold}] }
表格结构：{ type, row_count, col_count, data: [[{text, bold}]] }
图片结构：{ type, file_name, image_path }

标题识别：# 开头 → heading_level=1，## 开头 → heading_level=2
空段落自动过滤，bold 字段支持样式继承检测。

可单独运行，也可通过 launch.py 串联执行。
"""

import json
import os
import sys
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import Table
from launch import DIR_NAME

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def is_run_bold(run):
    """判断单个 run 是否加粗（含样式继承）"""
    if run.bold:
        return True
    rpr = run._element.find(qn('w:rPr'))
    if rpr is not None:
        b = rpr.find(qn('w:b'))
        if b is not None:
            val = b.get(qn('w:val'))
            return val is None or val.lower() not in ('0', 'false')
    return False


def extract_images(element, doc, image_counter):
    """从 XML 元素中提取所有内联图片，返回 [(file_name, image_bytes), ...]"""
    images = []
    for drawing in element.findall('.//' + qn('w:drawing')):
        for tag in ('wp:inline', 'wp:anchor'):
            for inline in drawing.findall('.//' + qn(tag)):
                blip = inline.find('.//' + qn('a:blip'))
                if blip is None:
                    continue
                rId = blip.get(qn('r:embed'))
                if not rId:
                    continue
                try:
                    rel = doc.part.rels[rId]
                    image_part = rel.target_part
                    ext = image_part.content_type.split('/')[-1]
                    if ext == 'jpeg':
                        ext = 'jpg'
                    image_counter[0] += 1
                    images.append((f"image_{image_counter[0]}.{ext}", image_part.blob))
                except (KeyError, AttributeError):
                    continue
    return images


# ---------------------------------------------------------------------------
# 元素构建
# ---------------------------------------------------------------------------
def build_paragraph(paragraph):
    """
    解析段落元素，返回结构化 dict。
    - 标题（#/## 前缀）：去掉前缀，heading_level 设为 1 或 2，runs 统一 bold:false
    - 普通正文：heading_level 为 null，runs 保留原始加粗分析
    """
    text = paragraph.text or ''
    heading_level = None

    # 标题识别：## 优先于 # 检测（## 更长，必须先匹配）
    if text.startswith('##'):
        heading_level = 2
        text = text[3:] if text.startswith('## ') else text[2:]
    elif text.startswith('#'):
        heading_level = 1
        text = text[2:] if text.startswith('# ') else text[1:]

    # 构建 runs 片段列表
    if heading_level is not None:
        # 标题段落：单片段，不分析加粗
        runs = [{'text': text, 'bold': False}]
    else:
        # 普通正文：合并相邻且 bold 状态相同的 run
        runs = []
        for run in paragraph.runs:
            t = run.text
            if not t:
                continue
            b = is_run_bold(run)
            if runs and runs[-1]['bold'] == b:
                runs[-1]['text'] += t
            else:
                runs.append({'text': t, 'bold': b})

    return {
        'type': 'paragraph',
        'heading_level': heading_level,
        'runs': runs,
    }


def _is_row_merged_title(row):
    """判断该行是否是横向合并跨越全部列的合并单元格标题行。

    python-docx 对于横向合并的行，row.cells 会把同一个底层 <w:tc> 重复返回。
    因此当该行所有 cell._tc 指向同一个元素时，即为跨全列合并的标题行。
    """
    cells = row.cells
    if len(cells) < 2:
        return False
    first_tc = cells[0]._tc
    return all(c._tc is first_tc for c in cells)


def _cell_bold(cell):
    """检测单元格首个非空 run 是否加粗"""
    for p in cell.paragraphs:
        for run in p.runs:
            if run.text and run.text.strip():
                return is_run_bold(run)
    return False


def build_table(table):
    """解析表格元素，返回结构化 dict。
    若首行是跨全列合并的单元格，会作为 title 字段单独提取（不进入 data）。
    """
    rows = list(table.rows)

    title = None
    title_bold = False
    # 检测首行是否为合并标题
    if rows and _is_row_merged_title(rows[0]):
        first_cell = rows[0].cells[0]
        title_text = (first_cell.text or '').strip()
        if title_text:
            title = title_text
            title_bold = _cell_bold(first_cell)
            rows = rows[1:]  # 剩余行作为常规表格

    data = []
    for row in rows:
        row_data = []
        for cell in row.cells:
            cell_text = cell.text or ''
            cell_bold = _cell_bold(cell)
            row_data.append({'text': cell_text, 'bold': cell_bold})
        data.append(row_data)

    result = {
        'type': 'table',
        'row_count': len(data),
        'col_count': len(data[0]) if data else 0,
        'data': data,
    }
    if title:
        result['title'] = title
        result['title_bold'] = title_bold
    return result


# ---------------------------------------------------------------------------
# 核心解析：按文档顺序遍历所有元素
# ---------------------------------------------------------------------------
def parse_docx(docx_path, images_dir):
    """按文档原始顺序遍历段落、表格、图片，返回 elements 列表"""
    doc = Document(docx_path)
    image_counter = [0]
    elements = []
    index = 0

    for child in doc.element.body:
        tag = child.tag

        # ---- 段落 ----
        if tag == qn('w:p'):
            # 先提取段落内嵌的图片
            for img_name, img_blob in extract_images(child, doc, image_counter):
                elements.append({
                    'index': index,
                    'type': 'image',
                    'file_name': img_name,
                    'image_path': os.path.join('process', 'images', img_name),
                })
                with open(os.path.join(images_dir, img_name), 'wb') as f:
                    f.write(img_blob)
                index += 1

            # 再处理段落本身
            elem = build_paragraph(Paragraph(child, doc))
            if not elem['runs'] or not any(r['text'] for r in elem['runs']):
                continue
            elem['index'] = index
            elements.append(elem)
            index += 1

        # ---- 表格 ----
        elif tag == qn('w:tbl'):
            elem = build_table(Table(child, doc))
            elem['index'] = index
            elements.append(elem)
            index += 1

    return elements


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(input_path=None):
    # 未传值 → 默认 content_instance\{DIR_NAME}
    if input_path is None:
        input_path = fr"content_instance\{DIR_NAME}"
    # 如果传入的是文件夹，自动找第一个 .docx 文件
    if os.path.isdir(input_path):
        docx_files = sorted([
            f for f in os.listdir(input_path)
            if f.lower().endswith('.docx') and not f.startswith('~')
        ])
        if not docx_files:
            print(f"[ERROR] 文件夹中没有找到 .docx 文件: {input_path}")
            sys.exit(1)
        input_path = os.path.join(input_path, docx_files[0])
        print(f"[INFO] 自动选择: {docx_files[0]}")
    if not os.path.isfile(input_path):
        print(f"[ERROR] 文件不存在: {input_path}")
        sys.exit(1)
    if not input_path.lower().endswith('.docx'):
        print("[ERROR] 仅支持 .docx 格式文件")
        sys.exit(1)

    # 输出路径：输入文件所在目录 / process /
    input_dir = os.path.dirname(os.path.abspath(input_path))
    process_dir = os.path.join(input_dir, 'process')
    os.makedirs(process_dir, exist_ok=True)
    output_path = os.path.join(process_dir, 'step1_1_docx_to_json.json')

    images_dir = os.path.join(process_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    print(f"[INFO] 解析文档: {input_path}")
    elements = parse_docx(input_path, images_dir)

    result = {
        'file_name': os.path.basename(input_path),
        'total_elements': len(elements),
        'elements': elements,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 统计各类型数量
    stats = {}
    for e in elements:
        stats[e['type']] = stats.get(e['type'], 0) + 1
    stats_str = ', '.join(f'{k}: {v}' for k, v in sorted(stats.items()))
    print(f"[INFO] 共解析 {len(elements)} 个元素 ({stats_str})")
    print(f"[INFO] 输出文件: {output_path}")
    print("[DONE]")


if __name__ == '__main__':
    # 不传参 → 使用 launch.DIR_NAME 派生的默认路径；也可传入文件夹或 .docx 路径
    # input_path = fr"content_instance\{DIR_NAME}"
    main()
