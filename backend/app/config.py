import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


class Config:
    APP_VERSION = "1"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
    # Production paths are bound only after verified storage validation.
    DATA_ROOT = os.getenv("GEULBIT_DATA_ROOT")
    VOLUME_ID = os.getenv("GEULBIT_VOLUME_ID")
    DATABASE_PATH = None
    SQLALCHEMY_DATABASE_URI = None
    UPLOAD_FOLDER = None
    BACKUP_FOLDER = None
    TEMP_FOLDER = None
    FRONTEND_DIST = (PROJECT_ROOT / "dist").resolve()
    OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "kor+eng")
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")
    OCR_MAX_PAGES = int(os.getenv("OCR_MAX_PAGES", "100"))
    OCR_MAX_IMAGE_PIXELS = int(os.getenv("OCR_MAX_IMAGE_PIXELS", "40000000"))
    OCR_DPI = int(os.getenv("OCR_DPI", "300"))
    OCR_PAGE_TIMEOUT_SECONDS = int(os.getenv("OCR_PAGE_TIMEOUT_SECONDS", "30"))
    OCR_TOTAL_TIMEOUT_SECONDS = int(os.getenv("OCR_TOTAL_TIMEOUT_SECONDS", "180"))
    SECRET_FILE = None
    ADMIN_STATE_FILE = None
    ADMIN_AUDIT_FILE = None
    TESTING = False


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
