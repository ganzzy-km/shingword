"""Catalog batching must preserve private metadata, pinned revisions and TTL."""
from datetime import datetime, timedelta, timezone
import hashlib

from sqlalchemy import event

from v2_fixture import v2app, user_client
from test_writing_tools_api import ROOT, data, document, request
from app.extensions import db
from app.models import DocumentRevision, SourceDocument, Work, WorkDocument


def test_catalog_query_count_is_bounded_without_retention_queries(v2app):
    c,h,_=user_client(v2app)
    c.get('/api/workspace')
    counts=[]
    previous=0
    for count in (1,30):
        for i in range(previous,count):document(c,h,title='합성 목록 '+str(i))
        previous=count
        with v2app.app_context():engine=db.engine
        statements=[]
        def observe(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
        event.listen(engine,'before_cursor_execute',observe)
        try:rows=data(c.get(ROOT+'/sources'))
        finally:event.remove(engine,'before_cursor_execute',observe)
        assert len(rows)==count and all('content' not in row and 'pageData' not in row for row in rows)
        counts.append(len(statements))
        assert len(statements)<=8
    assert counts[0]==counts[1]


def test_catalog_filters_latest_ids_and_user_specific_state(v2app):
    c,h,uid=user_client(v2app);other,oh,_=user_client(v2app,'other')
    first=document(c,h,title='가시 합성 원작품');second=document(c,h,mode='MATCH_ONLY',title='대조 합성 원작품')
    hidden=document(other,oh,title='숨김 자료')
    latest=data(c.post('/api/source-documents/'+first['id']+'/revisions',headers=h,json={'expectedRevisionId':first['latestRevisionId'],'content':'별도의 불변 판본'}),201)
    with v2app.app_context():
        work=Work(owner_id=uid,title='가상 시',genre='시',scope='PRIVATE');db.session.add(work);db.session.flush()
        db.session.add(WorkDocument(work_id=work.id,document_id=first['id']));db.session.commit()
    state=data(c.patch(ROOT+'/sources/'+first['id']+'/state',headers=h,json={'revisionNumber':0,'data':{'favorite':True}}))
    rows=data(c.get(ROOT+'/sources'));assert {row['id'] for row in rows}=={first['id'],second['id']}
    shown=next(row for row in rows if row['id']==first['id'])
    assert shown['latestRevisionId']==latest['id'] and shown['genre']=='시' and shown['favorite']
    assert shown['lastUsed']==state['data']['lastUsed']
    assert [row['id'] for row in data(c.get(ROOT+'/sources?favorite=1&recent=1&genre=시&access=VIEW&scope=PRIVATE&q=가시'))]==[first['id']]
    assert data(c.get(ROOT+'/sources?q=숨김'))==[]
    assert [row['id'] for row in data(other.get(ROOT+'/sources'))]==[hidden['id']]
    assert all(not row['favorite'] for row in data(other.get(ROOT+'/sources')))
    match=next(row for row in rows if row['id']==second['id'])
    assert match['accessMode']=='MATCH_ONLY' and 'content' not in match and 'pageData' not in match


def test_catalog_publication_keeps_exact_delegated_revision(v2app):
    owner,h,_=user_client(v2app);admin,ah,_=user_client(v2app,'admin',role='ADMIN');reader,_,_=user_client(v2app,'reader')
    d=document(owner,h);first=d['latestRevisionId']
    latest=data(owner.post('/api/source-documents/'+d['id']+'/revisions',headers=h,json={'expectedRevisionId':first,'content':'공개하지 않은 후속 판본'}),201)
    req=request(owner,h,d)
    data(admin.patch(ROOT+'/publication-requests/'+req['id'],headers=ah,json={'state':'APPROVED','revisionNumber':1,'reviewConfirmed':True}))
    own=data(owner.get(ROOT+'/sources'))[0];shared=data(reader.get(ROOT+'/sources'))[0]
    assert own['latestRevisionId']==latest['id'] and shared['latestRevisionId']==first
    assert shared['scope']=='PUBLIC' and not shared['isOwner']
    assert 'content' not in shared and 'pageData' not in shared


def test_catalog_retention_still_uses_document_provenance(v2app):
    from app.v2.privacy_lifecycle import DOCUMENT_POLICY
    c,h,uid=user_client(v2app);alive=document(c,h,title='현재 개인 자료')
    with v2app.app_context():
        own=db.session.get(SourceDocument,alive['id']);at=datetime.now(timezone.utc)-timedelta(days=8)
        # Insert an old synthetic source, never rewrite immutable revisions.
        expired=SourceDocument(workspace_id=own.workspace_id,owner_id=uid,title='만료된 개인 자료',original_name='expired.txt',stored_name='expired-synthetic.txt',mime_type='text/plain',size=3,page_count=1,scope='PRIVATE',access_mode='VIEW',document_type='TEXT',created_at=at)
        db.session.add(expired);db.session.flush();expired_id=expired.id
        db.session.add(DocumentRevision(document_id=expired.id,revision_number=1,content='만료',content_hash=hashlib.sha256('만료'.encode()).hexdigest(),file_ref=expired.stored_name,created_at=at))
        db.session.commit()
    v2app.config['PRIVATE_DOCUMENT_RETENTION_POLICY']=DOCUMENT_POLICY
    rows=data(c.get(ROOT+'/sources'))
    assert [row['id'] for row in rows]==[alive['id']]
    assert c.get('/api/source-documents/'+expired_id).status_code==404
    with v2app.app_context():assert db.session.get(SourceDocument,expired_id) is not None
