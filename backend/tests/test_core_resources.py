import io

import fitz

from conftest import payload


def test_health_database_and_errors(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert payload(response) == {"status": "ok", "database": "ok", "version": "1"}
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.is_json


def test_workspace_and_settings_validation(client):
    assert client.patch("/api/workspace", json={"workspaceName": "학교 글빛"}).status_code == 200
    assert payload(client.get("/api/workspace"))["workspaceName"] == "학교 글빛"
    assert client.patch("/api/settings", json={"autosaveInterval": 30}).status_code == 200
    assert client.patch("/api/settings", json={"unknown": True}).status_code == 400


def test_rubric_crud_search_pagination_and_duplicate(client):
    created = client.post("/api/rubrics", json={"name": "문학 평가 기준", "subject": "국어", "items": [{"name": "근거 사용", "checkType": "자동 확인"}]})
    assert created.status_code == 201
    item = payload(created)
    assert item["cards"] == 1
    listed = client.get("/api/rubrics?search=문학&page=1&pageSize=10").get_json()
    assert listed["pagination"]["total"] == 1
    assert client.post(f"/api/rubrics/{item['id']}/duplicate").status_code == 201
    assert client.patch(f"/api/rubrics/{item['id']}", json={"name": "수정한 기준"}).status_code == 200
    assert client.delete(f"/api/rubrics/{item['id']}").status_code == 200
    assert client.get(f"/api/rubrics/{item['id']}").status_code == 404


def test_confirmed_rubric_ocr_text_creates_human_review_cards(client):
    uploaded = client.post(
        "/api/rubrics",
        data={"file": (io.BytesIO("1. 작품의 근거를 정확히 인용했는가\n2. 근거의 의미를 충분히 설명했는가".encode()), "rubric.txt")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201
    rubric = payload(uploaded)
    assert rubric["cards"] == 0
    confirmed = payload(client.patch(
        f"/api/rubrics/{rubric['id']}",
        json={"correctedText": "1. 작품의 근거를 정확히 인용했는가\n2. 근거의 의미를 충분히 설명했는가", "confirm": True},
    ))
    assert confirmed["status"] == "등록 완료"
    assert confirmed["cards"] == 2
    assert all(item["checkType"] == "사람의 판단 필요" for item in confirmed["items"])


def test_source_text_upload_ocr_edit_quote_and_delete_guard(client):
    response = client.post("/api/source-documents", data={"title": "작품", "author": "작가", "file": (io.BytesIO("원문 텍스트입니다.".encode()), "source.txt")}, content_type="multipart/form-data")
    assert response.status_code == 201
    source = payload(response)
    assert source["pageData"][0]["originalText"] == "원문 텍스트입니다."
    assert client.patch(f"/api/source-documents/{source['id']}/pages/1", json={"correctedText": "수정 원문", "confirm": True}).status_code == 200
    quote = payload(client.post("/api/quote-cards", json={"documentId": source["id"], "selectedText": "수정 원문", "quote": "다른 원문", "work": "작품"}))
    assert quote["verificationStatus"] == "원문과 다름"
    assert client.delete(f"/api/source-documents/{source['id']}").status_code == 409
    assert client.delete(f"/api/quote-cards/{quote['id']}").status_code == 200
    assert client.delete(f"/api/source-documents/{source['id']}").status_code == 200


def test_pdf_text_layer_and_invalid_file(client):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "This PDF contains a searchable text layer for OCR extraction.")
    pdf_bytes = document.tobytes()
    document.close()
    response = client.post("/api/source-documents", data={"file": (io.BytesIO(pdf_bytes), "source.pdf")}, content_type="multipart/form-data")
    assert response.status_code == 201
    assert "searchable" in payload(response)["pageData"][0]["originalText"]
    denied = client.post("/api/source-documents", data={"file": (io.BytesIO(b"bad"), "bad.exe")}, content_type="multipart/form-data")
    assert denied.status_code == 400


def test_secure_files_and_spa_fallback(client):
    assert client.get("/settings").status_code == 200
    assert client.get("/backend/instance/geulbit.db").status_code == 404
    assert client.get("/.env").status_code == 404
    assert client.get("/src/App.tsx").status_code == 404
