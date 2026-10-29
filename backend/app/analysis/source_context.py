"""Optional source/genre signals within the existing pure analysis package."""
import hashlib
import re
from rapidfuzz import fuzz
from .quotation import extract_quotations
from .snapshot import normalize_text

GENRES=('소설','시','희곡','비평문','에세이','기타')
VERSION='geulbit.source-context/4'
LIMITATION='출처 일치와 구조 신호는 의미 동일성이나 주장의 논리적 타당성을 확정하지 않습니다.'

def genre_signals(text,genre):
    lines=[{'start':m.start(),'end':m.end(),'text':m.group()} for m in re.finditer(r'[^\n]+',text)]
    nonempty=[x for x in lines if x['text'].strip()]
    features={'genre':genre if genre in GENRES else '기타','lineCount':len(nonempty),'stanzaCount':len([p for p in re.split(r'\n\s*\n',text) if p.strip()]),'boundaryPreserved':True}
    patterns={'소설':{'action':r'걸었|떠났|말했다|돌아왔|갈등|장면|서술자'},'시':{'image':r'빛|그늘|바람|흙|꽃|뿌리|어둠'},'희곡':{'dialogue':r'(?m)^\s*[^:\n]{1,30}:','stageDirection':r'[\[(][^\]\)\n]+[\])]'},'비평문':{'argument':r'논제|개념|근거|반론|주장'},'에세이':{'experience':r'나는|내가|경험|겪었|느꼈'}}
    features['signals']={key:len(re.findall(pattern,text)) for key,pattern in patterns.get(genre,{}).items()}
    if genre=='시':features['repeatedLines']=len(nonempty)-len({x['text'] for x in nonempty})
    return features

def local_questions(body,result,checks,works):
    questions=[]
    confirmed={'EXACT_MATCH','NORMALIZED_MATCH','OMISSION_MATCH'}
    def named_sources(text):
        # Titles inside a quotation are not the student's source attribution.
        for quote in reversed(extract_quotations(text)):
            text=text[:quote.start]+' '*(quote.end-quote.start)+text[quote.end:]
        return {w['revisionId'] for w in works if any(name and name in text for name in [w.get('title','')]+w.get('aliases',[]))}
    def claim_source(quote):
        # Selecting a work does not make it the source of every interpretation.
        # Explicit titles/aliases identify scope; ambiguous multi-work claims
        # stay unassigned instead of silently pointing at the first work.
        matches=named_sources(quote)
        if len(matches)==1:return next(iter(matches))
        if not matches and len(works)==1:return works[0]['revisionId']
        return None
    def question_link(node,revision):
        # Consume the existing decision, never rescore/reapprove a relation.
        # Unknown/contradictory states and ambiguous sources fail closed here.
        if not node or 'EVIDENCE_CANDIDATE' not in node.get('roles',[]):return None,False
        nodes={c['id']:c for c in result.get('roleCandidates',[])}
        links=[r for r in result.get('relations',[]) if r.get('evidenceId')==node['id']]
        source_names={name for w in works if w['revisionId']==revision for name in [w.get('title','')]+w.get('aliases',[]) if name}
        eligible={};comparison=False
        def text_at(span):
            if not isinstance(span,dict):return ''
            a,b=span.get('start'),span.get('end')
            return body[a:b] if type(a) is int and type(b) is int and 0<=a<b<=len(body) else ''
        evidence=body[node['start']:node['end']]
        for link in links:
            claim=nodes.get(link.get('claimId'))
            if not claim or 'CLAIM_CANDIDATE' not in claim.get('roles',[]):continue
            claim_span={'start':claim['start'],'end':claim['end']}
            evidence_span={'start':node['start'],'end':node['end']}
            if link.get('claimSpan')!=claim_span or link.get('evidenceSpan')!=evidence_span:continue
            claim_text=text_at(claim_span)
            explanation=text_at((link.get('followingExplanation') or {}).get('span'))
            context=claim_text+' '+evidence+' '+explanation
            names=named_sources(context)
            # A conditional comparison question can remain safe across works;
            # it does not declare that one work proves a claim about another.
            comparison=comparison or (len(names)>=2 and bool(re.search(r'비교|공통점|차이점|대조|반면|[와과] 달리',context)))
            states={r.get('assessment') for r in links if r.get('claimId')==claim['id']}
            if states!={'SUFFICIENT_SIGNALS'}:continue
            if link.get('interpretation')!='STRUCTURAL_SUPPORT_CANDIDATE_NOT_LOGICAL_VALIDITY':continue
            if claim_source(claim_text)!=revision or names-{revision}:continue
            # Use the engine's existing explicit/inherited work frame as well.
            # A sole selected source must not adopt a named, unselected work.
            if any(c.get('workFrame') and c['workFrame'] not in source_names for c in (claim,node)):continue
            eligible[(claim['id'],node['id'])]=link
        # Selection/list order cannot resolve multiple distinct approved claims.
        return (next(iter(eligible.values())) if len(eligible)==1 else None),comparison
    def add(kind,span,revision,reason,question):
        if len(questions)>=2 or span['start']>=span['end']:return
        key=hashlib.sha256((kind+str(span)+str(revision)).encode()).hexdigest()[:16]
        if any(q['id']==key for q in questions):return
        questions.append({'id':key,'type':kind,'question':question,'essaySpan':span,'focusQuote':body[span['start']:span['end']],'revisionId':revision,'reason':reason})
    checked=set()
    priority={'OMISSION_ORDER_MISMATCH':4,'SIMILAR_DIFFERENCE_CANDIDATE':3,'OMISSION_SIMILAR_CANDIDATE':3,'PARTIAL_OMISSION_CANDIDATE':2,'NOT_FOUND_IN_SELECTED_REVISION':1}
    for check in checks:
        key=(check['essaySpan']['start'],check['essaySpan']['end'])
        if key in checked:continue
        checked.add(key)
        group=[c for c in checks if c['essaySpan']==check['essaySpan']]
        if any(c['status'] in confirmed for c in group):continue
        # Rank actual search evidence before emitting one question per quote.
        # Selection/database order must not assign an unlocated quote's source.
        ranked=sorted((c for c in group if c['status'] in priority),key=lambda c:(priority[c['status']],c.get('matchedSegments',0),c.get('similarity',0)),reverse=True)
        if not ranked:continue
        best=ranked[0];score=lambda c:(priority[c['status']],c.get('matchedSegments',0),c.get('similarity',0))
        tied=[c for c in ranked if score(c)==score(best)]
        if len(tied)>1:continue
        span=best['essaySpan'];brief=body[span['start']:span['end']][:24]
        add('QUOTE_RECHECK',span,best['revisionId'],best['status'],f'‘{brief}’라는 인용의 표현과 생략 순서를 선택한 판본에서 다시 확인해 볼까요?')
    for quote in result.get('quotations',[]):
        span={'start':quote['contentStart'],'end':quote['contentEnd']}
        hits=[c for c in checks if c['essaySpan']==span and c['status'] in confirmed];hit=hits[0] if hits else None
        if hit:
            if len({c['revisionId'] for c in hits})>1:add('SOURCE_ATTRIBUTION',span,hit['revisionId'],'MULTIPLE_MATCHING_REVISIONS','이 구절과 일치한 여러 판본 중 실제로 참고한 출처를 구분해 볼까요?')
            else:
                focus=body[span['start']:span['end']]
                brief=focus[:24]+('…' if len(focus)>24 else '')
                node=next((c for c in result.get('roleCandidates',[]) if c['start']<=span['start'] and c['end']>=span['end']),None)
                link,comparison=question_link(node,hit['revisionId'])
                kind='EVIDENCE_EXPLANATION';reason='SOURCE_AND_CONNECTION_CHECK'
                question=f'‘{brief}’와 연결하려는 자신의 해석이 있다면, 작품 출처와 연결할 수 있는 이유를 먼저 확인해 볼까요?'
                if link:
                    claim=body[link['claimSpan']['start']:link['claimSpan']['end']]
                    question=f'‘{claim[:32]}'+('…' if len(claim)>32 else '')+f'’라는 해석을 ‘{brief}’가 어떻게 뒷받침하는지 설명할 수 있을까요?'
                    reason='APPROVED_STRUCTURE_NOT_LOGICAL_PROOF'
                elif comparison:
                    kind='SOURCE_COMPARISON';reason='EXPLICIT_COMPARISON_REQUIRES_SOURCE_CHECK'
                    question=f'두 작품을 비교하려는 의도라면, ‘{brief}’의 출처를 구분하고 각 작품의 공통점과 차이점을 확인해 볼까요?'
                add(kind,span,hit['revisionId'],reason,question)
                if link and questions and questions[-1]['essaySpan']==span:questions[-1]['claimSpan']=link['claimSpan']
            if questions and questions[-1]['essaySpan']==span:questions[-1]['sourceSpan']=hit.get('sourceSpan') or hit.get('sourceSpans')
            if questions and questions[-1]['essaySpan']==span:questions[-1]['matchingRevisionIds']=[c['revisionId'] for c in hits]
    if works:
        for claim in result.get('roleCandidates',[]):
            if 'CLAIM_CANDIDATE' not in claim['roles']:continue
            span={'start':claim['start'],'end':claim['end']};quote=body[span['start']:span['end']]
            revision=claim_source(quote)
            if not revision:continue
            if re.search(r'모든|누구나|언제나|항상|반드시',quote):add('GENERALIZATION_SCOPE',span,revision,'GENERALIZATION_IN_STUDENT_CLAIM','이 결론을 적용할 수 있는 범위와 작품에서 확인할 수 있는 반례를 구분해 볼까요?')
            if re.search(r'의미|개념|상징',quote):add('CONCEPT_DISTINCTION',span,revision,'CONCEPT_IN_STUDENT_CLAIM','이 글에서 사용한 개념의 의미를 작품의 표현과 구분해 설명할 수 있을까요?')
            if re.search(r'인물|행동|말했다|말한다',quote):add('CHARACTER_INTERPRETATION',span,revision,'CHARACTER_SIGNAL_IN_STUDENT_CLAIM','작품에서 확인되는 인물의 행동과 자신의 해석을 어떻게 연결할 수 있을까요?')
    if works and not questions:
        claim=next((c for c in result.get('roleCandidates',[]) if 'CLAIM_CANDIDATE' in c['roles']),None)
        if claim:
            span={'start':claim['start'],'end':claim['end']};revision=claim_source(body[span['start']:span['end']])
            if revision:add('SOURCE_EVIDENCE',span,revision,'CLAIM_WITH_SELECTED_WORK','선택한 작품에서 이 해석과 연결되는 구절이나 장면을 확인할 수 있을까요?')
    return questions

def source_context(body,result,sources,checks):
    works=[];indirect=[]
    quoted=[(q['start'],q['end']) for q in result.get('quotations',[])]
    for source in sources:
        text=source['text'];meta={k:v for k,v in source.items() if k!='text'}
        works.append({**meta,'genreSignals':genre_signals(text,source.get('genre','기타'))})
        # Only observed scene/action candidates; similarity alone is insufficient.
        for candidate in result.get('roleCandidates',[]):
            span={'start':candidate['start'],'end':candidate['end']}
            if 'EVIDENCE_CANDIDATE' not in candidate['roles'] or any(a<span['end'] and b>span['start'] for a,b in quoted):continue
            query=body[span['start']:span['end']]
            if len(query)<8 or not re.search(r'장면|행동|말하|말했|인물|화자|서술자|경험',query):continue
            nouns={t['form'] for sentence in result['sentences'] if sentence['start']==span['start'] for t in sentence['morphology']['tokens'] if t['pos'].startswith('N') and len(t['form'])>=2}
            if len([n for n in nouns if n in text])<2:continue
            # Literary framing is not part of the paraphrased event itself.
            # Keep its original essay span; normalize only the search query.
            search=re.sub(r'^(?:인물|주인공|화자)\s+','',query)
            search=re.sub(r'(?:는|던)\s+행동을\s+한다[.!?]?\s*$','',search)
            alignment=fuzz.partial_ratio_alignment(search,text)
            excerpt=text[alignment.dest_start:alignment.dest_end] if alignment else ''
            shared=[n for n in nouns if n in excerpt]
            negated=lambda value:bool(re.search(r'않|못|(?:^|\s)안\s',value))
            supported=bool(alignment and negated(query)==negated(excerpt) and (alignment.score>=85 or (alignment.score>=75 and len(shared)>=4)))
            if supported and alignment.dest_end>alignment.dest_start:
                indirect.append({'status':'INDIRECT_QUOTE_CANDIDATE','essaySpan':span,'revisionId':source['revisionId'],'documentId':source['documentId'],'sourceSpan':{'start':alignment.dest_start,'end':alignment.dest_end},'similarity':round(alignment.score,2),'limitation':LIMITATION})
    return {'version':VERSION,'works':works,'indirectCandidates':indirect,'questions':local_questions(body,result,checks,works),'configuration':{'indirectSurfaceFloor':85,'supportedParaphraseFloor':75,'minimumWindowNouns':4,'negationAgreementRequired':True,'queryNormalization':'literary-frame-phrases/v1'},'limitation':LIMITATION}
