"""Versioned catalogue around existing local patterns. No network at runtime."""
import hashlib
import json
import re

from .quotation import extract_quotations, overlaps_quotation
from .spelling import RULES
from .norms_reference import rule_reference
from .norms_catalogue import catalogue_manifest
from .reviewed_norms import reviewed_records, lexical_records

# Version 6 unifies reviewed display metadata and protects the known place name.
RULESET_VERSION = "geulbit.local-reviewed/11"
RULE_TITLES = ["할 수 있다 · 의존 명사 띄어쓰기", "몇일 → 며칠", "외곡 → 왜곡",
               "상징적으러 → 상징적으로", "로서·로써의 의미 구별", "뿐의 띄어쓰기",
               "대로의 띄어쓰기", "만큼의 띄어쓰기"]
CATEGORY_LABELS = {"spacing": "띄어쓰기", "spelling": "맞춤법", "typo": "오타 후보", "context": "문맥 구별"}
RULE_SCOPES = ["할·볼·읽을·쓸 뒤 수와 있·없의 제한된 표현을 검사합니다.",
               "몇일·몇 일 후보를 검사합니다. 고유 어휘와 직접 인용은 보호합니다.",
               "왜곡을 뜻할 가능성이 있는 외곡 후보입니다. 규범집 조항 대조 전이며 외곡리는 제외합니다.",
               "상징적으러의 제한된 오타 후보입니다. 규범집 조항 대조 전입니다.",
               "학생으로써·독자로써·교사로써의 자격 문맥만 확인합니다. 수단·재료·시간의 로써는 일괄 수정하지 않습니다.",
               "웃을뿐 표현만 검사합니다. 친구뿐 같은 조사와 구별합니다.",
               "아는대로 표현만 검사합니다. 법대로 같은 조사와 구별합니다.",
               "애쓴만큼 표현만 검사합니다. 고등학생만큼 같은 조사와 구별합니다."]
EXAMPLES = [
    ("할수 있다", "할 수 있다", "할수라는 인물", ["할수"]),
    ("몇일 동안", "며칠 동안", "몇일이라는 작품", ["몇일"]),
    ("외곡", "왜곡", "외곡리", ["외곡리"]),
    ("상징적으러", "상징적으로", "상징적으러라는 이름", ["상징적으러"]),
    ("학생으로써 책임을 진다", "학생으로서 책임을 진다", "도구로써", []),
    ("웃을뿐이다", "웃을 뿐이다", "친구뿐이다", []),
    ("아는대로 말한다", "아는 대로 말한다", "법대로 한다", []),
    ("애쓴만큼 얻는다", "애쓴 만큼 얻는다", "고등학생만큼 안다", []),
]
SOURCE_URLS = {
    0: "https://www.korean.go.kr/kornorms/m/m_regltn.do",
    1: "https://www.korean.go.kr/front/mcfaq/mcfaqView.do?mcfaq_seq=8631",
}


# Keep the legacy engine patterns untouched. V2 uses this reviewed catalogue.
REVIEWED_RULES = list(RULES)
REVIEWED_RULES[0] = (re.compile(r"(?:할|볼|읽을|쓸)수[ \t]*(?:있|없)[가-힣]*"), None, *RULES[0][2:])
REVIEWED_RULES[1] = (re.compile(r"(?<![가-힣A-Za-z0-9_])몇[ \t]*일"), *RULES[1][1:])
REVIEWED_RULES[2] = (re.compile(r"외곡(?!리)"), *RULES[2][1:])
REVIEWED_RULES[4] = (re.compile(r"(?<![가-힣A-Za-z0-9_])(?:학생으로써|독자로써|교사로써)"), None, "문맥 확인 필요", "지위나 자격을 나타내는 문맥이면 '(으)로서'인지 확인해 주세요. 수단·재료·시간 기준의 '(으)로써'는 올바를 수 있습니다.", "한글 맞춤법 제57항", False, "context")
REVIEWED_RULES.extend([
    (re.compile(r"(?<![가-힣A-Za-z0-9_])웃을뿐"), "웃을 뿐", "확인 필요", "용언의 관형사형 뒤 의존 명사 '뿐'은 띄어 씁니다. 체언 뒤 조사 '뿐'과 구별합니다.", "한글 맞춤법 제42항", False, "spacing"),
    (re.compile(r"(?<![가-힣A-Za-z0-9_])아는대로"), "아는 대로", "확인 필요", "관형사형 뒤 의존 명사 '대로'는 띄어 씁니다. '법대로' 같은 조사는 붙입니다.", "한글 맞춤법 제42항", False, "spacing"),
    (re.compile(r"(?<![가-힣A-Za-z0-9_])애쓴만큼"), "애쓴 만큼", "확인 필요", "관형사형 뒤 의존 명사 '만큼'은 띄어 씁니다. 체언 뒤 조사는 붙입니다.", "한글 맞춤법 제42항", False, "spacing"),
])


def catalogue():
    result = []
    for i, (pattern, replacement, _status, reason, clause, _auto, category) in enumerate(REVIEWED_RULES):
        positive, negative, exception, _vocabulary = EXAMPLES[i]
        result.append({"rule_id": f"gb-local-{i+1:03d}", "version": RULESET_VERSION, "category": category,
                       "title": RULE_TITLES[i], "categoryLabel": CATEGORY_LABELS[category],
                       "scope": RULE_SCOPES[i], "execution": "BOUNDED_CANDIDATES", "autoApply": False,
                       "examples": {"candidate": [positive], "normal": [negative], "exception": [exception],
                                    "exceptionVocabulary": _vocabulary},
                       "tier": "오류 후보" if i in SOURCE_URLS else "확인 필요", "condition": pattern.pattern,
                       "exception": "직접 인용 및 선택 자료의 고유 어휘와 겹치는 구간은 보호한다.",
                       "reason": reason, "suggestion": replacement,
                       "source": {"legacyCaption": clause, "url": SOURCE_URLS.get(i),
                                  "verifiedAt": "2026-10-10" if i in SOURCE_URLS else None,
                                  "status": "PRIMARY_SOURCE_CHECKED" if i in SOURCE_URLS else "SUPPLIED_REFERENCE_PASSAGE_CHECKED" if i >= 4 else "LEGACY_SOURCE_UNVERIFIED",
                                  "primaryReference": rule_reference(f"gb-local-{i+1:03d}")},
                       "positive_examples": [positive], "negative_examples": [negative],
                       "exception_examples": [exception], "known_false_positives": ["작품 고유 어휘 및 지역명"]})
    for record in result:
        record['selectionPolicy']='CONTEXT_REQUIRED' if record['category']=='context' else 'STANDARD_SPELLING'
        if record['category']=='context':
            record['alternatives']=[{'text':'(으)로서','when':'지위·자격','example':'학생으로서 책임을 진다.'},{'text':'(으)로써','when':'수단·재료·시간 기준','example':'말로써 뜻을 전한다.'}]
            record['reason'] += " 지위·자격이면 '(으)로서', 수단·재료·시간 기준이면 '(으)로써'를 선택합니다. 글쓴이의 뜻을 확정할 수 없으므로 한 표기로 자동 교체하지 않습니다."
    return result + reviewed_records(RULESET_VERSION, rule_reference) + lexical_records(RULESET_VERSION) + expression_records()


def ruleset_hash():
    payload = {"detectors": catalogue(), "normsCatalogue": catalogue_manifest()}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def local_findings(text, *, disabled=(), vocabulary=(), snapshot=None, candidates=()):
    quotes = extract_quotations(text)
    protected = []
    for word in vocabulary:
        if not isinstance(word, str) or not word:
            raise ValueError("VOCABULARY_INVALID")
        cursor = 0
        while (start := text.find(word, cursor)) >= 0:
            protected.append((start, start+len(word)))
            cursor = start+len(word)
    results = []
    for rule in catalogue():
        if rule["rule_id"] in disabled or rule.get("execution")=="CONTEXTUAL_MORPHOLOGY":
            continue
        for match in re.finditer(rule['condition'], text):
            if overlaps_quotation(match.start(), match.end(), quotes) or any(match.start() < end and match.end() > start for start, end in protected):
                continue
            results.append({"ruleId": rule["rule_id"], "ruleVersion": rule["version"],
                            "start": match.start(), "end": match.end(), "quote": match.group(),
                            "tier": rule["tier"], "reason": rule["reason"], "suggestion": re.sub(r"수[ \t]*", " 수 ", match.group(), count=1) if rule["rule_id"] == "gb-local-001" else rule["suggestion"],
                            "source": rule["source"], "autoApply": False,
                            "selectionPolicy":rule.get('selectionPolicy','STANDARD_SPELLING'),
                            "alternatives":rule.get('alternatives',[])})
    if snapshot is not None:
        results.extend(expression_findings(text,snapshot,candidates,quotes,protected,disabled))
    return sorted(results, key=lambda f:(f["start"], f["end"], f["ruleId"]))


def expression_records():
    descriptions=(('gb-expression-repeat','EXCESSIVE_REPETITION','반복 표현 검토','같은 설명이 집중적으로 되풀이되는지 확인해 주세요.'),
                  ('gb-expression-vague','VAGUE_EXPRESSION','모호 표현 검토','이 표현의 의미를 조금 더 구체적으로 설명할 수 있는지 확인해 보세요.'))
    return [{'rule_id':identifier,'kind':kind,'version':RULESET_VERSION,'category':'expression','categoryLabel':'표현 제안',
             'title':title,'scope':'직접 인용과 구체적인 작품 근거를 보호하는 제한된 문맥 검사',
             'execution':'CONTEXTUAL_MORPHOLOGY','condition':'(?!)','tier':'표현 제안','reason':reason,
             'suggestion':None,'autoApply':False,'selectionPolicy':'CONTEXT_REQUIRED','alternatives':[],
             'source':{'status':'LOCAL_HEURISTIC_NOT_NORMATIVE','url':None,'primaryReference':None,'legacyCaption':'로컬 표현 검토 휴리스틱','verifiedAt':None},
             'positive_examples':['같은 설명의 불필요한 반복'],'negative_examples':['근거가 있는 신중한 해석'],'exception_examples':['인용·시의 의도적인 후렴'],
             'examples':{'candidate':['같은 설명의 불필요한 반복'], 'normal':['근거가 있는 신중한 해석'], 'exception':['인용·시의 의도적인 후렴']}}
            for identifier,kind,title,reason in descriptions]


def expression_findings(text,snapshot,candidates,quotes,protected,disabled):
    """Suggestions only. Reuse Kiwi sentence tokens; no semantic equivalence claim."""
    records={r['kind']:r for r in expression_records()};findings=[];seen={}
    by_number={c['sentenceNumber']:c for c in candidates}
    def protected_span(start,end):
        return overlaps_quotation(start,end,quotes) or any(start<b and end>a for a,b in protected)
    def emit(kind,start,end):
        record=records[kind]
        if record['rule_id'] in disabled or protected_span(start,end):return
        findings.append({'ruleId':record['rule_id'],'ruleVersion':RULESET_VERSION,'kind':kind,'category':'expression',
                         'start':start,'end':end,'quote':text[start:end],'tier':'표현 제안','reason':record['reason'],
                         'suggestion':None,'source':record['source'],'autoApply':False,'selectionPolicy':'CONTEXT_REQUIRED','alternatives':[]})
    for sentence in snapshot['sentences']:
        start,end=sentence['start'],sentence['end'];value=text[start:end];tokens=sentence['morphology']['tokens']
        if protected_span(start,end):continue
        signature=tuple((t['form'],t['pos']) for t in tokens if t['pos'].startswith(('NN','VV','VA','MAG')))
        if len(signature)>=3:seen.setdefault(signature,[]).append(sentence)
        context=[c for n in range(sentence['number']-1,sentence['number']+2) if (c:=by_number.get(n)) and c['paragraph']==sentence['paragraph']]
        grounded=any('EVIDENCE_CANDIDATE' in c['roles'] for c in context) or bool(re.search(r'\d+\s*(?:번|명|개|쪽|%)',value))
        if grounded:continue
        match=re.search(r'어떤 면에서|여러 가지|굉장히|매우|많이|다양(?:하다|한)|것 같다',value)
        if match:emit('VAGUE_EXPRESSION',start+match.start(),start+match.end())
    poetic=bool(re.search(r'(?:후렴|시구|반복).{0,30}(?:의도|리듬|되풀이)|의도.{0,30}(?:후렴|반복)',text))
    if not poetic:
        for group in seen.values():
            # Repeated topic nouns in different predicates are not duplicate explanations.
            if len(group)>=3 and len(group)/max(1,len(snapshot['sentences']))>=0.25:
                emit('EXCESSIVE_REPETITION',group[1]['start'],group[1]['end'])
    return findings
