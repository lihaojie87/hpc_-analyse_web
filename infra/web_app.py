from pathlib import Path

import requests
from flask import Flask, Response, request, send_from_directory

WEB_ROOT = Path('/web/dist')
BACKEND = 'http://127.0.0.1:8000'
app = Flask(__name__, static_folder=str(WEB_ROOT), static_url_path='')


def proxy(path: str):
    upstream = f'{BACKEND}/{path}'
    try:
        r = requests.request(
            method=request.method,
            url=upstream,
            headers={k: v for k, v in request.headers if k.lower() not in {'host', 'content-length'}},
            data=request.get_data(),
            params=request.args,
            timeout=30,
        )
    except requests.RequestException as exc:
        return Response(f'backend unavailable: {exc}', status=502, content_type='text/plain')
    excluded = {'content-encoding', 'content-length', 'transfer-encoding', 'connection'}
    headers = [(k, v) for k, v in r.raw.headers.items() if k.lower() not in excluded]
    return Response(r.content, status=r.status_code, headers=headers, content_type=r.headers.get('Content-Type'))


@app.route('/api/<path:path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'])
def api_proxy(path: str):
    return proxy(f'api/{path}')


@app.route('/health/<path:path>', methods=['GET', 'HEAD', 'OPTIONS'])
def health_proxy(path: str):
    return proxy(f'health/{path}')


@app.route('/docs', methods=['GET', 'HEAD'])
def docs_proxy():
    return proxy('docs')


@app.route('/openapi.json', methods=['GET', 'HEAD'])
def openapi_proxy():
    return proxy('openapi.json')


@app.get('/')
def index():
    return send_from_directory(WEB_ROOT, 'index.html')


@app.get('/<path:path>')
def assets(path: str):
    target = WEB_ROOT / path
    if target.is_file():
        return send_from_directory(WEB_ROOT, path)
    return send_from_directory(WEB_ROOT, 'index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
