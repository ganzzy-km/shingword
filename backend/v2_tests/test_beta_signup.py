"""Local synthetic claims; real OIDC cryptography is covered by auth tests."""
from types import SimpleNamespace
import re
import pytest
from v2_fixture import v2app, user_client
from app.extensions import db
from app.models import User, Consent, ActivityRecord
from app.v2.auth_api import CHALLENGE_COOKIE
from app.v2.beta_signup import COOKIE, KIND, TTL

def configure(app):
    app.config.update(BETA_SIGNUP_ENABLED=True,BETA_SIGNUP_POLICY={'approved':True,'version':'synthetic-beta-v1','notice':'Synthetic beta privacy notice','contact':'Contact synthetic operator directly'})

def login(app,client,subject='new-beta'):
    app.config['OIDC_FLOW']=SimpleNamespace(testing=True,finish=lambda *_a,**_k:{'sub':subject,'email':'synthetic@example.test','emailVerified':True,'displayName':'가상 가입자'})
    app.extensions['v2_challenges']['synthetic-ticket']=object()
    client.set_cookie(CHALLENGE_COOKIE,'synthetic-ticket')
    return client.get('/api/auth/callback?state=synthetic&code=synthetic')

def form(client):
    r=client.get('/api/auth/enrollment');assert r.status_code==200
    csrf=re.search(r'name="csrf" value="([^"]+)"',r.text).group(1)
    return {'csrf':csrf,'policyVersion':'synthetic-beta-v1','age14':'yes','privacyConsent':'yes'}

def test_consent_then_immediate_user_and_sub_reuse(v2app):
    configure(v2app);c=v2app.test_client();r=login(v2app,c)
    assert r.status_code==302 and r.location=='/api/auth/enrollment'
    cookie=next(x for x in r.headers.getlist('Set-Cookie') if x.startswith(COOKIE+'='))
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert c.get('/api/writings').status_code==401
    data=form(c);r=c.post('/api/auth/enrollment',data=data)
    assert r.status_code==302 and r.location=='/'
    s=c.get('/api/auth/session').json['data'];assert s['status']=='ACTIVE' and s['role']=='USER'
    assert c.get('/api/writings').status_code==200
    assert c.post('/api/auth/enrollment',data=data).status_code==401
    assert login(v2app,c).location=='/'
    with v2app.app_context():
        assert User.query.count()==1 and Consent.query.filter_by(kind=KIND).count()==1
    assert c.post('/api/auth/logout',headers={'X-CSRF-Token':s['csrfToken']}).status_code==401
    refreshed=c.get('/api/auth/session').json['data']
    assert c.post('/api/auth/logout',headers={'X-CSRF-Token':refreshed['csrfToken']}).status_code==200
    assert c.get('/api/writings').status_code==401

@pytest.mark.parametrize('field,value',[('csrf','wrong'),('age14','no'),('privacyConsent','no'),('policyVersion','old')])
def test_reject_missing_conditions_without_activation(v2app,field,value):
    configure(v2app);c=v2app.test_client();login(v2app,c);data=form(c);data[field]=value
    assert c.post('/api/auth/enrollment',data=data).status_code==401
    with v2app.app_context():
        assert User.query.one().status=='PENDING_APPROVAL' and Consent.query.count()==0

def test_expired_and_tampered_enrollment_ticket(v2app,monkeypatch):
    import time
    configure(v2app);c=v2app.test_client();login(v2app,c)
    ticket=c.get_cookie(COOKIE).value;c.set_cookie(COOKIE,ticket+'tampered')
    assert c.get('/api/auth/enrollment').status_code==401
    c.set_cookie(COOKIE,ticket);now=time.time();monkeypatch.setattr('itsdangerous.timed.time.time',lambda:now+TTL+2)
    assert c.get('/api/auth/enrollment').status_code==401

def test_blocked_pending_history_and_inactive_never_activate(v2app):
    configure(v2app);c=v2app.test_client()
    with v2app.app_context():
        u=User(oidc_issuer='https://accounts.google.com',oidc_subject='blocked',status='PENDING_APPROVAL');db.session.add(u);db.session.flush()
        db.session.add(ActivityRecord(action='ACCOUNT_STATUS_CHANGED',target_type='user',target_id=u.id,details={'status':'INACTIVE'}));db.session.commit()
    assert login(v2app,c,'blocked').status_code==401
    with v2app.app_context():u=User.query.one();u.status='INACTIVE';db.session.commit()
    assert login(v2app,c,'blocked').status_code==401

def test_disable_during_consent_invalidates_ticket(v2app):
    configure(v2app);c=v2app.test_client();login(v2app,c);data=form(c)
    with v2app.app_context():u=User.query.one();u.status='INACTIVE';u.session_version+=1;db.session.commit()
    assert c.post('/api/auth/enrollment',data=data).status_code==401
    with v2app.app_context():assert Consent.query.count()==0 and User.query.one().status=='INACTIVE'

def test_existing_active_session_needs_current_consent(v2app):
    c,_,_=user_client(v2app);configure(v2app)
    assert c.get('/api/writings').status_code==403
    assert login(v2app,c,'synthetic-user').location=='/api/auth/enrollment'
    assert c.post('/api/auth/enrollment',data=form(c)).status_code==302
    assert c.get('/api/writings').status_code==200

def test_replaced_ticket_and_policy_change_reject_old_grant(v2app):
    configure(v2app);c=v2app.test_client();login(v2app,c);old=c.get_cookie(COOKIE).value;data=form(c)
    login(v2app,c);new=c.get_cookie(COOKIE).value;c.set_cookie(COOKIE,old)
    assert c.post('/api/auth/enrollment',data=data).status_code==401
    c.set_cookie(COOKIE,new);data=form(c);v2app.config['BETA_SIGNUP_POLICY']['version']='new-version'
    assert c.post('/api/auth/enrollment',data=data).status_code==401

def test_disabled_signup_preserves_old_pending_behavior(v2app):
    c=v2app.test_client();r=login(v2app,c)
    assert r.json['data']['status']=='PENDING_APPROVAL'
    assert c.get('/api/auth/enrollment').status_code==503


def test_collapsible_notice_preserves_approved_text_and_escapes_html(v2app):
    from html import unescape
    configure(v2app)
    paragraphs=['지인 대상 안내', 'Google 계정 이용 안내', '에세이는 7일 보존', '탈퇴 후 2개월 보존', '내려받은 PDF 이용 안내', '<script>민감한 문자열</script> & 추가 안내']
    v2app.config['BETA_SIGNUP_POLICY']['notice']='\n'.join(paragraphs)
    v2app.config['BETA_SIGNUP_POLICY']['contact']='직접 연락 <문의> & 삭제 요청'
    c=v2app.test_client();login(v2app,c)
    r=c.get('/api/auth/enrollment');assert r.status_code==200
    contents=re.findall(r'<p class="privacy-section-content">(.*?)</p>',r.text,re.S)
    assert [unescape(p) for p in contents]==paragraphs+['직접 연락 <문의> & 삭제 요청']
    assert '<script>' not in r.text
    assert len(re.findall(r'<details>',r.text))==7 and '<details open' not in r.text
    assert 'checked' not in r.text
    assert 'name="age14" value="yes" required' in r.text
    assert 'name="privacyConsent" value="yes" required' in r.text
    with v2app.app_context():
        assert User.query.one().status=='PENDING_APPROVAL' and Consent.query.count()==0
