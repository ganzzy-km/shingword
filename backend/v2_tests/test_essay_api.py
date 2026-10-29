from v2_fixture import v2app,user_client
from app.extensions import db
from app.models import WritingVersion,Writing
from sqlalchemy.exc import IntegrityError
import pytest


def create(client,headers,body='가😀'):
    response=client.post('/api/writings',headers=headers,json={'title':'synthetic essay','content':body})
    assert response.status_code==201;return response.json['data']


def test_actual_draft_persist_and_owner_listing(v2app):
    a,h,uid=user_client(v2app);b,hb,_=user_client(v2app,'synthetic-other');w=create(a,h)
    assert a.get('/api/writings/'+w['id']).json['data']['content']=='가😀'
    assert len(a.get('/api/records').json['data'])==1 and b.get('/api/records').json['data']==[]
    assert b.get('/api/writings/'+w['id']).status_code==404


def test_autosave_conflict_never_overwrites(v2app):
    c,h,_=user_client(v2app);w=create(c,h)
    r=c.post('/api/writings/'+w['id']+'/autosave',headers=h,json={'content':'new','revisionNumber':1});assert r.status_code==200 and r.json['data']['revisionNumber']==2
    r=c.post('/api/writings/'+w['id']+'/autosave',headers=h,json={'content':'old delayed','revisionNumber':1});assert r.status_code==409
    assert c.get('/api/writings/'+w['id']).json['data']['content']=='new'


def test_noop_save_and_bool_revision_rejected(v2app):
    c,h,_=user_client(v2app);w=create(c,h)
    for revision,status in [(1,200),(True,409)]:
        r=c.post('/api/writings/'+w['id']+'/autosave',headers=h,json={'content':'가😀','revisionNumber':revision});assert r.status_code==status
    assert c.get('/api/writings/'+w['id']).json['data']['revisionNumber']==1


def test_nfc_lf_and_unpaired_surrogate_validation(v2app):
    c,h,_=user_client(v2app);w=create(c,h,'가\r\n😀')
    assert w['content']=='가\n😀'
    assert c.post('/api/writings',headers=h,json={'content':'\ud800'}).status_code==400


def test_latest_equal_snapshot_reused_but_a_b_a_new_version(v2app):
    c,h,_=user_client(v2app);w=create(c,h,'A')
    def version(body,revision):
        r=c.post('/api/writings/'+w['id']+'/versions',headers=h,json={'content':body,'revisionNumber':revision});assert r.status_code==201;return r.json['data']
    a=version('A',1);same=version('A',1);b=version('B',1);a2=version('A',2)
    assert a['id']==same['id'] and a2['id']!=a['id'] and a2['versionNumber']==3 and a2['parentId']==b['id']


def test_snapshot_immutable(v2app):
    c,h,_=user_client(v2app);w=create(c,h)
    r=c.post('/api/writings/'+w['id']+'/versions',headers=h,json={'content':'가😀','revisionNumber':1})
    with v2app.app_context():
        v=db.session.get(WritingVersion,r.json['data']['id']);v.content='changed'
        with pytest.raises(IntegrityError):db.session.commit()
        db.session.rollback();assert v.content=='가😀'


def test_metadata_owner_spoof_and_admin_idor(v2app):
    c,h,_=user_client(v2app);admin,ah,_=user_client(v2app,'synthetic-admin','ADMIN');w=create(c,h)
    assert admin.patch('/api/writings/'+w['id'],headers=ah,json={'content':'stolen','revisionNumber':1}).status_code==404
    assert c.patch('/api/writings/'+w['id'],headers=h,json={'ownerId':'other','revisionNumber':1}).status_code==400


def test_version_conflict_and_cross_essay_compare(v2app):
    c,h,_=user_client(v2app);a=create(c,h,'A');b=create(c,h,'B')
    av=c.post('/api/writings/'+a['id']+'/versions',headers=h,json={'content':'A','revisionNumber':1}).json['data']
    bv=c.post('/api/writings/'+b['id']+'/versions',headers=h,json={'content':'B','revisionNumber':1}).json['data']
    assert c.get('/api/writing-versions/'+av['id']+'/compare/'+bv['id']).status_code==404
    assert c.post('/api/writings/'+a['id']+'/versions',headers=h,json={'content':'lost','revisionNumber':0}).status_code==409


def test_simultaneous_saves_have_one_winner(v2app):
    from concurrent.futures import ThreadPoolExecutor
    a,ha,_=user_client(v2app);b,hb,_=user_client(v2app);w=create(a,ha)
    def save(args):
        client,headers,body=args
        return client.post('/api/writings/'+w['id']+'/autosave',headers=headers,json={'content':body,'revisionNumber':1}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(save,[(a,ha,'synthetic A'),(b,hb,'synthetic B')]))
    assert sorted(statuses)==[200,409]
    assert a.get('/api/writings/'+w['id']).json['data']['revisionNumber']==2


def test_failed_commit_rolls_back_draft_and_version(v2app,monkeypatch):
    c,h,_=user_client(v2app);w=create(c,h,'preserved synthetic draft')
    def fail():raise RuntimeError('synthetic storage failure')
    with monkeypatch.context() as patch:
        patch.setattr(db.session,'commit',fail)
        response=c.post('/api/writings/'+w['id']+'/versions',headers=h,json={'content':'uncommitted','revisionNumber':1})
        assert response.status_code==500
    assert c.get('/api/writings/'+w['id']).json['data']['content']=='preserved synthetic draft'
    assert c.get('/api/writings/'+w['id']+'/versions').json['data']==[]
