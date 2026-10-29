from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
from app.extensions import db
from app.models import AppSetting

def test_standard_spelling_and_context_guidance_reaches_existing_ui_contract(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'곰곰 생각한다. 곰곰이 생각한다. 곰곰히 생각한다. 번번히 실패한다. 학생으로써 책임을 진다.')
    ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    spelling=[f for f in result['findings'] if f['type']=='spelling']
    assert not any(f['current'] in ('곰곰','곰곰이') for f in spelling)
    gom=next(f for f in spelling if f['current']=='곰곰히')
    assert gom['suggestion']=='곰곰이' and {a['text'] for a in gom['metadata']['alternatives']}=={'곰곰','곰곰이'}
    ambiguous=next(f for f in spelling if f['current']=='번번히')
    assert ambiguous['suggestion'] is None and ambiguous['severity']=='info' and ambiguous['title']=='표현 제안'
    assert ambiguous['metadata']['selectionPolicy']=='CONTEXT_REQUIRED'
    role=next(f for f in spelling if f['current']=='학생으로써')
    assert role['suggestion'] is None and len(role['metadata']['alternatives'])==2
    assert all(f['metadata']['autoApply'] is False for f in spelling)


def test_rules_candidates_source_and_precise_span(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'나는 할수 있다. 몇일 동안 썼다. 😀')
    ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert len(result['findings'])>=2
    for f in result['findings']:
        assert w['content'][f['startOffset']:f['endOffset']]==f['current']
        assert f['metadata']['autoApply'] is False
    assert result['result']['manifest']['rulesetHash']==result['inputManifest']['context']['rulesetHash']
    rules=c.get('/api/rules').json['data'];assert {f"gb-local-{i:03d}" for i in range(1,9)} <= {r["id"] for r in rules} and len(rules)==39 and not any(r['autoFixable'] for r in rules)


def test_quote_protection_correct_spacing_and_legacy_uncertainty(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'“나는 할수 있다.” 나는 할 수 있다. 도구로써 사용했다.')
    ids=analyze(v2app,c,h,w).json['data'];findings=c.get('/api/analyses/'+ids['analysisId']).json['data']['findings']
    spelling=[f for f in findings if f['type']=='spelling']
    assert not any(f['current']=='할수 있다' for f in spelling)
    assert not any(f['severity']=='error' for f in spelling)


def test_reported_essay_word_forms_preserve_correct_spellings_and_suggestion_direction(v2app):
    c,h,_=user_client(v2app)
    body='조용한 희생은 잊어버리기 쉽상이다. 누군가에게 버팀목이 될 수 있을지 곰곰히 생각해보게 된다. 곰곰 생각하고 곰곰이 살핀다. “쉽상이다”는 원문 인용이다.'
    w=essay(c,h,body);ids=analyze(v2app,c,h,w).json['data']
    data=c.get('/api/analyses/'+ids['analysisId']).json['data']
    candidates=[f for f in data['findings'] if f['rule'] in ('gb-lexical-001','gb-norm-005')]
    assert [(f['current'],f['suggestion']) for f in candidates]==[('쉽상','십상'),('곰곰히','곰곰이')]
    for f in candidates:assert body[f['startOffset']:f['endOffset']]==f['current']


def test_disabled_rule_and_snapshot_configuration_preserved(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'나는 할수 있다.')
    first=analyze(v2app,c,h,w).json['data']
    with v2app.app_context():db.session.add(AppSetting(key='disabled_rules',value=['gb-local-001']));db.session.commit()
    second=analyze(v2app,c,h,w).json['data']
    a=c.get('/api/analyses/'+first['analysisId']).json['data'];b=c.get('/api/analyses/'+second['analysisId']).json['data']
    assert any(f['rule']=='gb-local-001' for f in a['findings'])
    assert not any(f['rule']=='gb-local-001' for f in b['findings'])
    assert a['contextSnapshot']['disabledRules']==[] and b['contextSnapshot']['disabledRules']==['gb-local-001']


def test_simple_essay_normal_errors_quote_and_repeat_determinism(v2app):
    import json
    from pathlib import Path
    c,h,_=user_client(v2app)
    normal='나는 친구로서 책임을 다할 수 있다. 며칠 동안 읽은 내용을 아는 대로 말한다. 친구뿐 아니라 다른 독자도 애쓴 만큼 배운다. 말로써 생각을 전하고 올해로써 독서를 시작한 지 2년이 된다. 불이 꺼져간다. 😀'
    mixed='''나는 학생으로써 책임을 다할수 있다. 몇 일 동안 읽을수 없었다. 웃을뿐이다. 아는대로 말하고 애쓴만큼 배운다.

친구뿐이다. 법대로 한다. 말로써 생각을 전한다. 올해로써 2년이 된다. 불이 꺼져 간다.

작품에는 “몇일 동안 웃을뿐이다.”라는 직접 인용이 있다. 😀'''
    results=[]
    for body in [normal,mixed,mixed]:
        w=essay(c,h,body);ids=analyze(v2app,c,h,w).json['data']
        result=c.get('/api/analyses/'+ids['analysisId']).json['data']
        local=[f for f in result['findings'] if (f['rule'] or '').startswith('gb-local-')]
        for f in local:assert body[f['startOffset']:f['endOffset']]==f['current'] and f['metadata']['autoApply'] is False
        assert result['inputManifest']['context']['rulesetVersion']=='geulbit.local-reviewed/9'
        norms=result['inputManifest']['context']['normsCatalogue']
        assert norms==result['result']['manifest']['normsCatalogue']
        assert norms['defaultReference'] and norms['provisionCount']==134
        assert norms['linkedProvisions']==11 and norms['referenceOnlyProvisions']==123
        results.append([{'rule':f['rule'],'quote':f['current'],'start':f['startOffset'],'end':f['endOffset'],'severity':f['severity']} for f in local])
    assert results[0]==[] and results[1]==results[2]
    assert len(results[1])==7
    assert {f['rule'] for f in results[1]}=={'gb-local-001','gb-local-002','gb-local-005','gb-local-006','gb-local-007','gb-local-008'}
    path=Path('artifacts/norms-analysis');path.mkdir(parents=True,exist_ok=True)
    (path/'simple-essay.json').write_text(json.dumps({'normalEssay':normal,'mixedEssay':mixed,'normalFindings':results[0],'mixedFindings':results[1],'repeatDeterministic':True,'source':'Synthetic essays + real Flask API, isolated SQLite and Kiwi; not operating data'},ensure_ascii=False,indent=2),encoding='utf-8')
