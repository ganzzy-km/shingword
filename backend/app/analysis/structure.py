"""Structure candidates: counts of observed clues, not grading/probabilities."""
import re

from .snapshot import analyze_snapshot, normalize_text, validate_snapshot
from .ruleset import local_findings, ruleset_hash, RULESET_VERSION
from .norms_catalogue import catalogue_manifest

CLAIM_CLUES = ("생각한다", "라고 볼 수", "보여 준다", "보여준다", "의미한다", "상징한다", "드러낸다", "조명한다", "조명하는", "중요하다", "필요하다", "가치가", "가치를", "일 것이다")
EXPLANATION_CLUES = ("이는", "즉", "의미", "알 수 있다", "드러낸다", "보여 준다")
STRUCTURE_VERSION = 'geulbit.structure/8'
GENERIC_NOUNS = {'것','수','나','우리','이','그','내용','작품','인물','문장','생각','경우','점'}
ACTION_LEMMAS = {'걷','떠나','달리','말하','외치','건네','돕','숨기','묻','묻히','지키','돌보','희생하','버리','피하','구하','쓰러지','피우','포기하'}
ACTION_LEMMAS |= {'망설이','기다리','옮기','접','펴','놓','열','나누'}
ACTION_LEMMAS |= {'적','남기','닫','앉'}
INTERPRETATION_NOUNS = {'가치','의미','사랑','희생','헌신','책임','용기','자유','관계','연대','권력','배려','슬픔','환대','단절','태도','선택','존중'}
INTERPRETATION_NOUNS |= {'삶','경험'}


def prepare_relation_sources(text, documents, checks):
    """Frozen metadata/matcher receipts only; no DB, file or source-text access.

    A work identity is never derived from a revision ID. Title ambiguity and
    multiple matching works stay UNKNOWN. Revision ambiguity within one work
    is recorded separately from work ambiguity.
    """
    from .quotation import extract_quotations
    visible=list(text)
    for quote in extract_quotations(text):
        for i in range(quote.start,quote.end):visible[i]=' '
    visible=''.join(visible);works={};revisions={};names={}
    for doc in documents:
        rid=doc.get('revisionId');did=doc.get('documentId')
        if not isinstance(rid,str) or not isinstance(did,str):continue
        ids=set()
        for meta in doc.get('workMetadata',[]):
            wid=meta.get('workId');title=meta.get('title')
            if not isinstance(wid,str) or not wid or not isinstance(title,str) or not title:continue
            ids.add(wid);work=works.setdefault(wid,{'workId':wid,'revisionIds':set(),'names':set()})
            work['revisionIds'].add(rid)
            for name in [title]+(meta.get('aliases') or []):
                if isinstance(name,str) and name:
                    work['names'].add(name);names.setdefault(name,set()).add(wid)
        revisions[rid]={'revisionId':rid,'documentId':did,'workIds':sorted(ids)}
    mentions=[]
    for name,ids in sorted(names.items()):
        for match in re.finditer(re.escape(name),visible):
            a,b=match.span();left=visible[a-1] if a else '';tail=visible[b:]
            if left and (left.isalnum() or left=='_'):continue
            if tail and tail[0].isalnum() and not re.match(r'^(?:에서(?:는)?|에게|으로|보다|처럼|은|는|이|가|을|를|의|에|와|과)(?:\s|[.,，。!?」〉>)]|$)',tail):continue
            known=sorted(ids);unique=len(known)==1
            mentions.append({'span':{'start':a,'end':b},'name':name,'workId':known[0] if unique else None,
                             'workIds':known,'certainty':'EXPLICIT' if unique else 'UNKNOWN',
                             'reasonCode':'UNIQUE_REGISTERED_TITLE' if unique else 'AMBIGUOUS_REGISTERED_TITLE'})
    # Overlapping registered names do not silently select the shorter title.
    for mention in mentions:
        overlaps=[m for m in mentions if m['span']['start']<mention['span']['end'] and mention['span']['start']<m['span']['end']]
        if len({wid for m in overlaps for wid in m['workIds']})>1:
            mention.update(certainty='UNKNOWN',workId=None,reasonCode='OVERLAPPING_REGISTERED_TITLES')
    quote_sources={}
    for check in checks:
        if check.get('status') not in {'EXACT_MATCH','NORMALIZED_MATCH','OMISSION_MATCH'}:continue
        ref=revisions.get(check.get('revisionId'));span=check.get('essaySpan')
        if not ref or ref['documentId']!=check.get('documentId') or not isinstance(span,dict):continue
        a,b=span.get('start'),span.get('end')
        if type(a) is not int or type(b) is not int or not 0<=a<b<=len(text):continue
        entry=quote_sources.setdefault((a,b),{'workIds':set(),'revisionIds':set(),'unknownWork':False})
        entry['workIds'].update(ref['workIds']);entry['revisionIds'].add(ref['revisionId'])
        entry['unknownWork']=entry['unknownWork'] or not ref['workIds']
    quotes=[]
    for (a,b),entry in sorted(quote_sources.items()):
        ids=sorted(entry['workIds']);rids=sorted(entry['revisionIds']);unique=len(ids)==1 and not entry['unknownWork']
        quotes.append({'span':{'start':a,'end':b},'workId':ids[0] if unique else None,'workIds':ids,
                       'revisionIds':rids,'certainty':'EXPLICIT' if unique else 'UNKNOWN',
                       'revisionAmbiguous':len(rids)>1,'reasonCode':'CONFIRMED_SELECTED_QUOTE' if unique else 'AMBIGUOUS_OR_UNMAPPED_QUOTE'})
    return {'version':'geulbit.relation-sources/1','works':[{**w,'names':sorted(w['names']),'revisionIds':sorted(w['revisionIds'])} for _,w in sorted(works.items())],
            'revisions':list(revisions.values()),'mentions':sorted(mentions,key=lambda m:(m['span']['start'],m['span']['end'])),'quotes':quotes}


def relation_source_scopes(candidates, information):
    """Explicit observations and bounded paragraph inference; no semantic role."""
    scopes={};paragraph_scope={}
    for node in candidates:
        overlap=lambda x:x['span']['start']<node['end'] and node['start']<x['span']['end']
        mentions=[m for m in information['mentions'] if overlap(m)]
        quotes=[q for q in information['quotes'] if overlap(q)]
        named={w for m in mentions if m['certainty']=='EXPLICIT' for w in m['workIds']}
        quoted={w for q in quotes if q['certainty']=='EXPLICIT' for w in q['workIds']}
        ambiguous=any(m['certainty']=='UNKNOWN' for m in mentions) or (not named and any(q['certainty']=='UNKNOWN' for q in quotes))
        conflicting=bool(named and quoted and not named & quoted)
        ids=sorted(named or quoted);certainty='EXPLICIT' if ids and not ambiguous and not conflicting else 'UNKNOWN'
        inferred_from=None
        if not mentions and not quotes and node['paragraph'] in paragraph_scope:
            ids, inferred_from=paragraph_scope[node['paragraph']];certainty='INFERRED';ids=list(ids)
        if named and certainty=='EXPLICIT':
            if len(named)==1:paragraph_scope[node['paragraph']]=(sorted(named),node['id'])
            else:paragraph_scope.pop(node['paragraph'],None)
        scopes[node['id']]={'workId':ids[0] if len(ids)==1 and certainty!='UNKNOWN' else None,'workIds':ids,
            'revisionIds':sorted({rid for q in quotes for rid in q['revisionIds']}),
            'certainty':certainty,'inferredFrom':inferred_from,'mentions':mentions,
            'ambiguous':ambiguous,'conflictingObservations':conflicting}
    return scopes


def source_relation_policy(claim,evidence,scopes,text,*,sentence_tokens=None):
    c=scopes[claim['id']];e=scopes[evidence['id']]
    # Quoted dialogue saying "compare" is not the student's comparison cue.
    from .quotation import extract_quotations
    segments=[];named=set();target_pairs=[];collective_target=False
    for node,scope in [(claim,c),(evidence,e)]:
        part=list(text[node['start']:node['end']])
        for q in extract_quotations(text[node['start']:node['end']]):
            for i in range(q.start,q.end):part[i]=' '
        visible=''.join(part)
        if sentence_tokens is None:
            # Direct policy callers reuse the same Kiwi adapter. The normal
            # analysis path supplies its existing immutable sentence tokens.
            from .morphology import analyze_morphology
            morphology=analyze_morphology(text[node['start']:node['end']])
            tokens=[{**t,'start':t['start']+node['start'],'end':t['end']+node['start']}
                    for t in morphology['morphemes']] if morphology['analyzer']=='kiwi' else []
        else:tokens=sentence_tokens.get(node['sentenceNumber'],[])
        tokens=[t for t in tokens if visible[t['start']-node['start']:t['end']-node['start']].strip()]
        mentions=[m for m in scope['mentions'] if m['certainty']=='EXPLICIT']
        for i,t in enumerate(tokens):
            form,pos=t['form'],t['pos'];a,b=t['start'],t['end'];tail=tokens[i+1:]
            if any(m['span']['start']<=a<m['span']['end'] for m in mentions):continue
            if form in {'비교','대조'} and pos=='NNG':
                # 비교적(MAG), 비교+적(XSN), and negated 비교하다 do
                # not assert that the student is comparing these works.
                if not tail or (tail[0]['form'],tail[0]['pos'])!=('하','XSV'):continue
                if any(x['form'] in {'않','못하','말'} for x in tail[1:4]):continue
                if i and tokens[i-1]['form'] in {'안','못'}:continue
            elif form in {'공통점','차이점','반면'} and pos=='NNG':
                if tail and tail[0]['pos']=='XSN':continue
            elif form=='달리' and pos=='MAG' and i and tokens[i-1]['form'] in {'와','과'} and tokens[i-1]['pos']=='JKB':
                a=tokens[i-1]['start']
            else:continue
            # A completed intervening predicate closes the comparison target
            # phrase (e.g. works were read, then grades were compared).
            boundary=max([node['start']]+[x['end'] for x in tokens[:i] if x['pos'].startswith(('VV','VA','XSV','XSA','VCP'))])
            targets=[m for m in mentions if m['span']['start']>=boundary and (m['span']['end']<=a or form in {'반면','달리'})]
            ids={m['workId'] for m in targets}
            coordinated=any(x['form'] in {'와','과'} and x['pos'] in {'JC','JKB'} and
                            any(m['span']['end']<=x['start'] for m in targets) and
                            any(m['span']['start']>=x['end'] for m in targets) for x in tokens if x['start']<b)
            contrast=form in {'반면','달리'} and any(m['span']['end']<=a for m in targets) and any(m['span']['start']>=b for m in targets)
            collective=any(x['form']=='두' and x['pos']=='MM' and j+1<len(tokens) and tokens[j+1]['form']=='작품' and
                           boundary<=x['start']<tokens[j+1]['end']<=a for j,x in enumerate(tokens))
            if not targets and not collective:continue
            segments.append({'start':a,'end':b})
            if len(ids)>=2 and (coordinated or contrast):target_pairs.append(ids)
            collective_target=collective_target or collective
        named.update(w for m in scope['mentions'] if m['certainty']=='EXPLICIT' for w in m['workIds'])
    ci,ei=set(c['workIds']),set(e['workIds']);known=c['certainty']!='UNKNOWN' and e['certainty']!='UNKNOWN'
    explicit_comparison=bool(target_pairs or (collective_target and len(named)==2))
    effect='NEUTRAL';reason='UNKNOWN_SOURCE_NEUTRAL'
    if c['ambiguous'] or e['ambiguous'] or c['conflictingObservations'] or e['conflictingObservations']:
        effect='REVIEW';reason='AMBIGUOUS_SOURCE_SCOPE'
    elif known and ci & ei:reason='SAME_WORK_ID'
    elif known and ci and ei and not ci & ei:
        if explicit_comparison:reason='EXPLICIT_COMPARISON'
        elif segments:effect='REVIEW';reason='COMPARISON_SCOPE_REQUIRES_REVIEW'
        elif c['certainty']==e['certainty']=='EXPLICIT':effect='REJECT';reason='EXPLICIT_DIFFERENT_WORK_IDS'
        else:effect='REVIEW';reason='INFERRED_CROSS_WORK_SCOPE'
    elif claim.get('workFrame') and evidence.get('workFrame') and claim['workFrame']!=evidence['workFrame']:
        effect='REVIEW';reason='UNRESOLVED_DECLARED_WORK_SCOPE'
    return {'version':'geulbit.source-relation-policy/1','claimSource':c,'evidenceSource':e,'effect':effect,
            'reasonCode':reason,'comparison':{'cueSpans':segments,'namedWorkIds':sorted(named),'explicit':explicit_comparison}}


def name_features(tokens):
    """Kiwi may split a name into adjoining NNP + NNG before its particle."""
    forms=set();actor=False
    for i,token in enumerate(tokens):
        if token['pos']!='NNP':continue
        parts=[token['form']];end=token['end'];j=i+1
        while j<len(tokens) and j<=i+2 and tokens[j]['pos'].startswith('NN') and tokens[j]['start']==end:
            parts.append(tokens[j]['form']);end=tokens[j]['end'];j+=1
        forms.update(parts)
        if j<len(tokens) and tokens[j]['pos'] in ('JKS','JX'):actor=True
    return forms,actor


def direct_reference_inputs(text, snapshot, candidates):
    """R1 grammatical/event observations only; never change candidate roles."""
    sentences={s['number']:s for s in snapshot['sentences']}
    quotes=snapshot['quotations'];references={};details={};prefix={}
    topic=re.compile(r'^\s*(?:(?:따라서|그러므로|즉)\s*[,，]?\s*)?(?P<det>이)\s*(?:(?P<count>두|세|여러)\s+)?(?P<noun>행동|장면|발언)(?P<plural>들)?(?P<particle>은|는)(?=\s|[,，]|$)')
    remote=re.compile(r'앞서(?=\s|[,，])|이전에(?=\s|[,，])|처음(?:에|의)?(?=\s|[,，])|첫\s*번째|첫\s+(?:행동|장면|발언)|앞(?:선)?\s*문단|\d+\s*문장\s*앞')
    for c in candidates:
        start,end=c['start'],c['end'];tokens=sentences[c['sentenceNumber']]['morphology']['tokens']
        local_quotes=[q for q in quotes if q['start']<end and q['end']>start]
        author=list(text[start:end])
        for q in local_quotes:
            for i in range(max(start,q['start']),min(end,q['end'])):author[i-start]=' '
        author=''.join(author)
        visible=[t for t in tokens if t['start']<t['end'] and not any(q['start']<=t['start']<q['end'] for q in local_quotes)]
        if 'EVIDENCE_CANDIDATE' in c['roles']:
            actions=sum(t['pos'].startswith('VV') and t['form'] in ACTION_LEMMAS-{'말하','외치'} for t in visible)
            utterances=max(sum(q.get('depth',0)==0 for q in local_quotes),sum(t['pos'].startswith('VV') and t['form'] in {'말','말하','외치'} for t in visible),int('CHARACTER_SPEECH' in c['evidenceTypes']))
            # An unlisted second verb must not disappear from uniqueness checks.
            # Count observed lexical predicates, without classifying their meaning.
            predicates=sum(t['pos'].startswith('VV') and t['form'] not in {'말','말하','외치'}
                           and not (i+1<len(visible) and visible[i+1]['pos']=='ETN') for i,t in enumerate(visible))
            events=max(predicates+utterances,int('SCENE_DESCRIPTION' in c['evidenceTypes']))
            prior=prefix.setdefault(c['paragraph'],{'count':0,'ids':[]})
            details[c['id']]={'actions':actions,'utterances':utterances,'events':events,'priorCount':prior['count'],'priorIds':list(prior['ids'])}
            if events and set(c['evidenceTypes'])&{'CHARACTER_ACTION','CHARACTER_SPEECH','SCENE_DESCRIPTION','DIRECT_QUOTE'}:
                prior['count']+=1;prior['ids']=(prior['ids']+[c['id']])[-8:]
        if 'CLAIM_CANDIDATE' not in c['roles']:continue
        match=topic.match(author)
        if not match:continue
        if not re.fullmatch(r'\s*(?:(?:따라서|그러므로|즉)\s*[,，]?\s*)?',text[start:start+match.start('det')]):continue
        observed=[]
        for group,pos in [('det','MM'),('noun','NNG'),('particle','JX')]:
            span=(start+match.start(group),start+match.end(group))
            token=next((t for t in visible if (t['start'],t['end'])==span and t['pos']==pos),None)
            if not token:break
            observed.append({k:token[k] for k in ['form','pos','start','end']})
        if len(observed)!=3:continue
        a,b=start+match.start('det'),start+match.end('particle');distant=remote.search(author,match.end())
        references[c['id']]={'version':'geulbit.r1.direct-reference/1','form':text[a:b],'span':{'start':a,'end':b},
            'kind':{'행동':'action','장면':'scene','발언':'speech'}[match['noun']], 'topicTokens':observed,
            'plural':bool(match['count'] or match['plural']),
            'remoteSpan':{'start':start+distant.start(),'end':start+distant.end()} if distant else None}
    return references,details


def direct_reference_decision(evidence,claim,reference,detail):
    if not reference or not detail or not detail['events']:return None
    if claim['sentenceNumber']!=evidence['sentenceNumber']+1 or claim['paragraph']!=evidence['paragraph']:return None
    if 'CLAIM_CANDIDATE' not in claim['roles'] or 'EVIDENCE_CANDIDATE' not in evidence['roles']:return None
    reasons=[]
    if reference['plural']:reasons.append('PLURAL_REFERENCE')
    if reference['remoteSpan']:reasons.append('EXPLICIT_REMOTE_REFERENCE')
    if detail['events']!=1:reasons.append('MULTIPLE_EVENTS_IN_PREVIOUS_SENTENCE')
    if detail['priorCount']:reasons.append('COMPETING_PRIOR_EVIDENCE')
    if reference['kind']=='action' and not detail['actions']:reasons.append('TARGET_KIND_UNVERIFIED')
    if reference['kind']=='speech' and not detail['utterances']:reasons.append('TARGET_KIND_UNVERIFIED')
    ework,cwork=evidence.get('workFrame'),claim.get('workFrame')
    work='CONFLICT' if ework and cwork and ework!=cwork else 'SAME_DECLARED_WORK' if ework and cwork else 'UNKNOWN'
    if work=='CONFLICT':reasons.append('DECLARED_WORK_CONFLICT')
    return {**reference,'evidenceId':evidence['id'],'claimId':claim['id'],
            'assessment':'REQUIRES_REVIEW' if reasons else 'SUFFICIENT_SIGNALS',
            'reasons':reasons or ['KIWI_DIRECT_TOPIC','ADJACENT_SAME_PARAGRAPH','UNIQUE_CONCRETE_PREVIOUS_TARGET','NO_EXPLICIT_REMOTE_OR_WORK_CONFLICT'],
            'eventCount':detail['events'],'competingEvidenceCount':detail['priorCount'],'competingEvidenceIds':detail['priorIds'],
            'workContext':work,'evidenceWorkFrame':ework,'claimWorkFrame':cwork,
            'meaning':'STRUCTURAL_REFERENCE_NOT_LOGICAL_VALIDITY'}


def relation_candidates(candidates, noun_sets, direct_references=None, evidence_details=None, *, source_information=None, source_text=None, sentence_tokens=None):
    """Bounded topic retrieval plus local frames; distance never proves support."""
    relations=[];by_number={c['sentenceNumber']:c for c in candidates}
    scopes=relation_source_scopes(candidates,source_information) if source_information and source_information['works'] else None
    # Posting lists retrieve topic-related claims anywhere in the essay.
    index={}
    for c in candidates:
        if 'CLAIM_CANDIDATE' in c['roles']:
            for noun in noun_sets[c['sentenceNumber']]:
                posting=index.setdefault(noun,[])
                if len(posting)<128:posting.append(c)
    for evidence in candidates:
        explanation=by_number.get(evidence['sentenceNumber']+1)
        keys=set(noun_sets[evidence['sentenceNumber']])
        if explanation and explanation.get('refersToPrevious'):keys.update(noun_sets[explanation['sentenceNumber']])
        disjoint=lambda c:c['id']!=evidence['id'] and (c['end']<=evidence['start'] or evidence['end']<=c['start'])
        retrieved={c['id']:c for key in keys for c in index.get(key,[]) if disjoint(c)}
        # Preserve bounded explicit-work retrieval without using distance as proof.
        local=(by_number.get(n) for n in range(evidence['sentenceNumber']-12,evidence['sentenceNumber']+13))
        retrieved.update({c['id']:c for c in local if c and 'CLAIM_CANDIDATE' in c['roles'] and disjoint(c) and abs(evidence['paragraph']-c['paragraph'])<=2})
        if 'EVIDENCE_CANDIDATE' in evidence['roles']:
            ranked=[]
            for claim in retrieved.values():
                distance=abs(evidence['sentenceNumber']-claim['sentenceNumber'])
                shared=sorted(noun_sets[claim['sentenceNumber']] & noun_sets[evidence['sentenceNumber']])
                explanation=by_number.get(evidence['sentenceNumber']+1)
                explained_shared=[]
                if (explanation and explanation['id']!=claim['id']
                    and explanation['paragraph']==evidence['paragraph'] and explanation.get('refersToPrevious')
                    and (set(noun_sets[evidence['sentenceNumber']]) & noun_sets[explanation['sentenceNumber']] or set(evidence.get('actionLemmas',[])) & set(explanation.get('actionLemmas',[])) or 'DIRECT_QUOTE' in evidence['evidenceTypes'])):
                    explained_shared=sorted(noun_sets[claim['sentenceNumber']] & noun_sets[explanation['sentenceNumber']])
                follows_explanation=len(explained_shared)>=2 or (claim['paragraph']==evidence['paragraph'] and bool(set(explained_shared)&INTERPRETATION_NOUNS))
                if follows_explanation:shared=sorted(set(shared)|set(explained_shared))
                same=claim['paragraph']==evidence['paragraph']
                bridge=bool(evidence['connectionSignals']) or follows_explanation
                scoped_work=claim['explicitWorkTopic'] and 'WORK_EVENT_REFERENCE' in evidence['evidenceTypes'] and same and distance<=2
                if not scopes and claim.get('workFrame') and evidence.get('workFrame') and claim['workFrame']!=evidence['workFrame']:continue
                if not shared and not scoped_work:continue
                if (distance>12 or abs(evidence['paragraph']-claim['paragraph'])>2) and not (follows_explanation and len(explained_shared)>=2):continue
                if not same and len(shared)<2 and not (shared and bridge):continue
                score=min(len(shared),3)*2+int(same)+int(distance<=3)+int(bridge)+int(scoped_work)*2
                if score<4:continue
                signals=[]
                if shared:signals.append('SHARED_TOPIC_NOUNS')
                if same:signals.append('SAME_PARAGRAPH')
                if bridge:signals.append('EXPLICIT_CONNECTION_EXPRESSION')
                if scoped_work:signals.append('EXPLICIT_SAME_WORK_FRAME')
                if follows_explanation:signals.append('FOLLOWING_QUOTE_EXPLANATION')
                ranked.append((score,claim,shared,signals,explanation if follows_explanation else None))
            ranked.sort(key=lambda r:(-r[0],r[1]['sentenceNumber']))
            # Text-order expansion must not erase an existing decision. Keep
            # the original competition/margin within each orientation, without
            # relabeling a following interpretation as a new semantic role.
            claim_first=[r for r in ranked if r[1]['end']<=evidence['start']]
            evidence_first=[r for r in ranked if evidence['end']<=r[1]['start']]
            def winner(group):
                return group[0] if group and (len(group)==1 or group[0][0]-group[1][0]>=2) else None
            forward=winner(claim_first);reverse=winner(evidence_first)
            selected=forward
            # Search candidates remain in retrieved for the frozen evaluator.
            # Do not emit a second relation or turn new weak candidates into
            # REVIEW noise. Unresolved prior competition also remains unresolved.
            if not claim_first and reverse and reverse[0]>=7:selected=reverse
            if selected:
                score,claim,shared,signals,explanation=selected
                relations.append({'id':f"relation-{claim['sentenceNumber']}-{evidence['sentenceNumber']}",
                    'claimId':claim['id'],'evidenceId':evidence['id'],
                    'claimSentence':claim['sentenceNumber'],'evidenceSentence':evidence['sentenceNumber'],
                    'claimSpan':{'start':claim['start'],'end':claim['end']},
                    'evidenceSpan':{'start':evidence['start'],'end':evidence['end']},
                    'sameParagraph':claim['paragraph']==evidence['paragraph'],
                    'sentenceDistance':abs(evidence['sentenceNumber']-claim['sentenceNumber']),
                    'paragraphDistance':abs(evidence['paragraph']-claim['paragraph']),
                    'direction':'EVIDENCE_TO_CLAIM',
                    'textOrder':'CLAIM_FIRST' if claim['end']<=evidence['start'] else 'EVIDENCE_FIRST',
                    'sharedNouns':shared,'signals':signals,'score':score,
                    'confidence':'STRONG_SIGNALS' if score>=7 else 'REVIEW_SIGNALS',
                    'assessment':'SUFFICIENT_SIGNALS' if score>=7 else 'REQUIRES_REVIEW',
                    'interpretation':'STRUCTURAL_SUPPORT_CANDIDATE_NOT_LOGICAL_VALIDITY'})
                if explanation:relations[-1]['followingExplanation']={'sentenceNumber':explanation['sentenceNumber'],'span':{'start':explanation['start'],'end':explanation['end']}}
            # R1 is independent of lexical scores and orientation competition.
            # Only the immediately following claim can have this direct target.
            claim=by_number.get(evidence['sentenceNumber']+1)
            receipt=direct_reference_decision(evidence,claim,(direct_references or {}).get(claim['id']),(evidence_details or {}).get(evidence['id'])) if claim else None
            if receipt:
                existing=next((r for r in relations if r['claimId']==claim['id'] and r['evidenceId']==evidence['id']),None)
                link=existing if existing is not None else {'id':f"relation-{claim['sentenceNumber']}-{evidence['sentenceNumber']}",
                    'claimId':claim['id'],'evidenceId':evidence['id'],'claimSentence':claim['sentenceNumber'],'evidenceSentence':evidence['sentenceNumber'],
                    'claimSpan':{'start':claim['start'],'end':claim['end']},'evidenceSpan':{'start':evidence['start'],'end':evidence['end']},
                    'sameParagraph':True,'sentenceDistance':1,'paragraphDistance':0,'direction':'EVIDENCE_TO_CLAIM','textOrder':'EVIDENCE_FIRST',
                    'sharedNouns':sorted(noun_sets[claim['sentenceNumber']]&noun_sets[evidence['sentenceNumber']]),'signals':[],'score':None,
                    'interpretation':'STRUCTURAL_SUPPORT_CANDIDATE_NOT_LOGICAL_VALIDITY'}
                link.update({'approvalRoute':'R1_DIRECT_REFERENCE','directReference':receipt,'assessment':receipt['assessment'],
                             'scoreMeaning':'R1_FORMAL_GUARDS_NOT_PROBABILITY',
                             'confidence':'STRONG_SIGNALS' if receipt['assessment']=='SUFFICIENT_SIGNALS' else 'REVIEW_SIGNALS'})
                link['signals']=list(dict.fromkeys(link['signals']+['R1_DIRECT_REFERENCE']+receipt['reasons']))
                if existing is None:relations.append(link)
    if scopes:
        source_observable=False
        for link in relations:
            claim=by_number[link['claimSentence']];evidence=by_number[link['evidenceSentence']]
            policy=source_relation_policy(claim,evidence,scopes,source_text,sentence_tokens=sentence_tokens)
            ref=link.get('directReference')
            # Replace only the legacy text-name source guard when registered
            # work identity/comparison is verified. R1 grammatical/event guards
            # and all general scores/margins remain exactly the existing ones.
            if (ref and ref['assessment']=='REQUIRES_REVIEW' and ref['reasons']==['DECLARED_WORK_CONFLICT']
                and policy['effect']=='NEUTRAL' and policy['reasonCode'] in {'SAME_WORK_ID','EXPLICIT_COMPARISON'}):
                ref.update(assessment='SUFFICIENT_SIGNALS',reasons=['VERIFIED_WORK_ID_SOURCE_GUARD'],sourceGuardOverride=True)
                link.update(assessment='SUFFICIENT_SIGNALS',confidence='STRONG_SIGNALS')
            source_observable=source_observable or policy['effect']!='NEUTRAL' or bool(ref and ref.get('sourceGuardOverride')) or bool(claim.get('workFrame') and evidence.get('workFrame') and claim['workFrame']!=evidence['workFrame'])
            link['anchorAssessment']=link['assessment'];link['sourceDecision']=policy
            if policy['effect']!='NEUTRAL':
                link['assessment']='REJECTED' if policy['effect']=='REJECT' else 'REQUIRES_REVIEW'
                link['confidence']='SOURCE_REJECTED' if policy['effect']=='REJECT' else 'REVIEW_SIGNALS'
        # Purely neutral source preparation preserves the existing /8 result.
        # A /9 snapshot is introduced only when source policy changes observable
        # decisions or resolves a former text-name conflict.
        if not source_observable:
            for link in relations:
                del link['anchorAssessment'];del link['sourceDecision']
    return relations


def _nominal_surface_key(text, part):
    """Exact normalized source slice of an already bounded nominal phrase.

    POS still qualifies the phrase; neither POS nor token segmentation defines
    its identity. No spelling, spacing, possessors or name parts are removed.
    """
    if not part or not part[0]['pos'].startswith(('NN','NP')) or not part[-1]['pos'].startswith(('NN','NP')):
        return None
    previous_end=None
    for token in part:
        start,end=token['start'],token['end']
        if (type(start) is not int or type(end) is not int or not 0<=start<end<=len(text)
            or (previous_end is not None and start<previous_end)
            or not (token['pos'].startswith(('NN','NP')) or token['pos']=='JKG')):
            return None
        previous_end=end
    surface=text[part[0]['start']:part[-1]['end']]
    return surface if surface.strip() else None


def analyze_structure(text, *, version_id, disabled_rules=(), vocabulary=(), source_information=None):
    text = normalize_text(text)
    result = analyze_snapshot(text, version_id=version_id)
    candidates, noun_sets, by_paragraph = [], {}, {}
    work_frame=None
    literary_paragraph=None
    previous_declared_scope=None

    def nominal_at(part,case_index):
        # Surface-bound nominal head/possessor, not a semantic entity resolver.
        first=case_index-1
        if first<0 or not part[first]['pos'].startswith(('NN','NP')):return None
        while first:
            before=part[first-1]
            if before['pos'].startswith(('NN','NP')) and before['end']==part[first]['start']:
                first-=1
            elif before['pos']=='JKG' and first>=2 and part[first-2]['pos'].startswith(('NN','NP')):
                first-=2
            else:break
        key=_nominal_surface_key(text,part[first:case_index])
        if key is None:return None
        return {'first':first,'case':case_index,'key':key,
                'start':part[first]['start'],'head':part[case_index-1]}

    def subject_before(part,stop,lower):
        subjects=[nominal_at(part,j) for j,t in enumerate(part[:stop])
                  if t['start']>=lower and t['pos'] in {'JKS','JX'}]
        subjects=[s for s in subjects if s]
        discarded=set()
        # A subject in "I attend + ETM + school + topic" belongs to the
        # modifier. Its later nominal head is the actual event subject.
        nominal_tags={'NNG','NNP','NNB','NP','MM','JKG','XSN'}
        for left,right in zip(subjects,subjects[1:]):
            endings=[j for j in range(left['case']+1,right['case']) if part[j]['pos']=='ETM']
            if endings and all(t['pos'] in nominal_tags for t in part[endings[-1]+1:right['case']]):
                discarded.add(left['case'])
        # A separate subject inside an object's relative clause is not the
        # outer event actor. Ambiguous remaining subjects cause abstention.
        for j,t in enumerate(part[:stop]):
            if t['pos']!='ETM':continue
            tail=j+1
            while tail<stop and part[tail]['pos'] in nominal_tags:tail+=1
            prior=[s for s in subjects if s['case']<j and s['case'] not in discarded]
            if tail<stop and part[tail]['pos']=='JKO' and len(prior)>1:
                discarded.add(prior[-1]['case'])
        subjects=[s for s in subjects if s['case'] not in discarded]
        return subjects[0] if len(subjects)==1 else None
    for sentence in result["sentences"]:
        start, end = sentence["start"], sentence["end"]
        value = text[start:end]
        quotes = [q for q in result["quotations"] if q["start"] < end and q["end"] > start]
        # A quotation's speaker is not automatically the essay author's claim.
        unquoted=list(value)
        for q in quotes:
            for i in range(max(start,q['start']),min(end,q['end'])):unquoted[i-start]=' '
        author_text=''.join(unquoted)
        explicit_frame=re.search(r'(?:소설|시|희곡)\s*[「〈<]([^」〉>]+)[」〉>]',author_text)
        if explicit_frame:
            work_frame=explicit_frame.group(1)
            literary_paragraph=None
        tokens=sentence['morphology']['tokens']
        declared_scope_start=None
        location=next((t for t in tokens if explicit_frame and t['pos']=='JKB' and t['form']=='에서'
                       and t['start']>=start+explicit_frame.end()
                       and not author_text[explicit_frame.end():t['start']-start].strip()),None)
        if location:
            # Reading/naming a book is not a declaration that the following
            # school rules or essay instructions are events in that book.
            literary_paragraph=sentence['paragraph']
            declared_scope_start=location['end']
        name_nouns,named_actor=name_features(tokens)
        nouns={t['form'] for t in tokens if t['pos'].startswith('NN')}
        has_predicate=any(t['pos'].startswith(('VV','VA','VCP','XSV','XSA')) for t in tokens)
        claim = [x for x in CLAIM_CLUES if x in author_text]
        if '생각한다' in claim and not re.search(r'(?:다고|라고|것|필요|중요|의미|가치).{0,24}생각한다',author_text):claim.remove('생각한다')
        if not (nouns & {'사랑','희생','헌신','자유','책임','용기','관계','삶','태도','가치','선택','성장','의미','연대','권력','불평등'}):
            claim=[x for x in claim if x not in ('드러낸다','보여준다','보여 준다')]
        evaluative=bool(re.search(r'(?:가치|의미|사랑|중요성|헌신|희생).*(?:작품이다|형태|보여|드러|상징|조명|것이다)',author_text))
        if evaluative:claim.append('EVALUATIVE_INTERPRETATION')
        # Interpretive nominal/comparative predicates need abstract concepts
        # and a real predicate; a scene description or isolated cue is insufficient.
        conceptual=bool(nouns & INTERPRETATION_NOUNS)
        nominal=bool(re.search(r'(?:태도|선택|경계|뜻|표현|실천|일)(?:이|인 것)(?:다|라고|라는)',author_text))
        comparative=bool(re.search(r'(?:보다|대신|아니라).*(?:가깝다|일이다|태도이다|선택이다)',author_text))
        conclusion=bool(re.match(r'\s*(?:따라서|결국|그러므로)',author_text) and len(nouns&INTERPRETATION_NOUNS)>=2)
        if conceptual and (nominal or comparative or conclusion):claim.append('CONCEPTUAL_INTERPRETATION')
        # Author interpretation, not literal reading or an attributed claim.
        # Require the observed topic, interpretive complement and terminal
        # declarative morphology; this supplies a role cue, not an approval.
        author_tokens=[t for t in tokens if t['start']<t['end'] and not any(q['start']<=t['start']<q['end'] for q in quotes)]
        interpretive_topic=(len(author_tokens)>=3 and (author_tokens[0]['form'],author_tokens[0]['pos'])==('이','MM')
                            and author_tokens[1]['form'] in {'행동','장면','발언','작품'} and author_tokens[1]['pos']=='NNG'
                            and author_tokens[2]['form'] in {'은','는'} and author_tokens[2]['pos']=='JX')
        for i,t in enumerate(author_tokens):
            if not interpretive_topic or i<2 or (t['form'],t['pos'])!=('읽히','VV'):continue
            head,particle=author_tokens[i-2:i];tail=author_tokens[i+1:]
            complement=author_tokens[3:i-2]
            interpreted_process=head['form'] not in {'과정','변화'}
            work_interpretation=head['form'] in INTERPRETATION_NOUNS
            process_predicate=direct_object=None
            if not interpreted_process and complement and complement[-1]['pos']=='ETM':
                p=len(complement)-2
                # Keep inner "-지 않-" on the same predicate, unlike negating
                # the final reading predicate. Other auxiliary chains abstain.
                if p>=2 and (complement[p]['form'],complement[p]['pos'])==('않','VX') and (complement[p-1]['form'],complement[p-1]['pos'])==('지','EC'):
                    p-=2
                if p>=0:
                    process_predicate=complement[p]
                    verbal=process_predicate['pos'].startswith('VV') and process_predicate['form'] not in {'읽','읽히'}
                    denominal=(process_predicate['pos']=='XSV' and p>0 and complement[p-1]['pos']=='NNG')
                    # Bound the direct argument after the latest clause/subject
                    # boundary. A previous modifier or connective is not a
                    # dependency link; Kiwi does not supply a dependency tree.
                    boundary=max((j for j,x in enumerate(complement[:p]) if x['pos'] in {'ETM','JKS','EC'}),default=-1)
                    objects=[j for j in range(boundary+1,p) if complement[j]['pos']=='JKO']
                    if len(objects)==1 and objects[0]>boundary+1 and complement[objects[0]-1]['pos']=='NNG':
                        direct_object=complement[objects[0]-1]
                        interpreted_process=verbal or denominal
                        # Only the argument head counts: "의미 단위" has head
                        # "단위", and a student's "경험" is in another clause.
                        # Work/process readings with a denominal or unclear
                        # center remain unsupported by this narrow new cue.
                        work_interpretation=(verbal and direct_object['form'] in INTERPRETATION_NOUNS)
            if author_tokens[1]['form']!='작품':work_interpretation=True
            if (head['pos']=='NNG' and head['form'] in INTERPRETATION_NOUNS|{'과정','변화'}
                and interpreted_process and work_interpretation
                and particle['pos']=='JKB' and particle['form'] in {'로','으로'}
                and tail and tail[0]['pos']=='EF' and tail[0]['form'] in {'ᆫ다','ㄴ다','는다','다'}
                and all(x['pos']=='SF' and x['form'] not in {'?','？'} for x in tail[1:])):
                claim.append('EXPLICIT_INTERPRETIVE_READING');break
        # Extend only missing role observations. Existing cues and the S3
        # reading-complement path above remain independent and unchanged.
        # A title supplies bounded literary context, never relationship points.
        literary_context=bool(work_frame and literary_paragraph==sentence['paragraph'])
        observed_tokens=[t for t in author_tokens if not explicit_frame or not
                         start+explicit_frame.start()<=t['start']<start+explicit_frame.end()]
        final_tokens=[t for t in observed_tokens if t['pos']!='SF']
        factual=bool(final_tokens and final_tokens[-1]['pos']=='EF'
                     and final_tokens[-1]['form'] in {'다','ᆫ다','ㄴ다','는다'}
                     and not any(t['pos']=='EC' and t['form'].endswith('면') for t in observed_tokens))
        if not claim and interpretive_topic and factual and any(x in author_text for x in CLAIM_CLUES if x in {'보여준다','보여 준다'}):
            for i,t in enumerate(observed_tokens):
                if (t['form'],t['pos'])!=('보이','VV') or i<2:continue
                head,particle=observed_tokens[i-2:i];tail=observed_tokens[i+1:]
                if (head['pos']=='NNG' and head['form'] in INTERPRETATION_NOUNS|{'비극'}
                    and particle['pos']=='JKO' and len(tail)>=3
                    and (tail[0]['form'],tail[0]['pos'])==('어','EC')
                    and (tail[1]['form'],tail[1]['pos'])==('주','VX') and tail[2]['pos']=='EF'
                    and all(x['pos']=='SF' for x in tail[3:])):
                    claim.append('LITERARY_INTERPRETIVE_SHOWING');break
        if not claim and literary_context and factual:
            for i,t in enumerate(observed_tokens):
                # Quoted proposition + terminal "can be viewed" is inference;
                # bare "can see" and somebody reporting it are not this form.
                if (t['form'],t['pos'])!=('보','VV') or i<4:continue
                prior=observed_tokens[i-1];tail=observed_tokens[i+1:]
                concept,origin,predicate=observed_tokens[i-4:i-1]
                subject=subject_before(observed_tokens,i-2,declared_scope_start or start)
                # Supported local proposition: subject + interpretation head
                # FROM + emerge + -다고 볼 수 있다. The concept must be the
                # predicate's actual immediately observed origin argument.
                attributed=bool(subject and (declared_scope_start is not None or
                                 (previous_declared_scope and previous_declared_scope['paragraph']==sentence['paragraph']
                                  and previous_declared_scope['work']==work_frame and subject['key'] in previous_declared_scope['participants'])))
                if (prior['pos']=='EC' and prior['form'] in {'다고','ᆫ다고','ㄴ다고','는다고','라고'}
                    and (predicate['form'],predicate['pos'])==('나오','VV')
                    and (origin['form'],origin['pos'])==('에서','JKB')
                    and concept['pos']=='NNG' and concept['form'] in INTERPRETATION_NOUNS|{'책임감'} and attributed
                    and len(tail)>=4 and tail[0]['pos']=='ETM' and tail[0]['form'] in {'ᆯ','ㄹ'}
                    and (tail[1]['form'],tail[1]['pos'])==('수','NNB')
                    and (tail[2]['form'],tail[2]['pos'])==('있','VA') and tail[3]['pos']=='EF'
                    and all(x['pos']=='SF' for x in tail[4:])):
                    claim.append('LITERARY_INFERENTIAL_VIEW');break
        qualifies_claim=bool(claim and nouns and has_predicate)
        connection=[x for x in ('예를 들어','이를 뒷받침','그 이유','이러한','이처럼','이 구절','이 장면','특히','실제로') if x in value]
        evidence = []
        if quotes: evidence.append("DIRECT_QUOTE")
        page_reference=bool(re.search(r'\d+\s*(?:쪽|페이지)(?:에|에서|의|[,.)\s]|$)',value))
        if page_reference:evidence.append('PAGE_REFERENCE')
        frame=bool(re.search(r'작품에서|시인은|화자는|주인공|인물은|인물이|그는|그녀는|소설에서|시에서|장면에서|(?:소설|희곡)\s+.{1,20}에서',value)) or named_actor or bool(nouns & {w for w in vocabulary if isinstance(w,str)})
        action=any(t['pos'].startswith('VV') and t['form'] in ACTION_LEMMAS
                   and not (i+1<len(tokens) and tokens[i+1]['pos']=='ETN') for i,t in enumerate(tokens))
        speech=any(x in value for x in ('말했다','외쳤다','대사','말한다'))
        if frame and speech:evidence.append('CHARACTER_SPEECH')
        if frame and action:evidence.append('CHARACTER_ACTION')
        if frame and has_predicate and any(x in value for x in ('장면','풍경','배경')):evidence.append('SCENE_DESCRIPTION')
        if frame and (action or quotes or page_reference):evidence.append('WORK_EVENT_REFERENCE')
        scoped_actions=set();event_state=False
        # These are observed transitive event forms inside a declared work's
        # same paragraph. Do not extend ACTION_LEMMAS: R1 event/uniqueness and
        # competing-target rules must retain their original observations.
        event_report=not any((t['pos']=='EC' and t['form'].endswith(('다고','라고')))
                             or (t['pos']=='ETM' and t['form'].endswith(('다는','라는'))) for t in observed_tokens)
        if not (action or quotes or page_reference) and literary_context and factual and event_report:
            for i,t in enumerate(observed_tokens):
                subject=subject_before(observed_tokens,i,declared_scope_start or start)
                if not subject:continue
                prefix=[x for x in observed_tokens if (declared_scope_start or start)<=x['start']<subject['start']]
                closed_background=any(x['pos']=='EC' for x in prefix) or any(
                    x['pos']=='ETM' and j+1<len(prefix) and prefix[j+1]['form'] in {'뒤','후','때'} for j,x in enumerate(prefix))
                direct_scope=declared_scope_start is not None and not closed_background
                adjacent=bool(previous_declared_scope and previous_declared_scope['paragraph']==sentence['paragraph']
                              and previous_declared_scope['work']==work_frame)
                repeated_subject=adjacent and subject['key'] in previous_declared_scope['participants']
                order_reference=False
                if adjacent and previous_declared_scope['prohibitions']==1:
                    for j in range(2,i):
                        if ((observed_tokens[j-2]['form'],observed_tokens[j-2]['pos'])==('그','MM')
                            and (observed_tokens[j-1]['form'],observed_tokens[j-1]['pos'])==('명령','NNG')
                            and observed_tokens[j]['pos']=='JKO' and j+1<=i
                            and observed_tokens[j+1]['form']=='어기' and observed_tokens[j+1]['pos'].startswith('VV')):
                            actor=subject_before(observed_tokens,j+1,start)
                            order_reference=bool(actor and actor['key']==subject['key'])
                if not (direct_scope or repeated_subject or order_reference):continue
                if (t['form'],t['pos'])==('숨지','VV'):
                    tail=observed_tokens[i+1:]
                    if len(tail)>=3 and (tail[0]['form'],tail[0]['pos'])==('어','EC') and (tail[1]['form'],tail[1]['pos'])==('있','VX') and tail[2]['pos']=='EF':
                        event_state=True
                verb=t['pos'].startswith('VV') and t['form'] in {'업','어기','행하'}
                prohibition=(t['form'],t['pos'])==('하','XSV') and i and (observed_tokens[i-1]['form'],observed_tokens[i-1]['pos'])==('금지','NNG')
                if not (verb or prohibition):continue
                boundary=max((j for j,x in enumerate(observed_tokens[:i]) if x['pos'] in {'ETM','JKS','EC'}),default=-1)
                objects=[j for j in range(boundary+1,i) if observed_tokens[j]['pos']=='JKO']
                if len(objects)!=1 or objects[0]<=boundary+1 or not observed_tokens[objects[0]-1]['pos'].startswith('NN'):continue
                # A connective/adnominal/finite event is required; nominalized
                # instructions and an unbounded word occurrence do not qualify.
                if i+1==len(observed_tokens) or observed_tokens[i+1]['pos'] not in {'EC','EP','EF'}:continue
                scoped_actions.add('금지하' if prohibition else t['form'])
            if event_state:
                evidence.extend(['CONCRETE_EVENT_STATE','SCENE_DESCRIPTION','WORK_EVENT_REFERENCE'])
            if scoped_actions:
                evidence.extend(['SCOPED_TRANSITIVE_EVENT','CHARACTER_ACTION'])
                if 'WORK_EVENT_REFERENCE' not in evidence:evidence.append('WORK_EVENT_REFERENCE')
        page_context=frame or bool(nouns & {'책','소설','시','희곡','원문','판본','인물','화자'})
        qualifies_evidence=bool(quotes or (page_reference and page_context and has_predicate and nouns) or (frame and action and nouns) or event_state or scoped_actions)
        roles=(['CLAIM_CANDIDATE'] if qualifies_claim else [])+(['EVIDENCE_CANDIDATE'] if qualifies_evidence else [])
        item = {"id":f"sentence-{sentence['number']}","sentenceNumber": sentence["number"], "paragraph": sentence["paragraph"],
                "start": start, "end": end, "claimSignals": claim, "evidenceTypes": evidence,
                'actionLemmas':sorted({t['form'] for t in tokens if t['pos'].startswith('VV') and t['form'] in ACTION_LEMMAS}|scoped_actions),
                'roles':roles,'workFrame':work_frame,'connectionSignals':connection,'explicitWorkTopic':bool(re.search(r'이 작품|이 소설|이 시',author_text)),
                'refersToPrevious':bool(re.match(r'\s*(?:이는|이것은|이 말은|이 구절은|이 대사는|이 행동은|이 장면은|이 기다림은|그가)(?:\s|[,，])',author_text)),
                "explanationSignals": [x for x in EXPLANATION_CLUES if x in value],
                "scores": {"CLAIM_CANDIDATE": len(claim), "EVIDENCE_CANDIDATE": len(evidence),
                           "OTHER": int(not claim and not evidence)},
                "scoreMeaning": "OBSERVED_SIGNAL_COUNT_NOT_PROBABILITY"}
        candidates.append(item)
        # Only the immediately preceding explicit, unquoted work declaration
        # can supply participant/order anchors. Never propagate a name through
        # the document or treat a role prediction as independent source proof.
        previous_declared_scope=None
        if declared_scope_start is not None and factual and event_report:
            part=[x for x in observed_tokens if x['start']>=declared_scope_start]
            participants={n['key'] for j,x in enumerate(part) if x['pos'] in {'JKS','JX','JKO'}
                          for n in [nominal_at(part,j)] if n and n['head']['pos'].startswith('NN')}
            prohibitions=sum((x['form'],x['pos'])==('금지','NNG') and j+2<len(part)
                             and (part[j+1]['form'],part[j+1]['pos'])==('하','XSV')
                             and part[j+2]['pos'] in {'EP','EF'} for j,x in enumerate(part))
            previous_declared_scope={'paragraph':sentence['paragraph'],'work':work_frame,
                                     'participants':participants,'prohibitions':prohibitions}
        by_paragraph.setdefault(sentence["paragraph"], []).append(item)
        # A recurring character's name alone is not a support signal. Keep it
        # in sentence morphology, but remove all its split forms from overlap.
        noun_sets[sentence['number']]=nouns-GENERIC_NOUNS-name_nouns
    references,evidence_details=direct_reference_inputs(text,result,candidates)
    relations=(relation_candidates(candidates,noun_sets,references,evidence_details,source_information=source_information,source_text=text,
                                  sentence_tokens={s['number']:s['morphology']['tokens'] for s in result['sentences']})
               if source_information is not None else relation_candidates(candidates,noun_sets,references,evidence_details))
    structure_findings = []
    for item in candidates:
        examined = by_paragraph[item["paragraph"]]
        if 'CLAIM_CANDIDATE' in item['roles'] and not any('EVIDENCE_CANDIDATE' in s['roles'] for s in examined):
            structure_findings.append({"start": item["start"], "end": item["end"], "tier": "확인 필요",
                                       "kind": "LOCAL_EVIDENCE_REVIEW", "examinedParagraph": item["paragraph"],
                                       "reason": "이 문단의 규칙 범위에서 근거 후보가 적게 탐지되었습니다. 근거의 실제 존재 여부는 직접 확인해 주세요."})
        if "DIRECT_QUOTE" in item["evidenceTypes"]:
            following = next((s for s in examined if s["sentenceNumber"] == item["sentenceNumber"]+1), None)
            explained=bool(following and (following['explanationSignals'] or (following['refersToPrevious'] and 'CONCEPTUAL_INTERPRETATION' in following['claimSignals'])))
            if not item["explanationSignals"] and not explained:
                structure_findings.append({"start": item["start"], "end": item["end"], "tier": "확인 필요",
                                           "kind": "QUOTE_CONNECTION_REVIEW", "examinedParagraph": item["paragraph"],
                                           "reason": "이 인용문과 같은 문단의 바로 다음 문장에서 연결 설명을 확인해 주세요."})
    result.update({"roleCandidates": candidates, "relations": relations,
                   "findings": local_findings(text, disabled=disabled_rules, vocabulary=vocabulary, snapshot=result, candidates=candidates)+structure_findings})
    result["manifest"].update({"rulesetVersion": RULESET_VERSION, "rulesetHash": ruleset_hash(), "normsCatalogue": catalogue_manifest(),
                              'structureVersion':'geulbit.structure/9' if any('sourceDecision' in r for r in relations) else STRUCTURE_VERSION,'relationConfiguration':{'retrieval':'WHOLE_ESSAY_TOPIC_POSTINGS','maximumClaimsPerTopic':128,'legacyLocalWindow':12,'distantRequiresExplanation':True,'minimumSignalScore':4,'ambiguityMargin':2,'sameParagraphInterpretiveExplanation':True,'namesAloneSupport':False,'scoreMeaning':'STRUCTURAL_SIGNAL_COUNT_NOT_PROBABILITY','competition':'TEXT_ORDER_PARTITIONS_PRESERVE_FORWARD_DECISION','reverseOutput':'SUFFICIENT_SIGNALS_ONLY_WITHOUT_QUALIFYING_FORWARD_COMPETITION','r1':'KIWI_VERIFIED_ADJACENT_DIRECT_TOPIC_UNIQUE_TARGET/v1'},
                              "rulesConfiguration": {"disabled": sorted(disabled_rules), "vocabulary": sorted(vocabulary)}})
    result["limitations"] += ["후보 점수는 관찰한 단서 수입니다. 주장의 진위나 논리적 타당성을 채점하지 않습니다.",
                               "관계 후보는 전체 글의 주제어 색인으로 검색합니다. 장거리 연결에는 설명 문장의 추가 근거가 필요하며 불확실한 후보는 화살표로 표시하지 않습니다."]
    validate_snapshot(result,text,version_id=version_id)
    return result
