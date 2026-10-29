"""Additional access restriction for explicitly isolated external tests only."""
import base64
import hmac
import hashlib
import secrets
from http.cookies import SimpleCookie, CookieError
import threading
import time
from collections import deque


class IsolatedNetworkGate:
    COOKIE = 'geulbit_private_test'
    ACCESS_TTL = 3600

    def __init__(self, app, host, password, *, google_only=False, limit=120, window=60, clock=time.monotonic, wall_clock=time.time):
        if not password or len(password) < 16:
            raise ValueError("NETWORK_ACCESS_KEY_REQUIRED")
        self.app, self.host = app, host
        self.google_only=google_only
        self.expected = ("geulbit:" + password).encode()
        self.limit, self.window, self.clock = limit, window, clock
        self.events, self.lock = deque(), threading.Lock()
        self.wall_clock = wall_clock
        self.cookie_key = hmac.new(self.expected, ('private-test-cookie-v1:'+host).encode(), hashlib.sha256).digest()

    def access_cookie(self):
        value=str(int(self.wall_clock()))+'.'+secrets.token_hex(16)
        return value+'.'+hmac.new(self.cookie_key,value.encode(),hashlib.sha256).hexdigest()

    def valid_cookie(self, header):
        if len(header)>16384:return False
        try:
            cookie=SimpleCookie();cookie.load(header)
            value=cookie[self.COOKIE].value
            timestamp,nonce,signature=value.split('.')
            age=self.wall_clock()-int(timestamp)
            if not 0<=age<self.ACCESS_TTL or len(nonce)!=32:return False
            expected=hmac.new(self.cookie_key,(timestamp+'.'+nonce).encode(),hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature,expected)
        except (CookieError,KeyError,ValueError,TypeError):return False

    def __call__(self, environ, start_response):
        def deny(status, code, extra=()):
            body = ('{"error":{"code":"' + code + '"}}').encode()
            start_response(status, [("Content-Type", "application/json"), ("Cache-Control", "no-store"), *extra])
            return [body]
        if environ.get("HTTP_HOST") != self.host or environ.get("wsgi.url_scheme") != "https":
            return deny("400 Bad Request", "HTTPS_HOST_REQUIRED")
        with self.lock:
            now = self.clock()
            while self.events and self.events[0] <= now - self.window:
                self.events.popleft()
            if len(self.events) >= self.limit:
                return deny("429 Too Many Requests", "TEST_REQUEST_LIMIT", [("Retry-After", str(self.window))])
            self.events.append(now)
        header = environ.get("HTTP_AUTHORIZATION", "")
        try:
            supplied = base64.b64decode(header[6:], validate=True) if header.startswith("Basic ") and len(header) <= 1024 else b""
        except (ValueError, TypeError):
            supplied = b""
        basic_ok=hmac.compare_digest(supplied,self.expected)
        cookie_ok=self.valid_cookie(environ.get('HTTP_COOKIE',''))
        if not self.google_only and not basic_ok and not cookie_ok:
            # Challenge page navigation, not every failed background API call.
            challenge=() if environ.get('PATH_INFO','').startswith('/api/') else [("WWW-Authenticate", 'Basic realm="Geulbit isolated test", charset="UTF-8"')]
            return deny("401 Unauthorized", "PRIVATE_TEST_ACCESS_REQUIRED", challenge)
        origin = environ.get("HTTP_ORIGIN")
        if environ.get("REQUEST_METHOD") not in {"GET", "HEAD", "OPTIONS"} and origin and origin != "https://" + self.host:
            return deny("403 Forbidden", "ORIGIN_REJECTED")
        environ.pop("HTTP_AUTHORIZATION", None)
        def response(status,headers,exc_info=None):
            if not self.google_only and basic_ok and not cookie_ok:
                headers=list(headers)+[('Set-Cookie',self.COOKIE+'='+self.access_cookie()+'; Max-Age='+str(self.ACCESS_TTL)+'; Path=/; Secure; HttpOnly; SameSite=Lax')]
            return start_response(status,headers,exc_info)
        return self.app(environ, response)
