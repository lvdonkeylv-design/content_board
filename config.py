# ============================================================
# 全局配置 - content_board 项目共用
# ============================================================

# API 认证
API_URL = (
    'https://datahub.astrazeneca.cn:443/api/c2/exp/china-aigateway-proxy-api'
    '/v1/azure-openai/openai/deployments/gpt-5/chat/completions'
    '?api-version=2025-02-01-preview'
)

HEADERS = {
    'client_id': '85ee0b22e44b478593041d58384fedd1',
    'Content-Type': 'application/json',
    'client_secret': '9257acd878E84Ec89eB6C7A6C4869E75',
    'api-key': 'Bearer sk-55188119b9fa1f750e1183d7e05c0a34c417224e55602147ab9f7edbdf3001e6',
}

# 通用参数
MAX_RETRIES = 3
MAX_TOKENS = 8192

# 段落拆分阈值
SPLIT_THRESHOLD = 120  # 单个 text 超过此长度才触发拆分

# ============================================================
# 微信公众号配置
# ============================================================
WX_APP_ID = 'wx695573645e236c68'        # ← 填写你的 AppID
WX_APP_SECRET = '74f765478142dde0643604629c38ce57'    # ← 填写你的 AppSecret

WX_API_BASE = 'http://106.14.12.137:5000/wx/cgi-bin'

# 草稿箱推送默认值
WX_AUTHOR = '菜菜'
WX_CONTENT_SOURCE_URL = ''  # 创作来源（阅读原文链接）
WX_NEED_OPEN_COMMENT = 1    # 1=打开评论  0=关闭
WX_ONLY_FANS_COMMENT = 0    # 0=所有人可评论  1=仅粉丝
