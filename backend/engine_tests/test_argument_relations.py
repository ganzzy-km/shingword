import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import pytest
from analysis.structure import analyze_structure
from analysis.snapshot import normalize_text, validate_snapshot


CASES = [
    ('adjacent', '뿌리는 사랑을 상징한다. 시에서 뿌리는 꽃을 지킨다.', [(1,2)]),
    ('intervening explanation', '뿌리는 사랑을 상징한다. 그 사랑은 눈에 드러나지 않는다. 시에서 뿌리는 꽃을 지킨다.', [(1,3)]),
    ('several evidence', '뿌리는 사랑을 상징한다. 시에서 뿌리는 꽃을 지킨다. 시에서 뿌리는 어둠에 묻힌다.', [(1,2),(1,3)]),
    ('claim only', '뿌리는 사랑을 상징한다. 오늘의 독서를 마쳤다.', []),
    ('evidence only', '시에서 뿌리는 꽃을 지킨다.', []),
    ('cross paragraph', '뿌리의 희생은 사랑을 상징한다.\n\n시에서 뿌리는 희생을 하며 꽃을 지킨다.', [(1,2)]),
    ('unrelated nearby', '뿌리는 사랑을 상징한다. 주인공은 서울로 떠났다.', []),
    ('quote and page', '뿌리는 사랑을 상징한다. 시인은 12쪽에서 “뿌리는 꽃을 지킨다.”라고 말한다.', [(1,2)]),
    ('earlier relevant not nearest', '뿌리는 사랑을 상징한다. 인물의 독서는 자유를 상징한다. 시에서 뿌리는 꽃을 지킨다.', [(1,3)]),
    ('ambiguous claims', '뿌리는 사랑을 상징한다. 뿌리는 희생을 상징한다. 시에서 뿌리는 꽃을 지킨다.', []),
    ('no word-only decision', '따라서 집으로 간다. 장면이라는 단어를 배웠다.', []),
    ('literal mental and action expressions', '오늘 점심을 생각한다. 그는 얼굴을 드러낸다. 그는 책을 보여준다.', []),
    ('evidence before claim', '시에서 뿌리는 꽃을 지킨다. 뿌리는 사랑을 상징한다.', []),
    ('cross paragraph quote explained', '따라서 인물의 선택이 의미한다고 생각한다.\n\n인물이 “떠나겠다.”라고 말했다. 이는 선택의 의미를 보여 준다.', [(1,2)]),
    ('quote unrelated explanation', '뿌리는 사랑을 상징한다.\n\n인물이 “떠나겠다.”라고 말했다. 이는 자유로운 선택의 의미를 보여 준다.', []),
    ('no explicit reference in following sentence', '뿌리의 희생은 사랑을 상징한다.\n\n인물이 “떠나겠다.”라고 말했다. 사랑과 희생은 중요한 가치이다.', []),
]


@pytest.mark.parametrize('name,body,expected',CASES,ids=[x[0] for x in CASES])
def test_labeled_relation_cases(name,body,expected):
    result=analyze_structure(body,version_id='synthetic-role-v1')
    assert [(r['claimSentence'],r['evidenceSentence']) for r in result['relations']]==expected
    for relation in result['relations']:
        assert relation['claimSpan']['end']<=relation['evidenceSpan']['start']
        assert relation['sharedNouns'] or 'EXPLICIT_SAME_WORK_FRAME' in relation['signals']
    if name=='claim only':assert any('CLAIM_CANDIDATE' in c['roles'] for c in result['roleCandidates'])
    if name=='evidence only':assert any('EVIDENCE_CANDIDATE' in c['roles'] for c in result['roleCandidates'])
    if name in ('no word-only decision','literal mental and action expressions'):assert all(not c['roles'] for c in result['roleCandidates'])


def test_quote_is_not_automatically_author_claim():
    result=analyze_structure('“뿌리는 사랑을 상징한다.”',version_id='synthetic-quote-v1')
    assert not any('CLAIM_CANDIDATE' in c['roles'] for c in result['roleCandidates'])
    assert result['relations']==[]

def test_following_explanation_trace_is_exact_and_validated():
    text='따라서 인물의 선택이 의미한다고 생각한다.\n\n인물이 “떠나겠다.”라고 말했다. 이는 선택의 의미를 보여 준다.'
    result=analyze_structure(text,version_id='synthetic-explanation')
    link=result['relations'][0];assert 'FOLLOWING_QUOTE_EXPLANATION' in link['signals']
    trace=link['followingExplanation'];assert text[trace['span']['start']:trace['span']['end']]=='이는 선택의 의미를 보여 준다.'
    invalid=copy.deepcopy(result);invalid['relations'][0]['followingExplanation']['span']['start']+=1
    with pytest.raises(ValueError,match='INVALID_RELATION_EXPLANATION_SPAN'):validate_snapshot(invalid,text,version_id='synthetic-explanation')


def test_unicode_repeat_exact_ids_and_schema_rejects_invented_span():
    body=normalize_text('😀 \u1100\u1161 뿌리는 사랑을 상징한다.\r\n시에서 뿌리는 꽃을 지킨다.\r\n\r\n'*80)
    result=analyze_structure(body,version_id='synthetic-repeat-v1')
    assert len(result['relations'])==80
    ids=[r['id'] for r in result['relations']];assert len(set(ids))==80
    assert result==analyze_structure(body,version_id='synthetic-repeat-v1')
    for r in result['relations']:
        assert body[r['claimSpan']['start']:r['claimSpan']['end']].endswith('상징한다.')
        assert body[r['evidenceSpan']['start']:r['evidenceSpan']['end']]=='시에서 뿌리는 꽃을 지킨다.'
    invalid=copy.deepcopy(result);invalid['relations'][0]['claimSpan']['start']+=1
    with pytest.raises(ValueError,match='INVALID_RELATION_SPAN'):validate_snapshot(invalid,body,version_id='synthetic-repeat-v1')


def test_quality_record_for_labeled_corpus_only():
    import json
    rows=[]
    for name,body,expected in CASES:
        actual={(r['claimSentence'],r['evidenceSentence']) for r in analyze_structure(body,version_id='synthetic-quality')['relations']}
        gold=set(expected)
        rows.append({'case':name,'expected':sorted(gold),'actual':sorted(actual),'truePositive':len(actual & gold),'falsePositive':len(actual-gold),'falseNegative':len(gold-actual)})
    summary={'scope':f'{len(CASES)} curated synthetic cases, not general accuracy','cases':rows,
        'truePositive':sum(r['truePositive'] for r in rows),'falsePositive':sum(r['falsePositive'] for r in rows),'falseNegative':sum(r['falseNegative'] for r in rows)}
    assert summary['falsePositive']==0 and summary['falseNegative']==0
    directory=Path('artifacts/argument-links');directory.mkdir(parents=True,exist_ok=True)
    directory.joinpath('quality-results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
