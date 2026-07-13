# -*- coding: utf-8 -*-
"""
step1_3_bold_paragraphs.py
===========================
流水线第 1.3 步：调用大模型，为正文添加总结/判断性加粗标识。

输入：process/step1_2_split_paragraphs.json（step1_2 的输出）
输出：process/step1_3_bold_paragraphs.json（新文件，不覆盖原文件）

处理逻辑：
- 按标题分段，每组正文（4-5 段左右）交给大模型分析
- 识别总结性、判断性、序列性（第一/第二…）表达，标记为加粗
- 已有加粗的段落跳过
- 没有合适内容则不加，不瞎加
- 只修改 bold 字段，不增删改任何文字

可单独运行，也可通过 launch.py 串联执行。
"""

import json
import os
import sys
import time
import requests

from config import API_URL, HEADERS, MAX_RETRIES, MAX_TOKENS


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------
PROMPT = """你是一个专业的文章结构分析助手。请阅读以下正文段落，找出适合加粗的**总结性、判断性或序列性**表达。

## 什么样的句子适合加粗

- **总结性表达**：对前面几段内容做概括总结的句子
- **判断性表达**：给出观点、结论、定性判断的句子
- **序列性表达**：使用"第一""第二""首先""其次"等引导词的段落开头

## 加粗频率

- 大约每 4~5 个段落出现一处加粗即可
- 如果段落总数少于 5 段，最多加粗 1 处
- **不要加得过密**

## 严格限制

1. 如果某段落已经有加粗内容（标注为 bold=true），**跳过该段落，不要重复加粗**
2. 如果整个段落组中**没有**适合加粗的句子，**不要强行添加**
3. 加粗内容必须是原文中**完整的一句话或几句话**，不能只加粗半句
4. 加粗内容必须与原文**逐字一致**，不得改写
5. 只做加粗标记，不得修改、增加、删除任何原文

## 正文段落

{paragraphs}

## 输出要求

返回一个 JSON 对象，格式为：

{{"index": "要加粗的完整原文句子"}}

- key 是段落索引（字符串，与上面标注一致）
- value 是该段落中需要加粗的**原文句子**（必须逐字匹配）
- 如果整个段落组没有需要加粗的内容，返回空对象：{{}}
- 只输出 JSON，不输出任何解释、说明或代码块标记"""


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def call_model(api_url, headers, max_tokens, prompt, max_retries=MAX_RETRIES):
    """调用大模型，返回响应文本"""
    payload = {
        'max_completion_tokens': max_tokens,
        'messages': [{'role': 'user', 'content': prompt}],
        'stream': False,
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            result = resp.json()
            choices = result.get('choices', [])
            if choices:
                return choices[0].get('message', {}).get('content', '')
            return None
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait = 10 * (attempt + 1)
                print(f'  请求失败，{wait}s 后重试: {e}')
                time.sleep(wait)
            else:
                print(f'  请求最终失败: {e}')
    return None


def parse_json_object(response_text):
    """从响应中解析 JSON 对象"""
    if not response_text:
        return None
    response_text = response_text.strip()

    # 直接解析
    try:
        result = json.loads(response_text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 去除代码块标记
    cleaned = response_text.replace('```json', '').replace('```', '').strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 正则提取对象
    import re
    match = re.search(r'\{[\s\S]*\}', response_text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


def get_paragraph_text(elem):
    """提取段落全部文本"""
    return ''.join(r['text'] for r in elem.get('runs', []))


def has_bold_run(elem):
    """检查段落是否已有加粗 run"""
    return any(r.get('bold', False) for r in elem.get('runs', []))


def apply_bold_to_paragraph(elem, bold_text):
    """将段落中的指定文字设为加粗，返回新的 runs 列表。
    bold_text 必须是段落原文的连续子串。
    """
    full_text = get_paragraph_text(elem)
    runs = elem.get('runs', [])

    # 如果整段都是加粗目标 → 全部标 bold
    if bold_text == full_text:
        return [{'text': r['text'], 'bold': True} for r in runs]

    # 查找 bold_text 在 full_text 中的位置
    pos = full_text.find(bold_text)
    if pos == -1:
        return None  # 找不到匹配

    end_pos = pos + len(bold_text)

    # 将原始 runs 按字符位置展开，标记 bold 区间
    new_runs = []
    cursor = 0
    for run in runs:
        run_start = cursor
        run_end = cursor + len(run['text'])
        cursor = run_end

        # 计算该 run 与 bold 区间的交集
        overlap_start = max(run_start, pos)
        overlap_end = min(run_end, end_pos)

        if overlap_start >= overlap_end:
            # 无交集 → 保持原 bold 状态
            new_runs.append({'text': run['text'], 'bold': run.get('bold', False)})
        else:
            # 有交集 → 拆分为：前缀(原bold) + 交集(True) + 后缀(原bold)
            prefix_len = overlap_start - run_start
            suffix_start = overlap_end - run_start

            if prefix_len > 0:
                new_runs.append({
                    'text': run['text'][:prefix_len],
                    'bold': run.get('bold', False),
                })

            new_runs.append({
                'text': run['text'][prefix_len:suffix_start],
                'bold': True,
            })

            if suffix_start < len(run['text']):
                new_runs.append({
                    'text': run['text'][suffix_start:],
                    'bold': run.get('bold', False),
                })

    return new_runs


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(input_json, output_json=None):
    """读取 step1_2 JSON，添加加粗标识，写入新文件。
    input_json:  输入文件路径（step1_2_split_paragraphs.json）
    output_json: 输出文件路径，默认为同目录 step1_3_bold_paragraphs.json
    """
    if not os.path.isfile(input_json):
        print(f"[ERROR] 文件不存在: {input_json}")
        sys.exit(1)

    # 输出路径：默认同目录 step1_3_bold_paragraphs.json
    if output_json is None:
        output_json = os.path.join(os.path.dirname(input_json), 'step1_3_bold_paragraphs.json')

    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    elements = data['elements']
    _p = lambda s: s.replace('\xa0', ' ')  # NBSP → 普通空格，防止 GBK 报错

    # 按标题分段：收集每组正文段落
    sections = []  # [(body_elems_list, start_idx_in_elements), ...]
    current_body = []

    for i, elem in enumerate(elements):
        is_heading = (elem.get('type') == 'paragraph'
                      and elem.get('heading_level') is not None)
        is_non_paragraph = elem.get('type') not in ('paragraph',)

        if is_heading or is_non_paragraph:
            if current_body:
                sections.append(current_body)
                current_body = []
        else:
            # 普通正文段落
            current_body.append((i, elem))

    if current_body:
        sections.append(current_body)

    print(f"[INFO] 共 {len(sections)} 组正文段落需要分析")

    bold_count = 0
    call_count = 0

    for sec_idx, body_elems in enumerate(sections):
        if len(body_elems) < 2:
            continue  # 太短的段落组跳过

        # 构建发送给 LLM 的段落列表
        para_lines = []
        elem_lookup = {}  # str(index) → (i, elem)
        for i, elem in body_elems:
            idx = str(elem['index'])
            text = get_paragraph_text(elem)
            bold_flag = " [已有加粗]" if has_bold_run(elem) else ""
            para_lines.append(f"[{idx}]{bold_flag} {text}")
            elem_lookup[idx] = (i, elem)

        paragraphs_text = '\n'.join(para_lines)
        prompt = PROMPT.format(paragraphs=paragraphs_text)

        print(f"\n{'='*60}")
        print(f"  [BOLD] 第 {sec_idx + 1} 组 ({len(body_elems)} 段)")
        print(f"{'─'*60}")
        for line in para_lines:
            print(f"    {_p(line)}")
        print(f"{'─'*60}")

        response = call_model(API_URL, HEADERS, MAX_TOKENS, prompt)
        call_count += 1

        if not response:
            print(f"  [WARN] 模型调用失败，跳过本组")
            print(f"{'='*60}")
            continue

        bold_map = parse_json_object(response)
        if not bold_map:
            print(f"  [INFO] 本组无需加粗")
            print(f"{'='*60}")
            continue

        print(f"  [加粗结果] ({len(bold_map)} 处)")
        for idx, bold_text in bold_map.items():
            print(f"    index={idx}")
            print(f"      {_p(bold_text)}")

            if idx not in elem_lookup:
                print(f"      [WARN] index {idx} 不存在，跳过")
                continue

            i, elem = elem_lookup[idx]

            # 已有加粗则跳过
            if has_bold_run(elem):
                print(f"      [SKIP] 已有加粗，不重复处理")
                continue

            # 应用加粗
            new_runs = apply_bold_to_paragraph(elem, bold_text)
            if new_runs is None:
                print(f"      [WARN] 加粗文字在段落中未找到匹配，跳过")
                continue

            elements[i]['runs'] = new_runs
            bold_count += 1
            print(f"      [OK] 已加粗")

        print(f"{'='*60}")

    # 构建输出
    result = {
        'file_name': data.get('file_name', ''),
        'total_elements': len(elements),
        'elements': elements,
    }

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[INFO] 加粗完成: 共 {bold_count} 处（{call_count} 次模型调用）")
    print(f"[INFO] 输入文件: {input_json}")
    print(f"[INFO] 输出文件: {output_json}")
    print("[DONE]")


if __name__ == '__main__':
    # ---- 手动修改输入路径（输出自动存入同目录 step1_3_bold_paragraphs.json）----
    input_json = (
        r"content_instance\content_20260703_1"
        r"\process\step1_2_split_paragraphs.json"
    )
    main(input_json)
