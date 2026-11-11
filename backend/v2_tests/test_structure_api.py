from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze


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


def test_role_links_exact_version_ownership_and_immutable_after_edit(v2app):
    c,h,_=user_client(v2app)
    w=essay(c,h,'😀 뿌리는 사랑을 상징한다. 시에서 뿌리는 꽃을 지킨다.')
    ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert len(result['argumentLinks'])==1
    nodes={n['id']:n for n in result['argumentCandidates']};link=result['argumentLinks'][0]
    assert link['claimId'] in nodes and link['evidenceId'] in nodes
    assert link['claimText']==nodes[link['claimId']]['quote'] and link['evidenceText']==nodes[link['evidenceId']]['quote']
    assert link['claimSentenceId'] in {s['id'] for s in result['sentences']}
    for node in nodes.values():
        assert node['analysisRunId']==result['id'] and node['essayVersionId']==result['essayVersionId']
        assert w['content'][node['span']['start']:node['span']['end']]==node['quote']
    other,_,_=user_client(v2app,'synthetic-role-other')
    assert other.get('/api/analyses/'+ids['analysisId']).status_code==404
    assert c.patch('/api/writings/'+w['id'],headers=h,json={'content':'수정된 본문입니다.','revisionNumber':w['revisionNumber']}).status_code==200
    previous=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert previous['argumentLinks']==result['argumentLinks'] and previous['sourceVersion']==result['sourceVersion']
    assert previous['contextSnapshot']['essayContext']==result['contextSnapshot']['essayContext']


def test_legacy_nearest_following_snapshot_does_not_gain_new_arrows():
    from types import SimpleNamespace
    from app.v2.analysis_api import argument_view
    old={'roleCandidates':[{'sentenceNumber':1,'claimSignals':['생각한다'],'scores':{'CLAIM_CANDIDATE':1}}],
        'relations':[{'claimSentence':1,'evidenceSentence':2,'interpretation':'NEAREST_FOLLOWING_CANDIDATE_NOT_LOGICAL_VALIDITY'}]}
    result=argument_view(SimpleNamespace(id='old-run'),SimpleNamespace(id='old-version'),'가상 원문',old)
    assert result['argumentCandidates']==[] and result['argumentLinks']==[]


def test_actual_kiwi_browser_fixture_30000_codepoints(v2app):
    import json
    from pathlib import Path
    c,h,_=user_client(v2app)
    head='😀 가 뿌리는 사랑과 희생을 상징한다.\n'+('독자는 조용히 글의 맥락을 차근차근 살핀다 '*70)+'.\n시에서 뿌리는 희생을 하며 꽃을 지킨다.\n\n'
    body=(head+('독자는 천천히 낱말을 읽고 문장을 살핀다.\n\n'*1200))[:30000]
    w=essay(c,h,body);ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert result['status']=='completed' and len(result['argumentLinks'])==1
    link=result['argumentLinks'][0];assert link['evidenceSpan']['start']>1500 and link['claimSpan']['start']==0
    assert len(result['sourceVersion']['content'])==30000
    directory=Path('artifacts/argument-links');directory.mkdir(parents=True,exist_ok=True)
    directory.joinpath('kiwi-fixture.json').write_text(json.dumps({'mode':'ISOLATED_API_ACTUAL_KIWI_SYNTHETIC_TEXT','writing':c.get('/api/writings/'+w['id']).json['data'],'analysis':result},ensure_ascii=False),encoding='utf-8')
    empty=essay(c,h,'오늘 책을 읽었다. 날씨가 맑다.');empty_ids=analyze(v2app,c,h,empty).json['data']
    empty_result=c.get('/api/analyses/'+empty_ids['analysisId']).json['data']
    assert empty_result['argumentCandidates']==[] and empty_result['argumentLinks']==[]
    directory.joinpath('empty-fixture.json').write_text(json.dumps({'mode':'ISOLATED_API_ACTUAL_KIWI_SYNTHETIC_TEXT','writing':c.get('/api/writings/'+empty['id']).json['data'],'analysis':empty_result},ensure_ascii=False),encoding='utf-8')
