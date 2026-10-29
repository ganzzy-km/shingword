"""Pure entry point for the existing analysis package (PYTHONPATH=backend/app).

No Flask, persistence, network or AI imports. Coordinates address the canonical
NFC/LF input, which the calling version service must persist before analysis.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import unicodedata

from .engine import split_sentences
from .morphology import analyze_morphology, kiwi_available
from .quotation import extract_quotations

SCHEMA_VERSION = "geulbit.analysis.snapshot/2"
LEGACY_SCHEMA_VERSION = "geulbit.analysis.snapshot/1"
NORMALIZATION_VERSION = "NFC_LF/1"
ENGINE_VERSION = "2.0-candidate.1"


class AnalysisUnavailable(RuntimeError):
    pass


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("TEXT_REQUIRED")
    result = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    try:
        result.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("INVALID_UNICODE") from None
    return result


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_manifest() -> dict:
    directory = Path(__file__).parent
    sources = {p.name: _hash(p.read_bytes()) for p in sorted(directory.glob("*.py"))}
    return {"engineVersion": ENGINE_VERSION, "engineHash": _hash(json.dumps(sources, sort_keys=True).encode()),
            "normalizationVersion": NORMALIZATION_VERSION,
            "analyzer": "kiwi", "analyzerVersion": importlib.metadata.version("kiwipiepy"),
            "configuration": {"modelType": "cong", "numWorkers": -1, "topN": 3},
            "rulesetVersion": "not-applied", "offsetUnit": "unicode-code-point",
            "interval": "start-inclusive-end-exclusive"}


def _partitions(text: str) -> list[dict]:
    """Contiguous source partitions, including blank-line separators."""
    result, cursor = [], 0
    for match in re.finditer(r"\n[ \t]*\n", text):
        if cursor < match.start():
            result.append({"kind": "paragraph", "start": cursor, "end": match.start()})
        result.append({"kind": "separator", "start": match.start(), "end": match.end()})
        cursor = match.end()
    if cursor < len(text):
        result.append({"kind": "paragraph", "start": cursor, "end": len(text)})
    return result


def analyze_snapshot(text: str, *, version_id: str) -> dict:
    if not isinstance(version_id, str) or not version_id:
        raise ValueError("VERSION_REQUIRED")
    text = normalize_text(text)
    if not kiwi_available():
        raise AnalysisUnavailable("KIWI_UNAVAILABLE")
    sentences = []
    for sentence in split_sentences(text):
        morphology = analyze_morphology(sentence["text"])
        if morphology["analyzer"] != "kiwi":
            raise AnalysisUnavailable("KIWI_ANALYSIS_FAILED")
        # Preserve token provenance without duplicating the whole source body.
        tokens = []
        for token in morphology["morphemes"]:
            start, end = token["start"] + sentence["start"], token["end"] + sentence["start"]
            # Kiwi can infer a contracted morpheme with a zero-width source span.
            # Its form is linguistic output, never an invented source quotation.
            tokens.append({**token, "start": start, "end": end,
                           "surface": text[start:end], "virtual": start == end})
        sentences.append({"number": sentence["number"], "paragraph": sentence["paragraph"],
                          "start": sentence["start"], "end": sentence["end"],
                          "morphology": {"analyzer": "kiwi", "tokens": tokens,
                                         "confidence": morphology["confidence"],
                                         "alternatives": morphology["alternatives"]}})
    result = {"schemaVersion": SCHEMA_VERSION,
              "input": {"versionId": version_id, "sha256": _hash(text.encode()), "codePoints": len(text)},
              "manifest": _source_manifest(), "partitions": _partitions(text),
              "quotations": [{"start": q.start, "end": q.end, "contentStart": q.content_start,
                               "contentEnd": q.content_end, "type": q.quote_type, "depth": q.depth}
                              for q in extract_quotations(text)],
              "sentences": sentences,
              "limitations": ["형태소 후보는 의미나 논리적 타당성의 확정 판정이 아닙니다."]}
    validate_snapshot(result, text, version_id=version_id)
    return result


def validate_snapshot(result: dict, text: str, *, version_id: str) -> None:
    """Strict structural and span checks against the persisted input version."""
    if text != normalize_text(text):
        raise ValueError("CANONICAL_INPUT_REQUIRED")
    if (result.get("schemaVersion") not in {LEGACY_SCHEMA_VERSION,SCHEMA_VERSION} or result.get("input") !=
            {"versionId": version_id, "sha256": _hash(text.encode()), "codePoints": len(text)}):
        raise ValueError("INPUT_MANIFEST_MISMATCH")
    cursor = 0
    for item in result["partitions"]:
        if type(item["start"]) is not int or type(item["end"]) is not int or item["start"] != cursor or not cursor < item["end"] <= len(text):
            raise ValueError("PARTITION_GAP_OR_OVERLAP")
        cursor = item["end"]
    if cursor != len(text):
        raise ValueError("INCOMPLETE_INPUT")
    covered = bytearray(len(text))
    previous = 0
    for sentence in result["sentences"]:
        start, end = sentence["start"], sentence["end"]
        if type(start) is not int or type(end) is not int or not previous <= start < end <= len(text):
            raise ValueError("INVALID_SENTENCE_SPAN")
        covered[start:end] = b"\1" * (end - start)
        previous = end
        for token in sentence["morphology"]["tokens"]:
            ts, te = token["start"], token["end"]
            if (type(ts) is not int or type(te) is not int or not start <= ts <= te <= end
                    or (ts == te) != token.get("virtual") or text[ts:te] != token["surface"]):
                raise ValueError("INVALID_TOKEN_SPAN")
    if any(not covered[i] and not char.isspace() for i, char in enumerate(text)):
        raise ValueError("UNPROCESSED_INPUT")
    for q in result["quotations"]:
        if not 0 <= q["start"] < q["contentStart"] <= q["contentEnd"] < q["end"] <= len(text):
            raise ValueError("INVALID_QUOTE_SPAN")
    structure_version=result.get('manifest',{}).get('structureVersion')
    legacy_structures={'geulbit.structure/2','geulbit.structure/3','geulbit.structure/4','geulbit.structure/5','geulbit.structure/6'}
    if structure_version is not None and structure_version not in legacy_structures|{'geulbit.structure/7','geulbit.structure/8','geulbit.structure/9'}:
        raise ValueError('UNSUPPORTED_STRUCTURE_VERSION')
    if structure_version is not None:
        bidirectional=structure_version in {'geulbit.structure/7','geulbit.structure/8','geulbit.structure/9'}
        if bidirectional!=(result['schemaVersion']==SCHEMA_VERSION):raise ValueError('STRUCTURE_SCHEMA_MISMATCH')
        sentences={s['number']:s for s in result['sentences']};nodes={}
        for c in result.get('roleCandidates',[]):
            sentence=sentences.get(c.get('sentenceNumber'))
            if (not sentence or c.get('start')!=sentence['start'] or c.get('end')!=sentence['end']
                or not isinstance(c.get('id'),str) or c['id'] in nodes
                or not isinstance(c.get('roles'),list)
                or any(r not in ('CLAIM_CANDIDATE','EVIDENCE_CANDIDATE') for r in c['roles'])):
                raise ValueError('INVALID_CANDIDATE_SPAN')
            nodes[c['id']]=c
        seen_ids=set();seen_pairs=set()
        for r in result.get('relations',[]):
            claim=nodes.get(r.get('claimId'));evidence=nodes.get(r.get('evidenceId'))
            if (not claim or not evidence or 'CLAIM_CANDIDATE' not in claim['roles']
                or 'EVIDENCE_CANDIDATE' not in evidence['roles']
                or (not bidirectional and claim['end']>evidence['start'])
                or (bidirectional and not (claim['end']<=evidence['start'] or evidence['end']<=claim['start']))
                or r.get('claimSpan')!={'start':claim['start'],'end':claim['end']}
                or r.get('evidenceSpan')!={'start':evidence['start'],'end':evidence['end']}
                or r.get('interpretation')!='STRUCTURAL_SUPPORT_CANDIDATE_NOT_LOGICAL_VALIDITY'):
                raise ValueError('INVALID_RELATION_SPAN')
            if bidirectional:
                pair=(r['claimId'],r['evidenceId'])
                order='CLAIM_FIRST' if claim['end']<=evidence['start'] else 'EVIDENCE_FIRST'
                if (r.get('direction')!='EVIDENCE_TO_CLAIM' or r.get('textOrder')!=order
                    or r.get('sentenceDistance')!=abs(claim['sentenceNumber']-evidence['sentenceNumber'])
                    or r.get('paragraphDistance')!=abs(claim['paragraph']-evidence['paragraph'])):
                    raise ValueError('INVALID_RELATION_DIRECTION')
                if not isinstance(r.get('id'),str) or r['id'] in seen_ids or pair in seen_pairs:raise ValueError('DUPLICATE_RELATION')
                seen_ids.add(r['id']);seen_pairs.add(pair)
            if r.get('approvalRoute')=='R1_DIRECT_REFERENCE':
                ref=r.get('directReference');sentence=sentences[claim['sentenceNumber']]
                span=(ref or {}).get('span',{});a,b=span.get('start'),span.get('end')
                anchor_assessment=r.get('anchorAssessment') if structure_version=='geulbit.structure/9' else r.get('assessment')
                if (structure_version not in {'geulbit.structure/8','geulbit.structure/9'} or not isinstance(ref,dict)
                    or ref.get('version')!='geulbit.r1.direct-reference/1'
                    or ref.get('claimId')!=claim['id'] or ref.get('evidenceId')!=evidence['id']
                    or claim['sentenceNumber']!=evidence['sentenceNumber']+1 or claim['paragraph']!=evidence['paragraph']
                    or type(a) is not int or type(b) is not int or not claim['start']<=a<b<=claim['end']
                    or ref.get('form')!=text[a:b] or ref.get('kind') not in {'action','scene','speech'}
                    or ref.get('assessment')!=anchor_assessment or 'R1_DIRECT_REFERENCE' not in r.get('signals',[])
                    or ref.get('meaning')!='STRUCTURAL_REFERENCE_NOT_LOGICAL_VALIDITY'):
                    raise ValueError('INVALID_R1_REFERENCE')
                observed=[{k:t[k] for k in ('form','pos','start','end')} for t in sentence['morphology']['tokens'] if a<=t['start']<t['end']<=b]
                if (len(ref.get('topicTokens',[]))!=3 or any(t not in observed for t in ref['topicTokens'])
                    or [t['pos'] for t in ref['topicTokens']]!=['MM','NNG','JX']
                    or ref['topicTokens'][0]['form']!='이' or ref['topicTokens'][2]['form'] not in {'은','는'}
                    or ref['topicTokens'][1]['form']!={'action':'행동','scene':'장면','speech':'발언'}[ref['kind']]
                    or not re.fullmatch(r'\s*(?:(?:따라서|그러므로|즉)\s*[,，]?\s*)?',text[claim['start']:a])):raise ValueError('INVALID_R1_TOPIC_TOKENS')
                ework,cwork=evidence.get('workFrame'),claim.get('workFrame')
                work='CONFLICT' if ework and cwork and ework!=cwork else 'SAME_DECLARED_WORK' if ework and cwork else 'UNKNOWN'
                if ref.get('workContext')!=work or ref.get('evidenceWorkFrame')!=ework or ref.get('claimWorkFrame')!=cwork:raise ValueError('INVALID_R1_WORK_CONTEXT')
                override=(structure_version=='geulbit.structure/9' and ref.get('sourceGuardOverride') is True
                          and r.get('sourceDecision',{}).get('effect')=='NEUTRAL'
                          and r.get('sourceDecision',{}).get('reasonCode') in {'SAME_WORK_ID','EXPLICIT_COMPARISON'})
                if anchor_assessment=='SUFFICIENT_SIGNALS' and (ref.get('plural') is not False or ref.get('remoteSpan') is not None
                    or ref.get('eventCount')!=1 or ref.get('competingEvidenceCount')!=0 or ref.get('competingEvidenceIds')!=[]
                    or (ref.get('workContext') not in {'UNKNOWN','SAME_DECLARED_WORK'} and not override)
                    or not re.fullmatch(r'이\s*(?:행동|장면|발언)(?:은|는)',ref['form'])):raise ValueError('INVALID_R1_APPROVAL')
            if structure_version=='geulbit.structure/9':
                policy=r.get('sourceDecision',{});effect=policy.get('effect');anchor=r.get('anchorAssessment')
                if (policy.get('version')!='geulbit.source-relation-policy/1' or effect not in {'NEUTRAL','REVIEW','REJECT'}
                    or anchor not in {'SUFFICIENT_SIGNALS','REQUIRES_REVIEW'}
                    or r.get('assessment')!=({'REVIEW':'REQUIRES_REVIEW','REJECT':'REJECTED'}.get(effect,anchor))):raise ValueError('INVALID_SOURCE_POLICY')
                named=set()
                for field,node in [('claimSource',claim),('evidenceSource',evidence)]:
                    s=policy.get(field,{})
                    if (s.get('certainty') not in {'EXPLICIT','INFERRED','UNKNOWN'} or not isinstance(s.get('workIds'),list)
                        or not all(isinstance(w,str) and w for w in s['workIds'])
                        or not isinstance(s.get('revisionIds'),list) or not all(isinstance(w,str) and w for w in s['revisionIds'])
                        or 'text' in s or 'content' in s or 'excerpt' in s
                        or s.get('workId')!=(s['workIds'][0] if len(s['workIds'])==1 and s['certainty']!='UNKNOWN' else None)):
                        raise ValueError('INVALID_SOURCE_SCOPE')
                    if s['certainty']=='INFERRED':
                        previous=nodes.get(s.get('inferredFrom'))
                        if not previous or previous['paragraph']!=node['paragraph'] or previous['end']>node['start']:raise ValueError('INVALID_SOURCE_INFERENCE')
                    for mention in s.get('mentions',[]):
                        span=mention.get('span',{});a,b=span.get('start'),span.get('end')
                        if (type(a) is not int or type(b) is not int or not node['start']<=a<b<=node['end']
                            or text[a:b]!=mention.get('name') or mention.get('certainty') not in {'EXPLICIT','UNKNOWN'}
                            or not isinstance(mention.get('workIds'),list)):raise ValueError('INVALID_SOURCE_MENTION')
                        if mention['certainty']=='EXPLICIT':named.update(mention['workIds'])
                c,e=policy['claimSource'],policy['evidenceSource'];reason=policy.get('reasonCode');comparison=policy.get('comparison',{})
                for span in comparison.get('cueSpans',[]):
                    a,b=span.get('start'),span.get('end')
                    if (type(a) is not int or type(b) is not int or not any(n['start']<=a<b<=n['end'] for n in [claim,evidence])
                        or not re.fullmatch(r'비교|대조|공통점|차이점|반면|[와과]\s*달리',text[a:b])
                        or any(q['start']<b and a<q['end'] for q in result['quotations'])):raise ValueError('INVALID_COMPARISON_SPAN')
                if set(comparison.get('namedWorkIds',[]))!=named:raise ValueError('INVALID_COMPARISON_SOURCE_NAMES')
                if effect=='REJECT' and (reason!='EXPLICIT_DIFFERENT_WORK_IDS' or c['certainty']!='EXPLICIT' or e['certainty']!='EXPLICIT'
                    or not c['workIds'] or not e['workIds'] or set(c['workIds'])&set(e['workIds']) or comparison.get('cueSpans')):raise ValueError('INVALID_SOURCE_REJECTION')
                if reason=='SAME_WORK_ID' and not set(c['workIds'])&set(e['workIds']):raise ValueError('INVALID_SAME_WORK')
                if reason=='EXPLICIT_COMPARISON' and (comparison.get('explicit') is not True or not comparison.get('cueSpans')
                    or len(set(comparison.get('namedWorkIds',[])))<2):raise ValueError('INVALID_EXPLICIT_COMPARISON')
            following=r.get('followingExplanation')
            if following is not None:
                sentence=sentences.get(following.get('sentenceNumber'))
                if (not sentence or sentence['number']!=evidence['sentenceNumber']+1 or sentence['paragraph']!=evidence['paragraph']
                    or following.get('span')!={'start':sentence['start'],'end':sentence['end']}
                    or 'FOLLOWING_QUOTE_EXPLANATION' not in r.get('signals',[])):
                    raise ValueError('INVALID_RELATION_EXPLANATION_SPAN')
    json.dumps(result, ensure_ascii=False, allow_nan=False)
