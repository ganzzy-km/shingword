"""Region-request boundaries; synthetic isolated fixtures, no model inference."""
import copy

import pytest

from test_ocr_api import setup, ready
from v2_fixture import v2app, user_client
from app.extensions import db
from app.models import AppSetting, DocumentRevision, OcrRun, SourceDocument
from app.services import ocr_jobs as jobs


def saved_state(app, job_id):
    with app.app_context():
        run, record = jobs.row(job_id)
        return {
            "jobs": OcrRun.query.count(),
            "records": AppSetting.query.count(),
            "revisions": DocumentRevision.query.count(),
            "status": run.status,
            "metadata": copy.deepcopy(record.value),
        }


@pytest.mark.parametrize("engine", [[], {}, None, True, 1, "unknown"])
def test_malformed_region_engine_is_validation_error_without_writes(setup, engine):
    app, client, headers, owner, did, jid, document, _ = setup
    ready(app, jid)
    before = saved_state(app, jid)
    response = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers,
                           json={"page": 1, "box": [0, 0, 10, 10], "engine": engine})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"
    assert saved_state(app, jid) == before


@pytest.mark.parametrize("page", [True, False])
def test_boolean_page_is_validation_error_without_writes(setup, page):
    app, client, headers, owner, did, jid, document, _ = setup
    ready(app, jid)
    before = saved_state(app, jid)
    response = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers,
                           json={"page": page, "box": [0, 0, 10, 10], "engine": "paddle"})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "VALIDATION_ERROR"
    assert saved_state(app, jid) == before


def test_owner_queue_full_is_busy_without_draft_or_revision_changes(setup):
    app, client, headers, owner, did, jid, document, _ = setup
    ready(app, jid, "검수 중 원문😀")
    with app.app_context():
        item = db.session.get(SourceDocument, did)
        for _ in range(2):
            jobs.create_job(item, document["latestRevisionId"])
        db.session.commit()
    before = saved_state(app, jid)
    response = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers,
                           json={"page": 1, "box": [0, 0, 10, 10], "engine": "paddle"})
    assert response.status_code == 429
    assert response.json["error"]["code"] == "OCR_BUSY"
    assert saved_state(app, jid) == before


@pytest.mark.parametrize("unavailable", ["missing", "invalid"])
def test_unavailable_configuration_is_service_error_without_writes(setup, monkeypatch, unavailable):
    app, client, headers, owner, did, jid, document, _ = setup
    ready(app, jid)
    before = saved_state(app, jid)
    def config():
        if unavailable == "invalid":
            raise ValueError("OCR_CONFIG_UNAVAILABLE")
        return None
    monkeypatch.setattr(jobs, "config", config)
    response = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers,
                           json={"page": 1, "box": [0, 0, 10, 10], "engine": "paddle"})
    assert response.status_code == 503
    assert response.json["error"]["code"] == "OCR_UNAVAILABLE"
    assert saved_state(app, jid) == before


@pytest.mark.parametrize("condition,code", [("invalid_config", "OCR_UNAVAILABLE"), ("low_memory", "OCR_RESOURCE_BUSY")])
def test_vl_configuration_error_and_memory_denial_are_distinct_without_writes(setup, monkeypatch, condition, code):
    app, client, headers, owner, did, jid, document, _ = setup
    ready(app, jid)
    before = saved_state(app, jid)
    if condition == "invalid_config":
        def config():
            raise ValueError("OCR_CONFIG_UNAVAILABLE")
        monkeypatch.setattr(jobs, "config", config)
    else:
        monkeypatch.setattr(jobs, "host_memory", lambda: {"available": True, "physicalAvailableBytes": 1, "commitAvailableBytes": 1})
    response = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers,
                           json={"page": 1, "box": [0, 0, 10, 10], "engine": "vl"})
    assert response.status_code == 503
    assert response.json["error"]["code"] == code
    assert saved_state(app, jid) == before


def test_valid_duplicate_and_conflicting_region_requests_keep_existing_contract(setup):
    app, client, headers, owner, did, jid, document, _ = setup
    ready(app, jid)
    body = {"page": 1, "box": [0, 0, 10, 10], "engine": "paddle"}
    first = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers, json=body)
    assert first.status_code == 202
    before = saved_state(app, jid)
    again = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers, json=body)
    assert again.status_code == 202 and again.json["data"]["id"] == first.json["data"]["id"]
    assert saved_state(app, jid) == before
    conflict = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers,
                           json={**body, "box": [0, 0, 20, 20]})
    assert conflict.status_code == 409 and conflict.json["error"]["code"] == "OCR_BUSY"
    assert saved_state(app, jid) == before


@pytest.mark.parametrize("boundary", ["csrf", "foreign", "match_only"])
def test_authorization_precedes_region_processing_and_preserves_data(setup, boundary):
    app, client, headers, owner, did, jid, document, _ = setup
    ready(app, jid)
    expected = 401 if boundary == "csrf" else 404
    if boundary == "csrf":
        headers = {}
    elif boundary == "foreign":
        client, headers, _ = user_client(app, "synthetic-request-safety-other")
    else:
        with app.app_context():
            db.session.get(SourceDocument, did).access_mode = "MATCH_ONLY"
            db.session.commit()
    before = saved_state(app, jid)
    response = client.post("/api/ocr-jobs/" + jid + "/region", headers=headers,
                           json={"page": 1, "box": [0, 0, 10, 10], "engine": "paddle"})
    assert response.status_code == expected
    assert saved_state(app, jid) == before
