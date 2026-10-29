"""Selected-revision matching; no document store or persistent search index."""
from dataclasses import dataclass
import hashlib
import re
import unicodedata
from rapidfuzz import fuzz

from .auth import AuthDenied, require_active, require_private_owner


@dataclass(frozen=True)
class SelectedRevision:
    id: str
    document_id: str
    owner_id: str
    scope: str
    access_mode: str
    rights_confirmed: bool
    text: str


def _normalized(value):
    chars = [(i, c) for i, c in enumerate(value) if not c.isspace()]
    return "".join(c for _, c in chars), [i for i, _ in chars]


def require_revision_access(user, revision):
    require_active(user)
    if revision.scope == "PRIVATE":
        require_private_owner(user, revision.owner_id)
    elif revision.scope != "PUBLIC" or not revision.rights_confirmed:
        raise AuthDenied("RESOURCE_UNAVAILABLE")
    if revision.access_mode not in {"MATCH_ONLY", "VIEW", "DOWNLOAD"}:
        raise AuthDenied("RESOURCE_UNAVAILABLE")


def canonical_revision_text(revision):
    text = revision.text
    if text != unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")):
        raise ValueError("CANONICAL_REVISION_REQUIRED")
    return text


def match_quote(user, revision, quote, *, minimum_similarity, quoted=False):
    require_revision_access(user, revision)
    if (not revision.id or not revision.document_id or not isinstance(quote, str) or not quote
            or type(minimum_similarity) not in (int, float) or not 0 <= minimum_similarity <= 100):
        raise ValueError("MATCH_CONFIGURATION_REQUIRED")
    quote = unicodedata.normalize("NFC", quote.replace("\r\n", "\n").replace("\r", "\n"))
    text = canonical_revision_text(revision)
    result = {"revisionId": revision.id, "documentId": revision.document_id,
              "revisionHash": hashlib.sha256(text.encode()).hexdigest(), "status": "NOT_FOUND_IN_SELECTED_REVISION",
              "limitation": "선택한 판본의 탐색 결과이며 인용의 옳고 그름을 확정하지 않습니다."}
    if quoted and '~' in quote and not re.search(r'\d\s*~\s*\d',quote):
        parts=[p.strip() for p in quote.split('~')]
        if len(parts)>=2 and all(parts):
            cursor=0;segments=[];similar=False;all_present=True
            for part in parts:
                candidate=SelectedRevision(revision.id,revision.document_id,revision.owner_id,revision.scope,revision.access_mode,revision.rights_confirmed,text[cursor:])
                found=match_quote(user,candidate,part,minimum_similarity=minimum_similarity)
                if 'sourceSpan' not in found:
                    all_present=all_present and part in text
                    continue
                span={k:v+cursor for k,v in found['sourceSpan'].items()};cursor=span['end'];segments.append(span)
                similar=similar or found['status']=='SIMILAR_DIFFERENCE_CANDIDATE'
            if len(segments)==len(parts):result['status']='OMISSION_SIMILAR_CANDIDATE' if similar else 'OMISSION_MATCH'
            elif all_present:result['status']='OMISSION_ORDER_MISMATCH'
            else:result['status']='PARTIAL_OMISSION_CANDIDATE'
            result['sourceSpans']=segments;result['matchedSegments']=len(segments);result['totalSegments']=len(parts)
            return result
    start = text.find(quote)
    end, score = start+len(quote), 100
    if start >= 0:
        result["status"] = "EXACT_MATCH"
    else:
        normalized, mapping = _normalized(text)
        query, _ = _normalized(quote)
        if not query:
            raise ValueError("EMPTY_QUOTE")
        offset = normalized.find(query)
        if offset >= 0:
            start, end = mapping[offset], mapping[offset+len(query)-1]+1
            result["status"] = "NORMALIZED_MATCH"
        else:
            n = min(3, len(query))
            grams = {query[i:i+n] for i in range(len(query)-n+1)}
            # n-gram rejection before fuzzy matching. No unrelated edition substitution.
            if any(gram in normalized for gram in grams):
                alignment = fuzz.partial_ratio_alignment(query, normalized)
                if alignment and alignment.score >= minimum_similarity and alignment.dest_end > alignment.dest_start:
                    start, end, score = mapping[alignment.dest_start], mapping[alignment.dest_end-1]+1, alignment.score
                    result["status"] = "SIMILAR_DIFFERENCE_CANDIDATE"
    if result["status"] != "NOT_FOUND_IN_SELECTED_REVISION":
        result.update({"sourceSpan": {"start": start, "end": end}, "similarity": score})
        if revision.access_mode != "MATCH_ONLY":
            result["excerpt"] = text[start:end]
    return result
