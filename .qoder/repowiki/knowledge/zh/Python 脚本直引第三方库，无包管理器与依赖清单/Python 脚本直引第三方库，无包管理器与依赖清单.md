---
kind: dependency_management
name: Python 脚本直引第三方库，无包管理器与依赖清单
category: dependency_management
scope:
    - '**'
source_files:
    - config.py
    - launch.py
    - step1_1_docx_to_json.py
    - step1_2_split_long_paragraphs.py
    - step1_3_bold_paragraphs.py
---

本仓库是一个面向微信公众号文章生产的 Python 脚本集合，未使用任何 Python 包管理工具（pip、poetry、conda、requirements.txt、pyproject.toml 等），也未发现 go.mod、package.json、vendor/ 目录或 GOPRIVATE 配置。所有第三方依赖均以裸 `import` / `from ... import` 形式直接引入，由运行环境自行提供：
- `docx`（python-docx）：用于解析 Word 文档
- `requests`：调用 Azure OpenAI 代理 API 及微信公众号 API
- `ctypes.wintypes`：Windows 剪贴板二进制读写
- `Pillow`（在 step5_crop_cover.py 中裁剪封面图）
- 其余均为 Python 标准库模块（json、os、sys、re、base64、struct、xml.etree.ElementTree 等）

关键特征：
1. **无依赖声明文件** — 不存在 requirements.txt、setup.py、pyproject.toml、go.mod、package.json 等任何依赖清单。
2. **无版本锁定** — 没有 lockfile（如 poetry.lock、Pipfile.lock、go.sum、package-lock.json）。
3. **无私有源/代理配置** — 未发现 `.pip/pip.conf`、`~/.config/pypoetry/config.toml`、GOPRIVATE、npmrc 等。
4. **无 vendoring** — 未将第三方源码随仓分发。
5. **配置集中化但硬编码** — 外部服务凭据（Azure OpenAI、微信公众号 AppID/AppSecret）集中在 `config.py` 中以常量形式硬编码，未走环境变量注入。

开发者约定：新增依赖时直接在脚本顶部写 `import xxx`，由本地 Python 环境负责安装；如需可复现构建，建议后续引入 requirements.txt 或 pyproject.toml 并配合 CI 自动更新。