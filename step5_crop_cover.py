# -*- coding: utf-8 -*-
"""
step5_crop_cover.py
===================
1. 扫描 process/images 和 process/table 下的图片，超过 2000x2000 的等比缩放并替换原文件。
2. 从文章实例文件夹中找到第一个图片文件，裁剪为三种封面比例：
   - 2.35:1（微信公众号封面）
   - 16:9（通用横版）
   - 9:16（竖版/手机）
   保存到 content_instance/image/content_head/ 目录下。

使用方法：直接运行，路径由 launch.py 传入。
"""

import os
import sys
import shutil
from typing import Optional

import numpy as np
import cv2

from launch import DIR_NAME


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

# 图片尺寸上限
MAX_DIMENSION = 2000


def find_first_image(folder: str) -> Optional[str]:
    """在 folder 下（不含子目录）找到第一个图片文件，按文件名排序。"""
    if not os.path.isdir(folder):
        return None
    files = sorted(os.listdir(folder))
    for name in files:
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in IMAGE_EXTS:
            return full
    return None


def borrow_image_from_pool(content_dir: str) -> Optional[str]:
    """
    当 content_dir 下没有图片时，从 content_instance/image/ 顶层图片池借用一张：
    - 按文件名排序取第一张（不递归子目录）
    - 剪切（move）到 content_dir，避免下次重复借用同一张
    返回移动后的目标路径；池中无图片时返回 None。
    """
    content_instance_dir = os.path.dirname(os.path.abspath(content_dir))
    pool_dir = os.path.join(content_instance_dir, 'image')
    src = find_first_image(pool_dir)
    if src is None:
        return None

    dst = os.path.join(os.path.abspath(content_dir), os.path.basename(src))
    # 目标已存在则先删除，避免 move 报错（Windows 上 shutil.move 覆盖行为不一致）
    if os.path.isfile(dst):
        os.remove(dst)
    shutil.move(src, dst)
    _safe_print(f"[step5] 从图片池借用: {os.path.basename(src)} → 已剪切到工作目录")
    return dst


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


# ---------------------------------------------------------------------------
# 超大图片等比缩放
# ---------------------------------------------------------------------------
def scale_oversized_images(process_dir: str, max_dim: int = MAX_DIMENSION):
    """
    扫描 process_dir 下 images/ 和 table/ 子目录中的所有图片，
    若宽或高超过 max_dim，等比缩放后替换原文件。
    """
    scan_dirs = []
    for sub in ['images', 'table']:
        d = os.path.join(process_dir, sub)
        if os.path.isdir(d):
            scan_dirs.append(d)

    if not scan_dirs:
        return

    scaled_count = 0
    for d in scan_dirs:
        for name in sorted(os.listdir(d)):
            ext = os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXTS:
                continue

            img_path = os.path.join(d, name)
            buf = np.fromfile(img_path, dtype=np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if img is None:
                continue

            h, w = img.shape[:2]
            if w <= max_dim and h <= max_dim:
                continue

            # 等比缩放
            scale = max_dim / max(w, h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # 替换原文件
            success, encoded = cv2.imencode(ext, resized)
            if success:
                encoded.tofile(img_path)
                scaled_count += 1
                _safe_print(f"[step5] 缩放: {name} {w}x{h} -> {new_w}x{new_h}")

    if scaled_count:
        _safe_print(f"[step5] 共缩放 {scaled_count} 张超大图片")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(content_dir: Optional[str] = None):
    """
    主入口。
    content_dir: 文章实例文件夹路径（如 content_instance/content_20260710_1）
                 未传值 → 默认 content_instance\\{DIR_NAME}
    """
    if content_dir is None:
        content_dir = fr"content_instance\{DIR_NAME}"

    process_dir = os.path.join(content_dir, 'process')

    # 1. 缩放超大图片
    if os.path.isdir(process_dir):
        scale_oversized_images(process_dir)

    # 2. 找第一张图片作为封面原图
    img_path = find_first_image(content_dir)
    if img_path is None:
        # 工作目录里没有图片 → 从 content_instance/image/ 池里借一张（剪切）
        _safe_print("[step5] 工作目录无图片，尝试从 image 池借用...")
        img_path = borrow_image_from_pool(content_dir)
    if img_path is None:
        print("[step5] 未找到图片文件（工作目录和 image 池都为空），跳过封面裁剪")
        return

    img_name = os.path.basename(img_path)
    _safe_print(f"[step5] 找到封面原图: {img_name}")

    # 3. 生成三种比例的封面
    # 2.35:1 仍保存到 process/ 下（兼容 step6）
    # 16:9 和 9:16 保存到 content_instance/image/content_head/
    os.makedirs(process_dir, exist_ok=True)

    ext = os.path.splitext(img_path)[1].lower()

    # 2.35:1 封面 → process/step5_crop_cover.<ext>
    output_name = f"step5_crop_cover{ext}"
    output_path = os.path.join(process_dir, output_name)
    _safe_print(f"\n[step5] --- 生成 2.35:1 封面 ---")
    crop_to_ratio(img_path, output_path, 2.35)

    # 16:9 和 9:16 封面 → content_instance/image/content_head/
    content_instance_dir = os.path.dirname(os.path.abspath(content_dir))
    head_dir = os.path.join(content_instance_dir, 'image', 'content_head')
    os.makedirs(head_dir, exist_ok=True)

    # 提取文件夹标识（content_20260714_1 -> 20260714_1）
    folder_name = os.path.basename(os.path.abspath(content_dir))
    if folder_name.startswith('content_'):
        folder_id = folder_name[len('content_'):]
    else:
        folder_id = folder_name

    for ratio, label in [(16 / 9, "16_9"), (9 / 16, "9_16")]:
        output_name = f"head_{folder_id}_{label}{ext}"
        output_path = os.path.join(head_dir, output_name)
        _safe_print(f"\n[step5] --- 生成 {label.replace('_', ':')} 封面 ---")
        crop_to_ratio(img_path, output_path, ratio)


if __name__ == '__main__':
    # 默认让 main() 自行派生（fr"content_instance\{DIR_NAME}"）
    # 若要指定别的目录：保留下面显式行并改路径；不需要覆盖时把它注释掉即可
    content_dir = None
    content_dir = fr"content_instance\content_20260715_1"
    main(content_dir)
