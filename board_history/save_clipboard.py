# -*- coding: utf-8 -*-
"""
save_clipboard.py
=================
Reads ALL clipboard formats (text, HTML, RTF, images, custom binary formats, etc.)
from the Windows clipboard and saves them to a local directory.

Usage:
    python save_clipboard.py [output_dir]

If no output_dir is given, defaults to ./clipboard_data
"""

import ctypes
import ctypes.wintypes as wt
import os
import sys
import json

# ---------------------------------------------------------------------------
# Windows API constants
# ---------------------------------------------------------------------------
CF_TEXT          = 1
CF_BITMAP        = 2
CF_METAFILEPICT  = 3
CF_SYLK          = 4
CF_DIF           = 5
CF_TIFF          = 6
CF_OEMTEXT       = 7
CF_DIB           = 8
CF_PALETTE       = 9
CF_PENDATA       = 10
CF_RIFF          = 11
CF_WAVE          = 12
CF_UNICODETEXT   = 13
CF_ENHMETAFILE   = 14
CF_HDROP         = 15
CF_LOCALE        = 16
CF_DIBV5         = 17

GMEM_MOVEABLE    = 0x0002
GMEM_ZEROINIT    = 0x0040

STD_FORMAT_NAMES = {
    CF_TEXT:         "CF_TEXT",
    CF_BITMAP:       "CF_BITMAP",
    CF_METAFILEPICT: "CF_METAFILEPICT",
    CF_SYLK:         "CF_SYLK",
    CF_DIF:          "CF_DIF",
    CF_TIFF:         "CF_TIFF",
    CF_OEMTEXT:      "CF_OEMTEXT",
    CF_DIB:          "CF_DIB",
    CF_PALETTE:      "CF_PALETTE",
    CF_PENDATA:      "CF_PENDATA",
    CF_RIFF:         "CF_RIFF",
    CF_WAVE:         "CF_WAVE",
    CF_UNICODETEXT:  "CF_UNICODETEXT",
    CF_ENHMETAFILE:  "CF_ENHMETAFILE",
    CF_HDROP:        "CF_HDROP",
    CF_LOCALE:       "CF_LOCALE",
    CF_DIBV5:        "CF_DIBV5",
}

# ---------------------------------------------------------------------------
# Windows API function signatures  (64-bit safe)
# ---------------------------------------------------------------------------
user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.OpenClipboard.restype    = wt.BOOL
user32.OpenClipboard.argtypes   = [wt.HWND]

user32.CloseClipboard.restype   = wt.BOOL
user32.CloseClipboard.argtypes  = []

user32.EnumClipboardFormats.restype  = wt.UINT
user32.EnumClipboardFormats.argtypes = [wt.UINT]

user32.GetClipboardFormatNameW.restype  = wt.INT
user32.GetClipboardFormatNameW.argtypes = [wt.UINT, wt.LPWSTR, wt.INT]

user32.GetClipboardData.restype  = ctypes.c_void_p
user32.GetClipboardData.argtypes = [wt.UINT]

user32.CountClipboardFormats.restype = wt.INT
user32.CountClipboardFormats.argtypes = []

# 64-bit: must use c_void_p for handle/pointer returns
kernel32.GlobalAlloc.restype   = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes  = [wt.UINT, ctypes.c_size_t]

kernel32.GlobalLock.restype    = ctypes.c_void_p
kernel32.GlobalLock.argtypes   = [ctypes.c_void_p]

kernel32.GlobalUnlock.restype  = wt.BOOL
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

kernel32.GlobalSize.restype    = ctypes.c_size_t
kernel32.GlobalSize.argtypes   = [ctypes.c_void_p]

kernel32.GlobalFree.restype    = ctypes.c_void_p
kernel32.GlobalFree.argtypes   = [ctypes.c_void_p]


def get_format_name(fmt_id):
    """Return human-readable name for a clipboard format ID."""
    if fmt_id in STD_FORMAT_NAMES:
        return STD_FORMAT_NAMES[fmt_id]
    buf = ctypes.create_unicode_buffer(256)
    ret = user32.GetClipboardFormatNameW(fmt_id, buf, 256)
    if ret > 0:
        return buf.value
    return f"Unknown_{fmt_id}"


def save_clipboard(output_dir):
    """Open the clipboard, enumerate all formats, and save each one."""
    os.makedirs(output_dir, exist_ok=True)

    if not user32.OpenClipboard(0):
        print("[ERROR] Cannot open clipboard. Is another program using it?")
        sys.exit(1)

    try:
        count = user32.CountClipboardFormats()
        print(f"[INFO] Clipboard contains {count} format(s).")

        manifest = []

        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if fmt == 0:
                break

            fmt_name = get_format_name(fmt)
            h_data = user32.GetClipboardData(fmt)
            if not h_data:
                print(f"  [WARN] Format {fmt} ({fmt_name}): GetClipboardData returned NULL, skipping.")
                continue

            size = kernel32.GlobalSize(h_data)
            if size == 0:
                print(f"  [WARN] Format {fmt} ({fmt_name}): GlobalSize returned 0, skipping.")
                continue

            p_locked = kernel32.GlobalLock(h_data)
            if not p_locked:
                print(f"  [WARN] Format {fmt} ({fmt_name}): GlobalLock failed, skipping.")
                continue

            try:
                raw = ctypes.string_at(p_locked, size)
            finally:
                kernel32.GlobalUnlock(h_data)

            safe_name = fmt_name.replace("/", "_").replace("\\", "_").replace(":", "_")
            file_name = f"{fmt:05d}_{safe_name}.bin"
            file_path = os.path.join(output_dir, file_name)

            with open(file_path, "wb") as f:
                f.write(raw)

            print(f"  [OK] Format {fmt:>5}  |  {fmt_name:<40}  |  {size:>8} bytes  ->  {file_name}")

            manifest.append({
                "format_id":   fmt,
                "format_name": fmt_name,
                "file":        file_name,
                "size":        size,
            })

        manifest_path = os.path.join(output_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        print(f"\n[DONE] Saved {len(manifest)} format(s) to: {output_dir}")
        print(f"       Manifest: {manifest_path}")

    finally:
        user32.CloseClipboard()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "clipboard_data")
    print(f"[INFO] Saving clipboard to: {out}")
    save_clipboard(out)
