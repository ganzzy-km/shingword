from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app"))
import pytest
from analysis.ruleset import catalogue, local_findings, EXAMPLES, ruleset_hash
from analysis.structure import analyze_structure
from backend.components.auth import Principal,AuthDenied
from backend.components.quote_match import SelectedRevision,match_quote

USER=Principal("synthetic-user","synthetic-sub","USER","ACTIVE",1)


@pytest.mark.parametrize("i",range(5))
def test_rule_examples_negative_quote_and_vocabulary_exceptions(i):
    positive,negative,exception,vocabulary=EXAMPLES[i]
    rule=catalogue()[i]
    assert any(f["ruleId"]==rule["rule_id"] for f in local_findings(positive))
    assert not any(f["ruleId"]==rule["rule_id"] for f in local_findings(negative))
    assert local_findings('“'+positive+'”') == []
    assert not any(f["ruleId"]==rule["rule_id"] for f in local_findings(positive,disabled=[rule["rule_id"]]))
    if vocabulary:assert local_findings(exception,vocabulary=vocabulary) == []
    assert rule["source"]["status"] and rule["known_false_positives"]


def test_uncertain_rules_never_promoted_and_hash_is_reproducible():
    for rule in catalogue()[2:]:
        if rule['tier']=='오류 후보':assert rule['source']['status']=='PRIMARY_SOURCE_CHECKED'
        else:assert rule['tier'] in {'확인 필요','표현 제안'}
    assert next(r for r in catalogue() if r['rule_id']=='gb-norm-017')['tier']=='표현 제안'
    assert all(not f["autoApply"] for f in local_findings("할수 있다. 몇일. 로써."))
    assert ruleset_hash()==ruleset_hash()


def test_candidates_multiple_signals_and_cross_paragraph_relations():
    text='따라서 인물의 선택이 의미한다고 생각한다.\n\n인물이 “떠나겠다.”라고 말했다. 이는 선택의 의미를 보여 준다.'
    a=analyze_structure(text,version_id='v1');b=analyze_structure(text,version_id='v1')
    assert a==b and any(x['paragraphDistance']>0 for x in a['relations'])
    assert any('DIRECT_QUOTE' in x['evidenceTypes'] for x in a['roleCandidates'])
    assert all(x['scoreMeaning']=='OBSERVED_SIGNAL_COUNT_NOT_PROBABILITY' for x in a['roleCandidates'])
    assert all(text[f['start']:f['end']] for f in a['findings'])
    assert all('근거가 없다' not in f['reason'] for f in a['findings'])


@pytest.mark.parametrize('size',[10000,30000])
def test_long_structure_no_truncation(size):
    text=('따라서 인물의 선택이라고 생각한다.\n\n작품에서 인물이 “떠나겠다.”라고 말했다.\n\n'*1000)[:size]
    result=analyze_structure(text,version_id='long-v1')
    assert result['input']['codePoints']==size and result['partitions'][-1]['end']==size
    assert len(result['roleCandidates'])==len(result['sentences'])


def revision(text,mode='VIEW',owner=USER.id):
    return SelectedRevision('synthetic-rev1','synthetic-document',owner,'PRIVATE',mode,False,text)


def test_selected_revision_exact_normalized_fuzzy_and_not_found():
    text='인물은 책을 읽고 함께 길을 떠났다.'
    assert match_quote(USER,revision(text),'함께 길을 떠났다.',minimum_similarity=70)['status']=='EXACT_MATCH'
    assert match_quote(USER,revision(text),'함께길을떠났다.',minimum_similarity=70)['status']=='NORMALIZED_MATCH'
    assert match_quote(USER,revision(text),'함께 길을 떠났네.',minimum_similarity=70)['status']=='SIMILAR_DIFFERENCE_CANDIDATE'
    result=match_quote(USER,revision('다른 판본의 문장이다.'),'함께 길을 떠났다.',minimum_similarity=90)
    assert result['status']=='NOT_FOUND_IN_SELECTED_REVISION' and result['revisionId']=='synthetic-rev1'


def test_match_only_never_reveals_document_text_and_owner_is_required():
    result=match_quote(USER,revision('함께 길을 떠났다.','MATCH_ONLY'),'함께 길을 떠났다.',minimum_similarity=90)
    assert 'excerpt' not in result and 'text' not in result
    with pytest.raises(AuthDenied):match_quote(USER,revision('개인 문서',owner='other'),'개인',minimum_similarity=90)
