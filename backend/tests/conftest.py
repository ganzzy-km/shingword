import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.services.secrets_service import MemorySecretStore  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body><div id='root'>글빛</div></body></html>", encoding="utf-8")
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        "DATABASE_PATH": tmp_path / "test.db",
        "UPLOAD_FOLDER": tmp_path / "uploads",
        "BACKUP_FOLDER": tmp_path / "backups",
        "FRONTEND_DIST": dist,
        "MAX_CONTENT_LENGTH": 1024 * 1024,
        "SECRET_STORE": MemorySecretStore(),
        "ADMIN_STATE_FILE": tmp_path / "local-admin.json",
        "ADMIN_AUDIT_FILE": tmp_path / "local-admin-audit.jsonl",
    })
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()  # pytest owns this isolated directory; no FK bypass or table deletion


@pytest.fixture()
def client(app):
    return app.test_client()


def payload(response):
    return response.get_json()["data"]
