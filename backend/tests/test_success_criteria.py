from __future__ import annotations

import io

import fitz
import pytest
from PIL import Image

from app.analysis.engine import argument_links, classify_role
from app.analysis.spelling import spelling_findings
from app.services import ocr_service
from serve import _main_server_address
from validation.cases import CLASSIFICATION_CASES, LINK_CASES, SPELLING_CASES


def _image_bytes(kind):
    output = io.BytesIO()
    Image.new("RGB", (120, 60), "white").save(output, format=kind)
    return output.getvalue()


def _native_pdf_bytes():
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Native text PDF for the Geulbit upload validation.")
    value = document.tobytes()
    document.close()
    return value


def test_30_sentence_classification_dataset_is_complete_and_executable():
    assert len(CLASSIFICATION_CASES) == 30
    assert {category: sum(case["category"] == category for case in CLASSIFICATION_CASES) for category in {case["category"] for case in CLASSIFICATION_CASES}} == {
        "명확한 주장": 10,
        "명확한 근거": 10,
        "애매한 문장": 10,
    }
    results = [classify_role(case["text"])[0] for case in CLASSIFICATION_CASES]
    assert len(results) == 30
    assert all(result in {"주장", "근거", "설명", "효과", "탐구 질문 연결", "분류되지 않음"} for result in results)


def test_connected_cases_score_above_unconnected_cases():
    connected = []
    unconnected = []
    for case in LINK_CASES:
        score = argument_links(case["sentences"])[0]["score"]
        (connected if case["expected"] == "연결" else unconnected).append(score)
    assert len(connected) == len(unconnected) == 5
    assert min(connected) > max(unconnected)


def test_spelling_and_normal_sentence_expectations():
    for case in SPELLING_CASES:
        assert [item["current"] for item in spelling_findings(case["text"])] == case["expected"]


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("criteria.pdf", _native_pdf_bytes()),
        ("criteria.png", _image_bytes("PNG")),
        ("criteria.jpg", _image_bytes("JPEG")),
        ("criteria.jpeg", _image_bytes("JPEG")),
    ],
)
@pytest.mark.parametrize("endpoint", ["/api/rubrics", "/api/source-documents"])
def test_success_criterion_upload_formats(client, monkeypatch, filename, content, endpoint):
    monkeypatch.setattr(ocr_service, "_resolve_tesseract_command", lambda _value=None: None)
    response = client.post(
        endpoint,
        data={"file": (io.BytesIO(content), filename)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["originalName"] == filename


def test_school_server_address_defaults_and_validation(monkeypatch):
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)
    assert _main_server_address() == ("127.0.0.1", 5000)
    monkeypatch.setenv("APP_PORT", "70000")
    with pytest.raises(RuntimeError):
        _main_server_address()
