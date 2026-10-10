from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from werkzeug.exceptions import HTTPException

from .config import Config
from .extensions import db, migrate
from .seed import ensure_defaults, recover_interrupted_jobs
from .services.dictionary_service import DictionaryClient
from .services.secrets_service import DpapiSecretStore
from .storage import StorageBlocked, configure_storage


def create_app(config_object=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if config_object:
        if isinstance(config_object, dict):
            app.config.update(config_object)
        else:
            app.config.from_object(config_object)

    guard = configure_storage(app)
    db.init_app(app)
    migrate.init_app(app, db, directory=str(Path(__file__).resolve().parents[1] / "migrations"))

    from . import models  # noqa: F401
    from .routes.analyses import bp as analyses_bp
    from .routes.core import bp as core_bp
    from .routes.data import bp as data_bp
    from .routes.language import bp as language_bp
    from .routes.resources import bp as resources_bp
    from .routes.writings import bp as writings_bp

    for blueprint in [core_bp, resources_bp, writings_bp, analyses_bp, language_bp, data_bp]:
        app.register_blueprint(blueprint)

    secret_store = app.config.get("SECRET_STORE") or DpapiSecretStore(app.config["SECRET_FILE"])
    app.extensions["secret_store"] = secret_store
    app.extensions["dictionary_client"] = DictionaryClient(lambda: secret_store.get("stdictApiKey"))

    if guard:
        from flask import request

        @app.before_request
        def verified_storage_boundary():
            guard.check()
            # This legacy app has no student authentication/ownership yet.
            # Never expose its single-workspace API as a multi-user service.
            if request.path.startswith("/api/") and request.path != "/api/health":
                return jsonify({"error": {"code": "AUTHENTICATION_NOT_IMPLEMENTED", "message": "인증 및 소유권 검증이 완료되지 않아 사용자 API가 차단되었습니다.", "fields": {}}}), 503

    @app.errorhandler(StorageBlocked)
    def storage_blocked(error):
        return jsonify({"error": {"code": error.code, "message": "저장소 검증 또는 저장에 실패했습니다. 초안을 보존하고 서버의 저장소 상태를 확인해 주세요.", "fields": {}}}), 503

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self' https://www.googletagmanager.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'")
        return response

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": {"code": "FILE_TOO_LARGE", "message": "업로드 파일이 허용 용량을 초과했습니다.", "fields": {}}}), 413

    @app.errorhandler(Exception)
    def handle_error(error):
        if isinstance(error, HTTPException):
            if error.code == 404 and not str(getattr(error, "description", "")).startswith("API"):
                return error
            return jsonify({"error": {"code": error.name.upper().replace(" ", "_"), "message": error.description, "fields": {}}}), error.code
        if guard and isinstance(error, DBAPIError):
            guard.latch()
            db.session.remove()
            return storage_blocked(StorageBlocked("STORAGE_IO_FAILURE"))
        # Exception messages/SQL parameters may contain essay text or secrets.
        app.logger.error("Unhandled application error: %s", type(error).__name__)
        return jsonify({"error": {"code": "INTERNAL_ERROR", "message": "요청을 처리하지 못했습니다.", "fields": {}}}), 500

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path):
        if path.startswith("api/"):
            return jsonify({"error": {"code": "NOT_FOUND", "message": "API 경로를 찾을 수 없습니다.", "fields": {}}}), 404
        first_segment = path.split("/", 1)[0].lower()
        if first_segment in {"backend", "src", "uploads", "instance", "backups", "local-admin", ".git", ".env", "node_modules"} or path.lower().endswith((".db", ".sqlite", ".sqlite3", ".py", ".env")):
            return jsonify({"error": {"code": "NOT_FOUND", "message": "경로를 찾을 수 없습니다.", "fields": {}}}), 404
        dist = Path(app.config["FRONTEND_DIST"]).resolve()
        if not dist.is_dir():
            return jsonify({"error": {"code": "FRONTEND_NOT_BUILT", "message": "프론트엔드 production build가 필요합니다.", "fields": {}}}), 503
        candidate = (dist / path).resolve()
        if path and candidate.is_relative_to(dist) and candidate.is_file():
            return send_from_directory(dist, path)
        return send_from_directory(dist, "index.html")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with app.app_context():
        if app.config.get("TESTING"):
            db.create_all()
            ensure_defaults()
        else:
            @event.listens_for(db.engine, "before_cursor_execute")
            def verify_before_database_use(_connection, _cursor, _statement, _parameters, _context, _many):
                guard.check()
            # Readiness does not mutate schema, seed data, or interrupted jobs.
            # Recovery needs an approved authenticated 2.0 lifecycle.
    return app
