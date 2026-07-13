---
kind: external_dependency
name: 表格 HTML 渲染截图
slug: selenium-chrome
category: external_dependency
category_hints:
    - framework_behavior
scope:
    - '**'
---

使用 Selenium WebDriver 启动 headless Chrome 将 table_{n}.html 渲染为高清 PNG（force_device_scale_factor=2），窗口移出屏幕避免干扰，带 60 秒超时保护并强制终止残留的 chrome.exe/chromedriver.exe 进程。需要系统已安装 Chrome 浏览器。