from __future__ import annotations

from dataclasses import dataclass, field


OPEN_TO_CLOSE = {'"': '"', "'": "'", '“': '”', '‘': '’'}
CLOSE_TO_OPEN = {'”': '“', '’': '‘'}
QUOTE_TYPES = {'"': 'straight_double', "'": 'straight_single', '“': 'curly_double', '‘': 'curly_single'}


@dataclass(frozen=True)
class QuotationRange:
    _source: str = field(repr=False, compare=False)
    start: int
    end: int
    content_start: int
    content_end: int
    quote_type: str
    opener: str
    closer: str
    depth: int
    quote_id: str
    parent_id: str | None
    status: str

    @property
    def text(self) -> str:
        return self._source[self.content_start:self.content_end]

    @property
    def raw(self) -> str:
        return self._source[self.start:self.end]

    def to_dict(self) -> dict:
        return {'text': self.text, 'raw': self.raw, 'start': self.start, 'end': self.end,
                'contentStart': self.content_start, 'contentEnd': self.content_end,
                'quoteType': self.quote_type, 'opener': self.opener, 'closer': self.closer,
                'depth': self.depth}

    def location(self) -> dict:
        return {'quote_id': self.quote_id, 'start': self.start, 'end': self.end,
                'content_start': self.content_start, 'content_end': self.content_end,
                'delimiter_type': self.quote_type, 'depth': self.depth,
                'parent_id': self.parent_id, 'status': self.status}


@dataclass
class _Opening:
    start: int
    delimiter: str
    depth: int
    parent_id: str | None
    slot: int
    ambiguous: bool = False
    crossed: bool = False


def _word(char: str) -> bool:
    return char.isascii() and char.isalnum()


def extract_quotations(text: str, *, include_unresolved: bool = False) -> list[QuotationRange]:
    """Scan Unicode code points once. Unresolved entries mark only their delimiter.

    Existing callers receive closed ranges in opening order. Text slices are lazy
    so deeply nested input does not allocate a copy of each enclosing range.
    """
    text = text or ''
    stack: list[_Opening] = []
    slots: list[QuotationRange | None] = []
    active: dict[str, list[_Opening]] = {char: [] for char in OPEN_TO_CLOSE}
    escaped = False

    def finish(opening, index, status, closer=''):
        closed = status == 'CLOSED'
        start = opening.start
        slots[opening.slot] = QuotationRange(
            text, start, index + 1 if closed else start + 1, start + 1,
            index if closed else start + 1, QUOTE_TYPES[opening.delimiter],
            opening.delimiter, closer, opening.depth, f'q{start}', opening.parent_id, status)

    def pop():
        opening = stack.pop()
        active[opening.delimiter].pop()
        return opening

    for index, char in enumerate(text):
        if char == '\\':
            escaped = not escaped
            continue
        if escaped:
            escaped = False
            continue
        if char not in OPEN_TO_CLOSE and char not in CLOSE_TO_OPEN:
            continue
        previous = text[index - 1] if index else ''
        following = text[index + 1] if index + 1 < len(text) else ''
        if char in {"'", '’'} and _word(previous) and _word(following):
            continue
        opener = CLOSE_TO_OPEN.get(char, char)
        straight = char in {'"', "'"}
        matching = active[opener]
        # An English trailing possessive outside a corresponding quotation.
        if char in {"'", '’'} and _word(previous) and not _word(following) and not matching:
            continue
        looks_open = (not previous or previous.isspace() or previous in '([{') and bool(following and not following.isspace())
        looks_closed = bool(previous and not previous.isspace()) and (not following or following.isspace() or not following.isalnum())
        # Straight marks have no direction. Prefer clear adjacency, and only
        # pair with the top frame. Same-kind nested openings stay unresolved.
        closing = char in CLOSE_TO_OPEN or (straight and bool(matching) and not looks_open)
        if closing:
            if matching and stack[-1] is matching[-1]:
                opening = pop()
                status = 'MISMATCHED' if opening.crossed else 'AMBIGUOUS' if opening.ambiguous else 'CLOSED'
                finish(opening, index, status, char)
            else:
                # A closer aimed below the top crosses every intervening
                # frame. Pop each once, keeping the scan linear.
                if matching:
                    target = matching[-1]
                    while stack[-1] is not target:
                        finish(pop(), index, 'MISMATCHED')
                    finish(pop(), index, 'MISMATCHED', char)
                elif stack:
                    stack[-1].crossed = True
                slots.append(QuotationRange(text, index, index + 1, index, index,
                    QUOTE_TYPES[opener], '', char, len(stack),
                    f'q{index}', f'q{stack[-1].start}' if stack else None, 'UNMATCHED_CLOSE'))
            continue
        if straight and not matching and looks_closed and not looks_open:
            slots.append(QuotationRange(text, index, index + 1, index, index,
                QUOTE_TYPES[opener], '', char, len(stack), f'q{index}',
                f'q{stack[-1].start}' if stack else None, 'UNMATCHED_CLOSE'))
            continue
        opening = _Opening(index, char, len(stack), f'q{stack[-1].start}' if stack else None,
                           len(slots), ambiguous=straight and bool(matching))
        if opening.ambiguous:
            matching[-1].ambiguous = True
        matching.append(opening)
        stack.append(opening)
        slots.append(None)

    while stack:
        opening = pop()
        status = 'MISMATCHED' if opening.crossed else 'AMBIGUOUS' if opening.ambiguous else 'UNCLOSED'
        finish(opening, opening.start, status)
    return [item for item in slots if item is not None and (include_unresolved or item.status == 'CLOSED')]


def containing_quotation(start: int, end: int, ranges: list[QuotationRange]) -> QuotationRange | None:
    return next((item for item in ranges if start >= item.content_start and end <= item.content_end), None)


def overlaps_quotation(start: int, end: int, ranges: list[QuotationRange]) -> bool:
    return any(start < item.end and end > item.start for item in ranges)
