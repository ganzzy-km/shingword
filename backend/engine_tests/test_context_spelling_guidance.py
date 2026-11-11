import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
from analysis.ruleset import local_findings,catalogue,ruleset_hash

def test_gomgom_standard_forms_never_rewritten():
    for text in ['곰곰 생각한다.','곰곰이 생각한다.','나는 곰곰이 되짚어 보았다.']:
        assert local_findings(text)==[]
    f=local_findings('😀 곰곰히 생각해 보았다.')[0]
    assert f['suggestion']=='곰곰이' and f['autoApply'] is False
    assert {a['text'] for a in f['alternatives']}=={'곰곰','곰곰이'}
    assert '별도 표준형이 아닙니다' in f['reason']
    assert 'qna_seq=305970' in f['source']['url']
    assert local_findings('“곰곰히”라고 썼다.')==[]
    assert local_findings('곰곰히',vocabulary=['곰곰히'])==[]

def test_ambiguous_pair_is_only_a_conditional_expression_proposal():
    for text in ['번번히 실패한다.','논 전체를 번번히 골랐다.','번번히']:
        f=local_findings(text)[0]
        assert f['tier']=='표현 제안' and f['suggestion'] is None
        assert f['selectionPolicy']=='CONTEXT_REQUIRED' and f['autoApply'] is False
        assert '의도했다면' in f['reason'] and '일괄 교체하지' in f['reason']
    assert local_findings('번번이 실패한다.')==[]
    assert local_findings('“번번히”')==[]

def test_existing_context_rule_offers_meanings_not_forced_replacement():
    f=local_findings('학생으로써 책임을 진다.')[0]
    assert f['suggestion'] is None and f['selectionPolicy']=='CONTEXT_REQUIRED'
    assert {a['text'] for a in f['alternatives']}=={'(으)로서','(으)로써'}
    assert local_findings('말로써 뜻을 전한다.')==[]
    assert local_findings('학생으로서 책임을 진다.')==[]
    assert ruleset_hash()==ruleset_hash()
