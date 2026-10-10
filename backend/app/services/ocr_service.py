from __future__ import annotations

import importlib.util
import math
import os
import shutil
import subprocess
import time
from pathlib import Path


OCR_STATUS_MESSAGES = {
    "not_required": "문서의 원문 텍스트를 추출했습니다. OCR이 필요하지 않습니다.",
    "completed": "OCR이 완료되었습니다. 추출 결과를 확인해 주세요.",
    "partial": "이 파일의 일부 페이지만 처리되었습니다. 결과를 확인해 주세요.",
    "unavailable": "서버에 한글 OCR 환경이 설치되어 있지 않습니다. 다른 기능은 계속 사용할 수 있습니다.",
    "failed": "문서에서 글자를 추출하지 못했습니다. 파일을 확인한 뒤 다시 시도해 주세요.",
}


class OcrFileError(ValueError):
    """A safe, user-facing document processing error."""


def _resolve_tesseract_command(configured_command: str | None = None) -> str | None:
    candidate = (configured_command or os.getenv("TESSERACT_CMD", "")).strip()
    if candidate:
        expanded = Path(os.path.expandvars(os.path.expanduser(candidate)))
        if expanded.is_file():
            return str(expanded.resolve())
        return shutil.which(candidate)
    return shutil.which("tesseract")


def _run_diagnostic_command(command: str, *arguments: str):
    return subprocess.run(
        [command, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        shell=False,
        env=os.environ.copy(),
    )


def diagnose_ocr(
    configured_command: str | None = None,
    required_languages: tuple[str, ...] = ("kor", "eng"),
):
    """Return a path-free OCR readiness report safe for the normal API."""

    if importlib.util.find_spec("fitz") is None:
        return {
            "status": "pymupdf_missing",
            "ready": False,
            "languages": [],
            "message": "서버에 PDF 처리 모듈이 설치되어 있지 않습니다.",
        }
    command = _resolve_tesseract_command(configured_command)
    if not command:
        return {
            "status": "executable_missing",
            "ready": False,
            "languages": [],
            "message": OCR_STATUS_MESSAGES["unavailable"],
        }
    try:
        version = _run_diagnostic_command(command, "--version")
        if version.returncode != 0:
            return {
                "status": "executable_failed",
                "ready": False,
                "languages": [],
                "message": "OCR 실행 프로그램을 시작하지 못했습니다. 서버 설정을 확인해 주세요.",
            }
        listed = _run_diagnostic_command(command, "--list-langs")
    except (OSError, subprocess.SubprocessError):
        return {
            "status": "executable_failed",
            "ready": False,
            "languages": [],
            "message": "OCR 실행 프로그램을 시작하지 못했습니다. 서버 설정을 확인해 주세요.",
        }
    if listed.returncode != 0:
        return {
            "status": "tessdata_error",
            "ready": False,
            "languages": [],
            "message": "OCR 언어 데이터 위치를 확인하지 못했습니다. 서버 설정을 확인해 주세요.",
        }
    languages = sorted(
        line.strip()
        for line in listed.stdout.splitlines()
        if line.strip() and not line.lower().startswith("list of available languages")
    )
    missing = [language for language in required_languages if language not in languages]
    if missing:
        label = ", ".join(missing)
        return {
            "status": f"{missing[0]}_missing",
            "ready": False,
            "languages": languages,
            "missingLanguages": missing,
            "message": f"서버 OCR에 {label} 언어 데이터가 없습니다.",
        }
    return {
        "status": "ready",
        "ready": True,
        "languages": languages,
        "message": "OCR 실행 환경이 준비되었습니다.",
    }


def _meaningful_native_text(text: str):
    clean = "".join(character for character in text if not character.isspace())
    if not clean:
        return False
    replacement_ratio = (clean.count("�") + clean.count("□")) / len(clean)
    meaningful = sum(character.isalnum() or "가" <= character <= "힣" for character in clean)
    return replacement_ratio < 0.2 and (meaningful >= 10 or len(text.split()) >= 3)


def _text_and_confidence(data):
    lines: list[str] = []
    current_key = None
    current_words: list[str] = []
    confidences: list[float] = []
    count = len(data.get("text", []))
    for index in range(count):
        word = str(data["text"][index]).strip()
        if not word:
            continue
        key = tuple(
            data.get(name, [0] * count)[index]
            for name in ("block_num", "par_num", "line_num")
        )
        if current_key is not None and key != current_key and current_words:
            lines.append(" ".join(current_words))
            current_words = []
        current_key = key
        current_words.append(word)
        try:
            confidence = float(data.get("conf", ["-1"] * count)[index])
            if confidence >= 0:
                confidences.append(confidence)
        except (TypeError, ValueError):
            pass
    if current_words:
        lines.append(" ".join(current_words))
    text = "\n".join(lines).strip()
    confidence = sum(confidences) / len(confidences) if confidences else None
    return text, confidence


def _prepare_image(image, maximum_pixels: int):
    from PIL import ImageOps

    prepared = ImageOps.exif_transpose(image)
    if prepared.width * prepared.height > maximum_pixels:
        raise OcrFileError("이미지의 전체 픽셀 수가 허용 범위를 초과합니다.")
    grayscale = prepared.convert("L")
    low, high = grayscale.getextrema()
    return ImageOps.autocontrast(grayscale) if high - low < 80 else grayscale


def _ocr_image(
    image,
    language: str,
    command: str,
    maximum_pixels: int,
    timeout_seconds: int,
):
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = command
    prepared = _prepare_image(image, maximum_pixels)
    data = pytesseract.image_to_data(
        prepared,
        lang=language,
        output_type=pytesseract.Output.DICT,
        timeout=timeout_seconds,
        config="--oem 1 --psm 3",
    )
    return _text_and_confidence(data)


def _finalize_result(pages):
    successful = [page for page in pages if page["status"] in {"not_required", "completed"}]
    unavailable = [page for page in pages if page["status"] == "unavailable"]
    failed = [page for page in pages if page["status"] == "failed"]
    used_ocr = any(page["method"] == "ocr" for page in pages)
    if successful and (unavailable or failed):
        status = "partial"
    elif unavailable and not successful:
        status = "unavailable"
    elif failed and not successful:
        status = "failed"
    elif used_ocr:
        status = "completed"
    else:
        status = "not_required"
    return {
        "status": status,
        "pages": pages,
        "warning": OCR_STATUS_MESSAGES[status] if status in {"partial", "unavailable", "failed"} else None,
        "message": OCR_STATUS_MESSAGES[status],
    }


def _render_page(page, dpi: int, maximum_pixels: int):
    import fitz
    from PIL import Image

    scale = dpi / 72
    estimated_pixels = page.rect.width * scale * page.rect.height * scale
    if estimated_pixels > maximum_pixels:
        scale *= math.sqrt(maximum_pixels / estimated_pixels)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def extract_pages(
    path: Path,
    extension: str,
    language: str = "kor+eng",
    *,
    configured_command: str | None = None,
    maximum_pages: int = 100,
    maximum_pixels: int = 40_000_000,
    dpi: int = 300,
    timeout_seconds: int = 30,
    total_timeout_seconds: int = 180,
):
    """Extract native text per page and OCR only pages that need it."""

    extension = extension.lower()
    started = time.monotonic()
    if extension == ".txt":
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        return _finalize_result(
            [{"page": 1, "text": text, "confidence": None, "method": "native_text", "status": "not_required"}]
        )

    if extension == ".docx":
        from docx import Document

        text = "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
        return _finalize_result(
            [{"page": 1, "text": text, "confidence": None, "method": "native_text", "status": "not_required"}]
        )

    diagnostic = diagnose_ocr(configured_command, tuple(language.split("+")))
    command = _resolve_tesseract_command(configured_command) if diagnostic["ready"] else None

    if extension == ".pdf":
        import fitz

        pages = []
        try:
            document = fitz.open(path)
        except Exception as exc:
            raise OcrFileError("PDF 파일이 손상되었거나 열 수 없습니다.") from exc
        with document:
            if document.needs_pass:
                raise OcrFileError("암호로 보호된 PDF는 처리할 수 없습니다.")
            if document.page_count == 0:
                raise OcrFileError("페이지가 없는 PDF는 처리할 수 없습니다.")
            if document.page_count > maximum_pages:
                raise OcrFileError(f"PDF는 최대 {maximum_pages}페이지까지 처리할 수 있습니다.")
            for index, page in enumerate(document):
                blocks = page.get_text("blocks", sort=True)
                native_text = "\n".join(str(block[4]).strip() for block in blocks if str(block[4]).strip()).strip()
                if _meaningful_native_text(native_text):
                    pages.append({"page": index + 1, "text": native_text, "confidence": None, "method": "native_text", "status": "not_required"})
                    continue
                if not command:
                    pages.append({"page": index + 1, "text": native_text or None, "confidence": None, "method": "unavailable", "status": "unavailable"})
                    continue
                if time.monotonic() - started >= total_timeout_seconds:
                    pages.append({"page": index + 1, "text": None, "confidence": None, "method": "failed", "status": "failed"})
                    continue
                try:
                    image = _render_page(page, dpi, maximum_pixels)
                    try:
                        text, confidence = _ocr_image(image, language, command, maximum_pixels, timeout_seconds)
                    finally:
                        image.close()
                    pages.append({"page": index + 1, "text": text or None, "confidence": confidence, "method": "ocr", "status": "completed" if text else "failed"})
                except Exception:
                    pages.append({"page": index + 1, "text": None, "confidence": None, "method": "failed", "status": "failed"})
        return _finalize_result(pages)

    if extension in {".png", ".jpg", ".jpeg"}:
        if not command:
            return _finalize_result(
                [{"page": 1, "text": None, "confidence": None, "method": "unavailable", "status": "unavailable"}]
            )
        from PIL import Image

        try:
            with Image.open(path) as image:
                text, confidence = _ocr_image(image, language, command, maximum_pixels, timeout_seconds)
            return _finalize_result(
                [{"page": 1, "text": text or None, "confidence": confidence, "method": "ocr", "status": "completed" if text else "failed"}]
            )
        except OcrFileError:
            raise
        except Exception:
            return _finalize_result(
                [{"page": 1, "text": None, "confidence": None, "method": "failed", "status": "failed"}]
            )

    raise OcrFileError("지원하지 않는 문서 형식입니다.")
