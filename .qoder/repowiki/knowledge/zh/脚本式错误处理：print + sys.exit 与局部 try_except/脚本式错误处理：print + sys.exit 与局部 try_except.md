---
kind: error_handling
name: 脚本式错误处理：print + sys.exit 与局部 try/except
category: error_handling
scope:
    - '**'
source_files:
    - launch.py
    - step1_1_docx_to_json.py
    - step1_2_split_long_paragraphs.py
    - step6_push_draft.py
    - step2_2_html_to_image.py
    - step5_crop_cover.py
    - board_history/restore_clipboard.py
    - board_history/save_clipboard.py
    - board_history/docx_to_clipboard.py
---

本仓库是面向微信公众号文章生产的 Python 脚本集合，未引入统一异常体系或日志框架。错误处理采用就地捕获加控制台输出加进程退出的轻量模式，贯穿所有 step 脚本与 board_history 工具。

1. 系统与方法概览
- 无自定义 Exception/Error 类型定义，也未使用 logging 模块；错误信息一律通过 print 输出到标准输出。
- 关键路径校验失败（文件不存在、格式不对、配置缺失）直接调用 sys.exit(1) 终止当前脚本。
- 对外部依赖（HTTP 请求、JSON 解析、Windows 剪贴板 API）使用最小粒度的 try/except 包裹，捕获具体异常后打印提示并回退或重试。
- 对大模型调用封装了带指数退避的重试循环，失败时降级为保留原文。

2. 关键位置与模式
- 参数与前置条件校验：每个 step 的 main 入口在开头检查输入文件是否存在、后缀是否合法、config 中 AppID/AppSecret 是否填写，不满足则打印 [ERROR] 并 sys.exit(1)。典型文件：step1_1_docx_to_json.py、step6_push_draft.py、launch.py。
- HTTP 调用错误：requests 调用后统一 resp.raise_for_status()，并在 except requests.exceptions.RequestException 分支内按剩余重试次数打印警告并重试，最终失败返回 None 由上层降级处理。典型文件：step1_2_split_long_paragraphs.py、step6_push_draft.py。
- JSON 解析容错：对 LLM 返回的文本先尝试直接 json.loads，失败则去除代码块标记再解析，最后用正则提取数组片段，全部失败返回 None。典型文件：step1_2_split_long_paragraphs.py。
- Windows 剪贴板 I/O：board_history 子项目中对 win32clipboard 调用使用 try/except UnicodeEncodeError / OSError，捕获后打印包含 GetLastError 的错误信息并继续或跳过该条目。典型文件：restore_clipboard.py、save_clipboard.py、docx_to_clipboard.py。
- 外部截图与图片处理：step2_2_html_to_image.py 和 step5_crop_cover.py 在 Chrome 截图超时或 Pillow 无法读取图片时 raise RuntimeError，作为不可恢复错误向上冒泡。
- launch.py 编排层：仅做步骤开关与顺序调度，自身只校验输入文件存在性，不集中捕获下游异常；各 step 自行决定成功与失败语义。

3. 架构与约定
- 每个 step 都是独立可运行的脚本，错误处理边界以脚本为界，没有跨脚本的错误传播机制。
- 失败策略遵循快速失败与可降级：I/O 类错误直接退出；网络与 LLM 类错误走重试后降级（保留原文），保证流水线能继续产出可用中间产物。
- 所有诊断信息通过 print 输出，并以 [INFO]、[WARN]、[ERROR]、[DEBUG] 前缀区分级别，便于 grep 过滤。
- 未使用 panic/recover 等价物（Python 无此概念），也未见全局异常钩子或中间件。

4. 开发者应遵守的规则
- 新增步骤时，在 main 入口处对输入文件、必要配置执行显式校验，失败打印 [ERROR] 并 sys.exit(1)。
- 对外部 I/O（网络、文件系统、剪贴板、子进程）使用 try/except 捕获具体异常，打印可读信息后选择重试、降级或退出，避免裸抛导致整个流水线崩溃。
- 对 LLM 与第三方 API 调用复用带 MAX_RETRIES 的重试模式，失败返回 None 交由上层决定是否回退到上游数据。
- 诊断输出统一使用 [INFO]/[WARN]/[ERROR]/[DEBUG] 前缀，不要混用其他风格。
- 不要在脚本间传递异常对象；如需跨脚本报告错误，通过返回值或写入临时文件/缓存文件的方式传递。