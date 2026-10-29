import time
from datetime import timezone
from flask import g, abort
from ..models import User, Writing
from ..extensions import db
from components.auth import Principal, AuthDenied, require_private_owner


def principal(user):
    return Principal(user.id,user.oidc_subject,user.role,user.status,user.session_version,user.email or '',bool(user.email_verified)) if user else None


def owned_writing(identifier):
    item=db.session.get(Writing,identifier)
    expires=item.expires_at.replace(tzinfo=timezone.utc).timestamp() if item and item.expires_at else None
    try:require_private_owner(g.principal,item.owner_id if item else None,expires_at=expires,now=time.time())
    except AuthDenied:abort(404,description='API resource unavailable')
    return item


def admin_required():
    if g.principal.role!='ADMIN':abort(403,description='API administrator required')


def iso(value):
    if value is None:return None
    # SQLite strips tzinfo from new UTC timestamps; make the API offset explicit.
    if getattr(value,'tzinfo',False) is None:value=value.replace(tzinfo=timezone.utc)
    return value.isoformat()
