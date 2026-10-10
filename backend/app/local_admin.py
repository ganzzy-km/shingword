from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for

from .config import Config
from .services.dictionary_service import DictionaryClient
from .services.secrets_service import DpapiSecretStore, SafeStorageUnavailable, SecretStoreError


CONFIRMATION_PHRASE = "표준국어대사전 API 키 변경"
SESSION_IDLE_SECONDS = 10 * 60


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdminStateStore:
    def __init__(self, path: str | Path, audit_path: str | Path):
        self.path = Path(path)
        self.audit_path = Path(audit_path)
        self._lock = threading.RLock()

    def read(self) -> dict:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError, TypeError):
                return {}

    def update(self, changes: dict) -> dict:
        with self._lock:
            value = self.read()
            value.update(changes)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
            return value

    def audit(self, action: str, success: bool) -> None:
        record = {"action": action, "success": bool(success), "at": _utc_iso()}
        with self._lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


class LoginRateLimiter:
    def __init__(self, max_failures=5, lock_seconds=600, clock=None):
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self.clock = clock or time.monotonic
        self._entries: dict[str, dict] = {}
        self._lock = threading.Lock()

    def locked(self, identifier: str) -> bool:
        with self._lock:
            entry = self._entries.get(identifier, {})
            return entry.get("lockedUntil", 0) > self.clock()

    def fail(self, identifier: str) -> None:
        with self._lock:
            entry = self._entries.setdefault(identifier, {"failures": 0, "lockedUntil": 0})
            entry["failures"] += 1
            if entry["failures"] >= self.max_failures:
                entry["lockedUntil"] = self.clock() + self.lock_seconds
                entry["failures"] = 0

    def success(self, identifier: str) -> None:
        with self._lock:
            self._entries.pop(identifier, None)


def create_local_admin_app(config=None, secret_store=None, dictionary_transport=None):
    app = Flask(__name__, static_folder=None, template_folder="templates")
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    if not app.config.get("TESTING"):
        from .storage import configure_storage
        configure_storage(app)
    store = secret_store or app.config.get("SECRET_STORE") or DpapiSecretStore(app.config["SECRET_FILE"])
    state = AdminStateStore(app.config["ADMIN_STATE_FILE"], app.config["ADMIN_AUDIT_FILE"])
    limiter = LoginRateLimiter()
    dictionary = DictionaryClient(lambda: store.get("stdictApiKey"), transport=dictionary_transport)

    try:
        session_key = store.get("adminSessionKey")
        if not session_key:
            session_key = secrets.token_urlsafe(48)
            store.set("adminSessionKey", session_key)
        app.secret_key = session_key
        storage_available = True
    except (SafeStorageUnavailable, SecretStoreError):
        app.secret_key = secrets.token_urlsafe(48)
        storage_available = False

    app.config.update(
        SESSION_COOKIE_NAME="geulbit_local_admin",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
    )
    app.extensions["secret_store"] = store
    app.extensions["admin_state"] = state
    app.extensions["login_limiter"] = limiter
    app.extensions["dictionary_client"] = dictionary

    @app.before_request
    def local_only_and_session_timeout():
        if request.remote_addr not in {"127.0.0.1", "::1", None}:
            abort(403)
        if session.get("authenticated"):
            now = int(time.time())
            if now - int(session.get("lastSeen", 0)) > SESSION_IDLE_SECONDS:
                session.clear()
                return redirect(url_for("login", expired="1"))
            session["lastSeen"] = now
        if request.method == "POST":
            expected = session.get("csrf")
            supplied = request.form.get("csrf", "")
            if not expected or not hmac.compare_digest(str(expected), supplied):
                abort(400)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        if request.is_secure:
            cookies = response.headers.getlist("Set-Cookie")
            if cookies:
                del response.headers["Set-Cookie"]
                for cookie in cookies:
                    response.headers.add("Set-Cookie", cookie if "Secure" in cookie else cookie + "; Secure")
        return response

    def csrf_token():
        if not session.get("csrf"):
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    def render(page, **context):
        return render_template(
            f"local_admin/{page}.html",
            csrf=csrf_token(),
            storage_available=storage_available,
            confirmation_phrase=CONFIRMATION_PHRASE,
            **context,
        )

    def require_auth():
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return None

    def password_hasher():
        try:
            from argon2 import PasswordHasher

            return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        except ImportError as exc:
            raise RuntimeError("Argon2id 의존성을 사용할 수 없습니다.") from exc

    def verify_password(password: str) -> bool:
        password_hash = state.read().get("passwordHash")
        if not password_hash:
            return False
        try:
            return password_hasher().verify(password_hash, password)
        except Exception:
            return False

    @app.get("/")
    def root():
        if not state.read().get("passwordHash"):
            return redirect(url_for("setup"))
        return redirect(url_for("api_key" if session.get("authenticated") else "login"))

    @app.route("/local-admin/setup", methods=["GET", "POST"])
    def setup():
        if state.read().get("passwordHash"):
            return redirect(url_for("login"))
        error = None
        if request.method == "POST":
            password, confirmation = request.form.get("password", ""), request.form.get("passwordConfirm", "")
            if not storage_available:
                error = "Windows DPAPI를 사용할 수 없어 안전한 관리자 설정을 만들 수 없습니다."
            elif len(password) < 12:
                error = "관리자 비밀번호는 12자 이상으로 입력해 주세요."
            elif password != confirmation:
                error = "비밀번호 확인이 일치하지 않습니다."
            else:
                try:
                    state.update({"passwordHash": password_hasher().hash(password), "passwordUpdatedAt": _utc_iso()})
                    state.audit("admin_password_setup", True)
                    session.clear()
                    return redirect(url_for("login", setup="1"))
                except Exception:
                    state.audit("admin_password_setup", False)
                    error = "관리자 비밀번호를 안전하게 저장하지 못했습니다."
        return render("setup", error=error)

    @app.route("/local-admin/login", methods=["GET", "POST"])
    def login():
        if not state.read().get("passwordHash"):
            return redirect(url_for("setup"))
        identifier = request.remote_addr or "local"
        error = None
        if request.method == "POST":
            if limiter.locked(identifier):
                error = "로그인 실패 횟수를 초과했습니다. 10분 뒤 다시 시도해 주세요."
            elif verify_password(request.form.get("password", "")):
                limiter.success(identifier)
                state.audit("admin_login", True)
                session.clear()
                session.update(authenticated=True, lastSeen=int(time.time()), csrf=secrets.token_urlsafe(32))
                return redirect(url_for("api_key"))
            else:
                limiter.fail(identifier)
                state.audit("admin_login", False)
                error = "관리자 비밀번호가 올바르지 않습니다."
        return render("login", error=error, expired=request.args.get("expired") == "1", setup_done=request.args.get("setup") == "1", changed=request.args.get("changed") == "1")

    @app.get("/local-admin/api-key")
    def api_key():
        auth_redirect = require_auth()
        if auth_redirect:
            return auth_redirect
        configured = False
        masked = None
        try:
            current = store.get("stdictApiKey")
            configured = bool(current)
            masked = _mask_key(current) if current else None
        except (SafeStorageUnavailable, SecretStoreError):
            pass
        dictionary_state = state.read().get("dictionary", {})
        return render("api_key", configured=configured, masked=masked, dictionary=dictionary_state, error=request.args.get("error"), message=request.args.get("message"))

    @app.post("/local-admin/api-key")
    def save_api_key():
        auth_redirect = require_auth()
        if auth_redirect:
            return auth_redirect
        try:
            configured = store.contains("stdictApiKey")
        except Exception:
            configured = False
        password = request.form.get("password", "")
        new_key = request.form.get("newKey", "").strip()
        confirm_key = request.form.get("newKeyConfirm", "").strip()
        confirmation = request.form.get("confirmation", "")
        error = None
        if not storage_available:
            error = "Windows DPAPI를 사용할 수 없어 API 키를 저장할 수 없습니다."
        elif not verify_password(password):
            error = "관리자 비밀번호가 올바르지 않습니다."
        elif len(new_key) != 32 or any(char not in "0123456789abcdefABCDEF" for char in new_key):
            error = "API 키는 16진수 32자리여야 합니다."
        elif new_key != confirm_key:
            error = "새 API 키 확인이 일치하지 않습니다."
        elif configured and confirmation != CONFIRMATION_PHRASE:
            error = "변경 확인 문구가 정확히 일치하지 않습니다."
        if error:
            state.audit("stdict_key_replace" if configured else "stdict_key_register", False)
            return redirect(url_for("api_key", error=error))

        result = dictionary.validate_key(new_key)
        success = result.get("status") == "available" and bool(result.get("entries"))
        state.audit("stdict_key_replace" if configured else "stdict_key_register", success)
        if not success:
            if not configured:
                state.update({"dictionary": {"status": result.get("status"), "checkedAt": _utc_iso(), "configured": False}})
            return redirect(url_for("api_key", error=result.get("notice") or "API 연결 시험에 실패했습니다. 기존 키는 유지했습니다."))
        try:
            store.set("stdictApiKey", new_key)
            state.update({"dictionary": {"status": "available", "checkedAt": _utc_iso(), "configured": True}})
        except (SafeStorageUnavailable, SecretStoreError):
            state.audit("stdict_key_store", False)
            return redirect(url_for("api_key", error="검증은 성공했지만 안전한 저장에 실패했습니다. 기존 키는 유지했습니다."))
        session.clear()
        return redirect(url_for("login", changed="1"))

    @app.post("/local-admin/password")
    def change_password():
        auth_redirect = require_auth()
        if auth_redirect:
            return auth_redirect
        current = request.form.get("currentPassword", "")
        new = request.form.get("newPassword", "")
        confirmation = request.form.get("newPasswordConfirm", "")
        if not verify_password(current) or len(new) < 12 or new != confirmation:
            state.audit("admin_password_change", False)
            return redirect(url_for("api_key", error="현재 비밀번호와 12자 이상의 새 비밀번호 확인을 점검해 주세요."))
        state.update({"passwordHash": password_hasher().hash(new), "passwordUpdatedAt": _utc_iso()})
        state.audit("admin_password_change", True)
        session.clear()
        return redirect(url_for("login", changed="1"))

    @app.post("/local-admin/logout")
    def logout():
        if session.get("authenticated"):
            state.audit("admin_logout", True)
        session.clear()
        return redirect(url_for("login"))

    return app


def _mask_key(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}{'•' * 24}{value[-4:]}"
