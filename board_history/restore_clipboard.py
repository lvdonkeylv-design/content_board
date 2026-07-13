# -*- coding: utf-8 -*-
"""
restore_clipboard.py
====================
Reads previously saved clipboard data from a local directory and writes ALL
formats back to the Windows clipboard, faithfully reproducing the original
content (HTML, RTF, images, custom binary formats, etc.).

Usage:
    python restore_clipboard.py [input_dir]

If no input_dir is given, defaults to ./clipboard_data
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import json

# ---------------------------------------------------------------------------
# Windows API constants
# ---------------------------------------------------------------------------
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040

# ---------------------------------------------------------------------------
# Windows API function signatures  (64-bit safe)
# ---------------------------------------------------------------------------
user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.OpenClipboard.restype    = wt.BOOL
user32.OpenClipboard.argtypes   = [wt.HWND]

user32.CloseClipboard.restype   = wt.BOOL
user32.CloseClipboard.argtypes  = []

user32.EmptyClipboard.restype   = wt.BOOL
user32.EmptyClipboard.argtypes  = []

user32.SetClipboardData.restype  = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]

user32.RegisterClipboardFormatW.restype  = wt.UINT
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]

user32.GetClipboardFormatNameW.restype  = wt.INT
user32.GetClipboardFormatNameW.argtypes = [wt.UINT, wt.LPWSTR, wt.INT]

# 64-bit: must use c_void_p for handle/pointer returns
kernel32.GlobalAlloc.restype   = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes  = [wt.UINT, ctypes.c_size_t]

kernel32.GlobalLock.restype    = ctypes.c_void_p
kernel32.GlobalLock.argtypes   = [ctypes.c_void_p]

kernel32.GlobalUnlock.restype  = wt.BOOL
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

kernel32.GlobalFree.restype    = ctypes.c_void_p
kernel32.GlobalFree.argtypes   = [ctypes.c_void_p]


def resolve_format_id(fmt_id, fmt_name):
    """
    Return a valid clipboard format ID.
    For standard formats (id <= 17) the id is used as-is.
    For registered/custom formats, we call RegisterClipboardFormatW with the
    original name to obtain the runtime ID.
    """
    if fmt_id <= 17:
        return fmt_id
    rid = user32.RegisterClipboardFormatW(fmt_name)
    if rid == 0:
        print(f"  [WARN] RegisterClipboardFormatW failed for '{fmt_name}', using original id {fmt_id}")
        return fmt_id
    return rid


def restore_clipboard(input_dir):
    manifest_path = os.path.join(input_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"[ERROR] manifest.json not found in: {input_dir}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"[INFO] Found {len(manifest)} format(s) in manifest.")

    if not user32.OpenClipboard(0):
        print("[ERROR] Cannot open clipboard. Is another program using it?")
        sys.exit(1)

    try:
        user32.EmptyClipboard()
        success_count = 0

        for entry in manifest:
            fmt_id    = entry["format_id"]
            fmt_name  = entry["format_name"]
            file_name = entry["file"]
            file_path = os.path.join(input_dir, file_name)

            if not os.path.isfile(file_path):
                print(f"  [WARN] File not found: {file_path}, skipping format {fmt_id} ({fmt_name})")
                continue

            with open(file_path, "rb") as f:
                raw = f.read()

            data_size = len(raw)
            if data_size == 0:
                print(f"  [WARN] File is empty: {file_name}, skipping.")
                continue

            runtime_fmt = resolve_format_id(fmt_id, fmt_name)

            h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, data_size)
            if not h_mem:
                print(f"  [ERROR] GlobalAlloc failed for format {fmt_id} ({fmt_name}), skipping.")
                continue

            p_locked = kernel32.GlobalLock(h_mem)
            if not p_locked:
                print(f"  [ERROR] GlobalLock failed for format {fmt_id} ({fmt_name}), skipping.")
                kernel32.GlobalFree(h_mem)
                continue

            try:
                src_buf = ctypes.create_string_buffer(raw, data_size)
                ctypes.memmove(p_locked, ctypes.addressof(src_buf), data_size)
            finally:
                kernel32.GlobalUnlock(h_mem)

            result = user32.SetClipboardData(runtime_fmt, h_mem)
            if not result:
                err = ctypes.get_last_error()
                print(f"  [ERROR] SetClipboardData failed for format {runtime_fmt} ({fmt_name}), "
                      f"GetLastError={err}")
                kernel32.GlobalFree(h_mem)
                continue

            print(f"  [OK] Restored format {fmt_id:>5} -> runtime {runtime_fmt:>5}  |  "
                  f"{fmt_name:<40}  |  {data_size:>8} bytes")
            success_count += 1

        print(f"\n[DONE] Successfully restored {success_count}/{len(manifest)} format(s) to clipboard.")

    finally:
        user32.CloseClipboard()


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "content_20260629")
    print(f"[INFO] Restoring clipboard from: {src}")
    restore_clipboard(src)
