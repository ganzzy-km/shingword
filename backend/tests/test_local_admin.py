from __future__ import annotations

import json
import re

from app.local_admin import create_local_admin_app
from app.services.secrets_service import MemorySecretStore
from app.services.secrets_service import DpapiSecretStore


VALID_KEY = "a" * 32


class ValidDictionaryTransport:
    def get_json(self, endpoint, parameters):
        return {"channel": {"item": {
            "target_code": 404765, "word": "나무", "sup_no": 1, "pos": "명사",
            "sense": {"definition": "목질 식물.", "link": "https://stdict.korean.go.kr/search/searchView.do?word_no=404765"},
        }}}


def csrf(response):
    match = re.search(rb'name="csrf" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def make_admin(tmp_path):
    store = MemorySecretStore()
    app = create_local_admin_app({
        "TESTING": True,
        "SECRET_FILE": tmp_path / "secrets.dat",
        "ADMIN_STATE_FILE": tmp_path / "local-admin.json",
        "ADMIN_AUDIT_FILE": tmp_path / "audit.jsonl",
    }, secret_store=store, dictionary_transport=ValidDictionaryTransport())
    return app, store


def setup_and_login(client):
    token = csrf(client.get("/local-admin/setup"))
    response = client.post("/local-admin/setup", data={
        "csrf": token, "password": "안전한-관리자-비밀번호-123", "passwordConfirm": "안전한-관리자-비밀번호-123",
    })
    assert response.status_code == 302
    token = csrf(client.get("/local-admin/login"))
    response = client.post("/local-admin/login", data={"csrf": token, "password": "안전한-관리자-비밀번호-123"})
    assert response.status_code == 302


def test_local_admin_setup_login_key_mask_and_session_end(tmp_path):
    app, store = make_admin(tmp_path)
    client = app.test_client()
    setup_and_login(client)
    page = client.get("/local-admin/api-key")
    token = csrf(page)
    saved = client.post("/local-admin/api-key", data={
        "csrf": token,
        "password": "안전한-관리자-비밀번호-123",
        "newKey": VALID_KEY,
        "newKeyConfirm": VALID_KEY,
    })
    assert saved.status_code == 302
    assert store.get("stdictApiKey") == VALID_KEY
    assert client.get("/local-admin/api-key").status_code == 302

    token = csrf(client.get("/local-admin/login?changed=1"))
    client.post("/local-admin/login", data={"csrf": token, "password": "안전한-관리자-비밀번호-123"})
    page = client.get("/local-admin/api-key")
    assert VALID_KEY.encode() not in page.data
    assert b"aaaa" in page.data

    state = json.loads((tmp_path / "local-admin.json").read_text(encoding="utf-8"))
    assert "안전한-관리자-비밀번호-123" not in str(state)
    assert state["passwordHash"].startswith("$argon2id$")
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert VALID_KEY not in audit and "안전한-관리자-비밀번호-123" not in audit


def test_local_admin_csrf_rate_limit_and_external_denial(tmp_path):
    app, _ = make_admin(tmp_path)
    client = app.test_client()
    setup_and_login(client)
    assert client.post("/local-admin/logout", data={}).status_code == 400
    token = csrf(client.get("/local-admin/api-key"))
    client.post("/local-admin/logout", data={"csrf": token})

    for _ in range(5):
        page = client.get("/local-admin/login")
        client.post("/local-admin/login", data={"csrf": csrf(page), "password": "틀린 비밀번호"})
    page = client.get("/local-admin/login")
    locked = client.post("/local-admin/login", data={"csrf": csrf(page), "password": "안전한-관리자-비밀번호-123"})
    assert "10분" in locked.get_data(as_text=True)
    assert client.get("/local-admin/login", environ_base={"REMOTE_ADDR": "192.0.2.10"}).status_code == 403


def test_key_replacement_requires_phrase_and_preserves_existing_key_on_failure(tmp_path):
    app, store = make_admin(tmp_path)
    store.set("stdictApiKey", "b" * 32)
    client = app.test_client()
    setup_and_login(client)
    page = client.get("/local-admin/api-key")
    response = client.post("/local-admin/api-key", data={
        "csrf": csrf(page), "password": "안전한-관리자-비밀번호-123",
        "newKey": VALID_KEY, "newKeyConfirm": VALID_KEY, "confirmation": "틀린 문구",
    })
    assert response.status_code == 302
    assert store.get("stdictApiKey") == "b" * 32


def test_windows_dpapi_round_trip_does_not_store_plaintext(tmp_path):
    store = DpapiSecretStore(tmp_path / "secrets.dat")
    if not store.available:
        return
    secret = "0123456789abcdef" * 2
    store.set("stdictApiKey", secret)
    assert store.get("stdictApiKey") == secret
    assert secret.encode() not in (tmp_path / "secrets.dat").read_bytes()
