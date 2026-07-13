# -*- coding: utf-8 -*-
"""Verify full roundtrip: export → parse → expand → normalize → clipboard formats."""
import os, sys, re, json, base64, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from export_html import (load_clipboard_data, parse_html_format,
                          format_html_fragment, collapse_patterns,
                          html_to_plain_text)
from import_html import (parse_html_file, expand_patterns, normalize_whitespace,
                          build_html_format_binary, extract_plain_text,
                          build_all_formats)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(SCRIPT_DIR, "clipboard_data")
html_path = os.path.join(SCRIPT_DIR, "clipboard_export.html")

# 1) Load original clipboard data
orig_formats = load_clipboard_data(data_dir)
_, _, orig_fragment = parse_html_format(orig_formats["HTML Format"]["raw"])
orig_html_bin = orig_formats["HTML Format"]["raw"]
orig_plain = html_to_plain_text(orig_fragment)
print(f"[1] Original fragment:  {len(orig_fragment):,} chars")
print(f"[1] Original HTML bin:  {len(orig_html_bin):,} bytes")

# 2) Parse the export HTML file (same as import_html.py does)
content_fragment, raw_formats, original_fragment, original_plain_text = parse_html_file(html_path)
print(f"\n[2] Article content:   {len(content_fragment):,} chars")
print(f"[2] Original fragment stored: {original_fragment is not None}")

# 3) Expand + normalize
expanded = expand_patterns(content_fragment)
normalized = normalize_whitespace(expanded)
print(f"\n[3] After expand:       {len(normalized):,} chars")

# 4) Check if content unedited
collapsed_orig = collapse_patterns(format_html_fragment(original_fragment))
is_unedited = (content_fragment == collapsed_orig)
print(f"[4] Content unedited:   {is_unedited}")

# 5) Build all formats (using original fragment for HTML if unedited)
formats = build_all_formats(
    normalized, raw_formats,
    html_fragment_override=original_fragment if is_unedited else None,
    plain_text_override=original_plain_text if is_unedited else None
)

# 6) Compare HTML Format binary
print("\n" + "=" * 60)
new_html_bin = None
for entry in formats:
    if entry["format_name"] == "HTML Format":
        new_html_bin = entry["raw"]
        break

if new_html_bin == orig_html_bin:
    print("[PASS] HTML Format binary: EXACT MATCH")
else:
    print(f"[FAIL] HTML Format binary: mismatch")
    print(f"  Original: {len(orig_html_bin):,} bytes, sha256={hashlib.sha256(orig_html_bin).hexdigest()[:16]}")
    print(f"  New:      {len(new_html_bin):,} bytes, sha256={hashlib.sha256(new_html_bin).hexdigest()[:16]}")

# 7) Compare plain text (CF_UNICODETEXT)
if is_unedited and original_plain_text:
    new_plain = original_plain_text
    print(f"[INFO] Using stored original plain text ({len(new_plain)} chars)")
else:
    new_plain = extract_plain_text(normalized)
if new_plain == orig_plain:
    print("[PASS] Plain text: EXACT MATCH")
else:
    print(f"[WARN] Plain text: {len(new_plain)} chars vs {len(orig_plain)} chars")
    # Find first diff
    for i in range(min(len(new_plain), len(orig_plain))):
        if new_plain[i] != orig_plain[i]:
            print(f"  First diff at char {i}:")
            print(f"    orig: {repr(orig_plain[max(0,i-20):i+20])}")
            print(f"    new:  {repr(new_plain[max(0,i-20):i+20])}")
            break

# 8) Compare all format hashes
print("\n" + "=" * 60)
print("Format comparison (SHA-256):")
orig_by_name = {e["format_name"]: e for e in orig_formats.values()} if isinstance(orig_formats, dict) else {}
for name, info in orig_formats.items():
    orig_hash = hashlib.sha256(info["raw"]).hexdigest()[:16]
    new_entry = next((e for e in formats if e["format_name"] == name), None)
    if new_entry:
        new_hash = hashlib.sha256(new_entry["raw"]).hexdigest()[:16]
        status = "MATCH" if orig_hash == new_hash else "DIFF"
        print(f"  {status:6s}  {name:<45s}  orig={orig_hash}  new={new_hash}")
    else:
        print(f"  MISSING {name}")

# 9) Pattern stats
title_count = len(re.findall(r'<p class="title">', content_fragment))
body_count = len(re.findall(r'<p class="body">', content_fragment))
bold_count = len(re.findall(r'<p class="body-bold">', content_fragment))
empty_count = len(re.findall(r'<p class="empty-line">', content_fragment))
remaining_p = len(re.findall(r'<p\s+style="white-space', content_fragment))
print(f"\n[STATS] Article patterns:")
print(f"  title:       {title_count}")
print(f"  body:        {body_count}")
print(f"  body-bold:   {bold_count}")
print(f"  empty-line:  {empty_count}")
print(f"  un-collapsed <p>: {remaining_p}")
