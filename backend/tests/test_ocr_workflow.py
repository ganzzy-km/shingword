import io

import fitz
from PIL import Image

from app.models import OcrRun
from app.services import ocr_service
from conftest import payload


def _png_bytes(width=320, height=120):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def _pdf_bytes(page_count=1, with_text=True):
    document = fitz.open()
    for index in range(page_count):
        page = document.new_page()
        if with_text and index == 0:
            page.insert_text((72, 72), "This page has enough native text to skip optical recognition.")
    value = document.tobytes()
    document.close()
    return value


def test_ocr_diagnostic_distinguishes_missing_executable(monkeypatch):
    monkeypatch.setattr(ocr_service, "_resolve_tesseract_command", lambda _value=None: None)
    result = ocr_service.diagnose_ocr()
    assert result["status"] == "executable_missing"
    assert result["ready"] is False
    assert "한글 OCR 환경" in result["message"]
    assert "command" not in result


def test_mixed_pdf_uses_native_text_and_ocr_only_for_scan_page(tmp_path, monkeypatch):
    path = tmp_path / "mixed.pdf"
    path.write_bytes(_pdf_bytes(page_count=2))
    monkeypatch.setattr(
        ocr_service,
        "diagnose_ocr",
        lambda *_args, **_kwargs: {"ready": True, "status": "ready"},
    )
    monkeypatch.setattr(
        ocr_service, "_resolve_tesseract_command", lambda _value=None: "tesseract-test"
    )
    monkeypatch.setattr(
        ocr_service,
        "_ocr_image",
        lambda *_args, **_kwargs: ("스캔 페이지의 한글과 English", 91.5),
    )

    result = ocr_service.extract_pages(path, ".pdf")

    assert result["status"] == "completed"
    assert [page["method"] for page in result["pages"]] == ["native_text", "ocr"]
    assert "native text" in result["pages"][0]["text"]
    assert result["pages"][1]["text"] == "스캔 페이지의 한글과 English"


def test_exif_orientation_is_applied_without_changing_original():
    image = Image.new("RGB", (80, 40), "white")
    exif = image.getexif()
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=exif)
    original = output.getvalue()
    with Image.open(io.BytesIO(original)) as loaded:
        prepared = ocr_service._prepare_image(loaded, 1_000_000)
        assert prepared.size == (40, 80)
    assert output.getvalue() == original


def test_rubric_ocr_unavailable_is_safe_and_persistent(app, client, monkeypatch):
    monkeypatch.setattr(ocr_service, "_resolve_tesseract_command", lambda _value=None: None)
    created = client.post(
        "/api/rubrics",
        data={"file": (io.BytesIO(_png_bytes()), "한글 자료.png")},
        content_type="multipart/form-data",
    )
    assert created.status_code == 201
    item = payload(created)
    assert item["status"] == "OCR 실행 환경 필요"
    assert item["originalName"] == "한글 자료.png"
    assert item["ocr"]["status"] == "unavailable"

    rerun = client.post(f"/api/rubrics/{item['id']}/ocr")
    assert rerun.status_code == 200
    rerun_item = payload(rerun)
    assert rerun_item["ocr"]["status"] == "unavailable"
    assert "다른 기능은 계속 사용할 수 있습니다" in rerun_item["ocr"]["message"]
    assert payload(client.get(f"/api/rubrics/{item['id']}"))["ocr"]["status"] == "unavailable"
    with app.app_context():
        assert OcrRun.query.filter_by(target_type="rubric", target_id=item["id"]).count() == 2
    assert client.delete(f"/api/rubrics/{item['id']}").status_code == 200
    with app.app_context():
        assert OcrRun.query.filter_by(target_type="rubric", target_id=item["id"]).count() == 0


def test_duplicate_ocr_submission_is_rejected(client, monkeypatch):
    monkeypatch.setattr(ocr_service, "_resolve_tesseract_command", lambda _value=None: None)
    item = payload(
        client.post(
            "/api/rubrics",
            data={"file": (io.BytesIO(_png_bytes()), "source.png")},
            content_type="multipart/form-data",
        )
    )
    from app.routes import resources

    key = ("rubric", item["id"])
    resources._active_ocr_targets.add(key)
    try:
        response = client.post(f"/api/rubrics/{item['id']}/ocr")
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "OCR_ALREADY_RUNNING"
    finally:
        resources._active_ocr_targets.discard(key)


def test_upload_rejects_disguised_image_and_page_limit(app, client):
    disguised = client.post(
        "/api/source-documents",
        data={"file": (io.BytesIO(b"not an image"), "fake.png")},
        content_type="multipart/form-data",
    )
    assert disguised.status_code == 400
    assert list(app.config["UPLOAD_FOLDER"].iterdir()) == []

    app.config["OCR_MAX_PAGES"] = 1
    too_many = client.post(
        "/api/source-documents",
        data={"file": (io.BytesIO(_pdf_bytes(page_count=2)), "long.pdf")},
        content_type="multipart/form-data",
    )
    assert too_many.status_code == 400
    assert "최대 1페이지" in too_many.get_json()["error"]["message"]


def test_text_pdf_is_not_marked_as_ocr_required(client):
    response = client.post(
        "/api/source-documents",
        data={"file": (io.BytesIO(_pdf_bytes()), "native.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    item = payload(response)
    assert item["status"] == "등록 완료"
    assert item["ocr"]["status"] == "not_required"
    assert item["pageData"][0]["extractionMethod"] == "native_text"


def test_ocr_status_endpoint_never_exposes_server_path(client, monkeypatch):
    from app.routes import resources

    monkeypatch.setattr(
        resources,
        "diagnose_ocr",
        lambda *_args: {
            "status": "ready",
            "ready": True,
            "languages": ["eng", "kor"],
            "message": "OCR 실행 환경이 준비되었습니다.",
        },
    )
    data = payload(client.get("/api/ocr/status"))
    assert data["languages"] == ["eng", "kor"]
    assert "path" not in data
    assert "command" not in data
