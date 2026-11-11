"""Optional question boundary. No provider URL/key or shared text cache here."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from .auth import require_private_owner

TEMPLATES = {
    "ASSUMPTION": "이 주장과 근거 사이에 어떤 전제가 필요한가요?",
    "CONCEPT": "이 구절의 핵심 개념을 어떻게 구분할 수 있나요?",
    "CAUSALITY": "이 근거로 인과 관계를 설명하려면 무엇을 더 확인해야 하나요?",
    "EVIDENCE": "이 근거는 주장에 어떤 방식으로 연결되나요?",
    "COUNTEREXAMPLE": "이 주장에 적용되지 않는 범위나 반례가 있을까요?",
}

# The model selects a grounded focus and a question intent. Server-owned
# wording cannot introduce a character, ending, event or score from the model.
QUESTION_OPTIONS = {
    "ASSUMPTION": (TEMPLATES["ASSUMPTION"], "이 구절을 이해하려면 어떤 전제를 먼저 확인해야 하나요?", "이 전제가 달라지면 주장과 근거의 연결은 어떻게 달라질까요?"),
    "CONCEPT": (TEMPLATES["CONCEPT"], "이 구절에서 같은 뜻으로 사용한 개념이 있는지 확인해 볼까요?", "핵심 개념을 다른 뜻으로 이해하면 해석은 어떻게 달라질까요?"),
    "CAUSALITY": (TEMPLATES["CAUSALITY"], "이 구절의 관계를 원인과 결과로 해석할 근거는 무엇인가요?", "이 관계를 설명할 다른 가능성도 생각해 볼 수 있나요?"),
    "EVIDENCE": (TEMPLATES["EVIDENCE"], "이 구절이 뒷받침하는 주장의 범위는 어디까지인가요?", "이 구절의 관찰과 자신의 해석을 어떻게 구분할 수 있나요?"),
    "COUNTEREXAMPLE": (TEMPLATES["COUNTEREXAMPLE"], "이 구절의 해석이 성립하지 않는 조건도 있을까요?", "다른 관점에서 이 구절을 읽으면 무엇을 다시 확인해야 하나요?"),
}


def selection_questions(value, context):
    """Decode the bounded provider selection into the existing UI contract."""
    if not isinstance(value, dict) or set(value) != {"status", "selections"}:
        raise ValueError("AI_SCHEMA_INVALID")
    if value["status"] not in ("OK", "INSUFFICIENT_CONTEXT") or not isinstance(value["selections"], list) or len(value["selections"]) > 2:
        raise ValueError("AI_SCHEMA_INVALID")
    if value["status"] == "INSUFFICIENT_CONTEXT" and value["selections"]:
        raise ValueError("AI_SCHEMA_INVALID")
    output = []; seen = set()
    for item in value["selections"]:
        if not isinstance(item, dict) or set(item) != {"excerptIndex", "questionIndex"}:
            raise ValueError("AI_SCHEMA_INVALID")
        excerpt, question = item["excerptIndex"], item["questionIndex"]
        if type(excerpt) is not int or type(question) is not int or not 0 <= excerpt < len(context["excerpts"]) or not 0 <= question < len(QUESTION_OPTIONS[context["questionType"]]) or (excerpt, question) in seen:
            raise ValueError("AI_SCHEMA_INVALID")
        seen.add((excerpt, question))
        output.append({"focusQuote": context["excerpts"][excerpt]["quote"], "questionType": context["questionType"], "question": QUESTION_OPTIONS[context["questionType"]][question]})
    return {"questions": output}


@dataclass(frozen=True)
class AIContext:
    owner_id: str
    payload: dict


def preview_context(user, *, owner_id, version_id, canonical_text, spans, question_type, references=()):
    require_private_owner(user, owner_id)
    if question_type not in TEMPLATES or not version_id or not spans:
        raise ValueError("AI_CONTEXT_REQUIRED")
    excerpts = []
    for span in spans:
        start, end = span["start"], span["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(canonical_text):
            raise ValueError("AI_SPAN_INVALID")
        quote = canonical_text[start:end]
        if span.get("quote") != quote:
            raise ValueError("AI_QUOTE_MISMATCH")
        excerpts.append({"start": start, "end": end, "quote": quote})
    # Explicitly selected excerpts only; no essay, work text or thought memo field.
    context = {"versionId": version_id, "questionType": question_type, "excerpts": excerpts}
    if references:
        context['references'] = deepcopy(list(references))
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return AIContext(owner_id, context), hashlib.sha256(encoded.encode()).hexdigest()


def validate_questions(value, context):
    if not isinstance(value, dict) or set(value) != {"questions"} or not isinstance(value["questions"], list) or len(value["questions"]) > 2:
        raise ValueError("AI_SCHEMA_INVALID")
    quotes = {x["quote"] for x in context["excerpts"]}
    for item in value["questions"]:
        if (not isinstance(item, dict) or set(item) != {"focusQuote", "questionType", "question"}
                or item["focusQuote"] not in quotes or item["questionType"] != context["questionType"]
                or item["question"] not in QUESTION_OPTIONS[item["questionType"]]):
            # Reject arbitrary free-form facts even if a provider prompt asks
            # for grounding. Accepted wording remains owned by this server.
            raise ValueError("AI_OUTPUT_UNVERIFIABLE")
    return deepcopy(value)


def questions(user, *, context, preview_hash, consent, enabled=False,
              external_terms_approved=False, reserve_budget=None, provider=None):
    if not isinstance(context, AIContext):
        raise ValueError("SERVER_CONTEXT_REQUIRED")
    require_private_owner(user, context.owner_id)
    context = deepcopy(context.payload)
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if not consent or hashlib.sha256(encoded.encode()).hexdigest() != preview_hash:
        raise ValueError("AI_CONSENT_OR_PREVIEW_INVALID")
    fallback = {"questions": [{"focusQuote": context["excerpts"][0]["quote"],
                               "questionType": context["questionType"],
                               "question": TEMPLATES[context["questionType"]]}]}
    if not enabled or not external_terms_approved or reserve_budget is None or provider is None:
        return {"status": "LOCAL_FALLBACK_EXTERNAL_DISABLED", **fallback}
    # The real budget/cooldown/concurrency store is a mandatory integration,
    # never replaced by an unbounded in-process counter or cross-user cache.
    if reserve_budget(user.id) is not True:
        return {"status": "LOCAL_FALLBACK_LIMIT", **fallback}
    try:
        result = validate_questions(provider(deepcopy(context)), context)
        return {"status": "PROVIDER_VALIDATED" if result['questions'] else "INSUFFICIENT_CONTEXT", **result}
    except Exception:
        return {"status": "LOCAL_FALLBACK_INVALID_OR_UNAVAILABLE", **fallback}
