from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import text
from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
from app.extensions import db
from app.models import Writing, WritingVersion, Analysis, UserAnnotation

def setup(app):
    c,h,_=user_client(app)
    w=essay(c,h,'😀 곰곰이 생각한다.\r\n같은 구절. 같은 구절.')
    ids=analyze(app,c,h,w).json['data']
    v=c.get('/api/analyses/'+ids['analysisId']).json['data']['sourceVersion']
    return c,h,w,v

def payload(v,start=0,end=2):
    return {'essayVersionId':v['id'],'span':{'start':start,'end':end},'quote':v['content'][start:end],'content':'내 해석과 수정 계획'}

def test_crud_multiple_conflict_and_no_essay_side_effect(v2app):
    c,h,w,v=setup(v2app)
    with v2app.app_context():
        db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)+timedelta(days=7);db.session.commit()
    before=c.get('/api/writings/'+w['id']).json['data']
    assert before['expiresAt'] is not None
    a=c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v));assert a.status_code==201
    note=a.json['data']
    assert note['span']=={'start':0,'end':2} and note['quote']=='😀 '
    assert c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v)).status_code==201
    assert len(c.get('/api/writings/'+w['id']+'/annotations').json['data'])==2
    path='/api/annotations/'+note['id']
    edited=c.patch(path,headers=h,json={'content':'修正한 메모','revisionNumber':1});assert edited.status_code==200
    assert c.patch(path,headers=h,json={'content':'옛 요청','revisionNumber':1}).status_code==409
    assert c.delete(path,headers=h,json={'confirmation':'삭제','revisionNumber':1}).status_code==409
    assert c.delete(path,headers=h,json={'confirmation':'삭제','revisionNumber':2}).status_code==200
    after=c.get('/api/writings/'+w['id']).json['data']
    for key in ('content','revisionNumber','expiresAt','updatedAt','currentVersionId','analysisRuns'):assert before[key]==after[key]
    with v2app.app_context():assert WritingVersion.query.count()==1 and Analysis.query.count()==1

@pytest.mark.parametrize('change',[{'content':''},{'content':' '*3},{'content':'x'*5001},{'span':{'start':-1,'end':2}},{'span':{'start':0,'end':999}},{'span':{'start':True,'end':2}},{'span':[]},{'quote':'다른 원문'},{'ownerId':'forged'},{'essayVersionId':[]}])
def test_invalid(v2app,change):
    c,h,w,v=setup(v2app)
    assert c.post('/api/writings/'+w['id']+'/annotations',headers=h,json={**payload(v),**change}).status_code==400

def test_owner_admin_csrf_foreign_version(v2app):
    c,h,w,v=setup(v2app)
    note=c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v)).json['data']
    for role in ('USER','ADMIN'):
        other,oh,_=user_client(v2app,'other-'+role,role=role)
        assert other.get('/api/writings/'+w['id']+'/annotations').status_code==404
        assert other.patch('/api/annotations/'+note['id'],headers=oh,json={'content':'盗用','revisionNumber':1}).status_code==404
        assert other.delete('/api/annotations/'+note['id'],headers=oh,json={'confirmation':'삭제','revisionNumber':1}).status_code==404
    # Existing session boundary deliberately returns ACCESS_DENIED/401 for CSRF failure.
    assert c.post('/api/writings/'+w['id']+'/annotations',json=payload(v)).status_code==401
    second=essay(c,h,'다른 글');v2=analyze(v2app,c,h,second).json['data']['essayVersionId']
    assert c.post('/api/writings/'+w['id']+'/annotations',headers=h,json={**payload(v),'essayVersionId':v2}).status_code==400

def test_reanalysis_relink_preserves_origin_and_deletion(v2app):
    c,h,w,v=setup(v2app);note=c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v)).json['data']
    changed=c.patch('/api/writings/'+w['id'],headers=h,json={'revisionNumber':w['revisionNumber'],'content':'새 원문. 😀 구절'}).json['data']
    run=analyze(v2app,c,h,changed).json['data'];new=c.get('/api/analyses/'+run['analysisId']).json['data']['sourceVersion']
    assert c.get('/api/writings/'+w['id']+'/annotations').json['data'][0]['essayVersionId']==v['id']
    relink=c.patch('/api/annotations/'+note['id'],headers=h,json={**payload(new,0,3),'revisionNumber':1}).json['data']
    assert relink['essayVersionId']==new['id'] and relink['originalAnchor']==note['originalAnchor']
    assert c.delete('/api/writings/'+w['id'],headers=h,json={'confirmation':w['title'] or '삭제'}).status_code in (200,202)
    with v2app.app_context():assert UserAnnotation.query.count()==0

def test_expired_read_write_block_and_graph_cleanup(v2app):
    c,h,w,v=setup(v2app);note=c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v)).json['data']
    with v2app.app_context():
        item=db.session.get(Writing,w['id']);item.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
    assert c.get('/api/writings/'+w['id']+'/annotations').status_code==404
    assert c.patch('/api/annotations/'+note['id'],headers=h,json={'content':'메모','revisionNumber':1}).status_code==404
    with v2app.app_context():
        from app.v2.operations_api import remove_essay_graph
        remove_essay_graph(w['id']);db.session.commit()
        assert UserAnnotation.query.count()==0
        assert not db.session.execute(text('PRAGMA foreign_key_check')).all()

def test_database_anchor_and_origin_guards(v2app):
    c,h,w,v=setup(v2app);note=c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v)).json['data']
    with v2app.app_context():
        for query in ["UPDATE user_annotations SET quote='다른 원문' WHERE id=:id", "UPDATE user_annotations SET original_anchor='{}' WHERE id=:id"]:
            with pytest.raises(Exception):db.session.execute(text(query),{'id':note['id']});db.session.commit()
            db.session.rollback()

def test_actual_api_browser_fixture(v2app):
    import json
    from pathlib import Path
    original=json.loads(Path('artifacts/argument-links/kiwi-fixture.json').read_text(encoding='utf-8'))
    c,h,_=user_client(v2app);w=essay(c,h,original['analysis']['sourceVersion']['content'])
    ids=analyze(v2app,c,h,w).json['data'];analysis=c.get('/api/analyses/'+ids['analysisId']).json['data']
    version=analysis['sourceVersion'];span=analysis['argumentCandidates'][-1]['span']
    note=c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(version,span['start'],span['end'])).json['data']
    out=Path('artifacts/annotations');out.mkdir(parents=True,exist_ok=True)
    fixture={'mode':'ISOLATED_ACTUAL_API_KIWI_SYNTHETIC_30000','writing':c.get('/api/writings/'+w['id']).json['data'],'analysis':analysis,'annotations':[note],'versions':c.get('/api/writings/'+w['id']+'/versions').json['data']}
    changed=c.patch('/api/writings/'+w['id'],headers=h,json={'revisionNumber':w['revisionNumber'],'content':'새 원문. 😀 구절'}).json['data']
    next_run=analyze(v2app,c,h,changed).json['data']
    fixture['relinkScenario']={'writing':c.get('/api/writings/'+w['id']).json['data'],'analysis':c.get('/api/analyses/'+next_run['analysisId']).json['data'],'versions':c.get('/api/writings/'+w['id']+'/versions').json['data']}
    (out/'api-fixture.json').write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf-8')

def test_repeated_quote_exact_second_span_and_withdraw_cleanup(v2app):
    c,h,w,v=setup(v2app);start=v['content'].rindex('같은 구절.')
    note=c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v,start,start+6)).json['data']
    assert note['span']['start']==start
    assert c.get('/api/annotations/'+note['id']).json['data']==note
    assert c.post('/api/account/withdraw',headers=h,json={'confirmation':'WITHDRAW'}).status_code in (200,202)
    with v2app.app_context():assert UserAnnotation.query.count()==0

def test_requires_completed_analysis_not_just_version(v2app):
    c,h,_=user_client(v2app);w=essay(c,h,'분석 전 원문')
    v=c.post('/api/writings/'+w['id']+'/versions',headers=h,json={'content':w['content'],'revisionNumber':w['revisionNumber']}).json['data']
    assert c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v)).status_code==400

def test_backup_restores_notes_but_never_resurrects_deleted_notes(v2app,tmp_path):
    import sqlite3
    from app.services import backup_service as backup
    c,h,w,v=setup(v2app)
    c.post('/api/writings/'+w['id']+'/annotations',headers=h,json=payload(v))
    key=b'0123456789abcdef0123456789abcdef'
    with v2app.app_context():
        bundle=backup.build_bundle(key,quiescent=True)
        backup.restore_bundle(bundle,key,tmp_path/'before-delete',v2app.config['DATABASE_PATH'])
    with sqlite3.connect(tmp_path/'before-delete/db/geulbit.sqlite3') as restored:assert restored.execute('SELECT count(*) FROM user_annotations').fetchone()==(1,)
    assert c.delete('/api/writings/'+w['id'],headers=h,json={'confirmation':w['title'] or '삭제'}).status_code in (200,202)
    with v2app.app_context():backup.restore_bundle(bundle,key,tmp_path/'after-delete',v2app.config['DATABASE_PATH'])
    with sqlite3.connect(tmp_path/'after-delete/db/geulbit.sqlite3') as restored:
        assert restored.execute('SELECT count(*) FROM user_annotations').fetchone()==(0,)
        assert restored.execute('PRAGMA foreign_key_check').fetchall()==[]
