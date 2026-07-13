# -*- coding: utf-8 -*-
"""
launch.py
=========
Word 文档 → 剪贴板 一键流水线。

只需指定 Word 文件路径，自动执行以下步骤：
  step1_1  Word → JSON（段落/表格/图片）
  step1_2  LLM 拆分过长段落
  step1_3  LLM 添加总结性加粗标识
  step2_1  JSON 中的表格 → HTML 文件
  step2_2  表格 HTML → PNG 截图 + JSON 中 table 替换为 image
  step3    最终 JSON → 渲染到 HTML 模板
  step4    HTML → 剪贴板（图片自动 base64 内嵌）
  step5    封面图片裁剪为 2.35:1
  step6    推送到微信公众号草稿箱

跳过步骤：将对应的 SKIP 标志设为 True 即可。
使用方法：修改 if __name__ 块的 input_path，直接运行。
"""

import json
import os
import sys
import time


# ===== 跳过控制 =====
SKIP_STEP1_1 = False  # Word → JSON
SKIP_STEP1_2 = False  # LLM 拆分过长段落
SKIP_STEP1_3 = False  # LLM 添加总结性加粗
SKIP_STEP2_1 = False  # 表格 → HTML
SKIP_STEP2_2 = False  # HTML → PNG + JSON 替换
SKIP_STEP3   = False  # JSON → HTML 模板渲染
SKIP_STEP4   = False  # HTML → 剪贴板
SKIP_STEP5   = False  # 封面图片裁剪 2.35:1
SKIP_STEP6   = False  # 推送到公众号草稿箱

TOTAL_STEPS = 9


def run_pipeline(input_path):
    """执行完整流水线"""
    if not os.path.isfile(input_path):
        print(f"[ERROR] 文件不存在: {input_path}")
        sys.exit(1)

    # 派生所有路径
    input_dir = os.path.dirname(os.path.abspath(input_path))
    process_dir = os.path.join(input_dir, 'process')
    table_dir = os.path.join(process_dir, 'table')

    step1_1_json = os.path.join(process_dir, 'step1_1_docx_to_json.json')
    step1_2_json = os.path.join(process_dir, 'step1_2_split_paragraphs.json')
    step1_3_json = os.path.join(process_dir, 'step1_3_bold_paragraphs.json')
    step2_json   = os.path.join(process_dir, 'step2_table_to_image.json')
    step3_html   = os.path.join(process_dir, 'step3_json_to_html.html')

    os.makedirs(process_dir, exist_ok=True)
    os.makedirs(table_dir, exist_ok=True)

    print(f"{'='*60}")
    print(f"  Word → 剪贴板 流水线")
    print(f"  输入: {os.path.basename(input_path)}")
    print(f"  输出目录: {process_dir}")
    print(f"{'='*60}\n")

    total_start = time.time()

    # ---- step1_1: Word → JSON ----
    if not SKIP_STEP1_1:
        print(f"{'─'*60}")
        print(f"[STEP 1/{TOTAL_STEPS}] Word → JSON")
        print(f"{'─'*60}")
        from step1_1_docx_to_json import main as step1_1_main
        step1_1_main(input_path)
        print()
    else:
        print(f"[STEP 1/{TOTAL_STEPS}] 已跳过\n")

    # ---- step1_2: LLM 拆分过长段落 ----
    if not SKIP_STEP1_2:
        print(f"{'─'*60}")
        print(f"[STEP 2/{TOTAL_STEPS}] LLM 拆分过长段落")
        print(f"{'─'*60}")
        from step1_2_split_long_paragraphs import main as step1_2_main
        step1_2_main(step1_1_json, step1_2_json)
        print()
    else:
        print(f"[STEP 2/{TOTAL_STEPS}] 已跳过\n")

    # ---- step1_3: LLM 添加总结性加粗 ----
    if not SKIP_STEP1_3:
        print(f"{'─'*60}")
        print(f"[STEP 3/{TOTAL_STEPS}] LLM 添加总结性加粗")
        print(f"{'─'*60}")
        from step1_3_bold_paragraphs import main as step1_3_main
        bold_input = step1_2_json if not SKIP_STEP1_2 else step1_1_json
        step1_3_main(bold_input, step1_3_json)
        print()
    else:
        print(f"[STEP 3/{TOTAL_STEPS}] 已跳过\n")

    # 下游步骤使用最终 JSON（按跳过情况逐级回退）
    if not SKIP_STEP1_3:
        active_json = step1_3_json
    elif not SKIP_STEP1_2:
        active_json = step1_2_json
    else:
        active_json = step1_1_json

    # ---- 自动检测是否有表格 ----
    has_tables = False
    if os.path.isfile(active_json):
        with open(active_json, 'r', encoding='utf-8') as f:
            _data = json.load(f)
        has_tables = any(e.get('type') == 'table' for e in _data.get('elements', []))
    if not has_tables:
        print(f"[INFO] JSON 中无表格元素，跳过 step2_1 / step2_2\n")

    # ---- step2_1: 表格 → HTML ----
    if has_tables and not SKIP_STEP2_1:
        print(f"{'─'*60}")
        print(f"[STEP 4/{TOTAL_STEPS}] 表格 JSON → HTML 文件")
        print(f"{'─'*60}")
        from step2_1_table_to_html import main as step2_1_main
        step2_1_main(active_json)
        print()
    else:
        print(f"[STEP 4/{TOTAL_STEPS}] 已跳过\n")

    # ---- step2_2: HTML → PNG + JSON 替换 ----
    if has_tables and not SKIP_STEP2_2:
        print(f"{'─'*60}")
        print(f"[STEP 5/{TOTAL_STEPS}] 表格 HTML → PNG + JSON table→image")
        print(f"{'─'*60}")
        from step2_2_html_to_image import main as step2_2_main
        step2_2_main(table_dir, active_json)
        print()
    else:
        print(f"[STEP 5/{TOTAL_STEPS}] 已跳过\n")

    # step3 使用的 JSON：有表格用 step2 输出，无表格直接用 active_json
    step3_input = step2_json if has_tables else active_json

    # ---- step3: JSON → HTML 模板渲染 ----
    if not SKIP_STEP3:
        print(f"{'─'*60}")
        print(f"[STEP 6/{TOTAL_STEPS}] JSON → HTML 模板渲染")
        print(f"{'─'*60}")
        from step3_json_to_html import main as step3_main
        step3_main(step3_input)
        print()
    else:
        print(f"[STEP 6/{TOTAL_STEPS}] 已跳过\n")

    # ---- step4: HTML → 剪贴板 ----
    if not SKIP_STEP4:
        print(f"{'─'*60}")
        print(f"[STEP 7/{TOTAL_STEPS}] HTML → 剪贴板（图片 base64 内嵌）")
        print(f"{'─'*60}")
        from step4_upload_clipboard import main as step4_main
        step4_main(step3_html)
        print()
    else:
        print(f"[STEP 7/{TOTAL_STEPS}] 已跳过\n")

    # ---- step5: 封面图片裁剪 2.35:1 ----
    if not SKIP_STEP5:
        print(f"{'─'*60}")
        print(f"[STEP 8/{TOTAL_STEPS}] 封面图片裁剪 2.35:1")
        print(f"{'─'*60}")
        from step5_crop_cover import main as step5_main
        step5_main(input_dir)
        print()
    else:
        print(f"[STEP 8/{TOTAL_STEPS}] 已跳过\n")

    # ---- step6: 推送到公众号草稿箱 ----
    if not SKIP_STEP6:
        print(f"{'─'*60}")
        print(f"[STEP 9/{TOTAL_STEPS}] 推送到公众号草稿箱")
        print(f"{'─'*60}")
        from step6_push_draft import main as step6_main
        step6_main(input_dir)
        print()
    else:
        print(f"[STEP 9/{TOTAL_STEPS}] 已跳过\n")

    elapsed = time.time() - total_start
    print(f"{'='*60}")
    print(f"  全部完成！耗时 {elapsed:.1f} 秒")
    print(f"{'='*60}")


if __name__ == '__main__':
    # ---- 手动修改 Word 文件路径 ----
    # input_path = r"content_instance\content_20260703_1\众邦银行被接管_7426.docx"
    input_path = r"content_instance\content_20260710_1\抵押物变库存，宁夏银行开店卖房_8141.docx"
    run_pipeline(input_path)
