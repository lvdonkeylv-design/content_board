# -*- coding: utf-8 -*-
"""
step5_crop_cover.py
===================
从文章实例文件夹中找到第一个图片文件，裁剪为 2.35:1 封面比例，
保存到 process 目录下，以 step5_ 为前缀命名。

使用方法：直接运行，路径由 launch.py 传入。
"""

import os
import sys
from typing import Optional

import numpy as np
import cv2


def _safe_print(msg: str):
    """GBK 终端安全打印，遇 emoji/特殊字符自动 fallback。"""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('gbk', errors='replace').decode('gbk'))


# 支持的图片扩展名
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif'}

# 目标宽高比
TARGET_RATIO = 2.35

# 文件大小上限（微信公众号永久素材图片限制 10MB）
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def find_first_image(folder: str) -> Optional[str]:
    """在 folder 下（不含子目录）找到第一个图片文件，按文件名排序。"""
    files = sorted(os.listdir(folder))
    for name in files:
        ext = os.path.splitext(name)[1].lower()
        if ext in IMAGE_EXTS:
            return os.path.join(folder, name)
    return None


def _save_image(img: np.ndarray, output_path: str) -> int:
    """
    保存图片到 output_path，自动处理中文/emoji 路径。
    返回保存后的文件大小（bytes）。
    """
    ext = os.path.splitext(output_path)[1].lower()
    success, encoded = cv2.imencode(ext, img)
    if success:
        encoded.tofile(output_path)
    return os.path.getsize(output_path)


def _save_image_with_limit(img: np.ndarray, output_path: str,
                           max_bytes: int = MAX_FILE_SIZE) -> int:
    """
    保存图片，若超过 max_bytes 则逐步降低 JPEG quality 压缩。
    返回最终文件大小（bytes）。
    """
    ext = os.path.splitext(output_path)[1].lower()
    is_jpeg = ext in {'.jpg', '.jpeg'}

    # 先以 quality=95 保存
    params = [cv2.IMWRITE_JPEG_QUALITY, 95] if is_jpeg else []
    success, encoded = cv2.imencode(ext, img, params)
    if success:
        encoded.tofile(output_path)

    file_size = os.path.getsize(output_path)
    if file_size <= max_bytes:
        return file_size

    if not is_jpeg:
        # 非 JPEG 格式无法调 quality，尝试缩小分辨率
        return _shrink_to_fit(img, output_path, max_bytes)

    # 二分搜索合适的 quality（10~94）
    lo, hi = 10, 94
    best_size = file_size
    while lo <= hi:
        mid = (lo + hi) // 2
        params = [cv2.IMWRITE_JPEG_QUALITY, mid]
        success, encoded = cv2.imencode(ext, img, params)
        if success:
            encoded.tofile(output_path)
        size = os.path.getsize(output_path)
        if size <= max_bytes:
            best_size = size
            lo = mid + 1   # 尝试更高质量
        else:
            hi = mid - 1   # 需要更低质量

    # 用最佳 quality 再保存一次（确保最终文件是 <= max_bytes 的最高质量）
    params = [cv2.IMWRITE_JPEG_QUALITY, hi + 1 if hi >= 10 else 10]
    success, encoded = cv2.imencode(ext, img, params)
    if success:
        encoded.tofile(output_path)
    best_size = os.path.getsize(output_path)

    _safe_print(f"[step5] 压缩: quality={hi + 1 if hi >= 10 else 10}, "
                f"大小 {best_size / 1024 / 1024:.2f}MB")
    return best_size


def _shrink_to_fit(img: np.ndarray, output_path: str,
                   max_bytes: int) -> int:
    """
    非 JPEG 格式时，通过逐步缩小分辨率使文件 <= max_bytes。
    """
    ext = os.path.splitext(output_path)[1].lower()
    scale = 0.9
    current = img.copy()
    for _ in range(10):  # 最多缩 10 次
        h, w = current.shape[:2]
        current = cv2.resize(current, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        success, encoded = cv2.imencode(ext, current)
        if success:
            encoded.tofile(output_path)
        size = os.path.getsize(output_path)
        if size <= max_bytes:
            _safe_print(f"[step5] 压缩: 缩放至 {current.shape[1]}x{current.shape[0]}, "
                        f"大小 {size / 1024 / 1024:.2f}MB")
            return size
    return os.path.getsize(output_path)


def crop_to_ratio(img_path: str, output_path: str, ratio: float = TARGET_RATIO):
    """
    将图片中心裁剪为目标宽高比 (ratio:1)，并保存。
    - 若原图宽高比 > ratio：裁宽度（左右居中）
    - 若原图宽高比 < ratio：裁高度（上下居中）
    """
    # 使用绝对路径避免中文/emoji路径问题
    img_path = os.path.abspath(img_path)
    buf = np.fromfile(img_path, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"无法读取图片: {img_path}")

    h, w = img.shape[:2]
    current_ratio = w / h

    if abs(current_ratio - ratio) < 1e-4:
        # 已经是目标比例，直接保存
        file_size = _save_image_with_limit(img, output_path)
        _safe_print(f"[step5] 原图已是 {ratio}:1 比例，直接保存 "
                    f"({file_size / 1024 / 1024:.2f}MB)")
        return

    if current_ratio > ratio:
        # 太宽，裁左右
        new_w = int(round(h * ratio))
        x_start = (w - new_w) // 2
        cropped = img[:, x_start:x_start + new_w]
    else:
        # 太高，裁上下
        new_h = int(round(w / ratio))
        y_start = (h - new_h) // 2
        cropped = img[y_start:y_start + new_h, :]

    file_size = _save_image_with_limit(cropped, output_path)
    ch, cw = cropped.shape[:2]
    _safe_print(f"[step5] 原图: {w}x{h} ({current_ratio:.2f}:1)")
    _safe_print(f"[step5] 裁剪后: {cw}x{ch} ({cw/ch:.2f}:1)")
    _safe_print(f"[step5] 已保存: {output_path} ({file_size / 1024 / 1024:.2f}MB)")


def main(content_dir: str):
    """
    主入口。
    content_dir: 文章实例文件夹路径（如 content_instance/content_20260710_1）
    """
    # 找第一张图片
    img_path = find_first_image(content_dir)
    if img_path is None:
        print("[step5] 未找到图片文件，跳过封面裁剪")
        return

    img_name = os.path.basename(img_path)
    _safe_print(f"[step5] 找到封面原图: {img_name}")

    # 输出路径：process/step5_crop_cover.<ext>
    process_dir = os.path.join(content_dir, 'process')
    os.makedirs(process_dir, exist_ok=True)

    ext = os.path.splitext(img_path)[1].lower()
    output_name = f"step5_crop_cover{ext}"
    output_path = os.path.join(process_dir, output_name)

    crop_to_ratio(img_path, output_path)


if __name__ == '__main__':
    # 硬编码路径直跑
    content_dir = r"content_instance\content_20260710_1"
    main(content_dir)
