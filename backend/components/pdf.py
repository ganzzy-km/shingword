"""Memory-only version-bound PDF processing; route integration remains gated."""
import hashlib
import html
import io
import json
import re
from pathlib import Path
import unicodedata

import pymupdf as fitz

from .auth import require_private_owner
from .lifecycle import guarded_output


class PdfRejected(ValueError):
    pass


def _canonical(text):
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _fix_unicode_maps(document, font_path, source, extra_fonts=()):
    """MuPDF-generated maps use scalar hex for astral characters, not UTF-16.

    Expand ranges before encoding; also resolve the supplied font's glyph aliases
    to characters actually present in this report (space and CJK compatibility).
    """
    preferred_by_font = {}
    for path in (font_path, *extra_fonts):
        font = fitz.Font(fontfile=str(path))
        preferred_by_font[re.sub(r"\W", "", font.name)] = {
            font.has_glyph(ord(c)): ord(c) for c in source if font.has_glyph(ord(c))
        }
    visited = set()
    for page in document:
        for info in page.get_fonts():
            font_xref = info[0]
            kind, ref = document.xref_get_key(font_xref, "ToUnicode")
            if kind != "xref":
                continue
            xref = int(ref.split()[0])
            if xref in visited:
                continue
            visited.add(xref)
            stream = document.xref_stream(xref).decode("ascii")
            mapping = {}
            for block in re.findall(r"beginbfrange(.*?)endbfrange", stream, re.S):
                for start, end, target in re.findall(r"<([0-9a-f]+)>\s*<([0-9a-f]+)>\s*<([0-9a-f]+)>", block, re.I):
                    for gid in range(int(start, 16), int(end, 16)+1):
                        mapping[gid] = int(target, 16) + gid - int(start, 16)
            for block in re.findall(r"beginbfchar(.*?)endbfchar", stream, re.S):
                for gid, target in re.findall(r"<([0-9a-f]+)>\s*<([0-9a-f]+)>", block, re.I):
                    mapping[int(gid, 16)] = int(target, 16)
            mapping.update(preferred_by_font.get(re.sub(r"\W", "", info[3]), {}))
            lines = [f"<{gid:04x}> <{chr(cp).encode('utf-16-be').hex()}>" for gid, cp in sorted(mapping.items()) if cp <= 0x10ffff and not 0xd800 <= cp <= 0xdfff]
            chunks = [f"{len(lines[i:i+100])} beginbfchar\n" + "\n".join(lines[i:i+100]) + "\nendbfchar" for i in range(0, len(lines), 100)]
            cmap = "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /GeulbitUnicode def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <ffff>\nendcodespacerange\n" + "\n".join(chunks) + "\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend"
            document.update_stream(xref, cmap.encode("ascii"))


def create_report(user, *, owner_id, title, text, version_id, run_id, analysis,
                  font_path, max_pages, max_bytes, expires_at, now,
                  include_ai=False, ai_questions=(), thought_notes=(), inquiry_question=""):
    require_private_owner(user, owner_id, expires_at=expires_at, now=now())
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    if text != _canonical(text) or not version_id or not run_id or analysis.get("input") != {"versionId": version_id, "sha256": source_hash, "codePoints": len(text)}:
        raise PdfRejected("VERSION_RUN_MISMATCH")
    if not isinstance(max_pages, int) or max_pages < 1 or not isinstance(max_bytes, int) or max_bytes < 1:
        raise PdfRejected("PDF_LIMIT_CONFIGURATION_REQUIRED")
    font_path = Path(font_path).resolve()
    if not font_path.is_file():
        raise PdfRejected("KOREAN_FONT_REQUIRED")

    def produce():
        manifest = {"schemaVersion": "geulbit.pdf/1", "title": title, "text": text,
                    "sha256": source_hash, "versionId": version_id, "runId": run_id}
        # Copy only presentable sections, never runtime paths, user identity or arbitrary manifest JSON.
        paragraphs = [title]
        if inquiry_question:
            paragraphs.append(f"탐구질문: {inquiry_question}")
        paragraphs.extend([f"분석 버전: {version_id} / 실행: {run_id}", "작성한 본문", text, "분석의 한계"])
        paragraphs.extend(analysis.get("limitations", []))
        for finding in analysis.get("findings", []):
            paragraphs.append(f"{finding.get('tier', '확인 필요')}: {finding.get('reason', '')}")
            source = finding.get("source")
            if isinstance(source, str):
                paragraphs.append(source)
        if include_ai:
            paragraphs += ["선택한 AI 질문 및 생각 메모", *ai_questions, *thought_notes]
        emoji_path = font_path.parent / 'noto-emoji.ttf'
        def present(value):
            # Latin runs use the built-in sans face: KR shaping may substitute
            # digit glyphs whose generated ToUnicode aliases are CJK characters.
            pieces = re.split(r'([\x20-\x7e]+|[\U0001f000-\U0001faff\u200d\ufe0f]+)', str(value))
            rendered = []
            for piece in pieces:
                escaped = html.escape(piece).replace('\n', '<br/>')
                if piece and all(0x20 <= ord(c) <= 0x7e for c in piece):
                    escaped = '<span style="font-family:sans-serif">' + escaped + '</span>'
                elif piece and emoji_path.is_file() and any(0x1f000 <= ord(c) <= 0x1faff for c in piece):
                    escaped = '<span style="font-family:GeulbitEmoji">' + escaped + '</span>'
                rendered.append(escaped)
            return ''.join(rendered)
        content = ''.join('<p>' + present(p) + '</p>' for p in paragraphs)
        css = f"@font-face{{font-family:Geulbit;src:url('{font_path.name}');}} body{{font-family:Geulbit;font-size:11pt;line-height:1.65;}} p{{margin:0 0 12pt;}}"
        if emoji_path.is_file():
            css += f"@font-face{{font-family:GeulbitEmoji;src:url('{emoji_path.name}');}}"
        story = fitz.Story(html=content, user_css=css, archive=fitz.Archive(str(font_path.parent)))
        buffer = io.BytesIO()
        writer = fitz.DocumentWriter(buffer)
        try:
            more, pages = True, 0
            while more:
                if pages >= max_pages:
                    raise PdfRejected("PDF_PAGE_LIMIT")
                device = writer.begin_page(fitz.Rect(0, 0, 595, 842))
                more, _filled = story.place(fitz.Rect(48, 48, 547, 794))
                story.draw(device)
                writer.end_page()
                pages += 1
        finally:
            writer.close()
        with fitz.open(stream=buffer.getvalue(), filetype="pdf") as document:
            _fix_unicode_maps(document, font_path, "\n".join(map(str, paragraphs)), (emoji_path,) if emoji_path.is_file() else ())
            # Import is a new, confirmed essay, never account/version restoration.
            document.embfile_add("geulbit-source.json", json.dumps(manifest, ensure_ascii=False).encode(), filename="geulbit-source.json")
            document.set_metadata({"title": str(title), "creator": "Geulbit", "producer": "Geulbit"})
            result = document.tobytes(garbage=4, deflate=True)
        if len(result) > max_bytes:
            raise PdfRejected("PDF_SIZE_LIMIT")
        return result

    return guarded_output(user, owner_id=owner_id, expires_at=expires_at, now=now, producer=produce)


def extract_preview(user, data, *, max_bytes, max_pages):
    require_private_owner(user, user.id)
    if type(max_bytes) is not int or type(max_pages) is not int or max_bytes < 1 or max_pages < 1:
        raise PdfRejected("PDF_LIMIT_CONFIGURATION_REQUIRED")
    if not isinstance(data, bytes) or len(data) > max_bytes or not data.startswith(b"%PDF-"):
        raise PdfRejected("PDF_TYPE_OR_SIZE_INVALID")
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            if not document.is_pdf or document.needs_pass or document.is_repaired or not 0 < document.page_count <= max_pages:
                raise PdfRejected("PDF_ENCRYPTED_DAMAGED_OR_PAGE_LIMIT")
            if document.get_js() if hasattr(document, "get_js") else False:
                raise PdfRejected("PDF_ACTIVE_CONTENT")
            # PyMuPDF does not execute actions. Never expose embedded arbitrary files or paths.
            names = document.embfile_names()
            text = "\n".join(page.get_text(sort=True) for page in document)
            title, kind = "", "UNCLASSIFIED_TEXT_PDF"
            if "geulbit-source.json" in names:
                info = document.embfile_info("geulbit-source.json")
                if info["size"] > max_bytes:
                    raise PdfRejected("PDF_EMBEDDED_SIZE_LIMIT")
                candidate = json.loads(document.embfile_get("geulbit-source.json"))
                body = candidate.get("text")
                if (candidate.get("schemaVersion") != "geulbit.pdf/1" or not isinstance(body, str)
                        or hashlib.sha256(body.encode()).hexdigest() != candidate.get("sha256")):
                    raise PdfRejected("PDF_SOURCE_MANIFEST_INVALID")
                text, title, kind = body, str(candidate.get("title", "")), "IMPORTED_REPORT_UNTRUSTED"
            if not text.strip():
                raise PdfRejected("OCR_REQUIRED_NOT_SUPPORTED")
            return {"text": _canonical(text), "title": title, "kind": kind,
                    "mustConfirm": True, "restoreAnalysis": False, "restoreAccount": False,
                    "ownerId": user.id, "pages": document.page_count}
    except PdfRejected:
        raise
    except Exception:
        raise PdfRejected("PDF_INVALID") from None
