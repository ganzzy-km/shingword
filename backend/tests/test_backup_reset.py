import io
import zipfile

from PIL import Image

from conftest import payload
from app.models import OcrRun, Rubric, Workspace, WorkspaceSetting, Writing
from app.services import ocr_service


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(output, format="PNG")
    return output.getvalue()


def test_backup_create_download_and_invalid_restore(client):
    client.post("/api/rubrics", json={"name": "백업 기준"})
    created = client.post("/api/backups", json={"includeUploads": True})
    assert created.status_code == 201
    backup = payload(created)
    downloaded = client.get(backup["downloadUrl"])
    assert downloaded.status_code == 200
    assert downloaded.data.startswith(b"PK")
    invalid = client.post("/api/backups/restore", data={"confirmation": "복원", "file": (io.BytesIO(b"not zip"), "bad.zip")}, content_type="multipart/form-data")
    assert invalid.status_code == 400


def test_reset_requires_confirmation_and_clears_user_data(app, client, monkeypatch):
    client.post("/api/rubrics", json={"name": "삭제 기준"})
    monkeypatch.setattr(ocr_service, "_resolve_tesseract_command", lambda _value=None: None)
    client.post(
        "/api/rubrics",
        data={"file": (io.BytesIO(png_bytes()), "삭제할-업로드.png")},
        content_type="multipart/form-data",
    )
    client.post("/api/writings", json={"title": "삭제할 글", "content": "삭제 대상", "status": "임시 저장"})
    client.patch("/api/settings", json={"fontSize": "크게"})
    assert client.post("/api/workspace/reset", json={"confirmation": "아님"}).status_code == 400
    assert client.post("/api/workspace/reset", json={"confirmation": "초기화"}).status_code == 200
    assert client.get("/api/rubrics").get_json()["pagination"]["total"] == 0
    assert len(payload(client.get("/api/rules"))) >= 2
    assert list(app.config["UPLOAD_FOLDER"].iterdir()) == []
    with app.app_context():
        assert Rubric.query.count() == 0
        assert Writing.query.count() == 0
        assert OcrRun.query.count() == 0
        from app.seed import DEFAULT_SETTINGS
        assert {setting.key for setting in WorkspaceSetting.query.all()} == set(DEFAULT_SETTINGS)
        assert Workspace.query.one().user_name == ""


def test_export_json(client):
    response = client.get("/api/backups/export")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
