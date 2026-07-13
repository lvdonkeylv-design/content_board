---
kind: frontend_style
name: 微信公众号文章 HTML 模板与内联样式体系
category: frontend_style
scope:
    - '**'
source_files:
    - html_template/caicai_html_1_green_classical.html
    - html_template/caicai_html_1_green_table.html
    - step3_json_to_html.py
    - step2_1_table_to_html.py
---

本仓库的前端样式并非基于现代前端框架或 CSS 预处理工具，而是围绕「菜菜说金融」公众号排版需求构建的一套静态 HTML 模板加内联样式体系，由 Python 流水线脚本在生成阶段注入内容。

## 1. 系统与方法概述
- 模板驱动渲染：所有视觉样式集中在 html_template/ 下的 .html 文件中，通过 Python 的字符串替换（{{BODY_PLACEHOLDER}}、{{TABLE_PLACEHOLDER}}）将 JSON 数据渲染为最终 HTML。
- 内联样式优先：模板中大量使用 <section style="..."> 和 <p style="..."> 内联属性，这是为了兼容微信编辑器粘贴剪贴板时的样式保留策略。
- Xiumi 风格片段：装饰性头部/底部分隔线等来自秀米导出片段，以 <section> 嵌套结构呈现，保持品牌一致性。
- 无外部依赖：不引入任何 CSS 文件、CSS-in-JS、Tailwind、SCSS 等，全部样式自包含于单个 HTML 文件。

## 2. 核心文件与包
- html_template/caicai_html_1_green_classical.html — 正文主模板，定义全局字体、颜色、标题/正文/高亮类名以及秀米装饰片段。
- html_template/caicai_html_1_green_table.html — 表格独立模板，绿色表头加斑马纹行，含 JS 行高同步逻辑。
- step3_json_to_html.py — 读取 step2 JSON，按规则渲染段落/标题/图片，替换正文占位符。
- step2_1_table_to_html.py — 读取表格数据，生成 <table> 片段并填充到表格模板。
- board_history/docx_to_clipboard.py — 另一条路径（Word转剪贴板），直接拼接 Xiumi 风格 HTML 片段。

## 3. 架构与约定
- 主题色：统一采用绿色系（#7eb559 表头、rgb(235,252,229) 高亮背景、#ebfce5 偶数行底色）。
- 字体栈：'Microsoft YaHei', 'PingFang SC', sans-serif，兼顾 Windows 与 macOS。
- 字号层级：大标题 24px、小标题 18px、正文 18px（正文 section 内）、表格单元格 14px。
- 行高与间距：正文 line-height: 2; letter-spacing: 1px;；段间用 <p class="empty-line"><br></p> 分隔，避免连续空行。
- 加粗高亮：通过 <span class="hl"> 包裹 bold run，对应浅绿背景加粗。
- 图片居中：图片外层 <p style="text-align:center;">，max-width: 90% 适配手机屏幕。
- 表格布局：首行为 <thead>，其余为 <tbody>；奇偶行交替底色；td.bold 标记加粗单元格。
- 响应式策略：固定 max-width: 820px 容器加 margin: auto，移动端通过 max-width: 90% 图片自适应。

## 4. 开发者应遵循的规则
- 新增样式修改模板：所有视觉变更应在 html_template/*.html 中进行，不要在生产脚本里硬编码样式字符串。
- 保持内联兼容：如需新增元素，尽量使用内联 style= 而非外部 CSS，确保微信编辑器粘贴后样式不丢失。
- 复用现有类名：标题用 class="title"，正文用 class="body"，高亮用 class="hl"，空行用 class="empty-line"。
- 表格模板独立维护：表格样式只改 caicai_html_1_green_table.html，不要在正文模板中混入表格规则。
- 主题色集中管理：绿色主题值（如 #7eb559、rgb(235,252,229)）若需调整，应同步更新两个模板文件保持一致。
- 禁止引入外部资源：不得在模板中添加 <link> 或 <script src=...>，微信环境会拦截。
- 新模板命名规范：复制现有模板文件时沿用 caicai_html_1_<主题>_<用途>.html 命名约定。