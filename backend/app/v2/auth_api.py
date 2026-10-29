import secrets
import threading
import time
import click
from flask import Blueprint, current_app, g, request, redirect, jsonify, abort, render_template_string
from ..extensions import db
from ..models import User, ActivityRecord
from ..utils import success, api_error, json_body
from components.auth import AuthDenied, SessionBoundary, public_google_profile
from .common import principal, admin_required

bp=Blueprint('v2_auth',__name__,url_prefix='/api')
COOKIE='geulbit_session'
CHALLENGE_COOKIE='geulbit_login'


def boundary():
    app=current_app
    if 'v2_session' not in app.extensions:
        app.extensions['v2_session']=SessionBoundary(app.config.get('SESSION_SIGNING_KEY'),max_age=app.config.get('SESSION_MAX_AGE'))
    return app.extensions['v2_session']


def install_auth(app):
    app.extensions['v2_challenges']={}
    app.extensions['v2_login_lock']=threading.Lock()

    @app.errorhandler(AuthDenied)
    def denied(error):
        # Whitelist public diagnostic codes; never provider details/tokens.
        code=str(error) if str(error) in {'PENDING_EXTERNAL','SESSION_CONFIGURATION_REQUIRED','STATE_INVALID','TOKEN_INVALID'} else 'ACCESS_DENIED'
        status=503 if code in {'PENDING_EXTERNAL','SESSION_CONFIGURATION_REQUIRED'} else (403 if getattr(g,'principal',None) else 401)
        return api_error(code,'인증 또는 권한을 확인해 주세요.',status)

    @app.before_request
    def authenticate_v2():
        if app.config.get('GOOGLE_LOGIN_ON_LANDING') is True and request.path=='/' and request.method in {'GET','HEAD'}:
            try:
                user=boundary().verify(request.cookies.get(COOKIE,''),load_user=lambda uid:principal(db.session.get(User,uid)),mutating=False)
                if app.config.get('BETA_SIGNUP_ENABLED') is True:
                    from .beta_signup import consented
                    if not consented(db.session.get(User,user.id)):raise AuthDenied('ACCESS_DENIED')
            except AuthDenied:
                return redirect('/api/auth/login')
        if not request.path.startswith('/api/') or request.path in {'/api/health','/api/auth/login','/api/auth/callback','/api/auth/enrollment'}:return
        g.principal=boundary().verify(request.cookies.get(COOKIE,''),load_user=lambda uid:principal(db.session.get(User,uid)),csrf=request.headers.get('X-CSRF-Token'),mutating=request.method not in {'GET','HEAD','OPTIONS'})
        if app.config.get('BETA_SIGNUP_ENABLED') is True:
            from .beta_signup import consented
            if not consented(db.session.get(User,g.principal.id)):raise AuthDenied('ACCESS_DENIED')

    @app.cli.command('bootstrap-admin')
    @click.option('--issuer',required=True)
    @click.option('--subject',required=True)
    @click.option('--confirm-account',required=True)
    def bootstrap_admin(issuer,subject,confirm_account):
        """Explicit operator account selection; never first-login promotion."""
        user=User.query.filter_by(oidc_issuer=issuer,oidc_subject=subject).one_or_none()
        from .privacy_lifecycle import withdrawn
        if not user or withdrawn(user.id) or not user.email_verified or user.email!=confirm_account or User.query.filter_by(role='ADMIN').first():
            raise click.ClickException('BOOTSTRAP_ACCOUNT_REQUIRED_OR_ALREADY_CONFIGURED')
        user.role='ADMIN';user.status='ACTIVE';user.session_version+=1
        db.session.add(ActivityRecord(action='BOOTSTRAP_ADMIN',target_type='user',target_id=user.id,details={}))
        db.session.commit();click.echo('ADMIN_BOOTSTRAP_COMPLETE')


@bp.get('/health')
def health():
    from sqlalchemy import text
    revision=db.session.execute(text('SELECT version_num FROM alembic_version')).scalar_one_or_none()
    flow=current_app.config.get('OIDC_FLOW')
    external='CONFIGURED_UNVERIFIED' if flow and getattr(flow,'external_approved',False) else 'PENDING_EXTERNAL'
    from ..storage import SCHEMA_HEAD
    return success({'status':'ok' if revision==SCHEMA_HEAD else 'blocked','database':'ok','schema':revision,'version':'2.0','externalAuthentication':external},status=200 if revision==SCHEMA_HEAD else 503)


@bp.get('/auth/login')
def login():
    boundary()  # refuse login before required signing/lifetime configuration
    flow=current_app.config.get('OIDC_FLOW')
    if not flow or (getattr(flow,'testing',False) and not current_app.testing):raise AuthDenied('PENDING_EXTERNAL')
    url,challenge=flow.begin(now=time.time());ticket=secrets.token_urlsafe(32)
    with current_app.extensions['v2_login_lock']:
        challenges=current_app.extensions['v2_challenges'];now=time.time()
        for key in list(challenges):
            if now-challenges[key].created>=flow.state_ttl:del challenges[key]
        if len(challenges)>=100:abort(429,description='API login capacity reached')
        challenges[ticket]=challenge
    response=redirect(url);response.set_cookie(CHALLENGE_COOKIE,ticket,max_age=flow.state_ttl,**SessionBoundary.cookie_attributes);return response


@bp.get('/auth/callback')
def callback():
    flow=current_app.config.get('OIDC_FLOW')
    if not flow or (getattr(flow,'testing',False) and not current_app.testing):raise AuthDenied('PENDING_EXTERNAL')
    with current_app.extensions['v2_login_lock']:
        challenge=current_app.extensions['v2_challenges'].pop(request.cookies.get(CHALLENGE_COOKIE,''),None)
    if not challenge:raise AuthDenied('STATE_INVALID')
    claims=flow.finish(challenge,state=request.args.get('state'),code=request.args.get('code'),now=time.time())
    isolated_account=current_app.config.get('ISOLATED_GOOGLE_ACCOUNT')
    if isolated_account and (claims.get('email')!=isolated_account or claims.get('emailVerified') is not True):
        raise AuthDenied('ACCESS_DENIED')
    user=User.query.filter_by(oidc_issuer='https://accounts.google.com',oidc_subject=claims['sub']).one_or_none()
    if not user:
        user=User(oidc_issuer='https://accounts.google.com',oidc_subject=claims['sub'])
        db.session.add(user)
    else:
        from .privacy_lifecycle import withdrawn
        if withdrawn(user.id):raise AuthDenied('ACCESS_DENIED')
    user.email=claims.get('email');user.email_verified=claims.get('emailVerified',False)
    db.session.commit()
    if current_app.config.get('BETA_SIGNUP_ENABLED') is True:
        from .beta_signup import consented, begin, eligible
        eligible(user)
        if not consented(user) or user.status=='PENDING_APPROVAL':
            response=begin(user,claims);response.delete_cookie(COOKIE,**SessionBoundary.cookie_attributes)
            response.delete_cookie(CHALLENGE_COOKIE,**SessionBoundary.cookie_attributes);return response
    if user.status!='ACTIVE':
        if request.accept_mimetypes.best == 'text/html':
            response=current_app.make_response(render_template_string('''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>글빛 계정 상태</title><link rel="stylesheet" href="/auth-status.css"><main><h1>글빛</h1><h2>{{ title }}</h2><p>{{ status }}</p><p>{{ message }}</p><a href="/api/auth/login">Google 로그인 다시 시도</a><a href="/">로그인 화면으로</a></main></html>''', title='관리자 승인 대기' if user.status=='PENDING_APPROVAL' else '계정 비활성화', status=user.status, message='로그인은 확인됐습니다. 관리자 승인 후 다시 로그인해 주세요.' if user.status=='PENDING_APPROVAL' else '관리자에게 계정 상태를 확인해 주세요.'))
        else:
            response=jsonify({'data':{'status':user.status}})
        response.delete_cookie(COOKIE,**SessionBoundary.cookie_attributes)
    else:
        cookie,csrf=boundary().issue(principal(user),profile=claims);response=redirect('/');response.set_cookie(COOKIE,cookie,max_age=boundary().max_age,**SessionBoundary.cookie_attributes)
    response.delete_cookie(CHALLENGE_COOKIE,**SessionBoundary.cookie_attributes);return response


@bp.get('/auth/session')
def session():
    signed=boundary().serializer.loads(request.cookies[COOKIE],max_age=boundary().max_age)
    user=db.session.get(User,g.principal.id)
    return success({'id':g.principal.id,'role':user.role,'status':user.status,'csrfToken':signed['csrf'], 'email':user.email, 'loginMethod':'Google OIDC', **public_google_profile(signed.get('profile',{}))})


@bp.route('/auth/enrollment',methods=['GET','POST'])
def enroll_beta():
    from .beta_signup import enrollment
    return enrollment()


@bp.post('/auth/logout')
def logout():
    user=db.session.get(User,g.principal.id);user.session_version+=1;db.session.commit()
    response=jsonify({'data':{'loggedOut':True}});response.delete_cookie(COOKIE,**SessionBoundary.cookie_attributes);return response


@bp.get('/admin/users')
def users():
    admin_required();return success([{'id':u.id,'status':u.status,'role':u.role} for u in User.query.all()])


@bp.patch('/admin/users/<uid>')
def update_user(uid):
    admin_required();data,error=json_body()
    if error:return error
    if set(data)-{'status'} or data.get('status') not in {'ACTIVE','INACTIVE','PENDING_APPROVAL'}:return api_error('VALIDATION_ERROR','계정 상태만 변경할 수 있습니다.')
    user=db.session.get(User,uid)
    if not user:abort(404,description='API resource unavailable')
    from .privacy_lifecycle import withdrawn
    if withdrawn(user.id):return api_error('ACCOUNT_WITHDRAWN','탈퇴한 계정은 이 경로에서 복구할 수 없습니다.',409)
    if user.id==g.principal.id:return api_error('INVALID_STATE','본인 계정은 이 경로에서 변경할 수 없습니다.',409)
    user.status=data['status'];user.session_version+=1
    if user.status=='INACTIVE':
        from .privacy_lifecycle import ledger
        ledger('user',user.id,sessionVersion=user.session_version)
    db.session.add(ActivityRecord(actor_id=g.principal.id,action='ACCOUNT_STATUS_CHANGED',target_type='user',target_id=uid,details={'status':user.status}));db.session.commit()
    return success({'id':user.id,'status':user.status})
