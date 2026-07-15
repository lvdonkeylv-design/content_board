# -*- coding: utf-8 -*-
"""
微信公众号 API 转发代理
部署在固定IP服务器上，解决本地IP变化导致的白名单问题。
"""
from flask import Flask, request, Response
import requests

app = Flask(__name__)

TARGET = "https://api.weixin.qq.com"


@app.route('/wx/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy(path):
    target_url = f"{TARGET}/{path}"
    
    # 转发请求
    resp = requests.request(
        method=request.method,
        url=target_url,
        headers={k: v for k, v in request.headers if k.lower() != 'host'},
        data=request.get_data(),
        params=request.args,
        timeout=30,
    )
    
    return Response(resp.content, resp.status_code, resp.headers.items())


@app.route('/health')
def health():
    return {"status": "ok", "message": "WeChat API Proxy is running"}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
