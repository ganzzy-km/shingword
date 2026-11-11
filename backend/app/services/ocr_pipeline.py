"""Inert PDF/image routing and OCR comparison. No spelling correction or voting."""
import ctypes
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import math
import re
import statistics
from pathlib import Path
import unicodedata


class OcrRejected(ValueError):
    pass


def normalize(text):
    return unicodedata.normalize('NFC', text.replace('\r\n', '\n').replace('\r', '\n'))


def native_quality(text):
    chars=[c for c in text if not c.isspace()]
    if not chars:return False
    bad=sum(c=='\ufffd' or (unicodedata.category(c).startswith('C') and c!='\t') for c in chars)
    letters=sum(c.isalnum() for c in chars)
    return bad==0 and letters>=4 and letters/len(chars)>=.55


def area(box):
    return max(0,box[2]-box[0])*max(0,box[3]-box[1])


def intersection(a,b):
    return area([max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])])


def validate_input(path, *, max_bytes=50*1024*1024,max_pages=100,max_pixels=16_000_000):
    from PIL import Image,ImageOps
    p=Path(path)
    if not p.is_file() or p.stat().st_size>max_bytes:raise OcrRejected('FILE_LIMIT')
    header=p.read_bytes()[:16]
    if header.startswith(b'%PDF-'):
        from pypdf import PdfReader
        import pypdfium2 as pdfium
        try:
            reader=PdfReader(str(p),strict=True)
            if reader.is_encrypted:raise OcrRejected('PDF_ENCRYPTED')
            if not 0<len(reader.pages)<=max_pages:raise OcrRejected('PAGE_LIMIT')
            # Traverse parsed objects, not byte substrings in compressed streams.
            seen=set()
            def check(obj,depth=0):
                from pypdf.generic import IndirectObject,DictionaryObject,ArrayObject
                if depth>64 or len(seen)>100000:raise OcrRejected('PDF_OBJECT_LIMIT')
                if isinstance(obj,IndirectObject):
                    key=(obj.idnum,obj.generation)
                    if key in seen:return
                    seen.add(key);return check(obj.get_object(),depth+1)
                if isinstance(obj,DictionaryObject):
                    if any(k in obj for k in ['/JavaScript','/JS','/Launch','/EmbeddedFile','/OpenAction','/AA']):raise OcrRejected('ACTIVE_PDF_CONTENT')
                    if obj.get('/S') in ['/JavaScript','/Launch'] or obj.get('/Type')=='/EmbeddedFile':raise OcrRejected('ACTIVE_PDF_CONTENT')
                    for value in obj.values():check(value,depth+1)
                elif isinstance(obj,ArrayObject):
                    for value in obj:check(value,depth+1)
            check(reader.trailer)
            with closing(pdfium.PdfDocument(p)) as doc:
                for page in doc:
                    w,h=page.get_size()
                    if w<=0 or h<=0 or w*h*(300/72)**2>max_pixels:raise OcrRejected('PIXEL_LIMIT')
            return {'mime':'application/pdf','pages':len(reader.pages)}
        except OcrRejected:raise
        except Exception as error:raise OcrRejected('DAMAGED_PDF') from error
    try:
        Image.MAX_IMAGE_PIXELS=max_pixels
        with Image.open(p) as image:
            if image.format not in {'PNG','JPEG','TIFF'}:raise OcrRejected('FILE_TYPE')
            if image.width*image.height>max_pixels or getattr(image,'n_frames',1)!=1:raise OcrRejected('PIXEL_OR_FRAME_LIMIT')
            image.verify();mime=Image.MIME.get(image.format,'image/png')
        return {'mime':mime,'pages':1}
    except OcrRejected:raise
    except Exception as error:raise OcrRejected('INVALID_IMAGE') from error


def pdf_box(page,box,width,height):
    import pypdfium2.raw as raw
    result=[]
    for x,y in [(box[0],box[1]),(box[2],box[3])]:
        a,b=ctypes.c_int(),ctypes.c_int()
        if not raw.FPDF_PageToDevice(page,0,0,width,height,0,x,y,ctypes.byref(a),ctypes.byref(b)):raise OcrRejected('COORDINATE_TRANSFORM')
        result.append((a.value,b.value))
    return [min(x[0] for x in result),min(x[1] for x in result),max(x[0] for x in result),max(x[1] for x in result)]


def table_cells(table):
    """Parse inert model table markup into cells; never render model HTML."""
    class Cells(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.row=-1;self.column=0;self.current=None;self.cells=[];self.occupied=set();self.limited=False
        def handle_starttag(self,tag,attrs):
            if self.limited:return
            if tag=='tr':self.row+=1;self.column=0
            if tag in {'td','th'}:
                while (self.row,self.column) in self.occupied:self.column+=1
                attrs=dict(attrs)
                try:rs=int(attrs.get('rowspan',1));cs=int(attrs.get('colspan',1))
                except (TypeError,ValueError):rs=cs=1
                if not 1<=rs<=64 or not 1<=cs<=64 or len(self.occupied)+rs*cs>100000 or len(self.cells)>=5000:self.limited=True;self.current=None;return
                self.current={'row':max(0,self.row),'column':self.column,'rowSpan':rs,'columnSpan':cs,'text':''}
                for r in range(max(0,self.row),max(0,self.row)+rs):
                    for c in range(self.column,self.column+cs):self.occupied.add((r,c))
                self.column+=cs
            elif tag=='br' and self.current:self.current['text']+='\n'
        def handle_data(self,data):
            if self.current:self.current['text']+=data
        def handle_endtag(self,tag):
            if tag in {'td','th'} and self.current:self.cells.append(self.current);self.current=None
    html=table.get('pred_html') or table.get('html') or ''
    if not isinstance(html,str) or len(html)>1024*1024:return []
    parser=Cells();parser.feed(html)
    return [] if parser.limited else parser.cells


def inspect_page(page,dpi=300):
    import pypdfium2.raw as raw
    w,h=page.get_size();width,height=math.ceil(w*dpi/72),math.ceil(h*dpi/72)
    tp=page.get_textpage();text=tp.get_text_bounded()
    # Physical line boundaries and indentation are retained as image coordinates.
    lines=[];current=[];bounds=[];duplicates=0;seen=set()
    def flush():
        if current and ''.join(current).strip() and bounds:
            lines.append({'text':''.join(current),'box':[min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)]})
        current.clear();bounds.clear()
    for i in range(tp.count_chars()):
        code=int(raw.FPDFText_GetUnicode(tp,i));char=chr(code) if code else ''
        if char in '\r\n':flush();continue
        box=pdf_box(page,tp.get_charbox(i),width,height)
        key=(char,tuple(box))
        if char.strip() and area(box)>0:
            if key in seen:duplicates+=1
            seen.add(key)
        current.append(char);bounds.append(box)
    flush();tp.close()
    images=[]
    for obj in page.get_objects():
        if obj.type==raw.FPDF_PAGEOBJ_IMAGE:
            box=pdf_box(page,obj.get_pos(),width,height)
            if area(box)>width*height*.005:images.append(box)
    good=native_quality(text) and duplicates<=max(1,len(text)*.02)
    route='native' if good and not images else ('mixed' if good else ('ocr' if images or text.strip() else 'blank'))
    # A PDF with vector outlines and no text is not a blank page.
    if route=='blank' and list(page.get_objects()):route='ocr'
    origin=pdf_box(page,(0,0,1,1),width,height)
    return {'route':route,'nativeText':text,'nativeLines':lines,'imageBoxes':images,
            'geometry':{'width':width,'height':height,'dpi':dpi,'pdfWidth':w,'pdfHeight':h,'rotation':page.get_rotation(),'cropBox':list(page.get_cropbox()),'mediaBox':list(page.get_mediabox()),'coordinateUnit':'RENDER_PIXEL_TOP_LEFT','transform':'PDFium FPDF_PageToDevice; rotation and crop applied','unitBox':origin},'quality':{'nativeAccepted':good,'duplicateCharacters':duplicates}}


def probe(path,**limits):
    meta=validate_input(path,**limits)
    if meta['mime']!='application/pdf':return {**meta,'needsOcr':True,'routes':['ocr'],'nativeText':''}
    import pypdfium2 as pdfium
    pages=[]
    with closing(pdfium.PdfDocument(path)) as doc:
        for page in doc:pages.append(inspect_page(page))
    return {**meta,'needsOcr':any(p['route'] in {'ocr','mixed'} for p in pages),'routes':[p['route'] for p in pages],'nativeText':normalize('\n\n'.join(p['nativeText'] for p in pages))}


def render_page(path,index):
    from PIL import Image
    if Path(path).read_bytes()[:5]==b'%PDF-':
        import pypdfium2 as pdfium
        with closing(pdfium.PdfDocument(path)) as doc:
            page=doc[index];info=inspect_page(page)
            image=page.render(scale=300/72).to_pil().convert('RGB')
    else:
        from PIL import ImageOps
        with Image.open(path) as im:
            orientation=im.getexif().get(274,1);original_size=list(im.size);im=ImageOps.exif_transpose(im)
            if 'A' in im.getbands():
                image=Image.new('RGB',im.size,'white');image.paste(im,mask=im.getchannel('A'))
            else:image=im.convert('RGB')
        info={'route':'ocr','nativeText':'','nativeLines':[],'imageBoxes':[], 'geometry':{'width':image.width,'height':image.height,'dpi':300,'coordinateUnit':'RENDER_PIXEL_TOP_LEFT','rotation':0,'cropBox':[0,0,image.width,image.height],'transform':'Pillow EXIF transpose from preserved original','exifOrientation':orientation,'originalImageSize':original_size}}
    if not info['nativeText'].strip() and image.convert('L').getextrema()==(255,255):info['route']='blank'
    return image,info


def align_lines(primary,secondary,*,groups=False):
    """Spatial correspondence; confidence from different engines is never ranked."""
    if len(primary)>1200 or len(secondary)>1200:raise OcrRejected('LINE_LIMIT')
    used=set();result=[];edges=[]
    for pi,line in enumerate(primary):
        candidates=[(intersection(line['box'],b['box'])/max(1,min(area(line['box']),area(b['box']))),i) for i,b in enumerate(secondary) if i not in used]
        if groups:
            edges.extend((pi,i) for i,b in enumerate(secondary) if intersection(line['box'],b['box'])/max(1,min(area(line['box']),area(b['box'])))>=.45)
        overlap,index=max(candidates,default=(0,None))
        other=secondary[index] if overlap>=.45 else None
        if other is not None:used.add(index)
        result.append({**line,'secondary':other,'difference':'SECONDARY_MISSING' if other is None else ('AGREEMENT' if line['text']==other['text'] else 'TEXT_DIFFERENCE')})
        if groups:result[-1]['rawPrimaryIndex']=pi
    for i,line in enumerate(secondary):
        if i not in used:result.append({**line,'secondary':line,'difference':'PRIMARY_MISSING','primaryMissing':True})
        if groups and i not in used:result[-1]['rawSecondaryIndex']=i
    if groups:
        # Extend the existing spatial comparison, keeping its legacy alternatives.
        # Connected components expose split/merged lines; they never choose text.
        neighbors={}
        for p,s in edges:
            neighbors.setdefault(('p',p),set()).add(('s',s));neighbors.setdefault(('s',s),set()).add(('p',p))
        seen=set();components=[]
        for node in neighbors:
            if node in seen:continue
            stack=[node];component=set()
            while stack:
                current=stack.pop()
                if current in component:continue
                component.add(current);stack.extend(neighbors[current]-component)
            seen.update(component);ps=sorted(i for kind,i in component if kind=='p');ss=sorted(i for kind,i in component if kind=='s')
            kind='1:1' if len(ps)==len(ss)==1 else '1:N' if len(ps)==1 else 'N:1' if len(ss)==1 else 'N:N'
            descriptor={'id':f'alignment-{len(components)+1}','kind':kind,'primaryIndexes':ps,'secondaryIndexes':ss,'automaticTextAdoption':False,'requiresReview':kind!='1:1'}
            components.append(descriptor)
            for line in result:
                if line.get('rawPrimaryIndex') in ps or line.get('rawSecondaryIndex') in ss:
                    line['alignment']=descriptor
                    if line.get('primaryMissing') and kind!='1:1':line['segmentationOnly']=True
    return result


def ruled_table_candidate(image):
    """Bounded image geometry trigger, not an inferred cell transcription."""
    import cv2
    import numpy as np
    view=image.copy();view.thumbnail((1200,1600))
    gray=cv2.cvtColor(np.asarray(view),cv2.COLOR_RGB2GRAY)
    binary=cv2.threshold(gray,180,255,cv2.THRESH_BINARY_INV)[1]
    h,w=binary.shape
    horizontal=cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((1,max(30,w//5)),np.uint8))
    vertical=cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((max(30,h//8),1),np.uint8))
    joints=cv2.bitwise_and(horizontal,vertical)
    count,_,_,_=cv2.connectedComponentsWithStats(joints)
    return count-1>=6


def compose_draft(lines,*,profile=None):
    pieces=[];offset=0;mapping=[]
    for index,line in enumerate(lines):
        text=line['text'];pieces.append(text)
        mapping.append({'lineId':line['id'],'rawStart':offset,'rawEnd':offset+len(text),'box':line['box']})
        offset+=len(text)+1
    raw='\n'.join(pieces);normalized=normalize(raw)
    segments=[];normalized_units=[];a=0;c=0
    # Linear normalization units; repeated source text must not cause a quadratic
    # sequence comparison. Combining/Jamo groups remain many-to-many segments.
    def jamo(char):return '\u1100'<=char<='\u11ff' or '\ua960'<=char<='\ua97f' or '\ud7b0'<=char<='\ud7ff'
    while a<len(raw):
        b=a+1
        if raw[a]=='\r' and b<len(raw) and raw[b]=='\n':b+=1
        else:
            while b<len(raw) and (unicodedata.combining(raw[b]) or jamo(raw[b])):b+=1
        value=normalize(raw[a:b]);d=c+len(value);kind='equal' if raw[a:b]==value else 'replace'
        normalized_units.append(value)
        if segments and kind=='equal' and segments[-1]['kind']=='equal':segments[-1]['raw'][1]=b;segments[-1]['normalized'][1]=d
        else:segments.append({'raw':[a,b],'normalized':[c,d],'kind':kind})
        a=b;c=d
    if ''.join(normalized_units)!=normalized:raise OcrRejected('NORMALIZATION_MAPPING_UNVERIFIED')
    if profile is not None:
        position=0
        for line,entry in zip(lines,mapping):
            value=normalize(line['text']);entry.update(start=position,end=position+len(value));position+=len(value)+1
    return {'rawText':raw,'text':normalized,'lineMap':mapping,'normalizationMap':segments,'locationUnit':'UNICODE_CODE_POINT_HALF_OPEN','normalization':'NFC/LF'}


LITERARY_PROFILES={'auto','poetry','prose','drama','commentary','other'}
LITERARY_POLICY={'version':'geulbit.ocr.literary/1','automaticTextReplacement':False,'automaticWhitespaceInsertion':False,'maxLocalRegions':4,'localBudgetSeconds':45,'maxRegionPixels':1_500_000}


def literary_structure(image,lines,draft,profile):
    """Image evidence and relative layout, separate from the literal TXT source."""
    if profile not in LITERARY_PROFILES:raise OcrRejected('INVALID_OCR_PROFILE')
    selected=[l for l in lines if l.get('includedInDraft')]
    maps={m['lineId']:m for m in draft['lineMap']};physical=[];boundaries=[]
    height=statistics.median([max(1,l['box'][3]-l['box'][1]) for l in selected]) if selected else 1
    for i,line in enumerate(selected):
        # Layout models may emit a separate block for every poetry line. Use
        # overlapping column extents, not an individual model block's left edge.
        def same_column(other):
            a=line['box'];b=other['box'];overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))
            return overlap/max(1,min(a[2]-a[0],b[2]-b[0]))>=.5 and abs(a[0]-b[0])<=height*3
        peers=[l for l in selected if same_column(l)] or [line]
        left=min(l['box'][0] for l in peers);right=max(l['box'][2] for l in peers)
        text=normalize(line['text']);speaker=re.match(r'^([^\s:：]{1,16})[:：]',text)
        stage=bool(re.match(r'^\s*[\[（(].*[\]）)]\s*$',text))
        item={'lineId':line['id'],'span':[maps[line['id']]['start'],maps[line['id']]['end']],'box':line['box'],'block':line.get('block'),'indentRatio':max(0,line['box'][0]-left)/max(1,right-left),'kind':'STAGE_DIRECTION_CANDIDATE' if stage else 'SPEAKER_CANDIDATE' if speaker else 'PHYSICAL_LINE','requiresReview':True}
        if speaker:item['speakerSpan']=[item['span'][0],item['span'][0]+speaker.end()]
        physical.append(item)
        if not i:continue
        previous=selected[i-1];gap=line['box'][1]-previous['box'][3]
        same_block=previous.get('block')==line.get('block')
        same_column=intersection([previous['box'][0],0,previous['box'][2],1],[line['box'][0],0,line['box'][2],1])>0
        gap_evidence=False
        if gap>height*1.5 and same_column:
            rect=[max(0,min(previous['box'][0],line['box'][0])),max(0,previous['box'][3]+1),min(image.width,max(previous['box'][2],line['box'][2])),min(image.height,line['box'][1]-1)]
            if area(rect)>0:
                band=image.crop(rect).convert('L');hist=band.histogram();gap_evidence=sum(hist[245:])/max(1,sum(hist))>=.98
        reasons=[]
        if gap_evidence:reasons.append('IMAGE_BLANK_GAP_WITHIN_BLOCK')
        if gap_evidence and not same_block:reasons[-1]='IMAGE_BLANK_GAP_ACROSS_MODEL_BLOCKS_REQUIRES_REVIEW'
        if same_block and same_column and line['box'][0]-left>height*.5:reasons.append('RELATIVE_INDENT_REQUIRES_REVIEW')
        if profile=='drama' and (speaker or stage):reasons.append('LITERAL_SPEAKER_OR_STAGE_BOUNDARY')
        if reasons:
            boundaries.append({'id':f'boundary-{line["id"]}','beforeLineId':line['id'],'position':item['span'][0],'kind':'STANZA' if profile=='poetry' else 'PARAGRAPH' if profile in {'prose','commentary'} else 'SPEAKER_OR_STAGE' if profile=='drama' else 'UNCLASSIFIED','reasons':reasons,'imageBlankBand':gap_evidence,'status':'REVIEW_PROPOSAL','automaticallyApplied':False})
    wraps=[]
    if profile in {'prose','commentary'}:
        for previous,line in zip(selected,selected[1:]):
            a=previous['box'];b=line['box'];start=maps[previous['id']].get('end');end=maps[line['id']].get('start')
            same_text_block=(previous.get('block') is not None and previous.get('block')==line.get('block')
                             and previous.get('blockType') in {'text','paragraph','body','content'} and line.get('blockType')==previous.get('blockType'))
            overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))/max(1,min(a[2]-a[0],b[2]-b[0]))
            if (not same_text_block or previous.get('engine')=='native' or line.get('engine')=='native'
                or not 0<=b[1]-a[3]<=height*1.2 or overlap<.8 or abs(a[0]-b[0])>height*.3
                or abs(a[2]-b[2])>height*1.5 or re.search(r'[.!?。？！…][\"”’\')\]]?\s*$',previous['text'])
                or start is None or end is None or draft['text'][start:end]!='\n'):continue
            wraps.append({'id':'wrap-'+previous['id']+'-'+line['id'],'fromLineId':previous['id'],'toLineId':line['id'],
                          'start':start,'end':end,'expected':'\n','status':'USER_REVIEW_ONLY','automaticallyApplied':False,
                          'reasons':['SAME_TEXT_BLOCK','ALIGNED_COLUMN','NORMAL_PHYSICAL_LINE_GAP'],
                          'leftText':normalize(previous['text']),'rightText':normalize(line['text'])})
    return {'version':LITERARY_POLICY['version'],'requestedProfile':profile,'effectiveProfile':profile if profile!='auto' else 'UNKNOWN','profileSource':'USER_DECLARED' if profile!='auto' else 'UNDETERMINED','physicalLines':physical,'boundaries':boundaries,'lineWrapCandidates':wraps,'reviewOperationsVersion':'geulbit.ocr.review/1','relativeIndentation':'DISPLAY_COORDINATES_ONLY_NOT_SPACE_COUNTS','readingOrder':'MODEL_BLOCK_AND_PHYSICAL_LINE_ORDER_REQUIRES_REVIEW','rawOrderPreserved':True,'textUnchanged':True}


def local_refinement_regions(page):
    """Observable errors only, bounded region proposals; no reference answers."""
    regions=[]
    for line in page['lines']:
        reasons=[];text=line['text']
        if line['difference']=='TEXT_DIFFERENCE':reasons.append('ENGINE_TEXT_DIFFERENCE')
        if line.get('primaryMissing') and not line.get('segmentationOnly'):reasons.append('PRIMARY_LINE_MISSING')
        if line.get('alignment',{}).get('kind') in {'1:N','N:1','N:N'}:reasons.append('LINE_SEGMENTATION_DIFFERENCE')
        chars=[c for c in text if not c.isspace()]
        if any(c=='\ufffd' or unicodedata.category(c).startswith('C') for c in chars) or (len(chars)>=4 and sum(c.isalnum() for c in chars)/len(chars)<.55):reasons.append('ABNORMAL_CHARACTER_COMPOSITION')
        if re.match(r'^[^\s:：]{1,16}[:：]\S',text):reasons.append('SPEAKER_SPACING_UNVERIFIED')
        if not reasons:continue
        related=[l for l in page['lines'] if line.get('alignment') and l.get('alignment',{}).get('id')==line['alignment']['id']] or [line]
        box=[max(0,min(l['box'][0] for l in related)-8),max(0,min(l['box'][1] for l in related)-8),min(page['width'],max(l['box'][2] for l in related)+8),min(page['height'],max(l['box'][3] for l in related)+8)]
        if area(box)>LITERARY_POLICY['maxRegionPixels'] or any(intersection(box,r['box'])/max(1,min(area(box),area(r['box'])))>.7 for r in regions):continue
        rows=len({round((l['box'][1]+l['box'][3])/2/max(1,l['box'][3]-l['box'][1])) for l in related if l.get('includedInDraft')})
        regions.append({'id':f'local-{len(regions)+1}','box':box,'lineIds':[l['id'] for l in related],'triggers':reasons,'psm':7 if rows<=1 else 6,'status':'REVIEW_ONLY'})
        if len(regions)>=LITERARY_POLICY['maxLocalRegions']:break
    return regions


def combine_page(image,info,paddle,tesseract,structure,*,profile=None):
    aligned=align_lines(paddle,tesseract,groups=profile is not None)
    if info['route']=='mixed':
        native=info['nativeLines']
        aligned=[l for l in aligned if not any(intersection(l['box'],n['box'])/max(1,area(l['box']))>.5 for n in native)]
        aligned+=[{**l,'engine':'native','difference':'NATIVE_PRESERVED','secondary':None} for l in native]
    blocks=structure.get('blocks',[])
    for line in aligned:
        overlapping=[(intersection(line['box'],b['box']),i) for i,b in enumerate(blocks)]
        overlap,block=max(overlapping,default=(0,None))
        line['block']=block if overlap>0 else None
        if profile is not None:line['blockType']=blocks[block].get('type') if overlap>0 else None
    aligned.sort(key=lambda l: (l['block'] if l['block'] is not None else len(blocks),l['box'][1],l['box'][0]))
    typical=statistics.median([max(1,l['box'][3]-l['box'][1]) for l in aligned]) if aligned else 1
    left=min([l['box'][0] for l in aligned],default=0)
    draft_index=0
    for i,line in enumerate(aligned):
        line['id']=f'line-{i+1}';line['indentPixels']=max(0,line['box'][0]-left)
        line['stanzaGapCandidateBefore']=i>0 and line['box'][1]-aligned[i-1]['box'][3]>typical*1.5
        line['includedInDraft']=not line.get('primaryMissing',False) or not paddle
        line['draftLineIndex']=draft_index if line['includedInDraft'] else None
        if line['includedInDraft']:draft_index+=1
    selected=[line for line in aligned if line['includedInDraft']]
    draft=compose_draft(selected,profile=profile)
    result={**info,'lines':aligned,'structure':structure,'enginesRaw':{'paddle':paddle,'tesseract':tesseract},
            'draftProvider':'PADDLE_WITH_MANUAL_SECONDARY_PROPOSALS' if paddle else 'TESSERACT_FALLBACK_REVIEW_ONLY',
            'draft':draft,'width':image.width,'height':image.height,'requiresReview':info['route'] in {'ocr','mixed'}}
    if profile is not None:result['literary']=literary_structure(image,aligned,draft,profile)
    return result


# A new draft policy, not a rewrite of old review records or confirmed revisions.
PRECISION_POLICY={'version':'geulbit.ocr.precision/6','maxLocalRegions':8,
                  'localBudgetSeconds':45,'maxRegionPixels':1_500_000,
                  'textSelection':'SPATIAL_REDETECTION_WITH_IMAGE_SUPPORT',
                  'preprocessing':'BOUNDED_CROP_VIEWS_ORIGINAL_COORDINATES'}


def ink_rows(image,box):
    """Physical ink bands. No characters or semantic labels are inferred here."""
    import numpy as np
    x0,y0,x1,y1=[int(v) for v in box]
    x0=max(0,x0);y0=max(0,y0);x1=min(image.width,x1);y1=min(image.height,y1)
    if x1<=x0 or y1<=y0:return []
    values=np.asarray(image.crop((x0,y0,x1,y1)).convert('L'))
    foreground=values<min(210,max(80,float(np.percentile(values,90))-35))
    active=foreground.sum(axis=1)>=max(2,(x1-x0)*.006)
    bands=[];start=None
    for i,on in enumerate(active.tolist()+[False]):
        if on and start is None:start=i
        if not on and start is not None:
            if i-start>=2:bands.append([start+y0,i+y0])
            start=None
    # Gaps inside a glyph (e.g. punctuation) must not become separate text lines.
    merged=[]
    for a,b in bands:
        if merged and a-merged[-1][1]<=max(2,(b-a)*.25):merged[-1][1]=b
        else:merged.append([a,b])
    return merged


def literal_key(text):
    return ''.join(c for c in normalize(text) if not c.isspace())


def sequence_edit_units(before,after):
    # Standard-library alignment keeps the OCR-only environment self-contained.
    # This UI/audit count is not used as CER; the evaluator computes exact CER.
    from difflib import SequenceMatcher
    return sum(max(b-a,d-c) for tag,a,b,c,d in SequenceMatcher(None,before,after).get_opcodes() if tag!='equal')


def preserves_existing_spacing(before,after):
    def runs(text):
        result={};offset=0
        for c in normalize(text):
            if c.isspace():result[offset]=result.get(offset,'')+c
            else:offset+=1
        return result
    old=runs(before);new=runs(after)
    # Existing multi-spaces, tabs and ideographic spaces are literal source
    # candidates. Image gaps cannot establish a new count/normalization for them.
    return all(new.get(at)==space for at,space in old.items()) and all(space==' ' for at,space in new.items() if at not in old)


def nonletter_signature(text):
    return ''.join(c for c in normalize(text) if not c.isalnum() and not c.isspace())


def supported_spacing(image,text,words,box,*,strict_gaps=False):
    """Only adopt spacing with matching literal words AND visible word gaps.

    Engine confidence is deliberately absent. TSV words are matched to TXT
    characters; a different tokenization or incomplete line causes abstention.
    """
    if not words or literal_key(''.join(w['text'] for w in words))!=literal_key(text):return False
    targets=[];offset=0
    for w in words:
        a=offset;offset+=len(literal_key(w['text']));targets.append((a,offset,w['box']))
    chars=[c for c in normalize(text) if not c.isspace()]
    boundaries=[];at=0
    for c in normalize(text):
        if c.isspace():boundaries.append(at)
        else:at+=1
    # A single printed token without any spacing cannot prove a spacing edit.
    if not boundaries:return False
    edges=[0]+sorted(set(boundaries))+[len(chars)]
    def union(parts):return [min(v[2][0] for v in parts),min(v[2][1] for v in parts),max(v[2][2] for v in parts),max(v[2][3] for v in parts)]
    for i,at in enumerate(edges[1:-1],1):
        # TSV may tokenize a Korean word into overlapping character boxes.
        # Match the literal TXT word span, then union every constituent box.
        left=[v for v in targets if v[0]>=edges[i-1] and v[1]<=at]
        right=[v for v in targets if v[0]>=at and v[1]<=edges[i+1]]
        if not left or not right or left[0][0]!=edges[i-1] or left[-1][1]!=at or right[0][0]!=at or right[-1][1]!=edges[i+1]:return False
        a,b=union(left),union(right);gap=b[0]-a[2];height=min(a[3]-a[1],b[3]-b[1])
        if gap<max(2,height*.12) or abs((a[1]+a[3]-b[1]-b[3])/2)>height*.5:return False
        band=[int(a[2])+1,int(max(a[1],b[1])),int(b[0])-1,int(min(a[3],b[3]))]
        if area(band)<=0:return False
        hist=image.crop(band).convert('L').histogram()
        if strict_gaps or sum(hist[220:])/max(1,sum(hist))<.94:
            # The new proof is for ASCII label delimiters only. Other glyph
            # sidebearings (notably fullwidth punctuation) are ambiguous; keep
            # the legacy whole-band refusal for those positions.
            if not 0<at<len(chars) or chars[at-1]!=':' or not chars[at].isalnum():return False
            # TSV boxes sometimes include the edge of a neighbouring glyph.
            # Keep the original full-band proof, or require a wider continuous
            # white cut inside that SAME gap; never lower its white threshold.
            strip=image.crop(band).convert('L');run=best=0
            for column in range(strip.width):
                values=strip.crop((column,0,column+1,strip.height)).histogram()
                run=run+1 if sum(values[220:])/max(1,sum(values))>=.97 else 0
                best=max(best,run)
            if best<max(3,math.ceil(height*.25)):return False
    return True


def restore_fragment_spacing(image,target,fragments):
    """Add only literal TSV spaces supported by the same row's image gap.

    Fragmented secondary detection cannot corroborate a whole-line replacement.
    It can prove an internal space where a unique, exact primary substring and
    its independent word boxes agree. No characters, punctuation, existing
    whitespace or unrecognised suffixes are rewritten.
    """
    text=target['text'];empty={'text':text,'insertedAtLiteralOffsets':[]}
    if target.get('engine')=='native' or text!=normalize(text) or '://' in text:return empty
    key=literal_key(text);box=target['box'];height=box[3]-box[1]
    if not key or height<=0:return empty
    # Additive repair is limited to an existing label/speaker delimiter.
    # Unspaced lexical words, times and URL syntax need other evidence/review.
    # Fullwidth colon has a large glyph sidebearing indistinguishable from a
    # printed space by this geometry alone; leave it for explicit review.
    match=re.match(r'^([^:：\n]{1,16})(:)(?=\S)',text)
    if not match or not text[match.end()].isalnum() or (text[match.end()-2].isdigit() and text[match.end()].isdigit()):return empty
    allowed_offset=len(literal_key(text[:match.end()]))
    windows=[]
    for f in fragments:
        words=f.get('words',[])
        if not words or literal_key(''.join(w['text'] for w in words))!=literal_key(f['text']):continue
        if any(area(w['box'])<=0 or intersection(w['box'],f['box'])/max(1,area(w['box']))<.95 for w in words):continue
        tokens=list(re.finditer(r'\S+',f['text']));offset=0;spans=[]
        for w in words:
            size=len(literal_key(w['text']));spans.append((offset,offset+size,w));offset+=size
        for a,b in zip(tokens,tokens[1:]):
            if a.group()[-1:]!=':' or f['text'][a.end():b.start()]!=' ':continue
            lo=len(literal_key(f['text'][:a.start()]));hi=len(literal_key(f['text'][:b.end()]))
            selected=[w for start,end,w in spans if start>=lo and end<=hi]
            if not selected or literal_key(''.join(w['text'] for w in selected))!=literal_key(a.group()+b.group()):continue
            bounds=[min(w['box'][0] for w in selected),min(w['box'][1] for w in selected),max(w['box'][2] for w in selected),max(w['box'][3] for w in selected)]
            windows.append({'text':a.group()+' '+b.group(),'words':selected,'box':bounds})
    hits=[]
    for f in windows:
        b=f['box']
        if area(b)<=0 or intersection(b,box)/max(1,area(b))<.8:continue
        if abs((b[1]+b[3]-box[1]-box[3])/2)>min(height,b[3]-b[1])*.5:continue
        if len(hits)>=32:return empty
        hits.append(f)
    offsets=set();positions=[i for i,c in enumerate(text) if not c.isspace()]
    for f in hits:
        words=f.get('words');anchor=literal_key(f['text'])
        if not words or len(anchor)<4 or key.count(anchor)!=1:continue
        # Only single ASCII internal spaces; not a proposed indentation/count.
        if f['text']!=normalize(f['text']) or f['text'].strip()!=f['text'] or any(c.isspace() and c!=' ' for c in f['text']) or '  ' in f['text']:continue
        if any(intersection(w['box'],f['box'])/max(1,area(w['box']))<.95 for w in words):continue
        # A text-column gutter is not a word gap, including merged OCR rows.
        if any(b['box'][0]-a['box'][2]>height*1.2 for a,b in zip(words,words[1:])):continue
        if not supported_spacing(image,f['text'],words,f['box'],strict_gaps=True):continue
        start=key.index(anchor);at=0
        for c in f['text']:
            if c==' ':
                boundary=start+at
                if boundary==allowed_offset and 0<boundary<len(positions) and positions[boundary]==positions[boundary-1]+1:offsets.add(boundary)
            else:at+=1
    insert={positions[at] for at in offsets}
    after=''.join((' ' if i in insert else '')+c for i,c in enumerate(text))
    assert literal_key(after)==key and preserves_existing_spacing(text,after)
    return {'text':after,'insertedAtLiteralOffsets':sorted(offsets)}


def _page_alternative(region,alternative):
    """Map crop inference boxes back to the untouched page, including scale."""
    scale=alternative.get('scale',1)
    if not isinstance(scale,(int,float)) or not 0<scale<=4:return []
    x,y=region['box'][:2];result=[]
    def original_box(b):
        matrix=alternative.get('inverseAffine',[1,0,0,0,1,0]);points=[]
        for a,c in [(b[0]/scale,b[1]/scale),(b[2]/scale,b[1]/scale),(b[0]/scale,b[3]/scale),(b[2]/scale,b[3]/scale)]:
            points.append((matrix[0]*a+matrix[1]*c+matrix[2]+x,matrix[3]*a+matrix[4]*c+matrix[5]+y))
        return [min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)]
    for l in alternative.get('lines',[]):
        line={**l,'box':original_box(l['box'])}
        if 'words' in l:
            line['words']=[{**w,'box':original_box(w['box'])} for w in l['words']]
        result.append(line)
    return result


def collapse_local_row_fragments(lines):
    """A detector's horizontal fragments are not independent physical lines."""
    rows=[]
    for l in sorted(lines,key=lambda l:((l['box'][1]+l['box'][3])/2,l['box'][0])):
        b=l['box'];row=next((r for r in rows if max(0,min(b[3],r[0]['box'][3])-max(b[1],r[0]['box'][1]))/max(1,min(b[3]-b[1],r[0]['box'][3]-r[0]['box'][1]))>=.65),None)
        if row is None:rows.append([l])
        else:row.append(l)
    result=[]
    for row in rows:
        row.sort(key=lambda l:l['box'][0])
        height=statistics.median(l['box'][3]-l['box'][1] for l in row)
        safe=all(-height*.3<=b['box'][0]-a['box'][2]<=height*2.5 for a,b in zip(row,row[1:]))
        if len(row)>1 and safe:
            result.append({**row[0],'text':''.join(l['text'] for l in row),'box':[min(l['box'][0] for l in row),min(l['box'][1] for l in row),max(l['box'][2] for l in row),max(l['box'][3] for l in row)],'fragmentLines':row})
        else:result.extend(row)
    return result


def select_precise_draft(image,page):
    """Evidence-bound selection; abstain rather than vote on competing strings.

    Raw model outputs and the pre-selection draft remain immutable alternatives.
    A missing line needs re-detection plus independent literal corroboration.
    Substitutions need stable crop recognition, spatial support and a limited
    edit. White-space edits additionally need visible TSV-aligned word gaps.
    """
    from copy import deepcopy
    before=deepcopy(page['draft']);decisions=[];lines=page['lines']
    for l in lines:
        l.setdefault('originalText',l['text']);l.setdefault('originalIncludedInDraft',l.get('includedInDraft',True))
    covered=set()
    for region in page.get('localRefinement',{}).get('candidates',[]):
        group=[l for l in lines if l['id'] in region['lineIds']]
        primary=[l for l in group if l.get('includedInDraft') and l.get('engine')!='native']
        tess=[];paddle=[]
        for alt in region.get('alternatives',[]):
            mapped=_page_alternative(region,alt)
            if alt['engine']=='tesseract_best':tess=mapped
            if alt['engine']=='PaddleOCR_LOCAL_REDETECTION':paddle=mapped
        paddle=collapse_local_row_fragments(paddle)
        rows=ink_rows(image,region['box'])
        outcome={'regionId':region['id'],'lineIds':region['lineIds'],'status':'RETAINED',
                 'reason':'INSUFFICIENT_SPATIAL_CORROBORATION','inkBands':rows,'changes':[]}
        # A one-to-many vertical split is accepted only for the SAME literal
        # sequence, re-detected by Paddle and Tess in separate physical rows.
        if len(primary)==1 and len(paddle)>1 and len(paddle)==len(tess)==len(rows):
            ordered=sorted(paddle,key=lambda l:l['box'][1]);ts=sorted(tess,key=lambda l:l['box'][1])
            same=all(literal_key(a['text'])==literal_key(b['text']) for a,b in zip(ordered,ts))
            separated=all(a['box'][3]<b['box'][1] for a,b in zip(ordered,ordered[1:]))
            if same and separated and literal_key(''.join(l['text'] for l in ordered))==literal_key(primary[0]['text']):
                original=primary[0];original['includedInDraft']=False
                for i,l in enumerate(ordered):
                    lines.append({**l,'id':original['id']+f'-split-{i+1}','includedInDraft':True,
                                  'difference':'VERIFIED_PHYSICAL_SPLIT','sourceLineIds':[original['id']],
                                  'block':original.get('block'),'blockType':original.get('blockType'),'originalText':original['text']})
                outcome.update(status='APPLIED',reason='SAME_LITERAL_SEQUENCE_IN_DISTINCT_IMAGE_ROWS',
                               changes=[{'lineId':original['id'],'before':original['text'],'after':'\n'.join(l['text'] for l in ordered)}])
                covered.add(original['id']);decisions.append(outcome);continue
        for target in group:
            if target['id'] in covered or target.get('engine')=='native' or target.get('segmentationOnly'):continue
            def spatial(candidates):
                hits=[l for l in candidates if intersection(l['box'],target['box'])/max(1,min(area(l['box']),area(target['box'])))>=.65]
                return hits[0] if len(hits)==1 else None
            p=spatial(paddle);t=spatial(tess)
            if not p or not t or len(ink_rows(image,p['box']))!=1:continue
            if literal_key(p['text'])!=literal_key(t['text']) or not literal_key(p['text']):continue
            if any(intersection(p['box'],l['box'])/max(1,min(area(p['box']),area(l['box'])))>.5 for l in lines if l.get('includedInDraft') and l['id']!=target['id']):continue
            candidate=p['text'];reason=None
            if target.get('primaryMissing'):
                if literal_key(target['text'])!=literal_key(candidate):continue
                reason='MISSING_LINE_IMAGE_AND_LOCAL_REDETECTION_CONFIRMED'
            elif literal_key(candidate)!=literal_key(target['text']):
                # Two same-engine runs are not treated as independent votes.
                # They establish crop stability; the independent engine and ink
                # geometry must corroborate the entire literal replacement.
                if p['text']!=t['text']:
                    # Both independent engines already agree on EVERY literal
                    # character, but detector fragments can lose spaces when
                    # joined. Equal-length character replacement can retain the
                    # primary's exact whitespace template instead of choosing
                    # either engine's conflicting spacing. No word is guessed.
                    literal=literal_key(candidate)
                    if target['text']!=normalize(target['text']) or len(literal)!=len(literal_key(target['text'])) or nonletter_signature(candidate)!=nonletter_signature(target['text']):continue
                    from difflib import SequenceMatcher
                    original=literal_key(target['text'])
                    if any(tag not in {'equal','replace'} or b-a!=d-c for tag,a,b,c,d in SequenceMatcher(None,original,literal,autojunk=False).get_opcodes()):continue
                    if any(a!=b and (not a.isalnum() or not b.isalnum()) for a,b in zip(original,literal)):continue
                    replacements=iter(literal)
                    candidate=''.join(c if c.isspace() else next(replacements) for c in target['text'])
                n=max(1,len(literal_key(target['text'])))
                if sequence_edit_units(literal_key(target['text']),literal_key(candidate))>max(1,int(n*.15)):continue
                if intersection(p['box'],target['box'])/max(1,area(target['box']))<.7:continue
                reason='LOCAL_LITERAL_PRIMARY_WHITESPACE_PRESERVED' if p['text']!=t['text'] else 'LOCAL_LITERAL_AND_SPATIAL_REDETECTION_CONFIRMED'
            if literal_key(candidate)==literal_key(target['text']) or target.get('primaryMissing'):
                # Spacing is adopted from actual TXT only with image evidence.
                if supported_spacing(image,t['text'],t.get('words'),t['box']):candidate=t['text']
                elif literal_key(candidate)==literal_key(target['text']) and candidate!=target['text'] and not supported_spacing(image,candidate,p.get('words'),p['box']):candidate=target['text']
                if candidate!=target['text'] and literal_key(candidate)==literal_key(target['text']):reason=reason or 'VISIBLE_WORD_GAPS_WITH_LITERAL_ALIGNMENT'
            if target.get('originalIncludedInDraft') and (not preserves_existing_spacing(target['text'],candidate) or nonletter_signature(target['text'])!=nonletter_signature(candidate)):
                outcome['reason']='EXISTING_WHITESPACE_OR_PUNCTUATION_PRESERVED_REVIEW_ONLY'
                continue
            if reason and (candidate!=target['text'] or not target.get('includedInDraft')):
                old=target['text'];target.update(text=candidate,includedInDraft=True,selectionReason=reason)
                covered.add(target['id']);outcome['changes'].append({'lineId':target['id'],'before':old if target.get('originalIncludedInDraft') else '', 'after':candidate,'reason':reason})
        if outcome['changes']:outcome.update(status='APPLIED',reason='EVIDENCE_BOUND_LOCAL_SELECTION')
        decisions.append(outcome)
    # Reuse already executed secondary detections. Exact partial lines can
    # corroborate gaps without authorising any whole-line character change.
    fragments=list(page.get('enginesRaw',{}).get('tesseract',[]))
    for region in page.get('localRefinement',{}).get('candidates',[]):
        for alt in region.get('alternatives',[]):
            if alt['engine']=='tesseract_best':fragments.extend(_page_alternative(region,alt))
    for target in lines:
        if not target.get('includedInDraft'):continue
        restored=restore_fragment_spacing(image,target,fragments)
        if restored['text']==target['text']:continue
        old=target['text'];target.update(text=restored['text'],selectionReason='EXACT_FRAGMENT_AND_VISIBLE_WORD_GAP')
        decisions.append({'regionId':None,'lineIds':[target['id']],'status':'APPLIED','reason':'EXACT_FRAGMENT_AND_VISIBLE_WORD_GAP',
                          'changes':[{'lineId':target['id'],'before':old,'after':restored['text'],'insertedAtLiteralOffsets':restored['insertedAtLiteralOffsets']} ]})
    # Retain geometrical order for all alternatives; only selected lines become
    # the draft. Global y/x sorting cannot interleave detected columns.
    formulas=[(i,b['box']) for i,b in enumerate(page.get('structure',{}).get('blocks',[])) if b.get('type') in {'formula','display_formula','inline_formula'}]
    for l in lines:
        if l.get('engine')!='native' and any(intersection(l['box'],b)/max(1,min(area(l['box']),area(b)))>=.7 and l.get('block')==i for i,b in formulas):
            l.update(includedInDraft=False,difference='FORMULA_REGION_SEPARATE',selectionReason='FORMULA_REGION_PRESERVED_SEPARATELY_NOT_TRANSCRIBED')
    selected=[l for l in lines if l.get('includedInDraft')]
    selected=precision_reading_order(selected,page.get('structure',{}),image.width)
    profile=page.get('literary',{}).get('requestedProfile','auto')
    gaps=physical_separators(image,selected,profile)
    for i,l in enumerate(selected):l['draftLineIndex']=i;l['separatorBefore']=gaps.get(l['id'],'\n' if i else '')
    page['draft']=compose_precision_draft(selected)
    page['literary']=literary_structure(image,selected,page['draft'],profile)
    page['literary'].update(version=PRECISION_POLICY['version'],readingOrder='BOUNDED_COLUMN_AND_PHYSICAL_ROWS',
                            textUnchanged=before['text']==page['draft']['text'],rawOrderPreserved=False)
    for boundary in page['literary']['boundaries']:
        if page['draft']['text'][:boundary['position']].endswith('\n\n'):
            boundary.update(automaticallyApplied=True,status='DRAFT_IMAGE_GAP_REQUIRES_USER_CONFIRMATION')
    page['precision']={'policy':dict(PRECISION_POLICY),'before':before,'decisions':decisions,
                       'changedCharacters':sequence_edit_units(before['text'],page['draft']['text']),
                       'changeCountDefinition':'Sequence-aligned edit units; exact CER measured separately against reference',
                       'requiresReview':True,'referenceUsed':False,'crossEngineConfidenceRanked':False}
    page['draftProvider']='IMAGE_SUPPORTED_LOCAL_SELECTION_REVIEW_REQUIRED'
    page['structure']=bind_ruled_cells(image,page.get('structure',{}),selected)
    if page.get('localRefinement'):
        page['localRefinement']['automaticallyChangedCharacters']=page['precision']['changedCharacters']
        page['localRefinement']['selection']=PRECISION_POLICY['textSelection']
    return page


def precision_reading_order(lines,structure,width):
    """Recursive whitespace cuts using boxes; no same-row column interleaving."""
    def order(items,depth=0):
        if len(items)<3 or depth>=4:return sorted(items,key=lambda l:(l['box'][1],l['box'][0]))
        tables=[b['box'] for b in structure.get('blocks',[]) if b.get('type')=='table']
        if tables and all(any(intersection(l['box'],b)/max(1,area(l['box']))>.7 for b in tables) for l in items):
            h=statistics.median(l['box'][3]-l['box'][1] for l in items)
            rows=[]
            for l in sorted(items,key=lambda l:l['box'][1]):
                if rows and abs(l['box'][1]-rows[-1][0]['box'][1])<h*.5:rows[-1].append(l)
                else:rows.append([l])
            return [l for row in rows for l in sorted(row,key=lambda l:l['box'][0])]
        # Separate physical page regions before looking for column gutters. A
        # short left-aligned footnote belongs after BOTH columns. Do not split
        # stanza gaps inside the same layout block into page-wide row bands.
        vertical=sorted(items,key=lambda l:l['box'][1])
        h=statistics.median(l['box'][3]-l['box'][1] for l in items);bottom=vertical[0]['box'][3]
        # Layout models can assign one block to EACH widely spaced body row.
        # Repeated leading is not a page boundary: otherwise row-band recursion
        # consumes its depth budget before the existing gutter search is reached.
        row_gaps=[];edge=bottom
        for l in vertical[1:]:
            if l['box'][1]>edge:row_gaps.append(l['box'][1]-edge)
            edge=max(edge,l['box'][3])
        region_gap=max(h*1.5,statistics.median(row_gaps)*1.7 if row_gaps else 0)
        for i,l in enumerate(vertical[1:],1):
            gap=l['box'][1]-bottom
            left_blocks={v.get('block') for v in vertical[:i] if v.get('block') is not None}
            right_blocks={v.get('block') for v in vertical[i:] if v.get('block') is not None}
            if gap>region_gap and not left_blocks.intersection(right_blocks):
                return order(vertical[:i],depth+1)+order(vertical[i:],depth+1)
            bottom=max(bottom,l['box'][3])
        boxes=sorted((l['box'][0],l['box'][2]) for l in items)
        cuts=[];right=boxes[0][1]
        for a,b in boxes[1:]:
            if a-right>width*.035:cuts.append((a-right,(a+right)/2))
            right=max(right,b)
        if cuts:
            _,cut=max(cuts);left=[l for l in items if l['box'][2]<cut];right=[l for l in items if l['box'][0]>cut]
            if len(left)>=2 and len(right)>=2:
                return order(left,depth+1)+order(right,depth+1)
        # A heading/footer may cross a genuine body gutter. Both sides must
        # contain several lines and no ambiguous spanner inside the body.
        h=statistics.median(l['box'][3]-l['box'][1] for l in items)
        for fraction in [.5,.45,.55,.4,.6]:
            cut=width*fraction
            left=[l for l in items if l['box'][2]<cut-h*.3];right=[l for l in items if l['box'][0]>cut+h*.3]
            spans=[l for l in items if l not in left and l not in right]
            if len(left)<2 or len(right)<2 or len(spans)>2:continue
            top=min(l['box'][1] for l in left+right);bottom=max(l['box'][3] for l in left+right)
            if any(l['box'][1]>top and l['box'][3]<bottom for l in spans):continue
            before=[l for l in spans if l['box'][1]<=top];after=[l for l in spans if l not in before]
            return order(before,depth+1)+order(left,depth+1)+order(right,depth+1)+order(after,depth+1)
        # Preserve model block order when a gutter cannot be established.
        if all(l.get('block') is not None for l in items):
            return sorted(items,key=lambda l:(l['block'],l['box'][1],l['box'][0]))
        return sorted(items,key=lambda l:(l['box'][1],l['box'][0]))
    # A table is a single reading-order object, not several text columns.
    remaining=list(lines);chunks=[]
    for i,b in enumerate(b['box'] for b in structure.get('blocks',[]) if b.get('type')=='table'):
        members=[l for l in remaining if intersection(l['box'],b)/max(1,area(l['box']))>=.7]
        if members:
            remaining=[l for l in remaining if l not in members]
            chunks.append({'box':b,'block':members[0].get('block'),'_tableLines':order(members),'id':f'table-order-{i}'})
    ordered=order(remaining+chunks)
    return [line for item in ordered for line in item.get('_tableLines',[item])]


def physical_separators(image,lines,profile):
    """Only visually supported blank lines. Never guess a space count/word."""
    gaps={}
    # A large white gap alone cannot distinguish a prose paragraph from a
    # heading/illustration break. Keep these as existing review proposals.
    if profile!='poetry':return gaps
    heights=[l['box'][3]-l['box'][1] for l in lines];h=statistics.median(heights) if heights else 1
    pairs=[(a,b) for a,b in zip(lines,lines[1:]) if b['box'][1]>a['box'][3] and intersection([a['box'][0],0,a['box'][2],1],[b['box'][0],0,b['box'][2],1])>0]
    ordinary=statistics.median([min(h,b['box'][1]-a['box'][3]) for a,b in pairs]) if pairs else h
    for a,b in pairs:
        gap=b['box'][1]-a['box'][3]
        if gap<=max(h*1.5,ordinary*1.7):continue
        rect=[max(a['box'][0],b['box'][0]),a['box'][3]+1,min(a['box'][2],b['box'][2]),b['box'][1]-1]
        if area(rect)<=0:continue
        hist=image.crop(rect).convert('L').histogram()
        if sum(hist[235:])/max(1,sum(hist))>=.98:gaps[b['id']]='\n\n'
    return gaps


def compose_precision_draft(lines):
    # Reuse the canonical normalization map by including separators inside each
    # mapping unit, then expose spans covering only the literal recognized line.
    raw=''.join(l.get('separatorBefore','\n' if i else '')+l['text'] for i,l in enumerate(lines))
    result=compose_draft([{'id':'page','text':raw,'box':[0,0,0,0]}],profile='auto')
    mapping=[];rp=0;np=0
    for i,l in enumerate(lines):
        sep=l.get('separatorBefore','\n' if i else '');rp+=len(sep);np+=len(normalize(sep))
        mapping.append({'lineId':l['id'],'rawStart':rp,'rawEnd':rp+len(l['text']), 'start':np,'end':np+len(normalize(l['text'])),'box':l['box']})
        rp+=len(l['text']);np+=len(normalize(l['text']))
    result['lineMap']=mapping
    return result


def precision_crop_view(crop):
    """Bounded, reversible view. The source image is never overwritten.

    Horizontal projection is image evidence for small skew only, not a complete
    orientation detector. Ambiguous/vertical/180-degree pages remain for review.
    """
    import numpy as np
    from PIL import Image,ImageOps
    gray=np.asarray(crop.convert('L'));thumb=gray
    if max(gray.shape)>900:
        scale=900/max(gray.shape);thumb=np.asarray(Image.fromarray(gray).resize((max(1,int(gray.shape[1]*scale)),max(1,int(gray.shape[0]*scale)))))
    low,high=[float(v) for v in np.percentile(thumb,[2,98])]
    meta={'contrastRange':[low,high],'originalSize':list(crop.size),'angleDegrees':0,
          'applied':[],'inverseAffine':[1,0,0,0,1,0],'orientation':'SMALL_SKEW_ONLY_OTHER_ORIENTATIONS_REQUIRE_REVIEW'}
    view=crop
    if high-low<110 and high-low>=20:
        view=ImageOps.autocontrast(crop,cutoff=0);meta['applied'].append('LOW_CONTRAST_AUTOCONTRAST')
    binary=(thumb<min(210,(low+high)/2)).astype(np.uint8)
    def score(mask):
        rows=mask.sum(axis=1).astype(float)
        return float((rows*rows).sum()/max(1,rows.sum()))
    base=score(binary);best=(base,0)
    if min(binary.shape)>=24:
        for angle in [-3,-2,-1,1,2,3]:
            value=score(np.asarray(Image.fromarray(binary).rotate(angle,resample=Image.Resampling.NEAREST)))
            if value>best[0]:best=(value,angle)
    meta['projectionGain']=best[0]/max(1,base)
    if best[1] and best[0]>base*1.25:
        angle=math.radians(best[1]);c=math.cos(angle);s=math.sin(angle);cx=crop.width/2;cy=crop.height/2
        view=view.rotate(best[1],resample=Image.Resampling.BICUBIC,fillcolor='white')
        meta.update(angleDegrees=best[1],inverseAffine=[c,-s,cx-c*cx+s*cy,s,c,cy-s*cx-c*cy])
        meta['applied'].append('IMAGE_PROJECTION_DESKEW')
    return view,meta


def bind_ruled_cells(image,structure,lines):
    """Existing layout table + visible ruled grid, retaining raw model cells.

    No invented cell text: literal selected OCR lines are assigned by geometry.
    Borderless/ambiguous grids retain the model's unverified alternatives.
    """
    import numpy as np
    from copy import deepcopy
    out=deepcopy(structure);tables=list(out.get('tables',[]));bound=[]
    for block in out.get('blocks',[]):
        if block.get('type')!='table':continue
        a=block['box'];box=[max(0,int(a[0])-6),max(0,int(a[1])-6),min(image.width,int(a[2])+6),min(image.height,int(a[3])+6)]
        if area(box)>4_000_000:continue
        ink=np.asarray(image.crop(box).convert('L'))<160
        def rules(values):
            groups=[]
            for i,on in enumerate(values):
                if not on:continue
                if groups and i-groups[-1][-1]<=2:groups[-1].append(i)
                else:groups.append([i])
            return [sum(g)/len(g) for g in groups]
        xs=rules(ink.mean(axis=0)>.65);ys=rules(ink.mean(axis=1)>.7)
        if not 3<=len(xs)<=48 or not 3<=len(ys)<=100 or (len(xs)-1)*(len(ys)-1)>2000:continue
        if min(b-a for a,b in zip(xs,xs[1:]))<8 or min(b-a for a,b in zip(ys,ys[1:]))<8:continue
        cells=[]
        for r,(top,bottom) in enumerate(zip(ys,ys[1:])):
            for c,(left,right) in enumerate(zip(xs,xs[1:])):
                cell=[left+box[0],top+box[1],right+box[0],bottom+box[1]]
                matches=[l for l in lines if cell[0]<(l['box'][0]+l['box'][2])/2<cell[2] and cell[1]<(l['box'][1]+l['box'][3])/2<cell[3]]
                matches.sort(key=lambda l:(l['box'][1],l['box'][0]))
                cells.append({'row':r,'column':c,'rowSpan':1,'columnSpan':1,'text':'\n'.join(l['text'] for l in matches),'box':cell,'lineIds':[l['id'] for l in matches],'requiresReview':True})
        bound.append({'cells':cells,'box':a,'geometrySource':'IMAGE_RULES_IN_ORIGINAL_PAGE_PIXELS','cellGeometryStatus':'IMAGE_RULED_GRID_REVIEW_REQUIRED','rawModelAlternatives':tables,'textSource':'SELECTED_LITERAL_OCR_NOT_MODEL_HTML'})
    if bound:out['tables']=bound
    return out


def orthogonal_view(image,angle):
    from PIL import Image
    options={90:(Image.Transpose.ROTATE_90,[0,-1,image.width,1,0,0]),
             180:(Image.Transpose.ROTATE_180,[-1,0,image.width,0,-1,image.height]),
             270:(Image.Transpose.ROTATE_270,[0,1,0,-1,0,image.height])}
    if angle not in options:return image,[1,0,0,0,1,0]
    transpose,inverse=options[angle]
    return image.transpose(transpose),inverse


def prepare_region_view(image,box,*,mode,parent_orientation=None):
    """Reuse verified document orientation, never classify a small crop anew.

    The coordinator supplies the owned parent's metadata, not client input.
    Original source pixels and public box coordinates remain unchanged.
    """
    if mode not in {'standard','precise'}:raise ValueError('INVALID_OCR_MODE')
    if len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):raise ValueError('INVALID_REGION_BOX')
    if not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height:raise ValueError('INVALID_REGION_BOX')
    pixels=[round(v) for v in box]
    if area(pixels)<=0 or area(pixels)>1_500_000:raise ValueError('REGION_PIXEL_LIMIT')
    parent=parent_orientation or {};angle=0
    if parent.get('applied'):
        angle=parent.get('angle');verification=parent.get('verification') or {}
        if (mode!='precise' or type(angle) is not int or angle not in {90,180,270}
            or verification.get('allowed') is not True
            or verification.get('basis')!='IMAGE_ROWS_AND_SAME_RECOGNIZER_VIEW_COMPARISON'):raise ValueError('UNVERIFIED_PARENT_ORIENTATION')
    view,inverse=orthogonal_view(image.convert('RGB').crop(pixels),angle)
    inverse=list(inverse);inverse[2]+=pixels[0];inverse[5]+=pixels[1]
    return view,{'angle':angle,'parentOrientationUsed':bool(angle),'originalSourceBox':list(box),'actualPixelBox':pixels,
                 'inverseAffineToOriginalPage':inverse,'sourcePreserved':True,'basis':'VERIFIED_PARENT_DOCUMENT_VIEW_NOT_NEW_REGION_INFERENCE'}


def orientation_verdict(prediction,old,new,original,corrected):
    """A classifier proposes a view; image/readability evidence decides it.

    OCR scores are compared only within the SAME pinned recognizer. A quarter
    turn may preserve high character confidence while scrambling line order;
    in that case horizontal ink concentration supplies the independent image
    signal. A half turn cannot use that signal and must improve recognition.
    """
    import numpy as np
    def quality(lines):
        return {'characters':sum(sum(c.isalnum() for c in l['text']) for l in lines),
                'meanConfidence':sum(l.get('confidence',0) for l in lines)/max(1,len(lines))}
    def projection(im):
        view=im.copy();view.thumbnail((900,900));ink=np.asarray(view.convert('L'))<180
        rows=ink.sum(axis=1).astype(float)
        return float((rows*rows).sum()/max(1,rows.sum()))
    prior=quality(old);candidate=quality(new);gain=projection(corrected)/max(1,projection(original))
    readable=candidate['characters']>=4 and candidate['meanConfidence']>=.9
    recognition_gain=candidate['meanConfidence']>=prior['meanConfidence']+.1 or (candidate['characters']>=max(4,prior['characters']*1.5) and candidate['meanConfidence']>=prior['meanConfidence'])
    physical_gain=prediction['angle'] in {90,270} and gain>=1.5 and candidate['characters']>=prior['characters']*.7 and candidate['meanConfidence']>=prior['meanConfidence']-.03
    allowed=prediction['angle'] in {90,180,270} and prediction['score']>=.8 and readable and (recognition_gain or physical_gain)
    return {'allowed':allowed,'originalQuality':prior,'candidateQuality':candidate,'imageProjectionGain':gain,
            'basis':'IMAGE_ROWS_AND_SAME_RECOGNIZER_VIEW_COMPARISON','independentAccuracyCalibration':False}


def restore_original_page_boxes(page,inverse,original_size):
    """Map known page geometry only; raw model coordinate frames stay explicit."""
    def box(b):
        ps=[(inverse[0]*x+inverse[1]*y+inverse[2],inverse[3]*x+inverse[4]*y+inverse[5]) for x,y in [(b[0],b[1]),(b[2],b[1]),(b[0],b[3]),(b[2],b[3])]]
        return [min(p[0] for p in ps),min(p[1] for p in ps),max(p[0] for p in ps),max(p[1] for p in ps)]
    for line in page['lines']:
        line['box']=box(line['box'])
        if line.get('secondary'):line['secondary']={**line['secondary'],'box':box(line['secondary']['box'])}
    for m in page['draft']['lineMap']:m['box']=box(m['box'])
    for m in page.get('precision',{}).get('before',{}).get('lineMap',[]):m['box']=box(m['box'])
    for line in page.get('literary',{}).get('physicalLines',[]):line['box']=box(line['box'])
    for block in page['structure'].get('blocks',[]):block['box']=box(block['box'])
    for region in page.get('localRefinement',{}).get('candidates',[]):
        region['inferenceViewBox']=list(region['box']);region['box']=box(region['box'])
        region['alternativeCoordinateFrame']='ORIENTED_VIEW_CROP; page inverseAffine is required'
    for table in page['structure'].get('tables',[]):
        if table.get('box'):table['box']=box(table['box'])
        for cell in table.get('cells',[]):
            if cell.get('box'):cell['box']=box(cell['box'])
    page.update(width=original_size[0],height=original_size[1])
    page['structure']['rawModelCoordinateFrame']='UPRIGHT_INFERENCE_VIEW; preprocessing.inverseAffine maps to original'
    return page
