from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
import json
import os
from pathlib import Path
import pytest
from app.analysis.snapshot import normalize_text


def _display_case(kind, *, long=False):
    # Post-baseline contract amendment. The positive R0 pair is reused from
    # test_r1_adds_independent_relation_without_erasing_prior_approval.
    if long:
        claim='😀 가 뿌리는 사랑과 희생을 상징한다.' if kind=='review' else '😀 가 커튼과 창문과 가림막은 안전과 책임을 상징한다.'
        evidence='시에서 뿌리는 희생을 하며 꽃을 지킨다.' if kind=='review' else '그는 커튼과 창문과 가림막을 접는다.'
        head=claim+'\n'+('독자는 조용히 글의 맥락을 차근차근 살핀다 '*70)+'.\n'+evidence+'\n\n'
        body=normalize_text((head+('독자는 천천히 낱말을 읽고 문장을 살핀다.\n\n'*1200))[:30000])
        evidence_number=3
    else:
        claim='😀 뿌리는 사랑을 상징한다.' if kind=='review' else '😀 커튼과 창문과 가림막은 안전과 책임을 상징한다.'
        evidence='시에서 뿌리는 꽃을 지킨다.' if kind=='review' else '그는 커튼과 창문과 가림막을 접는다.'
        body=normalize_text(claim+' '+evidence);evidence_number=2
    start=body.index(evidence)
    return {'body':body,'kind':kind,'claim':claim,'evidence':evidence,'claimSpan':{'start':0,'end':len(claim)},
            'evidenceSpan':{'start':start,'end':start+len(evidence)},'evidenceNumber':evidence_number,
            'relationId':'relation-1-'+str(evidence_number),'score':(6 if long else 4) if kind=='review' else 8}


def _assert_display_contract(result, case):
    body=case['body'];raw=result['result']
    assert result['status']=='completed' and result['sourceVersion']['content']==body
    assert result['essayVersionId']==result['sourceVersion']['id']==raw['input']['versionId']
    assert raw['input']['codePoints']==len(body)
    links=[r for r in raw['relations'] if r['id']==case['relationId']]
    assert len(links)==1 # Absence of a REVIEW relation cannot pass the negative.
    relation=links[0]
    assert relation['claimId']=='sentence-1' and relation['evidenceId']=='sentence-'+str(case['evidenceNumber'])
    assert relation['claimSpan']==case['claimSpan'] and relation['evidenceSpan']==case['evidenceSpan']
    assert relation['score']==case['score'] and relation.get('approvalRoute') is None
    assert relation['assessment']==('REQUIRES_REVIEW' if case['kind']=='review' else 'SUFFICIENT_SIGNALS')
    assert relation['direction']=='EVIDENCE_TO_CLAIM' and relation['textOrder']=='CLAIM_FIRST'
    nodes={n['id']:n for n in result['argumentCandidates']}
    claim_id=result['id']+':role:sentence-1';evidence_id=result['id']+':role:sentence-'+str(case['evidenceNumber'])
    assert claim_id in nodes and evidence_id in nodes
    assert 'CLAIM_CANDIDATE' in nodes[claim_id]['roles'] and 'EVIDENCE_CANDIDATE' in nodes[evidence_id]['roles']
    assert nodes[claim_id]['span']==case['claimSpan'] and nodes[evidence_id]['span']==case['evidenceSpan']
    for node in nodes.values():
        assert node['analysisRunId']==result['id'] and node['essayVersionId']==result['essayVersionId']
        assert body[node['span']['start']:node['span']['end']]==node['quote']
    assert len(result['argumentLinks'])==(0 if case['kind']=='review' else 1)
    if case['kind']=='approved':
        link=result['argumentLinks'][0]
        assert link['id']==result['id']+':'+case['relationId']
        assert link['claimId']==claim_id and link['evidenceId']==evidence_id
        assert link['claimText']==nodes[claim_id]['quote']==case['claim']
        assert link['evidenceText']==nodes[evidence_id]['quote']==case['evidence']
        assert link['claimSentenceId']==result['id']+':s1'
        assert link['evidenceSentenceId']==result['id']+':s'+str(case['evidenceNumber'])
        sentence_ids={s['id'] for s in result['sentences']}
        assert link['claimSentenceId'] in sentence_ids
        assert link['evidenceSentenceId'] in sentence_ids
        assert link['analysisRunId']==result['id'] and link['essayVersionId']==result['essayVersionId']
        assert link['claimSpan']==case['claimSpan'] and link['evidenceSpan']==case['evidenceSpan']


def _fixture_directory():
    # Default path/JSON contract remains the existing browser consumer's path.
    # Formal validation can direct newly generated evidence away from old files.
    directory=Path(os.environ.get('S4_DISPLAY_FIXTURE_ROOT','artifacts/argument-links'))
    directory.mkdir(parents=True,exist_ok=True)
    return directory


def test_candidates_and_relation_signals_not_grading(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'나는 이 작품이 의미가 있다고 생각한다. 작품에서 인물은 달렸다. 이는 선택을 보여 준다.')
    ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    raw=result['result'];assert raw['relations']
    assert any(x['scores']['CLAIM_CANDIDATE'] for x in raw['roleCandidates'])
    assert any(x['scores']['EVIDENCE_CANDIDATE'] for x in raw['roleCandidates'])
    assert all(x['scoreMeaning']=='OBSERVED_SIGNAL_COUNT_NOT_PROBABILITY' for x in raw['roleCandidates'])
    assert all(s['autoRole']=='분류되지 않음' for s in result['sentences'])
    assert '채점하지' in result['disclaimer']


def test_deterministic_same_version_and_scoped_feedback(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'나는 의미가 있다고 생각한다.\n\n“그는 말했다.”')
    first=analyze(v2app,c,h,w).json['data'];second=analyze(v2app,c,h,w).json['data']
    a=c.get('/api/analyses/'+first['analysisId']).json['data'];b=c.get('/api/analyses/'+second['analysisId']).json['data']
    assert first['analysisId']!=second['analysisId'] and first['essayVersionId']==second['essayVersionId']
    assert a['result']==b['result']
    for f in a['findings']:
        assert w['content'][f['startOffset']:f['endOffset']]==f['current']
        assert '근거가 없다' not in f['reason']


def test_long_10000_and_30000_complete_through_api(v2app):
    c,h,_=user_client(v2app)
    for size in [10000,30000]:
        body=('작품에서 인물이 걸었다. 나는 이를 의미 있는 선택이라고 생각한다. 😀\n\n'*1000)[:size]
        w=essay(c,h,body);ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
        assert result['status']=='completed' and result['sourceVersion']['content']==body
        assert result['result']['input']['codePoints']==size
        assert ''.join(body[p['start']:p['end']] for p in result['result']['partitions'])==body


@pytest.mark.parametrize('kind',['review','approved'],ids=['review-negative','approved-positive'])
def test_role_links_exact_version_ownership_and_immutable_after_edit(v2app,kind):
    c,h,_=user_client(v2app)
    case=_display_case(kind);w=essay(c,h,case['body'])
    ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    _assert_display_contract(result,case)
    _fixture_directory().joinpath(kind+'-short-fixture.json').write_text(json.dumps({'mode':'ISOLATED_API_ACTUAL_KIWI_SYNTHETIC_TEXT','writing':c.get('/api/writings/'+w['id']).json['data'],'analysis':result},ensure_ascii=False),encoding='utf-8')
    other,_,_=user_client(v2app,'synthetic-role-other')
    assert other.get('/api/analyses/'+ids['analysisId']).status_code==404
    assert c.patch('/api/writings/'+w['id'],headers=h,json={'content':'수정된 본문입니다.','revisionNumber':w['revisionNumber']}).status_code==200
    previous=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert previous['argumentLinks']==result['argumentLinks'] and previous['sourceVersion']==result['sourceVersion']
    assert previous['argumentCandidates']==result['argumentCandidates'] and previous['result']==result['result']
    assert previous['essayVersionId']==result['essayVersionId']
    assert previous['contextSnapshot']['essayContext']==result['contextSnapshot']['essayContext']


def test_legacy_nearest_following_snapshot_does_not_gain_new_arrows():
    from types import SimpleNamespace
    from app.v2.analysis_api import argument_view
    old={'roleCandidates':[{'sentenceNumber':1,'claimSignals':['생각한다'],'scores':{'CLAIM_CANDIDATE':1}}],
        'relations':[{'claimSentence':1,'evidenceSentence':2,'interpretation':'NEAREST_FOLLOWING_CANDIDATE_NOT_LOGICAL_VALIDITY'}]}
    result=argument_view(SimpleNamespace(id='old-run'),SimpleNamespace(id='old-version'),'가상 원문',old)
    assert result['argumentCandidates']==[] and result['argumentLinks']==[]


@pytest.mark.parametrize('kind',['review','approved'],ids=['review-negative','approved-positive'])
def test_actual_kiwi_browser_fixture_30000_codepoints(v2app,kind):
    import json
    from pathlib import Path
    c,h,_=user_client(v2app)
    case=_display_case(kind,long=True);body=case['body']
    w=essay(c,h,body);ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    _assert_display_contract(result,case)
    assert case['evidenceSpan']['start']>1500 and case['claimSpan']['start']==0
    assert len(result['sourceVersion']['content'])==30000
    assert ''.join(body[p['start']:p['end']] for p in result['result']['partitions'])==body
    directory=_fixture_directory()
    fixture_name='review-30000-fixture.json' if kind=='review' else 'kiwi-fixture.json'
    directory.joinpath(fixture_name).write_text(json.dumps({'mode':'ISOLATED_API_ACTUAL_KIWI_SYNTHETIC_TEXT','writing':c.get('/api/writings/'+w['id']).json['data'],'analysis':result},ensure_ascii=False),encoding='utf-8')
    if kind=='review':return # Never overwrite the positive browser fixture.
    empty=essay(c,h,'오늘 책을 읽었다. 날씨가 맑다.');empty_ids=analyze(v2app,c,h,empty).json['data']
    empty_result=c.get('/api/analyses/'+empty_ids['analysisId']).json['data']
    assert empty_result['argumentCandidates']==[] and empty_result['argumentLinks']==[]
    directory.joinpath('empty-fixture.json').write_text(json.dumps({'mode':'ISOLATED_API_ACTUAL_KIWI_SYNTHETIC_TEXT','writing':c.get('/api/writings/'+empty['id']).json['data'],'analysis':empty_result},ensure_ascii=False),encoding='utf-8')
