from __future__ import annotations

from dataclasses import dataclass, asdict


OPEN_TO_CLOSE = {"\"": "\"", "'": "'", "“": "”", "‘": "’"}
CLOSE_TO_OPEN = {"”": "“", "’": "‘"}
QUOTE_TYPES = {
    "\"": "straight_double",
    "'": "straight_single",
    "“": "curly_double",
    "‘": "curly_single",
}


@dataclass(frozen=True)
class QuotationRange:
    text: str
    raw: str
    start: int
    end: int
    content_start: int
    content_end: int
    quote_type: str
    opener: str
    closer: str
    depth: int

    def to_dict(self) -> dict:
        data = asdict(self)
        return {
            "text": data["text"],
            "raw": data["raw"],
            "start": data["start"],
            "end": data["end"],
            "contentStart": data["content_start"],
            "contentEnd": data["content_end"],
            "quoteType": data["quote_type"],
            "opener": data["opener"],
            "closer": data["closer"],
            "depth": data["depth"],
        }


def extract_quotations(text: str) -> list[QuotationRange]:
    """네 가지 따옴표를 중첩 범위와 함께 찾는다.

    닫히지 않은 따옴표는 보호 범위로 확정하지 않는다. 작은따옴표가 단어 안의
    아포스트로피로 쓰인 경우도 인용문으로 오인하지 않도록 영문자 사이에서는
    건너뛴다.
    """

    stack: list[tuple[str, int, int]] = []
    found: list[QuotationRange] = []
    for index, char in enumerate(text or ""):
        if char == "'" and 0 < index < len(text) - 1:
            if text[index - 1].isascii() and text[index - 1].isalnum() and text[index + 1].isascii() and text[index + 1].isalnum():
                continue

        if char in CLOSE_TO_OPEN:
            opener = CLOSE_TO_OPEN[char]
            match_index = next((i for i in range(len(stack) - 1, -1, -1) if stack[i][0] == opener), None)
            if match_index is None:
                continue
            open_char, start, depth = stack.pop(match_index)
            found.append(_make_range(text, open_char, char, start, index, depth))
            continue

        if char in {'"', "'"}:
            if stack and stack[-1][0] == char:
                open_char, start, depth = stack.pop()
                found.append(_make_range(text, open_char, char, start, index, depth))
            else:
                stack.append((char, index, len(stack)))
            continue

        if char in {"“", "‘"}:
            stack.append((char, index, len(stack)))

    return sorted(found, key=lambda item: (item.start, -item.end))


def _make_range(text: str, opener: str, closer: str, start: int, close_index: int, depth: int) -> QuotationRange:
    return QuotationRange(
        text=text[start + 1 : close_index],
        raw=text[start : close_index + 1],
        start=start,
        end=close_index + 1,
        content_start=start + 1,
        content_end=close_index,
        quote_type=QUOTE_TYPES[opener],
        opener=opener,
        closer=closer,
        depth=depth,
    )


def containing_quotation(start: int, end: int, ranges: list[QuotationRange]) -> QuotationRange | None:
    return next((item for item in ranges if start >= item.content_start and end <= item.content_end), None)


def overlaps_quotation(start: int, end: int, ranges: list[QuotationRange]) -> bool:
    return any(start < item.end and end > item.start for item in ranges)

