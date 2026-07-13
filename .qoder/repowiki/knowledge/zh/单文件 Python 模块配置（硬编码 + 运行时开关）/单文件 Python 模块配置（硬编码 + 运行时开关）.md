---
kind: configuration_system
name: 单文件 Python 模块配置（硬编码 + 运行时开关）
category: configuration_system
scope:
    - '**'
source_files:
    - config.py
    - launch.py
---

本仓库采用最简化的「单文件 Python 模块」配置方式，所有全局可配置项集中在根目录的 config.py 中，由各个处理步骤通过 from config import ... 直接导入使用。没有引入任何第三方配置框架、环境变量加载器或外部配置文件格式。

## 1. 使用的系统/方法
- Python 模块即配置：config.py 是一个普通 Python 模块，顶层变量即为配置项。
- 无外部配置文件：未发现 .env、.yaml、.toml、application.properties 等外部配置源；也未见 os.environ / dotenv 的使用。
- 流水线跳过开关：launch.py 顶部定义一组 SKIP_STEP* 布尔常量，用于控制九步流水线的执行路径，属于「运行时开关」而非持久化配置。

## 2. 关键文件与包
- config.py — 唯一的全局配置来源，包含三类常量：
  - API 认证与通用参数：API_URL、HEADERS、MAX_RETRIES、MAX_TOKENS、SPLIT_THRESHOLD
  - 微信公众号凭据与默认值：WX_APP_ID、WX_APP_SECRET、WX_API_BASE、WX_AUTHOR、WX_CONTENT_SOURCE_URL、WX_NEED_OPEN_COMMENT、WX_ONLY_FANS_COMMENT
- launch.py — 流水线入口，集中声明 SKIP_STEP1_1 ~ SKIP_STEP6 九个布尔开关，决定哪些步骤实际执行。

## 3. 架构与约定
- 单一真相源：所有对外部服务（Azure OpenAI、微信公众号 API）的凭据和 URL 都来自 config.py，被 step1_2_split_long_paragraphs.py、step1_3_bold_paragraphs.py、step6_push_draft.py 等模块直接 import 使用。
- 按职责分组注释块：config.py 用注释分隔「API 认证」「通用参数」「段落拆分阈值」「微信公众号配置」四个逻辑段，便于定位修改。
- 运行时开关与持久化配置分离：launch.py 中的 SKIP_* 仅影响当前一次运行流程，不写入磁盘；而 config.py 中的凭据是持久化在源码中的。
- board_history 子项目的独立 JSON 配置：board_history/docx_to_clipboard.py 会在输出目录生成 config.json，用于记录剪贴板条目结构并支持后续 regenerate.py 重新生成二进制数据——这是该子工具链内部的「可编辑中间配置」，与主流水线的 config.py 相互独立。

## 4. 开发者应遵循的规则
1. 新增全局配置项时统一放在 config.py，并按现有注释块归类，避免在各 step 脚本中散落硬编码字符串。
2. 不要在 step 脚本里重复定义相同常量，一律从 config 模块导入。
3. 敏感信息（AppID/AppSecret、API Key）目前硬编码在源码中，若需多人协作或 CI 环境，建议迁移到环境变量或 .env 文件并通过 python-dotenv 加载，并在 .gitignore 中排除。
4. 调整流水线行为优先改 launch.py 顶部的 SKIP_STEP* 开关，而不是去修改各 step 内部逻辑。
5. board_history 子项目生成的 config.json 仅供该子工具链内部使用，不要与根级 config.py 混淆。