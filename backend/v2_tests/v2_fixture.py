import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]))
from app import create_app
from app.extensions import db
from app.models import User
from app.services.secrets_service import MemorySecretStore
from app.v2.auth_api import boundary
from app.v2.common import principal


@pytest.fixture
def v2app(tmp_path):
    app=create_app({'TESTING':True,'GEULBIT_V2':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'isolated.sqlite3'),'DATABASE_PATH':tmp_path/'isolated.sqlite3','UPLOAD_FOLDER':tmp_path/'files','BACKUP_FOLDER':tmp_path/'backups','TEMP_FOLDER':tmp_path/'temp','FRONTEND_DIST':tmp_path/'dist','SECRET_STORE':MemorySecretStore(),'ADMIN_STATE_FILE':tmp_path/'admin.json','ADMIN_AUDIT_FILE':tmp_path/'audit.jsonl','SESSION_SIGNING_KEY':'synthetic-test-only-signing-key-000000000000','SESSION_MAX_AGE':3600})
    yield app
    with app.app_context():db.session.remove();db.engine.dispose()


def user_client(app,subject='synthetic-user',role='USER',email='',verified=False):
    with app.app_context():
        user=User.query.filter_by(oidc_subject=subject).one_or_none()
        if not user:
            user=User(oidc_issuer='https://accounts.google.com',oidc_subject=subject,status='ACTIVE',role=role,email=email,email_verified=verified);db.session.add(user);db.session.commit()
        identifier=user.id;cookie,csrf=boundary().issue(principal(user))
    client=app.test_client();client.set_cookie('geulbit_session',cookie)
    return client,{'X-CSRF-Token':csrf},identifier
