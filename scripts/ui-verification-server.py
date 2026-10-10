"""Local verification server; synthetic essays stay outside the user's database."""
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app import create_app
from app.services.secrets_service import MemorySecretStore
folder = root / ".tmp-ui-verification"
folder.mkdir(exist_ok=True)
app = create_app({
    "TESTING": True,
    "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(folder / 'test.db').as_posix()}",
    "DATABASE_PATH": folder / "test.db",
    "UPLOAD_FOLDER": folder / "uploads",
    "BACKUP_FOLDER": folder / "backups",
    "SECRET_STORE": MemorySecretStore(),
})
app.run(host="127.0.0.1", port=5055, threaded=True)
