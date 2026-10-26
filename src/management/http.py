"""Management HTTP adapter on the existing native gateway, not an inference service."""
import hmac
import json
from pathlib import Path

from model_catalog.catalog import ConfigError
from gateway.transport import error_event


WEB = Path(__file__).with_name('web')


def handle(handler, gateway, method):
    if not handler.path.startswith('/manage'):
        return False
    def reply(status, body, mime='application/json'):
        data = json.dumps(body, ensure_ascii=False).encode() if mime == 'application/json' else body
        handler.send_response(status)
        for key, value in {'Content-Type': mime, 'Content-Length': str(len(data)),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'Content-Security-Policy':
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}.items():
            handler.send_header(key, value)
        handler.end_headers(); handler.wfile.write(data)

    origin = f'http://127.0.0.1:{handler.server.server_port}'
    if handler.headers.get('Host') != f'127.0.0.1:{handler.server.server_port}':
        reply(403, {'code': 'INVALID_HOST'}); return True
    token = gateway.settings.get('management_token')
    authenticated = bool(token) and hmac.compare_digest(
        handler.headers.get('Authorization', ''), 'Bearer '+token)
    if (method == 'GET' and handler.path == '/manage/'
            and gateway.settings.get('management_auth_required', False) and not authenticated):
        reply(403, (WEB/'entry.html').read_bytes(), 'text/html; charset=utf-8')
        return True
    static = {'/manage/': ('index.html', 'text/html; charset=utf-8'),
              '/manage/entry.js': ('entry.js', 'application/javascript; charset=utf-8'),
              '/manage/app.js': ('app.js', 'application/javascript; charset=utf-8'),
              '/manage/style.css': ('style.css', 'text/css; charset=utf-8')}
    if method == 'GET' and handler.path in static:
        name, mime = static[handler.path]
        reply(200, (WEB/name).read_bytes(), mime); return True
    if (handler.headers.get('Origin') not in {None, origin}
            or (gateway.settings.get('management_auth_required', False) and
                (not token or not hmac.compare_digest(
                    handler.headers.get('Authorization', ''), 'Bearer '+token)))):
        reply(403, {'code': 'LOCAL_AUTH_REQUIRED'}); return True
    try:
        manager = gateway.manager
        if method == 'GET' and handler.path == '/manage/api/state':
            reply(200, manager.view()); return True
        if method != 'POST':
            reply(404, {'code': 'NOT_FOUND'}); return True
        if handler.headers.get_content_type() != 'application/json':
            reply(415, {'code': 'JSON_REQUIRED'}); return True
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 2*1024*1024 or handler.headers.get('Transfer-Encoding'):
            raise ConfigError('INVALID_BODY_SIZE')
        body = json.loads(handler.rfile.read(length))
        if not isinstance(body, dict):
            raise ConfigError('INVALID_BODY')
        if handler.path == '/manage/api/routing/preview':
            result = manager.preview_routing(body['mode'])
        elif handler.path == '/manage/api/routing':
            result = manager.set_routing(body['mode'], body.get('revision'))
        elif handler.path == '/manage/api/source':
            result = manager.set_source(body['mode'], body.get('cc_db_path'))
        elif handler.path == '/manage/api/provider':
            result = manager.save_provider(body['id'], body.get('spec'), body.get('api_key'), body.get('delete', False))
        elif handler.path == '/manage/api/publish':
            result = manager.publish()
        elif handler.path == '/manage/api/test':
            result = manager.test_connection(body['key'])
        else:
            reply(404, {'code': 'NOT_FOUND'}); return True
        reply(200, result)
    except Exception as error:
        event = {'code': error.code} if isinstance(error, ConfigError) else error_event(error, 'management')
        reply(400, event)
    return True
