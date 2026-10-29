import pytest
from backend.components.ai import TEMPLATES, preview_context, questions, validate_questions
from backend.components.auth import AuthDenied, Principal

USER = Principal("synthetic-user", "synthetic-sub", "USER", "ACTIVE", 1)


def preview():
    return preview_context(USER, owner_id=USER.id, version_id="synthetic-v1", canonical_text="선택 구절. 보내지 않는 문단.",
                           spans=[{"start":0,"end":6,"quote":"선택 구절."}], question_type="EVIDENCE")


def test_preview_matches_transmitted_minimal_context_and_default_blocks():
    context, digest = preview()
    calls = []
    result = questions(USER, context=context, preview_hash=digest, consent=True, provider=lambda c:calls.append(c))
    assert calls == [] and result["status"].endswith("DISABLED")
    assert "보내지 않는" not in str(context.payload) and set(context.payload) == {"versionId","questionType","excerpts"}


def test_consent_tampering_and_cross_user_context_are_rejected():
    context, digest = preview()
    for consent, value in [(False,digest),(True,"wrong")]:
        with pytest.raises(ValueError):
            questions(USER, context=context, preview_hash=value, consent=consent)
    other = Principal("other-user", "other-sub", "USER", "ACTIVE", 1)
    with pytest.raises(AuthDenied):
        questions(other, context=context, preview_hash=digest, consent=True)


@pytest.mark.parametrize("payload", [{}, {"questions":[] ,"extra":1}, {"questions":[{}]*3},
                                    {"questions":[{"focusQuote":"wrong","questionType":"EVIDENCE","question":TEMPLATES["EVIDENCE"]}]},
                                    {"questions":[{"focusQuote":"선택 구절.","questionType":"EVIDENCE","question":"알려 주지 않은 결말을 왜 바꿨나요?"}]}])
def test_invalid_or_invented_facts_are_not_accepted(payload):
    context, _ = preview()
    with pytest.raises(ValueError):
        validate_questions(payload,context.payload)


def test_provider_matches_preview_no_cache_or_analysis_mutation():
    context,digest = preview(); captured=[]
    def provider(value):
        captured.append(value)
        return {"questions":[]}
    result=questions(USER,context=context,preview_hash=digest,consent=True,enabled=True,external_terms_approved=True,
                     reserve_budget=lambda uid:uid==USER.id,provider=provider)
    assert result["questions"] == [] and captured == [context.payload]
    assert context.payload["excerpts"][0]["quote"] == "선택 구절."


def test_provider_failure_and_missing_budget_have_local_fallback():
    context,digest=preview()
    def fail(_):raise RuntimeError("synthetic-provider-failure")
    result=questions(USER,context=context,preview_hash=digest,consent=True,enabled=True,external_terms_approved=True,
                     reserve_budget=lambda _:True,provider=fail)
    assert result["status"].startswith("LOCAL_FALLBACK")
    calls=[]
    questions(USER,context=context,preview_hash=digest,consent=True,enabled=True,external_terms_approved=True,
              provider=lambda c:calls.append(c))
    assert calls == []
