import hashlib
from pathlib import Path
import pymupdf as fitz
import pytest
from backend.components.pdf import create_report, extract_preview, PdfRejected
from backend.components.auth import Principal, AuthDenied

USER=Principal("synthetic-user","synthetic-sub","USER","ACTIVE",1)
FONT=Path(__file__).resolve().parents[2]/"public/fonts/noto-sans-kr-regular.ttf"


def report(text="한글 😀 漢字와 특수 문자를 확인한다.", **changes):
    analysis={"input":{"versionId":"synthetic-v1","sha256":hashlib.sha256(text.encode()).hexdigest(),"codePoints":len(text)},
              "limitations":["후보는 확정적인 평가가 아닙니다."]}
    kwargs=dict(owner_id=USER.id,title="가상 글 분석 보고서",text=text,version_id="synthetic-v1",run_id="synthetic-run1",
                analysis=analysis,font_path=FONT,max_pages=100,max_bytes=20_000_000,expires_at=100,now=lambda:1)
    kwargs.update(changes)
    return create_report(USER,**kwargs)


def test_korean_unicode_report_extract_and_new_essay_preview():
    source="한글 😀 漢字와 특수 문자를 확인한다."
    data=report(source)
    preview=extract_preview(USER,data,max_bytes=20_000_000,max_pages=100)
    assert preview["text"]==source and preview["mustConfirm"]
    assert not preview["restoreAnalysis"] and not preview["restoreAccount"]
    with fitz.open(stream=data,filetype="pdf") as doc:
        text="".join(p.get_text() for p in doc)
        assert "한글" in text and "漢字" in text and "😀" in text
        assert "생각 메모" not in text


def test_pdf_visible_text_preserves_digit_ids_and_smiling_emoji():
    source = "한글 🙂😀 0123456789와 漢字를 확인한다."
    data = report(source, title="V2.1 보고서 0123456789")
    with fitz.open(stream=data, filetype="pdf") as doc:
        text = ''.join(page.get_text() for page in doc)
        assert source in text and "V2.1 보고서 0123456789" in text
        assert 'synthetic-v1' in text and 'synthetic-run1' in text
        assert '\x00' not in text and '\ufffd' not in text
        assert any('Noto Emoji' in font[3] for font in doc[0].get_fonts())
    assert extract_preview(USER, data, max_bytes=20_000_000, max_pages=100)['text'] == source


def test_long_pdf_last_paragraph_and_options():
    text="".join(f"{i}번째 가상 문단이다. 전체 본문을 보존한다.\n\n" for i in range(1000))
    data=report(text,include_ai=True,ai_questions=["근거를 확인할까요?"],thought_notes=["가상 생각 메모"])
    preview=extract_preview(USER,data,max_bytes=20_000_000,max_pages=100)
    assert preview["text"]==text and preview["pages"]>1
    with fitz.open(stream=data,filetype="pdf") as doc:
        extracted="".join(page.get_text() for page in doc)
        assert "999번째" in extracted and "가상 생각 메모" in extracted


@pytest.mark.parametrize("value", [b"not a pdf", b"%PDF-broken", b""])
def test_invalid_upload_is_not_success(value):
    with pytest.raises(PdfRejected):
        extract_preview(USER,value,max_bytes=1_000_000,max_pages=100)


def test_owner_version_limits_and_expiry_race():
    with pytest.raises(AuthDenied):report(owner_id="other-user")
    with pytest.raises(PdfRejected,match="MISMATCH"):report(version_id="wrong")
    with pytest.raises(PdfRejected,match="PAGE_LIMIT"):report("긴 글이다.\n"*3000,max_pages=1)
    clock=iter([1,1,101])
    with pytest.raises(AuthDenied):report(now=lambda:next(clock))


def test_scan_requires_ocr_and_encrypted_pdf_is_rejected():
    with fitz.open() as doc:
        doc.new_page()
        data=doc.tobytes()
        encrypted=doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw="synthetic-owner",user_pw="synthetic-user")
    with pytest.raises(PdfRejected,match="OCR_REQUIRED"):
        extract_preview(USER,data,max_bytes=1_000_000,max_pages=100)
    with pytest.raises(PdfRejected):
        extract_preview(USER,encrypted,max_bytes=1_000_000,max_pages=100)
