import time

from conftest import payload
from app.analysis.engine import classify_role, metrics, peel_results, split_sentences


def create_writing(client, content="이 글은 중요한 주장을 보여 준다. 실제로 장면에서 근거를 확인할수 있다. 따라서 할수 있다."):
    response = client.post("/api/writings", json={"title": "분석 글", "work": "작품", "inquiryQuestion": "중요한 주장은 무엇인가?", "content": content, "status": "임시 저장"})
    assert response.status_code == 201
    return payload(response)


def wait_job(client, job_id):
    for _ in range(500):
        data = payload(client.get(f"/api/analysis-jobs/{job_id}"))
        if data["status"] in {"completed", "failed", "cancelled"}:
            return data
        time.sleep(0.02)
    raise AssertionError("analysis job timed out")


def test_writing_autosave_conflict_versions_and_diff(client):
    writing = create_writing(client, "첫 본문")
    saved = client.post(f"/api/writings/{writing['id']}/autosave", json={"content": "새 본문", "revisionNumber": 1})
    assert saved.status_code == 200
    assert client.post(f"/api/writings/{writing['id']}/autosave", json={"content": "오래된 저장", "revisionNumber": 1}).status_code == 409
    version = payload(client.post(f"/api/writings/{writing['id']}/versions", json={"name": "수정본", "content": "더 새 본문"}))
    versions = payload(client.get(f"/api/writings/{writing['id']}/versions"))
    diff = payload(client.get(f"/api/writing-versions/{versions[0]['id']}/compare/{version['id']}"))
    assert any(item["type"] != "equal" for item in diff["operations"])


def test_analysis_job_metrics_spelling_revision_and_undo(client):
    writing = create_writing(client)
    started = client.post("/api/analyses", json={"writingId": writing["id"], "analysisTypes": ["전체 분석"]})
    assert started.status_code == 202
    refs = payload(started)
    assert wait_job(client, refs["jobId"])["status"] == "completed"
    result = payload(client.get(f"/api/analyses/{refs['analysisId']}"))
    assert result["metrics"]["명백한 맞춤법 오류 수"]["value"] >= 1
    finding = next(x for x in result["findings"] if x["type"] == "spelling" and x["suggestion"])
    applied = client.post(f"/api/findings/{finding['id']}/apply")
    assert applied.status_code == 200
    revision = payload(applied)
    assert "할 수 있다" in revision["content"]
    undone = client.post(f"/api/revisions/{revision['revisionId']}/undo")
    assert undone.status_code == 200
    assert "할수 있다" in payload(undone)["content"]

    deleted = client.delete(f"/api/writings/{writing['id']}", json={"confirmation": "삭제"})
    assert deleted.status_code == 200
    assert client.get(f"/api/writings/{writing['id']}").status_code == 404


def test_empty_writing_and_question_validation(client):
    draft = client.post("/api/writings", json={"title": "", "content": "", "status": "임시 저장"})
    assert draft.status_code == 201
    assert client.post("/api/analyses", json={"writingId": payload(draft)["id"]}).status_code == 400


def test_records_delete_preserves_rubric(client):
    rubric = payload(client.post("/api/rubrics", json={"name": "유지 기준"}))
    create_writing(client)
    assert client.delete("/api/records", json={"confirmation": "분석 기록 전체 삭제"}).status_code == 200
    assert client.get(f"/api/rubrics/{rubric['id']}").status_code == 200


def test_question_marks_inside_direct_quote_do_not_split_the_sentence():
    text = "이 장면의 경우 이 지시문이 존재함으로써 오이디푸스 왕의 대사 ‘크레온의 계략이냐? 아니면 네 놈의 계략이냐?’가 왜 언급되었는지 현재 오이디푸스 왕의 심리 상태는 어떤지 알 수 있다."
    sentences = split_sentences(text)
    assert len(sentences) == 1
    assert sentences[0]["text"] == text
    assert sentences[0]["start"] == 0
    assert sentences[0]["end"] == len(text)

    dialogue = split_sentences("그가 물었다. ‘왜?’ 다음 문장이 이어진다.")
    assert [sentence["text"] for sentence in dialogue] == ["그가 물었다.", "‘왜?’", "다음 문장이 이어진다."]

    role, confidence, rationale = classify_role(text, "오이디푸스 왕의 심리 상태는 어떠한가?")
    classified = [{**sentences[0], "role": role, "confidence": confidence, "rationale": rationale}]
    result_metrics = metrics(
        classified,
        [],
        peel_results(classified, "오이디푸스 왕의 심리 상태는 어떠한가?"),
        [],
        "오이디푸스 왕의 심리 상태는 어떠한가?",
    )
    assert result_metrics["근거 분석률"]["value"] == 100


def test_peel_metric_uses_each_element_instead_of_all_or_nothing():
    text = "이 작품의 핵심 주제는 공동체의 책임이다. 실제로 주인공은 약속을 지킨다."
    sentences = split_sentences(text)
    classified = []
    for sentence in sentences:
        role, confidence, rationale = classify_role(sentence["text"])
        classified.append({**sentence, "role": role, "confidence": confidence, "rationale": rationale})
    peels = peel_results(classified, "선택과 공동체 책임은 어떻게 연결되는가?")
    result_metrics = metrics(classified, [], peels, [], "선택과 공동체 책임은 어떻게 연결되는가?")
    assert peels[0]["elements"]["P"] == "충족"
    assert peels[0]["elements"]["E1"] == "충족"
    assert result_metrics["PEEL 충족률"]["value"] > 0


def test_each_analysis_run_is_listed_and_can_be_reopened(client):
    writing = create_writing(client)
    analysis_ids = []
    for _ in range(2):
        started = payload(client.post("/api/analyses", json={"writingId": writing["id"], "analysisTypes": ["전체 분석"]}))
        assert wait_job(client, started["jobId"])["status"] == "completed"
        analysis_ids.append(started["analysisId"])

    record = next(item for item in payload(client.get("/api/records?pageSize=100")) if item["id"] == writing["id"])
    assert [run["id"] for run in record["analysisRuns"]] == list(reversed(analysis_ids))
    for analysis_id in analysis_ids:
        result = payload(client.get(f"/api/analyses/{analysis_id}"))
        assert result["writing"]["title"] == "분석 글"
        assert "peelResults" in result
        assert "argumentLinks" in result
