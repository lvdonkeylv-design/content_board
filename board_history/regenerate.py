# -*- coding: utf-8 -*-
"""
regenerate.py
=============
从已编辑的 config.json 重新生成剪贴板数据文件夹中的二进制文件和 manifest.json，
使修改后的内容可以通过 restore_clipboard.py 恢复到剪贴板。

Usage:
    python regenerate.py <clipboard_data_dir>

示例:
    python regenerate.py content_20260629
"""

import os
import sys
import json

# 导入 docx_to_clipboard 中的核心函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docx_to_clipboard import (
    generate_html_from_config,
    build_clipboard_html,
    build_clipboard_data,
)


def regenerate(data_dir):
    config_path = os.path.join(data_dir, "config.json")
    if not os.path.isfile(config_path):
        print(f"[ERROR] config.json not found in: {data_dir}")
        print("        Run docx_to_clipboard.py first to generate the initial data.")
        sys.exit(1)

    # 1) Read config
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    print(f"[INFO] Loaded config with {len(config)} entries from: {config_path}")

    # 2) Validate config entries
    for i, entry in enumerate(config):
        if "type" not in entry:
            print(f"  [WARN] Entry {i} missing 'type', defaulting to 'body'")
            entry["type"] = "body"
        if "text" not in entry:
            entry["text"] = ""
        if "html_override" not in entry:
            entry["html_override"] = ""
        if entry["type"] not in ("title", "heading", "body", "empty"):
            print(f"  [WARN] Entry {i} has unknown type '{entry['type']}', "
                  "valid types: title, heading, body, empty")

    # 3) Regenerate HTML
    fragment = generate_html_from_config(config)
    html_bin = build_clipboard_html(fragment)

    # 4) Rebuild plain text
    plain_text = "\r\n\r\n".join(
        e["text"] for e in config if e.get("text", "").strip() and e["type"] != "empty"
    )

    # 5) Rewrite clipboard binary files + manifest
    manifest = build_clipboard_data(html_bin, plain_text, data_dir)

    # 6) Save updated config back (normalise any fields the user might have dropped)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\n[DONE] Regenerated {len(manifest)} format file(s) in: {data_dir}")
    print(f"       You can now run: python restore_clipboard.py \"{data_dir}\"")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python regenerate.py <clipboard_data_dir>")
        sys.exit(1)
    regenerate(sys.argv[1])
