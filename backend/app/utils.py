from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
import zipfile
from pathlib import Path

from flask import current_app, jsonify, request
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "txt", "docx"}
MIME_PREFIXES = {
    "pdf": b"%PDF",
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "docx": b"PK\x03\x04",
}
CANONICAL_MIME_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def success(data=None, message=None, status=200, pagination=None):
    payload = {"data": data}
    if message:
        payload["message"] = message
    if pagination:
        payload["pagination"] = pagination
    return jsonify(payload), status


def api_error(code, message, status=400, fields=None):
    return jsonify({"error": {"code": code, "message": message, "fields": fields or {}}}), status


def json_body():
    if not request.is_json:
        return None, api_error("INVALID_CONTENT_TYPE", "JSON 요청이 필요합니다.", 415)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return None, api_error("VALIDATION_ERROR", "JSON 객체를 입력해 주세요.")
    return value, None


def clamp_int(value, default, minimum=1, maximum=100):
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def pagination_args():
    return clamp_int(request.args.get("page"), 1), clamp_int(request.args.get("pageSize"), 20)


def paginate(query, serializer):
    page, page_size = pagination_args()
    result = query.paginate(page=page, per_page=page_size, error_out=False)
    return success(
        [serializer(item) for item in result.items],
        pagination={"page": page, "pageSize": page_size, "total": result.total},
    )


def validate_length(data, fields):
    errors = {}
    for name, limit in fields.items():
        value = data.get(name)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            errors[name] = f"{limit}자 이하의 문자열이어야 합니다."
    return errors


def save_upload(file_storage):
    raw_name = unicodedata.normalize("NFC", str(file_storage.filename or ""))
    original = Path(raw_name.replace("\\", "/")).name.strip()
    original = "".join(character for character in original if character.isprintable())[:255]
    if not original or original in {".", ".."}:
        raise ValueError("파일 이름이 없습니다.")
    extension = Path(original).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("지원하지 않는 파일 형식입니다.")

    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    expected = MIME_PREFIXES.get(extension)
    if expected and not header.startswith(expected):
        raise ValueError("파일 내용과 확장자가 일치하지 않습니다.")

    stored_name = f"{uuid.uuid4()}.{extension}"
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    upload_root.mkdir(parents=True, exist_ok=True)
    target = (upload_root / stored_name).resolve()
    if target.parent != upload_root.resolve():
        raise ValueError("안전하지 않은 파일 경로입니다.")
    file_storage.save(target)
    try:
        if extension == "pdf":
            import fitz

            with fitz.open(target) as document:
                if document.needs_pass:
                    raise ValueError("암호로 보호된 PDF는 업로드할 수 없습니다.")
                if document.page_count == 0:
                    raise ValueError("페이지가 없는 PDF는 업로드할 수 없습니다.")
                maximum_pages = int(current_app.config.get("OCR_MAX_PAGES", 100))
                if document.page_count > maximum_pages:
                    raise ValueError(f"PDF는 최대 {maximum_pages}페이지까지 업로드할 수 있습니다.")
        elif extension in {"png", "jpg", "jpeg"}:
            from PIL import Image

            with Image.open(target) as image:
                image.verify()
            with Image.open(target) as image:
                maximum_pixels = int(current_app.config.get("OCR_MAX_IMAGE_PIXELS", 40_000_000))
                if image.width * image.height > maximum_pixels:
                    raise ValueError("이미지의 전체 픽셀 수가 허용 범위를 초과합니다.")
        elif extension == "docx":
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ValueError("파일 내용과 DOCX 형식이 일치하지 않습니다.")
        elif extension == "txt":
            with target.open("rb") as stream:
                header = stream.read(8192)
            if b"\x00" in header:
                raise ValueError("텍스트 파일 형식이 아닙니다.")
    except ValueError:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise ValueError("파일이 손상되었거나 지원하는 형식이 아닙니다.") from exc
    mime = CANONICAL_MIME_TYPES[extension]
    return {
        "original_name": original,
        "stored_name": stored_name,
        "mime_type": mime,
        "size": target.stat().st_size,
        "path": target,
    }


def resolve_upload(stored_name):
    if not re.fullmatch(r"[0-9a-f-]{36}\.[a-z0-9]+", stored_name):
        return None
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    target = (root / stored_name).resolve()
    return target if target.parent == root and target.is_file() else None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso(value):
    return value.isoformat() if value else None
