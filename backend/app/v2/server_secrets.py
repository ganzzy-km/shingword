"""Server-only auth credentials from the existing DPAPI store; never generate."""
import os
from ..services.secrets_service import DpapiSecretStore


def load_auth_secrets(app):
    if app.testing:
        return  # Tests must supply their own explicit memory secrets/config.
    store = app.config.get('SECRET_STORE') or DpapiSecretStore(app.config['SECRET_FILE'])
    app.extensions['secret_store'] = store
    for config_key, secret_name in [
        ('SESSION_SIGNING_KEY', 'GEULBIT_SESSION_SIGNING_KEY'),
        ('GOOGLE_CLIENT_ID', 'GEULBIT_GOOGLE_CLIENT_ID'),
        ('GOOGLE_CLIENT_SECRET', 'GEULBIT_GOOGLE_CLIENT_SECRET'),
    ]:
        if not app.config.get(config_key):
            app.config[config_key] = os.getenv(secret_name) or store.get(secret_name)
