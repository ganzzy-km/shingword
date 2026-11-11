"""Explicit opt-in consent gate. Reuses OIDC, session cookies and consents."""
import hashlib
import secrets
from datetime import datetime, timezone
from itsdangerous import URLSafeTimedSerializer, BadSignature
from flask import current_app, request, redirect, render_template_string
from sqlalchemy import text
from ..extensions import db
from ..models import User, Consent, AppSetting, ActivityRecord
from components.auth import AuthDenied, SessionBoundary, public_google_profile

COOKIE='geulbit_enrollment'
TTL=300
KIND='required_privacy_14plus'

def policy():
    p=current_app.config.get('BETA_SIGNUP_POLICY')
    if not isinstance(p,dict) or p.get('approved') is not True or any(not isinstance(p.get(k),str) or not p[k].strip() for k in ['version','notice','contact']):
        raise AuthDenied('PENDING_EXTERNAL')
    return p

def signer():return URLSafeTimedSerializer(current_app.config['SESSION_SIGNING_KEY'],salt='geulbit-enrollment-v1')

def consented(user):
    return Consent.query.filter_by(user_id=user.id,kind=KIND,policy_version=policy()['version'],revoked_at=None).first() is not None

def eligible(user):
    from .privacy_lifecycle import withdrawn
    if not user or withdrawn(user.id) or user.status=='INACTIVE':raise AuthDenied('ACCESS_DENIED')
    if user.status=='PENDING_APPROVAL':
        if user.role!='USER' or db.session.get(AppSetting,'privacy_revoke:user:'+user.id):raise AuthDenied('ACCESS_DENIED')
        # Legacy denial/status history is ambiguous; never silently undo it.
        if ActivityRecord.query.filter_by(action='ACCOUNT_STATUS_CHANGED',target_type='user',target_id=user.id).first():raise AuthDenied('ACCESS_DENIED')

def begin(user,claims):
    p=policy();eligible(user)
    nonce=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
    key='beta_enrollment:'+user.id;row=db.session.get(AppSetting,key) or AppSetting(key=key)
    row.value={'nonceHash':hashlib.sha256(nonce.encode()).hexdigest(),'version':p['version'],'sessionVersion':user.session_version}
    db.session.add(row);db.session.commit()
    response=redirect('/api/auth/enrollment')
    response.set_cookie(COOKIE,signer().dumps({'uid':user.id,'nonce':nonce,'csrf':csrf,'sv':user.session_version,'profile':public_google_profile(claims)}),max_age=TTL,**SessionBoundary.cookie_attributes)
    return response

def notice_sections(notice):
    """Presentation only: retain every approved paragraph without rewriting policy."""
    headings=(
        ('지인 대상', '이용 대상과 서비스 소개'),
        ('Google 계정', '수집하는 정보와 이용 목적'),
        ('에세이는', '글·개인 자료의 보존과 삭제'),
        ('탈퇴 후', '탈퇴 기록과 보안 로그'),
        ('내려받은 PDF', 'PDF·백업 및 서비스 이용 제한'),
    )
    return [
        (next((title for prefix,title in headings if paragraph.startswith(prefix)), '개인정보 처리 안내'), paragraph)
        for paragraph in notice.splitlines() if paragraph.strip()
    ]


FORM='''<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>글빛 비공개 베타 가입</title><link rel="stylesheet" href="/auth-status.css?v=enrollment-sections-v1"></head>
<body><main class="enrollment-page">
<h1>글빛</h1><h2>비공개 베타 이용 안내</h2>
<p class="enrollment-intro">이용 전 개인정보 처리 안내를 확인해 주세요.<br>제목을 누르면 자세한 내용이 펼쳐집니다.</p>
<section class="privacy-sections" aria-label="개인정보 처리 안내">
{% for title, paragraph in sections %}
<details><summary>{{ title }}</summary><p class="privacy-section-content">{{ paragraph }}</p></details>
{% endfor %}
<details><summary>문의·동의 철회·삭제 요청</summary><p class="privacy-section-content">{{ contact }}</p></details>
</section>
<form class="enrollment-form" method="post" action="/api/auth/enrollment">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="policyVersion" value="{{ version }}">
<p><label><input type="checkbox" name="age14" value="yes" required> 만 14세 이상입니다.</label></p>
<p><label><input type="checkbox" name="privacyConsent" value="yes" required> 위 개인정보 처리 안내를 읽고 필수 처리에 동의합니다.</label></p>
<button type="submit">동의하고 내 서재 시작</button>
</form>
<p class="enrollment-note">동의하지 않으면 가입과 글 저장이 진행되지 않습니다. 외부 AI 전송 동의는 포함되지 않습니다.</p>
</main></body></html>'''

def enrollment():
    if current_app.config.get('BETA_SIGNUP_ENABLED') is not True:raise AuthDenied('PENDING_EXTERNAL')
    p=policy()
    try:ticket=signer().loads(request.cookies.get(COOKIE,''),max_age=TTL)
    except BadSignature:raise AuthDenied('ACCESS_DENIED')
    user=db.session.get(User,ticket.get('uid'));eligible(user)
    key='beta_enrollment:'+user.id;job=db.session.get(AppSetting,key)
    expected=hashlib.sha256(ticket.get('nonce','').encode()).hexdigest()
    if not job or not secrets.compare_digest(job.value.get('nonceHash',''),expected) or ticket.get('sv')!=user.session_version or job.value.get('sessionVersion')!=user.session_version or job.value.get('version')!=p['version']:
        raise AuthDenied('ACCESS_DENIED')
    if request.method=='GET':return render_template_string(FORM,sections=notice_sections(p['notice']),contact=p['contact'],csrf=ticket['csrf'],version=p['version'])
    if not secrets.compare_digest(request.form.get('csrf',''),ticket.get('csrf','')):raise AuthDenied('ACCESS_DENIED')
    if request.form.get('age14')!='yes' or request.form.get('privacyConsent')!='yes' or request.form.get('policyVersion')!=p['version']:raise AuthDenied('ACCESS_DENIED')
    # Short transaction CAS prevents parallel/replayed grants or revocation races.
    count=db.session.execute(text("UPDATE users SET status='ACTIVE', session_version=session_version+1 WHERE id=:id AND session_version=:sv AND status IN ('PENDING_APPROVAL','ACTIVE')"),{'id':user.id,'sv':ticket['sv']}).rowcount
    if count!=1:db.session.rollback();raise AuthDenied('ACCESS_DENIED')
    identifier=ticket['uid'];db.session.expire_all();user=db.session.get(User,identifier);eligible(user)
    job=db.session.get(AppSetting,key)
    if not job or not secrets.compare_digest(job.value.get('nonceHash',''),expected) or job.value.get('version')!=p['version']:
        db.session.rollback();raise AuthDenied('ACCESS_DENIED')
    if not consented(user):db.session.add(Consent(user_id=user.id,kind=KIND,policy_version=p['version'],granted_at=datetime.now(timezone.utc)))
    db.session.delete(db.session.get(AppSetting,key));db.session.commit()
    from .auth_api import boundary, COOKIE as SESSION_COOKIE
    from .common import principal
    cookie,_=boundary().issue(principal(user),profile=ticket.get('profile',{}))
    response=redirect('/');response.set_cookie(SESSION_COOKIE,cookie,max_age=boundary().max_age,**SessionBoundary.cookie_attributes)
    response.delete_cookie(COOKIE,**SessionBoundary.cookie_attributes);return response
