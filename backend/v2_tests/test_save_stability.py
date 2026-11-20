"""Isolated save integrity and existing throttling contracts; no production data."""
import sqlite3
import pytest
from v2_fixture import v2app,user_client
from app.v2.network_gate import IsolatedNetworkGate
from werkzeug.test import Client
from werkzeug.wrappers import Response

@pytest.mark.parametrize('field,value',[('title','새 제목'),('work','새 작품'),('inquiryQuestion','다른 탐구 질문'),('content','새 본문 😀')])
def test_each_tracked_field_persists_once_and_noop_does_not_add_revision(v2app,field,value):
    c,h,_=user_client(v2app)
    original={'title':'합성 제목','work':'합성 작품','inquiryQuestion':'합성 질문','content':'처음 본문 😀'}
    w=c.post('/api/writings',headers=h,json=original).json['data'];url='/api/writings/'+w['id']
    version=c.post(url+'/versions',headers=h,json={'revisionNumber':w['revisionNumber'],'content':original['content']}).json['data']
    result=c.patch(url,headers=h,json={field:value,'revisionNumber':w['revisionNumber']});assert result.status_code==200
    result=result.json['data'];assert result['revisionNumber']==w['revisionNumber']+1
    for key,old in original.items():assert result[key]==(value if key==field else old)
    retry=c.patch(url,headers=h,json={field:value,'revisionNumber':result['revisionNumber']});assert retry.status_code==200
    assert retry.json['data']['revisionNumber']==result['revisionNumber']
    assert c.get(url).json['data'][field]==value
    assert c.get(url+'/versions').json['data'][0]['content']==original['content']
    assert c.get(url+'/versions').json['data'][0]['id']==version['id']

def test_real_sqlite_busy_failure_does_not_commit_and_retry_succeeds(v2app):
    c,h,_=user_client(v2app);w=c.post('/api/writings',headers=h,json={'content':'보존할 합성 원문 😀'}).json['data'];url='/api/writings/'+w['id']
    blocker=sqlite3.connect(str(v2app.config['DATABASE_PATH']),timeout=1)
    try:
        blocker.execute('BEGIN IMMEDIATE')
        failed=c.patch(url,headers=h,json={'content':'잠금 중 합성 수정','revisionNumber':w['revisionNumber']})
        assert failed.status_code==500 and failed.json['error']['code']=='INTERNAL_ERROR'
        assert '잠금 중 합성 수정' not in failed.get_data(as_text=True)
    finally:blocker.rollback();blocker.close()
    current=c.get(url).json['data'];assert current['content']==w['content'] and current['revisionNumber']==w['revisionNumber']
    retry=c.patch(url,headers=h,json={'content':'잠금 해제 후 합성 수정','revisionNumber':w['revisionNumber']});assert retry.status_code==200
    assert c.get(url).json['data']['content']=='잠금 해제 후 합성 수정'

def test_existing_limiter_429_and_retry_after_without_body_or_identity():
    now=[0.0]
    def app(environ,start_response):start_response('200 OK',[('Content-Type','application/json')]);return [b'{}']
    gate=IsolatedNetworkGate(app,'localhost:8786','synthetic-password-000000',google_only=True,limit=2,clock=lambda:now[0])
    client=Client(gate,Response)
    for _ in range(2):assert client.patch('/api/writings/synthetic',base_url='https://localhost:8786',json={'content':'PRIVATE_SYNTHETIC_BODY'}).status_code==200
    r=client.patch('/api/writings/synthetic',base_url='https://localhost:8786',json={'content':'PRIVATE_SYNTHETIC_BODY'})
    assert r.status_code==429 and r.json['error']['code']=='TEST_REQUEST_LIMIT' and r.headers['Retry-After']=='60'
    assert 'PRIVATE_SYNTHETIC_BODY' not in r.get_data(as_text=True)
    now[0]=61
    assert client.patch('/api/writings/synthetic',base_url='https://localhost:8786',json={}).status_code==200
