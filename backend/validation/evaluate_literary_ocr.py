"""Paired OCR metrics, with data provenance and group-disjoint split validation.

Consumes frozen local references and actual page results. Does not infer labels,
modify an OCR draft, run an external service or certify synthetic test data.
"""
import argparse,hashlib,json,random,re,unicodedata
from collections import defaultdict,Counter
from pathlib import Path
from rapidfuzz.distance import Levenshtein

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def cer(reference,text):
    errors=Levenshtein.distance(reference,text)
    return {'errors':errors,'referenceCodePoints':len(reference),'CER':errors/len(reference) if reference else None}

def character_diagnostic(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def error_units(reference,text):
    """Alignment-dependent edit units; not a semantic correctness judgment."""
    units=set()
    for op in Levenshtein.editops(reference,text):
        units.add((op.tag,op.src_pos,text[op.dest_pos] if op.tag!='delete' else ''))
    return units


def structured_table_metrics(reference,page):
    """Separate cell correctness from unobservable counts of printed spaces."""
    labels=reference.get('tableCells')
    if labels is None:return None
    actual=[c for t in page.get('structure',{}).get('tables',[]) for c in t.get('cells',[])]
    def key(c):return (c['row'],c['column'],c.get('rowSpan',1),c.get('columnSpan',c.get('colSpan',1)),c['text'])
    expected_counts=Counter(key(c) for c in labels);actual_counts=Counter(key(c) for c in actual)
    true=sum((expected_counts&actual_counts).values());false=sum((actual_counts-expected_counts).values());missing=sum((expected_counts-actual_counts).values())
    def content(cells):return '\n'.join(c['text'] for c in sorted(cells,key=lambda c:(c['row'],c['column'])))
    return {'expectedCells':len(labels),'actualCells':len(actual),'TP':true,'FP':false,'FN':missing,
            'exactCellPrecision':true/(true+false) if true+false else None,'exactCellRecall':true/(true+missing) if true+missing else None,
            'cellTextCER':cer(content(labels),content(actual)),
            'definition':'Explicit row/column/span/text labels, not inferred page whitespace; separate from unchanged full-page strict CER'}


def extended_metrics(reference,page):
    expected=reference['text'];text=page['draft']['text'];ops=Levenshtein.editops(expected,text)
    predicted=Counter(x for x in text.splitlines() if x.strip());actual=Counter(x for x in expected.splitlines() if x.strip())
    result={'whitespaceExcludedDiagnostic':cer(''.join(expected.split()),''.join(text.split())),
            'editOperations':dict(Counter(op.tag for op in ops)),
            'missingExactLines':sum((actual-predicted).values()),'extraOrDuplicateExactLines':sum((predicted-actual).values()),
            'minimumManualCodePointEdits':len(ops),'actualHumanReviewSeconds':reference.get('humanReviewSeconds'),
            'seconds':page.get('seconds'),'peakJobCommitBytes':page.get('measurement',{}).get('peakJobCommitBytes'),
            'executedModelCalls':page.get('calls',[]),'modelFingerprint':page.get('fingerprint')}
    before=page.get('precision',{}).get('before',{}).get('text')
    result['automaticSelection']=None
    if before is not None:
        old=error_units(expected,before);new=error_units(expected,text)
        result['automaticSelection']={'beforeStrict':cer(expected,before),'afterStrict':cer(expected,text),
            'newErrorUnits':len(new-old),'removedErrorUnits':len(old-new),
            'definition':'Reference-aligned edit units; insertions and repeated characters can have ambiguous alignment',
            'decisionsApplied':sum(d['status']=='APPLIED' for d in page['precision']['decisions'])}
    labels=reference.get('lines',[]);selected=[l for l in page.get('lines',[]) if l.get('includedInDraft',True)]
    geometry=[];used=set()
    for label in labels:
        a=label['box'];candidates=[]
        for i,line in enumerate(selected):
            if i in used:continue
            b=line['box'];inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
            candidates.append((inter/max(1,union),i))
        overlap,index=max(candidates,default=(0,None));found=index is not None and overlap>=label.get('minimumIoU',.3)
        if found:used.add(index)
        geometry.append({'referenceLineId':label['id'],'matchedLineId':selected[index].get('id') if found else None,'IoU':overlap,'found':found,
            'literalExact':found and selected[index]['text']==label['text'],'referenceKind':label.get('kind'),'referenceIndentPixels':label.get('indentPixels')})
    result['lineGeometry']=geometry if labels else None
    ordered=[g['matchedLineId'] for g in geometry if g['found']]
    emitted=[m['lineId'] for m in page.get('draft',{}).get('lineMap',[]) if m['lineId'] in ordered]
    result['labelledReadingOrder']=(None if not labels else
        {'measurable':False,'reason':'MISSING_GEOMETRY_OR_DRAFT_LINE_MAP','expectedLines':len(labels),'matchedLines':len(ordered)}
        if len(ordered)!=len(labels) or len(emitted)!=len(ordered) else
        {'measurable':True,'exact':emitted==ordered,'expectedLines':len(labels),'matchedLines':len(ordered)})
    result['geometricMissingLines']=sum(not l['found'] for l in geometry) if labels else None
    local=[]
    for g,label in zip(geometry,labels):
        if not g['found']:continue
        line=next(l for l in selected if l.get('id')==g['matchedLineId'])
        old=line.get('originalText',line['text']) if line.get('originalIncludedInDraft',True) else ''
        if old==line['text']:continue
        prior=error_units(label['text'],old);after=error_units(label['text'],line['text'])
        local.append({'referenceLineId':label['id'],'beforeErrors':len(prior),'afterErrors':len(after),'newErrorUnits':len(after-prior),'removedErrorUnits':len(prior-after)})
    result['coordinateMatchedAutomaticTextErrors']=local if labels else None
    result['blankLineCountError']=sum(not l for l in text.split('\n'))-sum(not l for l in expected.split('\n'))
    tables=reference.get('tableCells');cells=[c for t in page.get('structure',{}).get('tables',[]) for c in t.get('cells',[])]
    result['tableCells']=None if tables is None else {'expected':len(tables),'exactRowColumnText':sum(any(all(c.get(k)==v.get(k) for k in ['row','column','text']) for c in cells) for v in tables),'coordinateLabels':sum('box' in c for c in cells),'actualCoordinates':cells}
    result['structuredTable']=structured_table_metrics(reference,page)
    return result

def page_metrics(reference,page):
    text=page['draft']['text'];expected=reference['text'];lines=expected.splitlines()
    result={'strict':cer(expected,text),'characterOnlyDiagnostic':cer(character_diagnostic(expected),character_diagnostic(text)),
            'exactPhysicalReferenceLines':sum(bool(l.strip()) and l in text.splitlines() for l in lines),'referenceNonblankLines':sum(bool(l.strip()) for l in lines),
            'geometricMissingLines':'NOT_MEASURED_WITHOUT_BOX_LABELS','automaticChangedCharacters':page.get('localRefinement',{}).get('automaticallyChangedCharacters',0),
            'humanReviewEditDistance':Levenshtein.distance(text,reference['reviewedText']) if 'reviewedText' in reference else None,'humanReviewSeconds':reference.get('humanReviewSeconds')}
    labels=reference.get('structureLabels')
    result['structure']=None
    if labels:
        physical=page.get('literary',{}).get('physicalLines',[])
        result['structure']={'physicalLineCountError':len(physical)-labels['physicalLineCount'],
            'stanzaBoundaryProposals':len([b for b in page.get('literary',{}).get('boundaries',[]) if b['kind']=='STANZA']),
            'relativeIndentCorrect':sum(abs(x['indentRatio']-y)<labels.get('indentTolerance',.05) for x,y in zip(physical,labels.get('indentRatios',[]))),
            'relativeIndentLabels':len(labels.get('indentRatios',[])),
            'speakerBoundaryCandidates':sum(x['kind']=='SPEAKER_CANDIDATE' for x in physical),'stageDirectionCandidates':sum(x['kind']=='STAGE_DIRECTION_CANDIDATE' for x in physical),
            'semanticStanzaOrParagraphAccuracy':'NOT_INFERRED_FROM_UNREVIEWED_PROPOSALS'}
    result.update(extended_metrics(reference,page))
    return result

def validate_manifest(manifest,root):
    entries=manifest.get('pages',[]);seen=set();groups={};inputs={}
    if not entries:raise ValueError('NO_EVALUATION_DATA')
    for p in entries:
        if p['id'] in seen:raise ValueError('DUPLICATE_PAGE_ID')
        seen.add(p['id']);group=(p['workId'],p['revisionId'],p['scanGroup'])
        if not all(isinstance(x,str) and x for x in group):raise ValueError('MISSING_GROUP_ID')
        if p['split'] not in {'development','regression','evaluation'}:raise ValueError('INVALID_SPLIT')
        for key in [('work',p['workId']),('edition',p['workId'],p['revisionId']),('scan',p['scanGroup'])]:
            if groups.setdefault(key,p['split'])!=p['split']:raise ValueError('GROUP_LEAKAGE')
        if inputs.setdefault(p['inputSha'],p['split'])!=p['split']:raise ValueError('INPUT_LEAKAGE')
        for key in ['input','reference','standardResult','preciseResult']:
            path=(root/p[key]).resolve()
            if not path.is_relative_to(root.resolve()) or path.is_symlink():raise ValueError('UNSAFE_EVALUATION_PATH')
            if sha(path)!=p[key+'Sha']:raise ValueError('EVALUATION_HASH_MISMATCH')
        if p.get('classification')=='REAL_LITERARY':
            if p.get('rightsStatus')!='CONFIRMED' or p.get('privacyReview')!='VERIFIED':raise ValueError('RIGHTS_OR_PRIVACY_UNVERIFIED')
            reviewers=p.get('referenceReviewers',[])
            if len(reviewers)!=2 or len({v['reviewerId'] for v in reviewers})!=2 or not all(v.get('human') and v.get('blindToPredictions') for v in reviewers):raise ValueError('INDEPENDENT_REFERENCE_REVIEW_MISSING')
            for reviewer in reviewers:
                evidence=(root/reviewer['evidence']).resolve()
                if not evidence.is_relative_to(root.resolve()) or sha(evidence)!=reviewer['evidenceSha']:raise ValueError('REFERENCE_EVIDENCE_MISMATCH')
    return len(entries)

def cluster_interval(records,iterations=1000):
    grouped=defaultdict(list)
    for r in records:grouped[r['group']].append(r)
    if len(grouped)<5:return {'interval':None,'reason':'FEWER_THAN_FIVE_DOCUMENT_CLUSTERS','clusters':len(grouped)}
    keys=list(grouped);rng=random.Random(20261016);values=[]
    for _ in range(iterations):
        rows=[r for key in rng.choices(keys,k=len(keys)) for r in grouped[key]];n=sum(r['referenceCodePoints'] for r in rows)
        if n:values.append(sum(r['preciseErrors']-r['standardErrors'] for r in rows)/n)
    values.sort();return {'interval':[values[int(len(values)*.025)],values[min(len(values)-1,int(len(values)*.975))]],'clusters':len(keys),'definition':'Precise minus standard strict CER; document-cluster bootstrap; descriptive not population certification'}

def evaluate(manifest,root):
    validate_manifest(manifest,root);records=[]
    for p in manifest['pages']:
        ref=json.loads((root/p['reference']).read_text(encoding='utf-8'));modes={}
        if ref['text']!=unicodedata.normalize('NFC',ref['text'].replace('\r\n','\n').replace('\r','\n')):raise ValueError('REFERENCE_NFC_LF_REQUIRED')
        for mode in ['standard','precise']:
            page=json.loads((root/p[mode+'Result']).read_text(encoding='utf-8'))
            if page.get('ocrMode')!=mode or page['inputSha']!=p['inputSha']:raise ValueError('MODE_INPUT_MISMATCH')
            modes[mode]=page_metrics(ref,page)
        records.append({'id':p['id'],'genre':p['genre'],'split':p['split'],'classification':p['classification'],'group':p['workId'],'documentGroup':'|'.join([p['workId'],p['revisionId'],p['scanGroup']]),'modes':modes,
                        'standardErrors':modes['standard']['strict']['errors'],'preciseErrors':modes['precise']['strict']['errors'],'referenceCodePoints':len(ref['text'])})
    totals={}
    for mode in ['standard','precise']:
        values=[r['modes'][mode]['strict'] for r in records];n=sum(v['referenceCodePoints'] for v in values);e=sum(v['errors'] for v in values)
        totals[mode]={'pages':len(values),'errors':e,'referenceCodePoints':n,'CER':e/n if n else None,'worstPageCER':max((v['CER'] for v in values if v['CER'] is not None),default=None)}
    held=[r for r in records if r['split']=='evaluation' and r['classification']=='REAL_LITERARY'];interval=cluster_interval(held)
    status='UNVERIFIED_DATA'
    if held:
        delta=sum(r['preciseErrors']-r['standardErrors'] for r in held)
        # Automatic changes are now evaluated against the frozen reference;
        # their existence must not masquerade as either correctness or failure.
        status='NO_GAIN' if delta>=0 else 'PASS_MEASURED_DATASET_ONLY' if interval['interval'] is not None and interval['interval'][1]<0 else 'UNVERIFIED_DATA'
    by_genre={}
    for genre in sorted({r['genre'] for r in records}):
        rows=[r for r in records if r['genre']==genre];n=sum(r['referenceCodePoints'] for r in rows)
        by_genre[genre]={'pages':len(rows),'referenceCodePoints':n,**{mode:{'errors':sum(r['modes'][mode]['strict']['errors'] for r in rows),'CER':sum(r['modes'][mode]['strict']['errors'] for r in rows)/n if n else None} for mode in ['standard','precise']}}
    return {'PRECISION_ADVANTAGE':status,'independentAccuracyCertification':False,'pages':len(records),'uniqueWorkClusters':len({r['group'] for r in records}),'uniqueDocumentClusters':len({r['documentGroup'] for r in records}),'actualUnusedRealPages':len(held),'totals':totals,'byGenre':by_genre,'pairedClusterInterval':interval,'records':records,'limitations':['Structure candidates are not confirmed boundaries','Synthetic rows never satisfy the actual-material advantage gate','Review time and geometry accuracy remain N/A without human measurements/labels']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest');p.add_argument('--manifest-sha');p.add_argument('--output',required=True);a=p.parse_args()
    if not a.manifest:
        result={'PRECISION_ADVANTAGE':'UNVERIFIED_DATA','realPages':0,'independentReferences':0,'reason':'NO_RIGHTS_CONFIRMED_FROZEN_REAL_MATERIAL_BUNDLE_PROVIDED'};code=3
    else:
        manifest=Path(a.manifest)
        if not a.manifest_sha or sha(manifest)!=a.manifest_sha:raise ValueError('FROZEN_MANIFEST_SHA_REQUIRED')
        result=evaluate(json.loads(manifest.read_text(encoding='utf-8')),manifest.parent);result['manifestSha']=a.manifest_sha;code=0
    with Path(a.output).open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='records'}));return code

if __name__=='__main__':raise SystemExit(main())
