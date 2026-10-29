"""Offline, reproducible import. Never guess table meanings or execute PDF text."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

SOURCE_HASH = "c56cfbc534c6459f3d67af72cdb96fb150bd5bf002c753fd1ce25aea95b045c5"
LINKS = {"SPELLING-027": ["gb-local-002"], "SPELLING-042": ["gb-local-001", "gb-local-006", "gb-local-007", "gb-local-008"], "SPELLING-057": ["gb-local-005"]}


def canonical(value):
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sections(pages, first, last, pattern, expected):
    """Anchored headings only; inline citations are not new articles."""
    markers = []
    for number in range(first, last + 1):
        for match in re.finditer(pattern, pages[number - 1]["text"]):
            markers.append((int(match.group(1)), number, match.start()))
    if [m[0] for m in markers] != list(range(1, expected + 1)):
        raise ValueError("PROVISION_SEQUENCE_INVALID")
    result = {}
    for i, (article, page, start) in enumerate(markers):
        end_page, end_offset = (markers[i+1][1], markers[i+1][2]) if i+1 < len(markers) else (last, len(pages[last-1]["text"]))
        segments = []
        for n in range(page, end_page + 1):
            a = start if n == page else 0
            b = end_offset if n == end_page else len(pages[n-1]["text"])
            if b > a:
                text = pages[n-1]["text"][a:b]
                segments.append({"page": n, "start": a, "end": b, "textSha256": digest(text)})
        result[article] = segments
    return result


def build(path):
    import pymupdf  # Import tool only. Pure analysis never imports a PDF parser.
    if hashlib.sha256(path.read_bytes()).hexdigest() != SOURCE_HASH:
        raise ValueError("APPROVED_REFERENCE_HASH_MISMATCH")
    with pymupdf.open(path) as pdf:
        if len(pdf) != 314:
            raise ValueError("REFERENCE_PAGE_COUNT_INVALID")
        pages = []
        for i, page in enumerate(pdf):
            text = canonical(page.get_text())
            pages.append({"page": i+1, "text": text, "textSha256": digest(text),
                          "blank": not bool(text.strip()), "layoutVerified": False,
                          "sourcePart": "A" if 10 <= i+1 <= 49 else "B" if 50 <= i+1 <= 313 else "COMPILATION_GUIDANCE"})
    article = r"(?m)^제[ \t]*(\d+)[ \t]*항"
    standalone = article + r"[ \t]*$"
    spelling_a = sections(pages, 10, 33, article, 57)
    spelling_b = sections(pages, 62, 192, standalone, 57)
    groups = [("SPELLING", 57, spelling_a, spelling_b),
              ("PUNCTUATION", 21, sections(pages, 34, 49, r"(?m)^(\d{1,2})\.[ \t]*", 21), {}),
              ("STANDARD_WORD", 26, {}, sections(pages, 200, 264, standalone, 26)),
              ("PRONUNCIATION", 30, {}, sections(pages, 266, 313, standalone, 30))]
    provisions = []
    for group, count, a, b in groups:
        for number in range(1, count + 1):
            identifier = f"{group}-{number:03d}"
            segments = a.get(number, []) + b.get(number, [])
            markers = []
            for segment in segments:
                text = pages[segment["page"]-1]["text"][segment["start"]:segment["end"]]
                for match in re.finditer(r"\[붙임[^\]]*\]|다만|허용|예외|경우|복수 표준어", text):
                    markers.append({"page": segment["page"], "start": segment["start"]+match.start(), "end": segment["start"]+match.end(), "label": match.group()})
            rules = LINKS.get(identifier, [])
            provisions.append({"rule_id": identifier, "version": "geulbit.norms/1", "category": group,
                "article": number, "defaultReference": True, "sourceSegments": segments,
                "condition": {"kind": "SOURCE_PROVISION_WITH_FULL_CONTEXT", "interpretationVerified": False},
                "exception": {"mustPreserveFullProvision": True, "markers": markers},
                "positive_examples": [], "negative_examples": [], "exampleReview": "NOT_INFERRED_FROM_TABLE_COLUMNS",
                "execution": "BOUNDED_CANDIDATES" if rules else "REFERENCE_ONLY",
                "detectorRuleIds": rules, "autoApply": False,
                "known_false_positives": ["인용·고유 어휘", "허용 표기·문맥·발음 및 표의 열 관계를 확인해야 함"]})
    return {"schemaVersion": "geulbit.norms.catalogue/1", "version": "geulbit.norms/1",
            "normalizationVersion": "NFC_LF_PRESERVE_WHITESPACE/1", "sourceSha256": SOURCE_HASH,
            "pageCount": 314, "provisionCount": 134, "currentNormsChecked": False,
            "layoutWarning": "A extraction loses original spacing; tables are not erroneous/correct pairs. Use B explanations and original PDF for executable reviews.",
            "pages": pages, "provisions": provisions}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = build(args.source)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(json.dumps({"pages": 314, "provisions": 134, "bytes": len(encoded), "catalogueSha256": hashlib.sha256(encoded).hexdigest()}))
