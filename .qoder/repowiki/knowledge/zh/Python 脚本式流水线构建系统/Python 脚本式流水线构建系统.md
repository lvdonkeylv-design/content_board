---
kind: build_system
name: Python 脚本式流水线构建系统
category: build_system
scope:
    - '**'
source_files:
    - launch.py
    - config.py
    - step1_1_docx_to_json.py
    - step1_2_split_long_paragraphs.py
    - step1_3_bold_paragraphs.py
    - step2_1_table_to_html.py
    - step2_2_html_to_image.py
    - step3_json_to_html.py
    - step4_upload_clipboard.py
    - step5_crop_cover.py
    - step6_push_draft.py
---

本仓库没有使用任何传统构建系统（Makefile、Dockerfile、CI 配置、包管理清单等），而是采用纯 Python 脚本加单入口编排的轻量级构建方式，将公众号文章从 Word 到草稿箱的完整处理流程以串行步骤组织。

## 1. 构建与运行方式
- 唯一入口：launch.py 作为一键启动器，按顺序调用 step1_1 到 step6 九个处理脚本。
- 跳过机制：通过 launch.py 顶部的 SKIP_STEP* 布尔开关控制是否执行某一步骤，便于调试和增量重跑。
- 每步独立可运行：每个 stepN_*.py 都实现 main() 并在 if __name__ == '__main__': 中暴露 CLI 入口，支持单独运行。
- 无依赖声明文件：未发现 requirements.txt、pyproject.toml、setup.py、Pipfile、poetry.lock 等；依赖通过脚本注释说明（如 pip install selenium、pip install requests）。

## 2. 关键文件与角色
- launch.py：流水线编排器，负责路径派生、目录创建、步骤调度、耗时统计。
- config.py：全局配置集中地，包含 LLM API 认证头、微信公众号 AppID/AppSecret、默认作者名、评论策略等。
- step1_1_docx_to_json.py：Word 解析为结构化 JSON（段落/表格/图片元数据）。
- step1_2_split_long_paragraphs.py / step1_3_bold_paragraphs.py：基于 LLM 的长段落拆分与加粗标注。
- step2_1_table_to_html.py / step2_2_html_to_image.py：表格渲染为 HTML 并用 Selenium + Chrome 截图为 PNG，再回填 JSON。
- step3_json_to_html.py：用模板替换占位符生成最终 HTML。
- step4_upload_clipboard.py：将 HTML 写入 Windows 剪贴板（图片自动 base64 内嵌）。
- step5_crop_cover.py：封面图裁剪为 2.35:1 比例。
- step6_push_draft.py：调用微信开放接口推送至公众号草稿箱。
- html_template/：存放可被 step3 渲染的 HTML 模板。
- content_instance/：每篇文章一个子目录，内含原始 docx、中间产物（JSON/HTML/PNG）及最终输出。

## 3. 架构约定与数据流
- 输入/输出目录约定：每个内容实例位于 content_instance/content_<日期>_<序号>/，中间产物统一放在同级的 process/ 下，表格产物在 process/table/。
- 中间格式：各步骤之间通过 JSON 传递结构化数据，HTML 仅作为最终渲染产物。
- 平台约束：剪贴板操作依赖 Windows（ctypes.wintypes），Selenium 截图需本地已安装 Chrome。
- 外部依赖：LLM 调用通过 Azure OpenAI 代理，微信公众号推送走微信开放平台 API。

## 4. 开发者应遵循的规则
- 新增步骤时，在 launch.py 中添加对应 SKIP_STEP* 标志并插入调度逻辑，保持 TOTAL_STEPS 计数同步。
- 所有共享常量（API Key、微信凭证、阈值等）放入 config.py，不要在脚本中硬编码。
- 每个新脚本必须提供 main() 函数并在 if __name__ == '__main__': 中暴露 CLI，以便单独调试。
- 中间产物命名遵循 stepN_xxx.json/html 前缀，确保 launch.py 的路径拼接能正确发现。
- 如需引入新的第三方库，请在脚本顶部注释中写明安装命令（当前仓库未维护统一的依赖清单）。