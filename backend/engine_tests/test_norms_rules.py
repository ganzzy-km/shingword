import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
from analysis.ruleset import catalogue, local_findings, RULESET_VERSION

@pytest.mark.parametrize("text,suggestion",[("할수 있다","할 수 있다"),("할수있다","할 수 있다"),("볼수없어요","볼 수 없어요"),("볼수 있어요","볼 수 있어요"),("읽을수 없습니다","읽을 수 없습니다"),("쓸수 없었다","쓸 수 없었다"),("다할수 있다","할 수 있다"),("몇일 동안","며칠"),("몇 일 동안","며칠"),("웃을뿐이다","웃을 뿐"),("아는대로 말한다","아는 대로"),("애쓴만큼 얻는다","애쓴 만큼")])
def test_pdf_backed_candidates_and_exact_offsets(text,suggestion):
    body="😀 "+text
    findings=local_findings(body)
    assert len(findings)==1 and findings[0]["suggestion"]==suggestion
    f=findings[0];assert body[f["start"]:f["end"]]==f["quote"]
    assert f["source"]["primaryReference"]["location"]["pdfPages"] and f["autoApply"] is False
    if f["ruleId"] in {"gb-local-006","gb-local-007","gb-local-008"}:assert f["tier"]=="확인 필요"

@pytest.mark.parametrize("text",["할 수 있다","볼 수 있어요","읽을 수 없습니다","쓸 수 없었다","며칠 동안","웃을 뿐이다","친구뿐이다","아는 대로 말한다","법대로 한다","애쓴 만큼 얻는다","고등학생만큼 안다","말로써 빚을 갚는다","쌀로써 떡을 빚는다","도구로써 사용했다","올해로써 20년이다","친구로서 할 말이다","불이 꺼져 간다","불이 꺼져간다","10개","제7항","몇 년 몇 월","할수라는 인물"])
def test_normal_and_permitted_forms_not_flagged(text):assert local_findings(text)==[]

@pytest.mark.parametrize("text",["읽을수 없다","몇 일","웃을뿐","아는대로","애쓴만큼","학생으로써"])
def test_direct_quote_and_selected_vocabulary_protected(text):
    assert local_findings("그는 “"+text+"”라고 썼다.")==[]
    assert local_findings(text+"라는 작품",vocabulary=[text])==[]

def test_context_is_confirmation_not_error_or_automatic_replacement():
    f=local_findings("학생으로써 책임을 진다.")[0]
    assert f["tier"]=="확인 필요" and f["suggestion"] is None and f["autoApply"] is False

def test_catalogue_examples_executable_and_disabling_each_rule():
    for rule in catalogue():
        rid=rule["rule_id"]
        for text in rule["positive_examples"]:
            assert any(f["ruleId"]==rid for f in local_findings(text))
            assert not any(f["ruleId"]==rid for f in local_findings(text,disabled=[rid]))
        for text in rule["negative_examples"]:
            assert not any(f["ruleId"]==rid for f in local_findings(text))
    assert RULESET_VERSION.endswith("/9")

def test_all_rule_metadata_and_explicit_exceptions():
    for rule in catalogue():
        assert rule['title'] and rule['scope'] and rule['categoryLabel']
        assert rule['examples']['candidate'] == rule['positive_examples']
        assert rule['examples']['normal'] == rule['negative_examples']
        assert rule['autoApply'] is False and rule['execution'] == 'BOUNDED_CANDIDATES'
        for text in rule['exception_examples']:
            assert not any(f['ruleId'] == rule['rule_id'] for f in local_findings(text, vocabulary=rule['examples']['exceptionVocabulary']))
        for text in rule['positive_examples']:
            assert local_findings('“'+text+'”') == []
    assert local_findings('외곡리에 살았다. 외곡리라는 지명이다.') == []
    assert any(f['ruleId'] == 'gb-local-003' for f in local_findings('사실을 외곡했다.'))
