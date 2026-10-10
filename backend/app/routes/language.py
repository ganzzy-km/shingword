from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, current_app, request

from ..analysis.integration import compare_sentences
from ..utils import api_error, json_body, success


bp = Blueprint("language", __name__, url_prefix="/api")


def _dictionary_client():
    return current_app.extensions["dictionary_client"]


@bp.get("/dictionary/status")
def dictionary_status():
    store = current_app.extensions["secret_store"]
    try:
        configured = store.contains("stdictApiKey")
    except Exception:
        configured = False
    status = "available" if configured else "not_configured"
    checked_at = None
    state_path = Path(current_app.config["ADMIN_STATE_FILE"])
    if configured and state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last = state.get("dictionary", {})
            status = last.get("status", status)
            checked_at = last.get("checkedAt")
        except (OSError, ValueError, TypeError):
            pass
    return success({
        "status": status,
        "available": status == "available",
        "checkedAt": checked_at,
        "notice": None if status == "available" else "공식 사전 보조 검증은 현재 제한되지만 나머지 분석 기능은 정상 동작합니다.",
    })


@bp.get("/dictionary/lookup")
def dictionary_lookup():
    query = request.args.get("q", "").strip()
    if not query:
        return api_error("VALIDATION_ERROR", "검색어를 입력해 주세요.", fields={"q": "필수 항목입니다."})
    return success(_dictionary_client().lookup(query))


@bp.get("/dictionary/entries/<target_code>")
def dictionary_entry(target_code):
    query = request.args.get("q", "").strip()
    if not query:
        return api_error("VALIDATION_ERROR", "표제어를 입력해 주세요.", fields={"q": "필수 항목입니다."})
    return success(_dictionary_client().detail(target_code, query))


@bp.post("/semantic/compare")
def semantic_compare():
    data, error = json_body()
    if error:
        return error
    left, right = data.get("left"), data.get("right")
    fields = {}
    if not isinstance(left, str) or not left.strip():
        fields["left"] = "첫 번째 문장을 입력해 주세요."
    if not isinstance(right, str) or not right.strip():
        fields["right"] = "두 번째 문장을 입력해 주세요."
    if isinstance(left, str) and len(left) > 2000:
        fields["left"] = "문장은 2,000자 이하여야 합니다."
    if isinstance(right, str) and len(right) > 2000:
        fields["right"] = "문장은 2,000자 이하여야 합니다."
    if fields:
        return api_error("VALIDATION_ERROR", "비교할 문장을 확인해 주세요.", fields=fields)
    return success(compare_sentences(left.strip(), right.strip()))

