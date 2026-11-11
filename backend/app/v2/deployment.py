"""Explicit HTTPS origin and loopback proxy boundaries; no deployment actions."""
import os
from urllib.parse import urlsplit
from flask import request, jsonify


def https_origin(value):
    try:
        p = urlsplit(value)
        if (p.scheme != 'https' or not p.hostname or p.username or p.password
                or p.path not in {'', '/'} or p.query or p.fragment
                or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError()
        _ = p.port
    except (ValueError, TypeError):
        raise ValueError('HTTPS_ORIGIN_CONFIGURATION_REQUIRED') from None
    return value.rstrip('/'), p.hostname


def configure_deployment(app):
    value = app.config.get('PUBLIC_ORIGIN', os.getenv('GEULBIT_PUBLIC_ORIGIN', ''))
    origin, host = https_origin(value) if value else (None, None)
    flow = app.config.get('OIDC_FLOW')
    if not app.testing and flow:
        if getattr(flow, 'testing', False):
            raise ValueError('TEST_PROVIDER_FORBIDDEN')
        if not origin or flow.redirect_uri != origin + '/api/auth/callback':
            raise ValueError('OIDC_REDIRECT_ORIGIN_MISMATCH')
    app.config['PUBLIC_ORIGIN'] = origin
    if not app.testing:
        app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1', '::1'] + ([host] if host else [])

    @app.before_request
    def https_auth_boundary():
        if app.testing or not request.path.startswith('/api/') or request.path == '/api/health':
            return
        if origin and (not request.is_secure or request.host != urlsplit(origin).netloc):
            return jsonify(error={'code': 'HTTPS_ORIGIN_REQUIRED', 'message': '승인된 HTTPS 주소로 접속해 주세요.', 'fields': {}}), 400


def waitress_proxy_options(env=None):
    env = os.environ if env is None else env
    proxy = env.get('GEULBIT_TRUSTED_PROXY', '').strip()
    options = {'clear_untrusted_proxy_headers': True, 'log_untrusted_proxy_headers': False}
    if proxy:
        if proxy not in {'127.0.0.1', '::1'} or not env.get('GEULBIT_PUBLIC_ORIGIN'):
            raise ValueError('EXPLICIT_LOOPBACK_HTTPS_PROXY_REQUIRED')
        https_origin(env['GEULBIT_PUBLIC_ORIGIN'])
        options.update(trusted_proxy=proxy, trusted_proxy_count=1,
                       trusted_proxy_headers={'x-forwarded-proto'})
    return options
