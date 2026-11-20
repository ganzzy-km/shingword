"""Original rubric preview is private; confirmation never rewrites file bytes."""
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path

import fitz
import pytest

from v2_fixture import v2app, user_client
from app.extensions import db
from app.models import RubricFile
from app.v2 import library_api


def upload(client, headers, kind="txt"):
    if kind == "pdf":
        pdf = fitz.open()
        pdf.new_page().insert_text((72, 72), "Synthetic rubric original text")
        original = pdf.tobytes()
        pdf.close()
    else:
        original = "가상 평가 기준😀\r\n학생의 근거를 확인한다.".encode("utf-8")
    response = client.post("/api/rubrics", headers=headers,
                           data={"file": (io.BytesIO(original), "synthetic." + kind)})
    assert response.status_code == 201
    return response.json["data"], original


@pytest.mark.parametrize("kind,mime", [("txt", "text/plain"), ("pdf", "application/pdf")])
def test_owner_gets_exact_original_inline_with_private_security_headers(v2app, kind, mime):
    client, headers, _ = user_client(v2app)
    rubric, original = upload(client, headers, kind)
    response = client.get("/api/files/rubrics/" + rubric["fileId"])
    assert response.status_code == 200 and response.data == original
    assert response.mimetype == mime
    assert response.headers["Content-Disposition"].startswith("inline;")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("role", ["USER", "ADMIN"])
def test_foreign_account_is_denied_before_any_filesystem_lookup(v2app, monkeypatch, role):
    owner, headers, _ = user_client(v2app)
    rubric, _ = upload(owner, headers)
    foreign, _, _ = user_client(v2app, "synthetic-file-foreign-" + role, role=role)
    def forbidden_path(*_):
        raise AssertionError("Filesystem must not be consulted for another owner's rubric")
    monkeypatch.setattr(library_api, "Path", forbidden_path)
    assert foreign.get("/api/files/rubrics/" + rubric["fileId"]).status_code == 404


def test_unauthenticated_request_does_not_serve_original(v2app):
    owner, headers, _ = user_client(v2app)
    rubric, _ = upload(owner, headers)
    response = v2app.test_client().get("/api/files/rubrics/" + rubric["fileId"])
    assert response.status_code == 401 and response.json["error"]["code"] == "ACCESS_DENIED"


def test_missing_record_and_deleted_rubric_do_not_serve_file(v2app):
    owner, headers, _ = user_client(v2app)
    assert owner.get("/api/files/rubrics/does-not-exist").status_code == 404
    rubric, _ = upload(owner, headers)
    assert owner.delete("/api/rubrics/" + rubric["id"], headers=headers).status_code in {200, 202}
    assert owner.get("/api/files/rubrics/" + rubric["fileId"]).status_code == 404


def test_missing_original_file_is_not_served(v2app):
    owner, headers, _ = user_client(v2app)
    rubric, _ = upload(owner, headers)
    with v2app.app_context():
        record = db.session.get(RubricFile, rubric["fileId"])
        (Path(v2app.config["UPLOAD_FOLDER"]) / record.stored_name).unlink()
    assert owner.get("/api/files/rubrics/" + rubric["fileId"]).status_code == 404


def test_expired_rubric_is_denied_before_filesystem_lookup(v2app, monkeypatch):
    from app.v2.privacy_lifecycle import DOCUMENT_POLICY
    owner, headers, _ = user_client(v2app)
    rubric, _ = upload(owner, headers)
    with v2app.app_context():
        db.session.get(RubricFile, rubric["fileId"]).updated_at = datetime.now(timezone.utc) - timedelta(days=8)
        db.session.commit()
    v2app.config["PRIVATE_DOCUMENT_RETENTION_POLICY"] = DOCUMENT_POLICY
    def forbidden_path(*_):
        raise AssertionError("Expired original must not reach filesystem access")
    monkeypatch.setattr(library_api, "Path", forbidden_path)
    assert owner.get("/api/files/rubrics/" + rubric["fileId"]).status_code == 404


@pytest.mark.parametrize("kind", ["relative_escape", "absolute_escape", "alternate_stream"])
def test_unsafe_stored_name_cannot_serve_outside_uploads(v2app, tmp_path, kind):
    owner, headers, _ = user_client(v2app)
    rubric, original = upload(owner, headers)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"private synthetic outside data")
    with v2app.app_context():
        record = db.session.get(RubricFile, rubric["fileId"])
        original_path = Path(v2app.config["UPLOAD_FOLDER"]) / record.stored_name
        record.stored_name = {"relative_escape": "../outside.txt", "absolute_escape": str(outside), "alternate_stream": "synthetic.txt:stream"}[kind]
        db.session.commit()
    assert owner.get("/api/files/rubrics/" + rubric["fileId"]).status_code == 404
    assert outside.read_bytes() == b"private synthetic outside data"
    assert original_path.read_bytes() == original


@pytest.mark.parametrize("mime", ["text/html", "image/png"])
def test_unsupported_mime_never_served_inline(v2app, mime):
    owner, headers, _ = user_client(v2app)
    rubric, _ = upload(owner, headers)
    with v2app.app_context():
        db.session.get(RubricFile, rubric["fileId"]).mime_type = mime
        db.session.commit()
    assert owner.get("/api/files/rubrics/" + rubric["fileId"]).status_code == 404


def test_correction_confirmation_preserves_original_bytes_and_file_identity(v2app):
    owner, headers, _ = user_client(v2app)
    rubric, original = upload(owner, headers)
    response = owner.patch("/api/rubrics/" + rubric["id"], headers=headers,
                           json={"correctedText": "사람이 확인한 평가 기준😀", "confirm": True})
    assert response.status_code == 200
    assert response.json["data"]["fileId"] == rubric["fileId"]
    assert response.json["data"]["status"] == "확인 완료"
    preview = owner.get("/api/files/rubrics/" + rubric["fileId"])
    assert preview.status_code == 200 and preview.data == original
    detail = owner.get("/api/rubrics/" + rubric["id"]).json["data"]
    assert detail["fileId"] == rubric["fileId"] and detail["correctedText"] == "사람이 확인한 평가 기준😀"
