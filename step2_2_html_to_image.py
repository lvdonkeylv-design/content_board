# -*- coding: utf-8 -*-
"""
step2_2_html_to_image.py
========================
流水线第 5 步：
  1. 读取 process/table/ 下的 table_{n}.html，
     使用 Selenium + Chrome 截图生成 PNG。
  2. 读取 step1 JSON，将 table 元素按序替换为 image 引用，
     输出 step2_table_to_image.json。

输入：process/table/table_{n}.html
      process/step1_docx_to_json.json
输出：process/table/table_{n}.png
      process/step2_table_to_image.json

依赖：pip install selenium（系统需已安装 Chrome）

可单独运行，也可通过 launch.py 串联执行。
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

# Chrome 截图超时（秒）
CHROME_TIMEOUT = 60


# ---------------------------------------------------------------------------
# HTML → PNG（带超时保护）
# ---------------------------------------------------------------------------
def html_to_png(html_path, png_path):
    """使用 Selenium + Chrome 将 HTML 文件截图为 PNG，带超时保护"""
    file_uri = Path(html_path).absolute().as_uri()

    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-background-networking')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-sync')
    options.add_argument('--disable-translate')
    options.add_argument('--mute-audio')
    options.add_argument('--force-device-scale-factor=2')  # 高清截图
    options.add_argument('--window-position=-32000,-32000')  # 窗口移出屏幕

    # 隐藏 chromedriver 黑色控制台窗口
    service = Service(creationflags=subprocess.CREATE_NO_WINDOW)

    driver = None
    timeout_triggered = threading.Event()

    def kill_chrome_on_timeout():
        """超时后强制终止 Chrome 和 chromedriver 进程"""
        timeout_triggered.set()
        print(f"[TIMEOUT] Chrome 超过 {CHROME_TIMEOUT}s 未响应，强制终止")
        _kill_chrome_processes()

    # 启动超时监控线程
    timer = threading.Timer(CHROME_TIMEOUT, kill_chrome_on_timeout)
    timer.start()

    try:
        driver = webdriver.Chrome(options=options, service=service)
        driver.set_page_load_timeout(30)
        driver.set_window_size(1600, 900)
        driver.get(file_uri)

        # 截取表格容器实际大小
        try:
            table_el = driver.find_element(By.CSS_SELECTOR, '.table-container')
            table_el.screenshot(str(png_path))
        except Exception:
            driver.save_screenshot(str(png_path))

        # 截图成功，取消超时
        timer.cancel()

    except Exception as e:
        timer.cancel()
        if timeout_triggered.is_set():
            raise RuntimeError(f"Chrome 截图超时，已强制终止: {html_path}")
        raise RuntimeError(f"Chrome 截图失败: {html_path}, 错误: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _kill_chrome_processes():
    """强制终止所有 Chrome 和 chromedriver 进程"""
    for proc_name in ['chrome.exe', 'chromedriver.exe']:
        try:
            subprocess.run(
                ['taskkill', '/F', '/IM', proc_name, '/T'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def main(table_dir, json_path):
    if not os.path.isdir(table_dir):
        print(f"[ERROR] 目录不存在: {table_dir}")
        sys.exit(1)

    # 找到所有 table_{n}.html
    html_files = sorted(
        f for f in os.listdir(table_dir)
        if f.startswith('table_') and f.endswith('.html')
    )

    if not html_files:
        print(f"[INFO] 目录下未找到 table_*.html 文件: {table_dir}")
        # 无表格时，将输入 JSON 原样输出为 step2_table_to_image.json，供下游继续使用
        if os.path.isfile(json_path):
            import shutil
            output_path = os.path.join(
                os.path.dirname(os.path.abspath(json_path)),
                'step2_table_to_image.json'
            )
            shutil.copy2(json_path, output_path)
            print(f"[INFO] 无表格，原样复制 JSON → {output_path}")
        return

    print(f"[INFO] 找到 {len(html_files)} 个 HTML 文件，开始截图...")

    failed = []
    for html_name in html_files:
        html_path = os.path.join(table_dir, html_name)
        png_name = html_name.replace('.html', '.png')
        png_path = os.path.join(table_dir, png_name)

        print(f"[INFO] {html_name} → {png_name}")
        try:
            html_to_png(html_path, png_path)
            print(f"[OK]   {png_name}")
        except RuntimeError as e:
            print(f"[FAIL] {e}")
            failed.append(html_name)
            # 如果超时导致 Chrome 被杀，等待一下再继续
            time.sleep(2)

    success_count = len(html_files) - len(failed)
    print(f"[DONE] 共生成 {success_count} 张截图（失败 {len(failed)} 张）")

    if failed:
        print(f"[WARN] 失败的截图: {', '.join(failed)}")

    # 截图结束后，清理可能残留的进程
    _kill_chrome_processes()

    # ---- 替换 JSON 中的 table 为 image ----
    replace_tables_in_json(json_path, table_dir, success_count)


def replace_tables_in_json(json_path, table_dir, table_count):
    """读取 step1 JSON，将 table 元素替换为 image 引用，输出新 JSON"""
    if not os.path.isfile(json_path):
        print(f"[WARN] JSON 文件不存在，跳过替换: {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 按顺序替换每个 table 元素
    table_idx = 0
    for elem in data['elements']:
        if elem['type'] != 'table':
            continue
        table_idx += 1
        if table_idx > table_count:
            break

        png_name = f'table_{table_idx}.png'
        # 构造相对路径（与 step1 中 image 元素风格一致）
        rel_path = os.path.join('process', 'table', png_name)

        elem.clear()
        elem['type'] = 'image'
        elem['file_name'] = png_name
        elem['image_path'] = rel_path

    # 输出到同目录
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(json_path)),
        'step2_table_to_image.json'
    )
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[DONE] 替换 {table_idx} 个 table → image，输出: {output_path}")


if __name__ == '__main__':
    # ---- 手动修改路径 ----
    json_path = r"content_instance\content_20260708_1\process\step1_3_bold_paragraphs.json"
    table_dir = r"content_instance\content_20260708_1\process\table"
    main(table_dir, json_path)
