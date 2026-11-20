import io
import pytest
from v2_fixture import v2app,user_client
from test_analysis_api import essay,analyze
from app.extensions import db
from app.models import UserAnnotation,QuoteCard,Analysis,Writing,PublicationRequest,SourceDocument

ROOT='/api/writing-tools'


def data(response,code=200):
    assert response.status_code==code,response.json
    return response.json['data']


def document(c,h,body='😀 첫 장면. 인물은 문을 연다. 마지막 빛.',mode='VIEW',title='독립 창작 자료'):
    return data(c.post('/api/source-documents',headers=h,data={'title':title,'author':'가상 작가','scope':'PRIVATE','accessMode':mode,'documentType':'TEXT','file':(io.BytesIO(body.encode()),'synthetic.txt')},content_type='multipart/form-data'),201)


def draft(c,h,body='😀 문을 연다. 이 선택은 함께 살기를 드러낸다.'):
    w=essay(c,h,body)
    v=data(c.post('/api/writings/'+w['id']+'/versions',headers=h,json={'revisionNumber':w['revisionNumber'],'name':'직접 연결'}),201)
    return w,v


def anchor(v,a,z):return {'essayVersionId':v['id'],'span':{'start':a,'end':z},'quote':v['content'][a:z]}


def source_anchor(d,a=0,z=3):return {'documentId':d['id'],'revisionId':d['latestRevisionId'],'span':{'start':a,'end':z},'quote':'😀 첫'}


def test_account_preferences_and_first_tutorial(v2app):
    c,h,_=user_client(v2app);other,_,_=user_client(v2app,'other')
    p=data(c.get(ROOT+'/preferences'));assert p['offerTutorial'] and p['data']['tutorial']=='UNSEEN'
    saved=data(c.patch(ROOT+'/preferences',headers=h,json={'revisionNumber':0,'data':{'fontSize':22,'lineHeight':2.1,'bodyWidth':900,'tutorial':'COMPLETED','tutorialStep':3}}))
    assert saved['revisionNumber']==1 and data(c.get(ROOT+'/preferences'))['data']['fontSize']==22
    assert data(other.get(ROOT+'/preferences'))['data']['fontSize']==18
    assert c.patch(ROOT+'/preferences',headers=h,json={'revisionNumber':0,'data':{'fontSize':24}}).status_code==409
    assert c.patch(ROOT+'/preferences',json={'revisionNumber':1,'data':{'focus':True}}).status_code==401


@pytest.mark.parametrize('patch',[{'fontSize':True},{'lineHeight':99},{'bodyWidth':1101},{'tutorial':'FORGED'},{'mobileTab':'other'},{'ownerId':'other'}])
def test_invalid_preferences(v2app,patch):
    c,h,_=user_client(v2app)
    assert c.patch(ROOT+'/preferences',headers=h,json={'revisionNumber':0,'data':patch}).status_code==400


def test_arbitrary_roles_many_to_many_and_original_annotations(v2app):
    c,h,_=user_client(v2app);w,v=draft(c,h)
    path=ROOT+'/writings/'+w['id']
    e=data(c.post(path+'/marks',headers=h,json={'kind':'USER_EVIDENCE','anchor':anchor(v,0,8)}),201)
    claim=data(c.post(path+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':anchor(v,9,len(v['content']))}),201)
    repeated=data(c.post(path+'/marks',headers=h,json={'kind':'USER_CLAIM','anchor':anchor(v,9,len(v['content']))}))
    assert repeated['id']==claim['id'] and claim['source']=='USER_DEFINED'
    link=data(c.post(path+'/links',headers=h,json={'claimId':claim['id'],'evidenceId':e['id'],'classification':'SUPPORT'}),201)
    assert link['kind']=='USER_LINK' and link['metadata']['classification']=='SUPPORT'
    assert data(c.post(path+'/links',headers=h,json={'claimId':claim['id'],'evidenceId':e['id']}))['id']==link['id']
    assert len(data(c.get(path+'/marks')))==3
    assert data(c.get('/api/writings/'+w['id']+'/annotations'))==[]
    assert c.patch('/api/annotations/'+claim['id'],headers=h,json={'revisionNumber':1,'content':'오인 변경'}).status_code==404
    changed=data(c.patch(ROOT+'/marks/'+link['id'],headers=h,json={'revisionNumber':1,'classification':'COUNTER'}))
    assert changed['metadata']['classification']=='COUNTER'
    assert c.patch(ROOT+'/marks/'+link['id'],headers=h,json={'revisionNumber':1,'classification':'SUPPORT'}).status_code==409
    with v2app.app_context():assert Analysis.query.count()==0


def test_body_edit_duplicate_quotes_conservative_stale(v2app):
    c,h,_=user_client(v2app);w,v=draft(c,h,'문을 연다. 끝을 생각한다.')
    row=data(c.post(ROOT+'/writings/'+w['id']+'/marks',headers=h,json={'kind':'USER_EVIDENCE','anchor':anchor(v,0,6)}),201)
    old=row['originalAnchor']
    w=data(c.patch('/api/writings/'+w['id'],headers=h,json={'revisionNumber':w['revisionNumber'],'content':'문을 연다. 문을 연다. 끝을 생각한다.'}))
    assert data(c.get(ROOT+'/writings/'+w['id']+'/marks'))[0]['resolution']['status']=='NEEDS_REVIEW'
    v2=data(c.post('/api/writings/'+w['id']+'/versions',headers=h,json={'revisionNumber':w['revisionNumber'],'name':'구간 재확인'}),201)
    relink=data(c.patch(ROOT+'/marks/'+row['id'],headers=h,json={'revisionNumber':1,'anchor':anchor(v2,0,6)}))
    assert relink['originalAnchor']==old and relink['essayVersionId']==v2['id']
    assert data(c.delete(ROOT+'/marks/'+row['id'],headers=h,json={'revisionNumber':2}))['deleted']


def test_source_catalog_favorites_recent_and_pinned_kwic(v2app):
    c,h,_=user_client(v2app);other,oh,_=user_client(v2app,'other')
    d=document(c,h);hidden=document(other,oh,title='절대 노출 금지 비공개')
    assert [x['id'] for x in data(c.get(ROOT+'/sources'))]==[d['id']]
    assert data(c.get(ROOT+'/sources?q=절대'))==[]
    state=data(c.patch(ROOT+'/sources/'+d['id']+'/state',headers=h,json={'revisionNumber':0,'data':{'favorite':True,'revisionId':d['latestRevisionId'],'offset':2}}))
    assert state['revisionNumber']==1 and state['data']['lastUsed']
    assert len(data(c.get(ROOT+'/sources?favorite=1&recent=1&access=VIEW')))==1
    hits=data(c.post(ROOT+'/sources/'+d['id']+'/search',headers=h,json={'revisionId':d['latestRevisionId'],'query':'😀'}))
    assert hits['hits'][0]['span']=={'start':0,'end':1}
    assert data(c.get(ROOT+'/sources/'+d['id']+'/state'))['data']['offset']==2
    assert c.get(ROOT+'/sources/'+hidden['id']+'/state').status_code==404


def test_partial_card_source_diff_and_revision_conflict(v2app):
    c,h,_=user_client(v2app);d=document(c,h);w,v=draft(c,h)
    partial=data(c.post(ROOT+'/cards',headers=h,json={'clientKey':'partial-0001','kind':'QUESTION','sourceType':'MY_INTERPRETATION','interpretation':'이 선택은 무엇을 남기는가?','writingId':w['id']}),201)
    assert partial['quote']=='' and partial['interpretation']
    body={'clientKey':'direct-0001','kind':'DIRECT_QUOTE','sourceType':'ORIGINAL','quote':'😀  첫','sourceAnchor':source_anchor(d),'writingId':w['id'],'writingAnchor':anchor(v,0,8),'interpretation':'내가 읽은 장면','claimText':'함께 사는 선택'}
    row=data(c.post(ROOT+'/cards',headers=h,json=body),201)
    assert data(c.post(ROOT+'/cards',headers=h,json=body))['id']==row['id']
    diff=data(c.post(ROOT+'/cards/'+row['id']+'/quotation-diff',headers=h,json={}))
    assert diff['applicable'] and not diff['exact'] and diff['revisionId']==d['latestRevisionId']
    assert diff['changes'][0]['kind']=='insert'
    edited=data(c.patch(ROOT+'/cards/'+row['id'],headers=h,json={'revisionNumber':1,'classification':'ALTERNATIVE'}))
    assert edited['revisionNumber']==2 and edited['classification']=='ALTERNATIVE'
    assert c.patch(ROOT+'/cards/'+row['id'],headers=h,json={'revisionNumber':1,'interpretation':'오래된 창'}).status_code==409
    assert not data(c.post(ROOT+'/cards/'+partial['id']+'/quotation-diff',headers=h,json={}))['applicable']


def request(c,h,d):
    return data(c.post(ROOT+'/publication-requests',headers=h,json={'documentId':d['id'],'revisionId':d['latestRevisionId'],'rightsConfirmed':True,'delegateReview':True,'rightsBasis':'직접 창작한 시험 원문으로 해당 판본의 공개를 허가합니다.'}),201)


def test_exact_revision_delegation_approve_withdraw_and_foreign_admin(v2app):
    c,h,_=user_client(v2app);admin,ah,_=user_client(v2app,'admin',role='ADMIN');b,bh,_=user_client(v2app,'reader')
    d=document(c,h);first=d['latestRevisionId']
    second=data(c.post('/api/source-documents/'+d['id']+'/revisions',headers=h,json={'expectedRevisionId':first,'content':'소유자의 다른 비공개 판본'}),201)
    req=request(c,h,d)
    assert admin.get('/api/source-documents/'+d['id']).status_code==404
    delegated=data(admin.get(ROOT+'/publication-requests/'+req['id']+'/revision'))
    assert delegated['revisionId']==first and '😀 첫 장면' in delegated['content']
    assert b.get(ROOT+'/publication-requests/'+req['id']+'/revision').status_code==404
    assert c.patch(ROOT+'/publication-requests/'+req['id'],headers=h,json={'state':'APPROVED','revisionNumber':1,'reviewConfirmed':True}).status_code==403
    approved=data(admin.patch(ROOT+'/publication-requests/'+req['id'],headers=ah,json={'state':'APPROVED','revisionNumber':1,'reviewConfirmed':True}))
    assert approved['state']=='APPROVED'
    shown=data(b.get('/api/source-documents/'+d['id']));assert shown['latestRevisionId']==first and '😀 첫 장면' in shown['content']
    assert b.get('/api/source-documents/'+d['id']+'/revisions/'+second['id']).status_code==404
    assert b.post('/api/source-documents/'+d['id']+'/search',headers=bh,json={'revisionId':second['id'],'quote':'판본'}).status_code==404
    w=essay(b,bh,'시험');assert b.post('/api/writings/'+w['id']+'/documents',headers=bh,json={'revisionId':second['id']}).status_code==404
    assert admin.patch('/api/source-documents/'+d['id']+'/scope',headers=ah,json={'scope':'PRIVATE','expectedRevisionId':first}).status_code==404
    withdrawn=data(c.patch(ROOT+'/publication-requests/'+req['id'],headers=h,json={'state':'WITHDRAWN','revisionNumber':2}))
    assert withdrawn['state']=='WITHDRAWN' and b.get('/api/source-documents/'+d['id']).status_code==404
    assert admin.get(ROOT+'/publication-requests/'+req['id']+'/revision').status_code==404
    assert admin.patch(ROOT+'/publication-requests/'+req['id'],headers=ah,json={'state':'APPROVED','revisionNumber':1,'reviewConfirmed':True}).status_code==409


def test_request_cancel_reject_and_no_blanket_privilege(v2app):
    c,h,_=user_client(v2app);admin,ah,_=user_client(v2app,'admin',role='ADMIN');other,oh,_=user_client(v2app,'other')
    d=document(c,h);req=request(c,h,d)
    same=data(c.post(ROOT+'/publication-requests',headers=h,json={'documentId':d['id'],'revisionId':d['latestRevisionId'],'rightsConfirmed':True,'delegateReview':True,'rightsBasis':'같은 판본에 대한 중복 제출을 차단합니다.'}))
    assert same['id']==req['id']
    assert other.post(ROOT+'/publication-requests',headers=oh,json={'documentId':d['id'],'revisionId':d['latestRevisionId'],'rightsConfirmed':True,'delegateReview':True,'rightsBasis':'타인 자료 공개를 시도하는 반례입니다.'}).status_code==404
    rejected=data(admin.patch(ROOT+'/publication-requests/'+req['id'],headers=ah,json={'state':'REJECTED','revisionNumber':1,'reason':'이용 근거 확인 필요'}))
    assert rejected['state']=='REJECTED' and admin.get(ROOT+'/publication-requests/'+req['id']+'/revision').status_code==404
    assert data(c.get('/api/source-documents/'+d['id']))['scope']=='PRIVATE'
