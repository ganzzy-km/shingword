import pytest
from sqlalchemy import text as sql
from v2_fixture import v2app,user_client
from test_analysis_api import analyze
from test_writing_tools_api import ROOT,data,document,draft,anchor,source_anchor,request
from app.extensions import db
from app.models import SourceDocument,User,Analysis,UserAnnotation,PublicationRequest


def test_reading_scroll_is_revision_bound_and_permission_checked(v2app):
    c,h,_=user_client(v2app);d=document(c,h)
    state=data(c.patch(ROOT+'/sources/'+d['id']+'/state',headers=h,json={'revisionNumber':0,'data':{'revisionId':d['latestRevisionId'],'offset':1,'scrollFraction':.625}}))
    assert state['data']['scrollFraction']==.625
    assert data(c.get(ROOT+'/sources/'+d['id']+'/state'))['data']['offset']==1
    for invalid in [True,-.1,1.01,'0.5']:
        assert c.patch(ROOT+'/sources/'+d['id']+'/state',headers=h,json={'revisionNumber':1,'data':{'scrollFraction':invalid}}).status_code==400
    with v2app.app_context():db.session.get(SourceDocument,d['id']).access_mode='MATCH_ONLY';db.session.commit()
    assert c.patch(ROOT+'/sources/'+d['id']+'/state',headers=h,json={'revisionNumber':1,'data':{'scrollFraction':.1}}).status_code==404
    assert 'scrollFraction' not in data(c.get(ROOT+'/sources/'+d['id']+'/state'))['data']


def test_expired_and_deleted_essay_cards_follow_existing_retention_graph(v2app):
    from datetime import datetime,timedelta,timezone
    from app.models import Writing,QuoteCard
    from app.v2.operations_api import remove_essay_graph
    c,h,_=user_client(v2app);w,v=draft(c,h)
    card=data(c.post(ROOT+'/cards',headers=h,json={'clientKey':'expiry-card-01','writingId':w['id'],'writingAnchor':anchor(v,0,8),'quote':v['content'][:8],'interpretation':'글에 연결한 개인 해석'}),201)
    standalone=data(c.post(ROOT+'/cards',headers=h,json={'clientKey':'work-only-card','interpretation':'독립 작품 노트'}),201)
    with v2app.app_context():db.session.get(Writing,w['id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.session.commit()
    assert c.get(ROOT+'/cards/'+card['id']).status_code==404
    assert all(x['id']!=card['id'] for x in data(c.get(ROOT+'/cards')))
    assert all(x['id']!=card['id'] for x in data(c.get('/api/quote-cards')))
    assert c.post(ROOT+'/cards/'+card['id']+'/quotation-diff',headers=h,json={}).status_code==404
    with v2app.app_context():
        remove_essay_graph(w['id']);db.session.commit();db.session.expire_all()
        assert db.session.get(QuoteCard,card['id']) is None
        assert db.session.get(QuoteCard,standalone['id']) is not None


def test_legacy_quote_card_can_gain_a_note_without_losing_original_fields(v2app):
    c,h,_=user_client(v2app)
    old=data(c.post('/api/quote-cards',headers=h,json={'quote':'기존에 저장한 사용자 구절','work':'기존 작품명','author':'기존 가상 작가','page':'12'}),201)
    changed=data(c.patch(ROOT+'/cards/'+old['id'],headers=h,json={'revisionNumber':1,'interpretation':'새 도구로 덧붙인 개인 메모'}))
    assert changed['quote']=='기존에 저장한 사용자 구절' and changed['work']=='기존 작품명'
    assert changed['author']=='기존 가상 작가' and changed['page']=='12'
    assert changed['sourceAnchor'] is None and changed['interpretation']=='새 도구로 덧붙인 개인 메모'
    assert not data(c.post(ROOT+'/cards/'+old['id']+'/quotation-diff',headers=h,json={}))['applicable']
    with v2app.app_context():
        from app.models import QuoteCard
        assert db.session.get(QuoteCard,old['id']).selected_text=='기존에 저장한 사용자 구절'


@pytest.mark.parametrize('role',['USER','ADMIN'])
def test_owner_boundaries_every_private_resource(v2app,role):
    c,h,_=user_client(v2app);b,bh,_=user_client(v2app,'foreign',role=role);d=document(c,h);w,v=draft(c,h)
    m=data(c.post(ROOT+'/writings/'+w['id']+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':anchor(v,0,8)}),201)
    card=data(c.post(ROOT+'/cards',headers=h,json={'clientKey':'private-card','kind':'NOTE','interpretation':'개인 메모','documentId':d['id'],'writingId':w['id']}),201)
    for path in [ROOT+'/writings/'+w['id']+'/marks',ROOT+'/writings/'+w['id']+'/sources',ROOT+'/cards/'+card['id'],ROOT+'/sources/'+d['id']+'/state',ROOT+'/cards?writingId='+w['id'],ROOT+'/cards?documentId='+d['id']]:
        assert b.get(path).status_code==404
    assert b.patch(ROOT+'/marks/'+m['id'],headers=bh,json={'revisionNumber':1,'kind':'USER_EVIDENCE'}).status_code==404
    assert b.delete(ROOT+'/cards/'+card['id'],headers=bh,json={'revisionNumber':1}).status_code==404
    assert b.post(ROOT+'/sources/'+d['id']+'/search',headers=bh,json={'revisionId':d['latestRevisionId'],'query':'첫'}).status_code==404
    assert data(b.get(ROOT+'/sources'))==[]


def test_match_only_no_new_context_card_diff_or_delegated_raw_text(v2app):
    c,h,_=user_client(v2app);admin,ah,_=user_client(v2app,'admin',role='ADMIN');d=document(c,h,mode='MATCH_ONLY')
    assert c.post(ROOT+'/sources/'+d['id']+'/search',headers=h,json={'revisionId':d['latestRevisionId'],'query':'첫'}).status_code==404
    assert c.post(ROOT+'/cards',headers=h,json={'clientKey':'match-raw-01','kind':'DIRECT_QUOTE','sourceType':'ORIGINAL','quote':'😀 첫','sourceAnchor':source_anchor(d)}).status_code==404
    assert c.patch(ROOT+'/sources/'+d['id']+'/state',headers=h,json={'revisionNumber':0,'data':{'revisionId':d['latestRevisionId'],'offset':1}}).status_code==404
    note=data(c.post(ROOT+'/cards',headers=h,json={'clientKey':'match-note1','kind':'QUESTION','sourceType':'MY_INTERPRETATION','interpretation':'개인 질문','documentId':d['id']}),201)
    assert note['sourceAnchor'] is None and note['sourceUnavailable'] and not note['quote']
    req=request(c,h,d)
    delegated=data(admin.get(ROOT+'/publication-requests/'+req['id']+'/revision'))
    assert 'content' not in delegated
    assert c.get('/api/source-documents/'+d['id']+'/revisions/'+d['latestRevisionId']).status_code==404
    assert c.get('/api/files/source/'+d['id']).status_code==404


@pytest.mark.parametrize('change',[{'quote':'위조 구간'},{'span':{'start':True,'end':3}},{'span':{'start':-1,'end':3}},{'span':{'start':0,'end':999}},{'essayVersionId':'unknown'}])
def test_unicode_anchor_forgery(v2app,change):
    c,h,_=user_client(v2app);w,v=draft(c,h)
    assert c.post(ROOT+'/writings/'+w['id']+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':{**anchor(v,0,8),**change}}).status_code==400


def test_same_text_different_revision_is_not_interchangeable(v2app):
    c,h,_=user_client(v2app);d=document(c,h);other=document(c,h)
    a={**source_anchor(d),'revisionId':other['latestRevisionId']}
    assert c.post(ROOT+'/cards',headers=h,json={'clientKey':'cross-source','kind':'DIRECT_QUOTE','sourceType':'ORIGINAL','quote':'😀 첫','sourceAnchor':a}).status_code==404


def test_original_source_revocation_redacts_cached_card_values(v2app):
    c,h,_=user_client(v2app);d=document(c,h)
    card=data(c.post(ROOT+'/cards',headers=h,json={'clientKey':'redact-quote','kind':'DIRECT_QUOTE','sourceType':'ORIGINAL','quote':'😀 첫','sourceAnchor':source_anchor(d),'interpretation':'내 질문'}),201)
    with v2app.app_context():db.session.get(SourceDocument,d['id']).access_mode='MATCH_ONLY';db.session.commit()
    shown=data(c.get(ROOT+'/cards/'+card['id']))
    assert shown['sourceAnchor'] is None and shown['quote']=='' and shown['interpretation']=='내 질문'
    assert c.post(ROOT+'/cards/'+card['id']+'/quotation-diff',headers=h,json={}).status_code==404
    assert data(c.get('/api/quote-cards'))==[]


def test_s4_snapshot_reanalysis_does_not_replace_manual_graph(v2app):
    c,h,_=user_client(v2app);w,v=draft(c,h)
    row=data(c.post(ROOT+'/writings/'+w['id']+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':anchor(v,0,8)}),201)
    with v2app.app_context():before=db.session.get(UserAnnotation,row['id']).original_anchor
    run=data(analyze(v2app,c,h,w),202)
    saved=data(c.get('/api/analyses/'+run['analysisId']))
    assert all(x.get('source')!='USER_DEFINED' for x in saved.get('argumentLinks',[]))
    after=data(c.get(ROOT+'/writings/'+w['id']+'/marks'))
    assert after[0]['originalAnchor']==before and after[0]['id']==row['id']


def test_changed_role_invalidates_old_link_and_self_overlap_denied(v2app):
    c,h,_=user_client(v2app);w,v=draft(c,h);path=ROOT+'/writings/'+w['id']
    e=data(c.post(path+'/marks',headers=h,json={'kind':'USER_EVIDENCE','anchor':anchor(v,0,8)}),201)
    wrong=data(c.post(path+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':anchor(v,0,8)}),201)
    assert c.post(path+'/links',headers=h,json={'claimId':wrong['id'],'evidenceId':e['id']}).status_code==400
    c1=data(c.post(path+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':anchor(v,9,len(v['content']))}),201)
    link=data(c.post(path+'/links',headers=h,json={'claimId':c1['id'],'evidenceId':e['id']}),201)
    data(c.patch(ROOT+'/marks/'+c1['id'],headers=h,json={'revisionNumber':1,'kind':'USER_EVIDENCE'}))
    assert next(x for x in data(c.get(path+'/marks')) if x['id']==link['id'])['resolution']['status']=='NEEDS_REVIEW'


def test_cancel_and_deactivated_owner_cannot_be_published(v2app):
    c,h,uid=user_client(v2app);admin,ah,_=user_client(v2app,'admin',role='ADMIN');d=document(c,h);req=request(c,h,d)
    data(c.patch(ROOT+'/publication-requests/'+req['id'],headers=h,json={'state':'WITHDRAWN','revisionNumber':1}))
    assert admin.patch(ROOT+'/publication-requests/'+req['id'],headers=ah,json={'state':'APPROVED','revisionNumber':1,'reviewConfirmed':True}).status_code==409
    assert data(c.get('/api/source-documents/'+d['id']))['scope']=='PRIVATE'
    d2=document(c,h);req2=request(c,h,d2)
    with v2app.app_context():db.session.get(User,uid).status='INACTIVE';db.session.commit()
    assert admin.patch(ROOT+'/publication-requests/'+req2['id'],headers=ah,json={'state':'APPROVED','revisionNumber':1,'reviewConfirmed':True}).status_code==409
    with v2app.app_context():assert db.session.get(SourceDocument,d2['id']).scope=='PRIVATE' and db.session.get(PublicationRequest,req2['id']).state=='PENDING'


@pytest.mark.parametrize('path',['/preferences','/cards','/publication-requests'])
def test_new_mutations_keep_csrf_and_anonymous_denial(v2app,path):
    c,h,_=user_client(v2app)
    assert c.post(ROOT+path,json={}).status_code in (401,405)
    assert v2app.test_client().get(ROOT+path).status_code==401


def test_reading_state_binds_essay_hash_and_same_document_note(v2app):
    c,h,_=user_client(v2app);d=document(c,h);other=document(c,h);w,v=draft(c,h)
    note=data(c.post(ROOT+'/cards',headers=h,json={'clientKey':'position-note','documentId':other['id'],'interpretation':'다른 작품 메모'}),201)
    state_path=ROOT+'/sources/'+d['id']+'/state'
    assert c.patch(state_path,headers=h,json={'revisionNumber':0,'data':{'revisionId':d['latestRevisionId'],'offset':2,'openCardId':note['id']}}).status_code==400
    saved=data(c.patch(state_path,headers=h,json={'revisionNumber':0,'data':{'revisionId':d['latestRevisionId'],'offset':2,'writingId':w['id'],'essayOffset':3}}))
    shown=data(c.get(state_path));assert shown['data']['essayOffset']==3 and shown['data']['essayBodySha256']
    data(c.patch('/api/writings/'+w['id'],headers=h,json={'revisionNumber':w['revisionNumber'],'content':'서로 다른 본문'}))
    stale=data(c.get(state_path));assert 'essayOffset' not in stale['data'] and stale['data']['offset']==2
