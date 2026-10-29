"""Validated PDF/text input; inert extraction, no OCR or external services."""
import re
import fitz
from ..analysis.snapshot import normalize_text


def extract_file(data,filename,*,max_bytes,max_pages):
    if not data or len(data)>max_bytes:raise ValueError('FILE_LIMIT')
    extension=filename.rsplit('.',1)[-1].lower() if '.' in filename else ''
    if extension=='txt':
        text=normalize_text(data.decode('utf-8-sig'))
        if any(ord(c)<32 and c not in '\n\t' for c in text):raise ValueError('INVALID_TEXT')
        return text,'text/plain',1
    if extension!='pdf' or not data.startswith(b'%PDF-'):raise ValueError('FILE_TYPE')
    with fitz.open(stream=data,filetype='pdf') as document:
        if document.needs_pass or document.is_repaired or not 0<document.page_count<=max_pages or document.xref_length()>100000:raise ValueError('UNSUPPORTED_PDF')
        for xref in range(1,document.xref_length()):
            if re.search(r'/(?:JavaScript|JS|Launch|EmbeddedFile|OpenAction|AA)\b',document.xref_object(xref)):raise ValueError('ACTIVE_PDF_CONTENT')
        text=normalize_text('\n\n'.join(page.get_text() for page in document))
        if len(text.encode())>max_bytes:raise ValueError('EXTRACTED_TEXT_LIMIT')
        if not text.strip():raise ValueError('OCR_REQUIRED')
        return text,'application/pdf',document.page_count
