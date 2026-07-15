# -*- coding: utf-8 -*-
"""
step6_push_draft.py
====================
流水线第 9 步：将生成的 HTML 内容推送到微信公众号草稿箱。

输入：
  - process/step1_3_bold_paragraphs.json  （提取正文生成摘要，回退 step1_2/step1_1）
  - process/step1_1_docx_to_json.json     （提取标题，heading_level=1）
  - process/step5_crop_cover.*            （封面图，step5 裁剪后）

推送字段：
  - title：从 step1_1 JSON 取一级标题
  - author：config.WX_AUTHOR（默认"菜菜"）
  - content：空字符串（占位）
  - thumb_media_id：上传 step5 封面图后获取
  - digest：调用大模型从正文中提取金句摘要
  - content_source_url：config.WX_CONTENT_SOURCE_URL
  - need_open_comment / only_fans_can_comment：config 配置

依赖：pip install requests
可单独运行，也可通过 launch.py 串联执行。
"""

import json
import os
import sys
import time
import requests

from config import (
    WX_APP_ID, WX_APP_SECRET, WX_API_BASE,
    WX_AUTHOR, WX_CONTENT_SOURCE_URL,
    WX_NEED_OPEN_COMMENT, WX_ONLY_FANS_COMMENT,
    API_URL, HEADERS, MAX_RETRIES, MAX_TOKENS,
)
from launch import DIR_NAME


# ---------------------------------------------------------------------------
# access_token
# ---------------------------------------------------------------------------
def get_access_token():
    """通过 AppID + AppSecret 获取 access_token"""
    url = f'{WX_API_BASE}/token'
    params = {
        'grant_type': 'client_credential',
        'appid': WX_APP_ID,
        'secret': WX_APP_SECRET,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if 'access_token' not in data:
        raise RuntimeError(f"获取 access_token 失败: {data}")
    print(f"[INFO] access_token 获取成功（有效期 {data.get('expires_in', '?')}s）")
    return data['access_token']


# ---------------------------------------------------------------------------
# 上传永久素材（封面图）
# ---------------------------------------------------------------------------
def upload_permanent_image(access_token, image_path):
    """上传永久图片素材，返回 media_id"""
    url = f'{WX_API_BASE}/material/add_material'
    params = {
        'access_token': access_token,
        'type': 'image',
    }
    with open(image_path, 'rb') as f:
        files = {'media': (os.path.basename(image_path), f, 'image/jpeg')}
        resp = requests.post(url, params=params, files=files, timeout=60)

    resp.raise_for_status()
    data = resp.json()
    if 'media_id' not in data:
        raise RuntimeError(f"上传封面图失败: {data}")

    print(f"[INFO] 封面图上传成功: media_id={data['media_id']}")
    return data['media_id']


# ---------------------------------------------------------------------------
# 从 step1_1 JSON 提取标题
# ---------------------------------------------------------------------------
_WX_TITLE_MAX_BYTES = 64  # 微信草稿 API 标题上限（UTF-8 字节）


def _truncate_to_byte_limit(text, max_bytes=_WX_TITLE_MAX_BYTES):
    """将文本截断到指定 UTF-8 字节数以内，不拆散单个字符"""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    # 逐字符累加字节，找到最大可容纳长度
    truncated = ''
    current_bytes = 0
    for ch in text:
        ch_bytes = len(ch.encode('utf-8'))
        if current_bytes + ch_bytes > max_bytes:
            break
        truncated += ch
        current_bytes += ch_bytes
    return truncated.rstrip()


def extract_title(json_path):
    """从 step1_1_docx_to_json.json 中提取 heading_level=1 的标题"""
    if not os.path.isfile(json_path):
        print(f"[WARN] JSON 文件不存在: {json_path}")
        return None

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for elem in data.get('elements', []):
        if (elem.get('type') == 'paragraph'
                and elem.get('heading_level') == 1):
            title = ''.join(r['text'] for r in elem.get('runs', []))
            title = title.strip()
            if title:
                original_len = len(title.encode('utf-8'))
                if original_len > _WX_TITLE_MAX_BYTES:
                    title = _truncate_to_byte_limit(title)
                    print(f"[WARN] 标题超长({original_len}字节)，已截断为: {title}")
                return title

    print("[WARN] 未找到 heading_level=1 的标题")
    return '无标题'


# ---------------------------------------------------------------------------
# 查找封面图文件
# ---------------------------------------------------------------------------
def find_cover_image(process_dir):
    """在 process 目录下找到 step5_crop_cover.* 文件"""
    for name in sorted(os.listdir(process_dir)):
        if name.startswith('step5_crop_cover'):
            path = os.path.join(process_dir, name)
            if os.path.isfile(path):
                return path
    return None


# ---------------------------------------------------------------------------
# 从 JSON 提取纯文本正文（供大模型生成摘要用）
# ---------------------------------------------------------------------------
def extract_body_text(json_path):
    """从 step1_3_bold_paragraphs.json 提取所有段落文本，拼接为正文。

    - 只处理 type=paragraph 的元素
    - heading_level > 0 的标题段落前后加空行，保持结构可读
    - 忽略 type=table / type=image 等非段落元素
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    elements = data.get('elements', [])
    lines = []

    for elem in elements:
        if elem.get('type') != 'paragraph':
            # 跳过表格、图片等非段落元素
            continue

        # 提取 runs 中所有 text
        text = ''.join(r['text'] for r in elem.get('runs', [])).strip()
        if not text:
            continue

        heading_level = elem.get('heading_level')

        if heading_level and heading_level >= 1:
            # 标题段落：前后加空行，使结构清晰
            if lines:
                lines.append('')
            lines.append(text)
            lines.append('')
        else:
            # 普通正文段落：每段一行
            lines.append(text)

    body = '\n'.join(lines).strip()
    return body


# ---------------------------------------------------------------------------
# 大模型调用（与 step1_2 / step1_3 一致的 call_model 封装）
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


# ---------------------------------------------------------------------------
# 调用大模型生成摘要金句
# ---------------------------------------------------------------------------
DIGEST_PROMPT = """请从以下文章正文中找出一句最精炼、最有概括力或最生动的原文语句，作为文章摘要或金句。

## 要求
1. 必须是文章中的**原文语句**，不得改写
2. 字数尽量简短，但至少 20 字，不超过100字
3. 能点出全文核心矛盾或反差感
4. 只输出这一句话，不要输出任何解释、引号或前缀
5. 如果总结不出来，返回不知道"""


def generate_digest(plain_text):
    """调用大模型从正文中提取摘要金句"""
    # 正文过长时截断（避免超出模型上下文窗口）
    max_input_chars = 15000
    if len(plain_text) > max_input_chars:
        print(f"  [INFO] 正文过长({len(plain_text):,}字符)，截取前 {max_input_chars:,} 字符")
        plain_text = plain_text[:max_input_chars]

    prompt = f"{DIGEST_PROMPT}\n\n## 文章正文\n\n{plain_text}"
    print(f"  [INFO] prompt 长度: {len(prompt):,} 字符")

    response = call_model(API_URL, HEADERS, MAX_TOKENS, prompt)
    if not response:
        return None

    content = response.strip()
    # 去除可能的引号
    if content.startswith(('"', '"', '"')) and content.endswith(('"', '"', '"')):
        content = content[1:-1]
    return content if content else None


# ---------------------------------------------------------------------------
# 推送草稿
# ---------------------------------------------------------------------------
def push_draft(access_token, article):
    """调用草稿箱 API 新增草稿"""
    url = f'{WX_API_BASE}/draft/add'
    params = {'access_token': access_token}
    payload = {'articles': [article]}

    # 手动 JSON 编码，确保中文不被转义为 \uXXXX
    json_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type': 'application/json; charset=utf-8'}

    resp = requests.post(url, params=params, data=json_bytes, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if 'media_id' not in data:
        raise RuntimeError(f"推送草稿失败: {data}")

    print(f"[INFO] 草稿推送成功! media_id={data['media_id']}")
    return data['media_id']


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(input_dir=None,
         step1_1_json=None,
         process_dir=None):
    """
    推送到公众号草稿箱。
    input_dir:   文章实例目录（如 content_instance/content_20260710_1）
                 未传值 → 默认 content_instance\\{DIR_NAME}
    step1_1_json: step1_1 JSON 路径（可选，默认自动派生）
    process_dir: process 目录（可选，默认自动派生）
    """
    if input_dir is None:
        input_dir = fr"content_instance\{DIR_NAME}"

    if not WX_APP_ID or not WX_APP_SECRET:
        print("[ERROR] 请先在 config.py 中填写 WX_APP_ID 和 WX_APP_SECRET")
        sys.exit(1)

    # 自动派生路径
    if process_dir is None:
        process_dir = os.path.join(input_dir, 'process')
    if step1_1_json is None:
        step1_1_json = os.path.join(process_dir, 'step1_1_docx_to_json.json')

    # ---- 1. 获取 access_token ----
    print(f"{'─'*60}")
    print("[STEP 1/5] 获取 access_token")
    access_token = get_access_token()

    # ---- 2. 提取标题 ----
    print(f"{'─'*60}")
    print("[STEP 2/5] 提取标题")
    title = extract_title(step1_1_json)
    if not title:
        print("[ERROR] 无法获取标题，终止")
        sys.exit(1)
    print(f"[INFO] 标题: {title}")
    print(f"[INFO] 标题字节数: {len(title.encode('utf-8'))} bytes")

    # ---- 3. 上传封面图 ----
    print(f"{'─'*60}")
    print("[STEP 3/5] 上传封面图")
    thumb_cache_path = os.path.join(process_dir, 'step6_thumb_media_id.txt')
    if os.path.isfile(thumb_cache_path):
        thumb_media_id = open(thumb_cache_path, 'r').read().strip()
        print(f"[INFO] 使用缓存封面 media_id: {thumb_media_id}")
    else:
        cover_path = find_cover_image(process_dir)
        if not cover_path:
            print("[ERROR] 未找到封面图（step5_crop_cover.*），请先运行 step5")
            sys.exit(1)
        print(f"[INFO] 封面图: {cover_path}")
        thumb_media_id = upload_permanent_image(access_token, cover_path)
        # 缓存 media_id
        with open(thumb_cache_path, 'w') as f:
            f.write(thumb_media_id)
        print(f"[INFO] 已缓存 media_id 到 {thumb_cache_path}")

    # ---- 4. 生成摘要 ----
    print(f"{'─'*60}")
    print("[STEP 4/5] 提取正文并生成摘要金句")
    # 按优先级查找输入 JSON：step1_3 > step1_2 > step1_1
    digest_candidates = [
        os.path.join(process_dir, 'step1_3_bold_paragraphs.json'),
        os.path.join(process_dir, 'step1_2_split_paragraphs.json'),
        step1_1_json,
    ]
    body_json = None
    for path in digest_candidates:
        if os.path.isfile(path):
            body_json = path
            break

    digest = ''
    if body_json:
        print(f"[INFO] 正文来源: {os.path.basename(body_json)}")
        body_text = extract_body_text(body_json)
        print(f"[INFO] 正文长度: {len(body_text):,} 字符")
        digest = generate_digest(body_text) or ''
        # 微信摘要上限 128 字，截断保护
        if len(digest) > 128:
            digest = digest[:128]
    else:
        print("[WARN] 未找到正文 JSON，跳过摘要生成")

    if digest:
        print(f"[INFO] 摘要: {digest}")
    else:
        print("[WARN] 无摘要，将使用微信默认")

    # ---- 5. 推送草稿 ----
    print(f"{'─'*60}")
    print("[STEP 5/5] 推送草稿")

    article = {
        'title': title,
        'author': WX_AUTHOR,
        'content': '空',
        'thumb_media_id': thumb_media_id,
        'need_open_comment': WX_NEED_OPEN_COMMENT,
        'only_fans_can_comment': WX_ONLY_FANS_COMMENT,
    }
    if digest:
        article['digest'] = digest
    if WX_CONTENT_SOURCE_URL:
        article['content_source_url'] = WX_CONTENT_SOURCE_URL

    # 调试：打印所有字段长度
    for k, v in article.items():
        if k == 'content':
            print(f"[DEBUG] {k}: {len(v):,} chars / {len(v.encode('utf-8')):,} bytes")
        else:
            print(f"[DEBUG] {k}: {repr(v)} ({len(str(v).encode('utf-8'))} bytes)")

    media_id = push_draft(access_token, article)

    print(f"\n{'='*60}")
    print(f"  草稿推送完成!")
    print(f"  标题: {title}")
    print(f"  作者: {WX_AUTHOR}")
    print(f"  摘要: {digest or '(默认)'}")
    print(f"  封面 media_id: {thumb_media_id}")
    print(f"  草稿 media_id: {media_id}")
    print(f"  留言: {'开启' if WX_NEED_OPEN_COMMENT else '关闭'}"
          f"{' (仅粉丝)' if WX_ONLY_FANS_COMMENT else ' (所有人)'}")
    print(f"{'='*60}")
    print("[DONE]")


if __name__ == '__main__':
    # 默认让 main() 自行派生（fr"content_instance\{DIR_NAME}"）
    # 若要指定别的目录：保留下面显式行并改路径；不需要覆盖时把它注释掉即可
    input_dir = None
    input_dir = fr"content_instance\content_20260715_1"
    main(input_dir)
