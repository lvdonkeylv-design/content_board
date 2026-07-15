# -*- coding: utf-8 -*-
"""
step1_2_split_long_paragraphs.py
=================================
流水线第 1.2 步：调用大模型，将过长段落拆分为多个短段落。

输入：process/step1_1_docx_to_json.json（step1_1 的输出）
输出：process/step1_2_split_paragraphs.json（新文件，不覆盖原文件）

处理逻辑：
- 遍历所有 paragraph 元素，检查每个 run.text 长度
- 超过阈值（默认 100 字符）时调用大模型按语义拆分
- 拆分后生成多个新 paragraph 元素，index 加 .1/.2 后缀
- 拼接一致性校验：拆分结果拼接后必须与原文一致
- 非段落元素（table/image）原样保留

可单独运行，也可通过 launch.py 串联执行。
"""

import json
import os
import re
import sys
import time
import requests

from config import API_URL, HEADERS, MAX_RETRIES, MAX_TOKENS, SPLIT_THRESHOLD
from launch import DIR_NAME


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------
PROMPT = """你是一个严格的文本段落拆分助手。请将以下过长的正文段落按语义拆分为多个较短的段落。

## 核心原则：语义完整优先

拆分必须以语义为依据，不能机械地按长度切割。
- 一个完整的意思还没讲完，绝对不能拆。
- 必须等到一个观点、一个论述讲完了，才能在它后面切一刀。
- 拆分点应该出现在“上一件事说完了”的地方，而不是“字数到了”的地方。

## 拆分段数参考

根据原文总长度大致确定拆分段数：
- 200 字以内 → 最多拆成 2 段
- 300 字以内 → 最多拆成 3 段
- 以此类推，每段大约 100 字左右

这只是参考，最终以语义完整为准。如果某一段论述必须讲完才能切断，可以稍长或稍短。

## 拆分位置规则

1. 只能在句号（。）、问号（？）、感叹号（！）、分号（；）之后拆分。
2. 不能在句子中间断开。
3. 不能在一个因果、转折、递进关系的中间切开（例如“虽然…但是…”不能在中间切）。
4. 拆分后每段不得少于 15 个字符。如果某段不足 15 字符，必须合并到相邻段落中。

## 铁律：原文一字不改

1. 拆分后所有段落拼接（直接连接，不加任何空格）结果必须与原文完全一致，一字不差。
2. 不得增删改任何原文文字、标点、空格。
3. 拆分后各段内容顺序必须与原文完全一致。

## 待拆分文本

{text}

## 输出要求

返回一个 JSON 数组，每个元素是一个字符串，代表拆分后的一个段落。
只输出 JSON 数组，不输出任何解释、说明或代码块标记。

示例输出：
["第一段内容。", "第二段内容。", "第三段内容。"]"""


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


def parse_json_array(response_text):
    """从响应中解析 JSON 数组"""
    if not response_text:
        return None
    response_text = response_text.strip()

    # 直接解析
    try:
        result = json.loads(response_text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 去除代码块标记
    cleaned = re.sub(r'^```json\s*', '', response_text)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        result = json.loads(cleaned.strip())
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 正则提取数组
    match = re.search(r'\[[\s\S]*\]', response_text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return None


def find_long_runs(runs, threshold):
    """找出超过阈值的 run 索引列表"""
    long_indices = []
    for i, run in enumerate(runs):
        if len(run['text']) > threshold:
            long_indices.append(i)
    return long_indices


def build_split_elements(original_elem, run_idx, split_texts, original_index):
    """
    将某个 run 的拆分结果构建为新的 paragraph 元素列表。
    - 拆分前的 runs 归入第一个新元素（index.1）
    - 拆分后的 runs 归入最后一个新元素（index.N）
    - 每段拆分文本作为单独的新元素
    """
    runs = original_elem['runs']
    elements = []

    # ---- 第一个元素：拆分前的 runs + 第一段拆分文本 ----
    first_runs = list(runs[:run_idx])
    first_runs.append({'text': split_texts[0], 'bold': runs[run_idx]['bold']})
    elements.append({
        'type': 'paragraph',
        'heading_level': None,
        'runs': first_runs,
        'index': f"{original_index}.1",
    })

    # ---- 中间元素：纯拆分文本 ----
    for i, text in enumerate(split_texts[1:-1], start=2):
        elements.append({
            'type': 'paragraph',
            'heading_level': None,
            'runs': [{'text': text, 'bold': runs[run_idx]['bold']}],
            'index': f"{original_index}.{i}",
        })

    # ---- 最后一个元素：最后一段拆分文本 + 拆分后的 runs ----
    last_i = len(split_texts)
    last_runs = [{'text': split_texts[-1], 'bold': runs[run_idx]['bold']}]
    last_runs.extend(runs[run_idx + 1:])
    elements.append({
        'type': 'paragraph',
        'heading_level': None,
        'runs': last_runs,
        'index': f"{original_index}.{last_i}",
    })

    return elements


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(input_json=None, output_json=None):
    """读取 step1_1 JSON，拆分过长段落，写入新文件。
    input_json:  输入文件路径（step1_1_docx_to_json.json）
                 未传值 → 默认 content_instance\\{DIR_NAME}\\process\\step1_1_docx_to_json.json
    output_json: 输出文件路径，默认为同目录 step1_2_split_paragraphs.json
    """
    # 未传值 → 派生自 DIR_NAME
    if input_json is None:
        input_json = fr"content_instance\{DIR_NAME}\process\step1_1_docx_to_json.json"

    if not os.path.isfile(input_json):
        print(f"[ERROR] 文件不存在: {input_json}")
        sys.exit(1)

    # 输出路径：默认同目录 step1_2_split_paragraphs.json
    if output_json is None:
        output_json = os.path.join(os.path.dirname(input_json), 'step1_2_split_paragraphs.json')

    with open(input_json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    elements = data['elements']
    new_elements = []
    split_count = 0
    call_count = 0

    for elem in elements:
        # 非段落元素原样保留
        if elem.get('type') != 'paragraph':
            new_elements.append(elem)
            continue

        # 找出过长的 run
        long_run_indices = find_long_runs(elem['runs'], SPLIT_THRESHOLD)
        if not long_run_indices:
            new_elements.append(elem)
            continue

        # 需要拆分 → 取第一个过长 run 调用大模型
        run_idx = long_run_indices[0]
        long_text = elem['runs'][run_idx]['text']
        original_index = elem['index']

        # 打印拆分前完整段落内容
        full_text = ''.join(r['text'] for r in elem['runs'])
        _p = lambda s: s.replace('\xa0', ' ')  # NBSP → 普通空格，防止 GBK 报错
        print(f"{'='*60}")
        print(f"  [SPLIT] index={original_index}  run[{run_idx}]"
              f"  run_len={len(long_text)}  full_len={len(full_text)}")
        print(f"{'─'*60}")
        print(f"  [拆分前] (runs={len(elem['runs'])})")
        print(f"    {_p(full_text)}")
        print(f"{'─'*60}")

        prompt = PROMPT.format(text=long_text)
        response = call_model(API_URL, HEADERS, MAX_TOKENS, prompt)
        call_count += 1

        if not response:
            print(f"  [WARN] 模型调用失败，保留原段落")
            print(f"{'='*60}")
            new_elements.append(elem)
            continue

        split_texts = parse_json_array(response)
        if not split_texts or len(split_texts) < 2:
            print(f"  [WARN] 拆分结果无效（需至少2段），保留原段落")
            print(f"{'='*60}")
            new_elements.append(elem)
            continue

        # 拼接一致性校验
        joined = ''.join(split_texts)
        if joined != long_text:
            print(f"  [WARN] 拼接不一致 (diff={len(joined) - len(long_text)})，保留原段落")
            print(f"    原文前80字: {long_text[:80]}")
            print(f"    拼接前80字: {joined[:80]}")
            print(f"{'='*60}")
            new_elements.append(elem)
            continue

        # 构建拆分后的元素
        split_elems = build_split_elements(elem, run_idx, split_texts, original_index)
        new_elements.extend(split_elems)
        split_count += 1

        # 打印拆分后结果
        print(f"  [拆分后] ({len(split_elems)} 段)")
        for se in split_elems:
            se_text = ''.join(r['text'] for r in se['runs'])
            print(f"    index={se['index']}  len={len(se_text)}")
            print(f"      {_p(se_text)}")
        print(f"{'='*60}")

    # 构建输出
    result = {
        'file_name': data.get('file_name', ''),
        'total_elements': len(new_elements),
        'elements': new_elements,
    }

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[INFO] 拆分完成: {split_count} 个段落被拆分（共 {call_count} 次模型调用）")
    print(f"[INFO] 元素数: {len(elements)} → {len(new_elements)}")
    print(f"[INFO] 输入文件: {input_json}")
    print(f"[INFO] 输出文件: {output_json}")
    print("[DONE]")


if __name__ == '__main__':
    # 默认让 main() 自行派生（fr"content_instance\{DIR_NAME}\process\step1_1_docx_to_json.json"）
    # 若要指定别的目录/文件：保留下面显式行并改路径；不需要覆盖时把它注释掉即可
    input_json = None
    input_json = fr"content_instance\content_20260715_1\process\step1_1_docx_to_json.json"
    main(input_json)
