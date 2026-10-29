"""Local inference process. Never imported by Flask; no remote document requests."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True',
                  OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false')


def deny_network():
    def blocked(*args,**kwargs):raise OSError('OCR_NETWORK_DISABLED')
    socket.create_connection=blocked;socket.getaddrinfo=blocked
    socket.socket.connect=blocked;socket.socket.connect_ex=blocked


def atomic(path,data):
    p=Path(path);tmp=p.with_suffix(p.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as out:json.dump(data,out,ensure_ascii=False,allow_nan=False)
    os.replace(tmp,p)


def serial(value):
    if isinstance(value,dict):return {str(k):serial(v) for k,v in value.items() if k not in {'input_img','doc_preprocessor_res'}}
    if isinstance(value,(list,tuple)):return [serial(v) for v in value]
    if hasattr(value,'tolist'):return value.tolist()
    if hasattr(value,'label') and hasattr(value,'bbox'):
        return {'block_label':value.label,'block_bbox':serial(value.bbox),'block_content':value.content,'block_id':value.index,'block_order':value.order_index}
    if isinstance(value,Path):return str(value)
    return value


def recognition_lines(ocr):
    lines=[]
    for i,text in enumerate(ocr.get('rec_texts',[])):
        boxes=ocr.get('rec_boxes',[]);polys=ocr.get('rec_polys',[])
        if len(boxes)>i:box=boxes[i]
        else:
            poly=polys[i];box=[min(p[0] for p in poly),min(p[1] for p in poly),max(p[0] for p in poly),max(p[1] for p in poly)]
        lines.append({'text':text,'box':list(map(float,box)),'confidence':float(ocr['rec_scores'][i]),'engine':'korean_PP-OCRv5_mobile_rec'})
    return lines


class LocalModels:
    def __init__(self,config):self.config=config;self.pipelines={};self.timings=[];self.verified=set()

    def stage(self,model,stage):
        print(json.dumps({'event':'OCR_MODEL_STAGE','model':model,'stage':stage,'monotonic':time.monotonic()}),flush=True)

    def verify(self,identifier):
        if identifier in self.verified or not self.config.get('manifest'):return
        path=Path(self.config['manifest']);data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=self.config['manifestSha']:raise RuntimeError('MODEL_MANIFEST_MISMATCH')
        manifest=json.loads(data);entry=next(m for m in manifest['models'] if m['id']==identifier)
        for name,pin in entry['files'].items():
            file=Path(entry['localDir'])/name;h=hashlib.sha256()
            with file.open('rb') as stream:
                for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
            if h.hexdigest()!=pin['sha256']:raise RuntimeError('MODEL_HASH_MISMATCH')
        self.verified.add(identifier)

    def lightweight(self,image):
        """Installed detector/recognizer only: no layout, table, Tess or VL."""
        checked=time.monotonic()
        for name in ['PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec']:self.verify('PaddlePaddle/'+name)
        verified=time.monotonic()
        self.stage('PaddleOCR:standard','IMPORT_BEGIN')
        from paddleocr import PaddleOCR
        self.stage('PaddleOCR:standard','IMPORT_END')
        imported=time.monotonic()
        key='standard';root=Path(self.config['models']);start=time.monotonic()
        if key not in self.pipelines:
            self.pipelines[key]=PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det',text_detection_model_dir=str(root/'PP-OCRv5_mobile_det'),
                text_recognition_model_name='korean_PP-OCRv5_mobile_rec',text_recognition_model_dir=str(root/'korean_PP-OCRv5_mobile_rec'),
                text_det_limit_side_len=960,text_det_limit_type='max',use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False,
                lang='korean',ocr_version='PP-OCRv5',device='cpu',engine='paddle_static',cpu_threads=1,enable_mkldnn=False,mkldnn_cache_capacity=3)
            self.timings.append({'model':'PaddleOCR:standard','loadSeconds':time.monotonic()-start})
        import numpy as np
        inference=time.monotonic()
        result=next(iter(self.pipelines[key].predict(np.asarray(image))));exported=result.json
        self.timings.append({'model':'PaddleOCR:standard','verificationSeconds':verified-checked,'importSeconds':imported-verified,'inferenceSeconds':time.monotonic()-inference})
        return recognition_lines(serial(exported.get('res',exported)))

    def versions(self,calls):
        from importlib.metadata import version
        versions={}
        if not calls:return versions
        if 'PaddleOCR' in calls or 'PP-StructureV3' in calls:versions['paddleocr']=version('paddleocr')
        if self.config.get('manifest'):
            manifest=json.loads(Path(self.config['manifest']).read_text(encoding='utf-8'))
            names=set(calls)
            if 'PP-StructureV3' in calls:names.add('PP-DocLayout_plus-L')
            if 'tesseract_best' in calls:names.add('tessdata_best');versions['tesseract']=manifest.get('Tesseract',{}).get('version')
            for entry in manifest['models']:
                name=entry['id'].rsplit('/',1)[-1]
                if name in names:versions[entry['id']]=entry['revision']
        return versions

    def orientation(self,image):
        """Pinned, installed CPU classifier; used only by the precise path."""
        self.verify('PaddlePaddle/PP-LCNet_x1_0_doc_ori')
        from paddleocr import DocImgOrientationClassification
        import numpy as np
        if 'orientation' not in self.pipelines:
            start=time.monotonic()
            self.pipelines['orientation']=DocImgOrientationClassification(model_name='PP-LCNet_x1_0_doc_ori',model_dir=str(Path(self.config['models'])/'PP-LCNet_x1_0_doc_ori'),device='cpu',cpu_threads=1,enable_mkldnn=False)
            self.timings.append({'model':'PP-LCNet_x1_0_doc_ori','loadSeconds':time.monotonic()-start})
        start=time.monotonic();result=next(iter(self.pipelines['orientation'].predict(np.asarray(image))))
        data=serial(result.json.get('res',result.json))
        self.timings.append({'model':'PP-LCNet_x1_0_doc_ori','inferenceSeconds':time.monotonic()-start})
        return {'angle':int(data['label_names'][0]),'score':float(data['scores'][0])}

    def structure(self,image,table=False,detector=None):
        checked=time.monotonic()
        detector=detector or self.config.get('detector','PP-OCRv5_server_det')
        if detector not in {'PP-OCRv5_server_det','PP-OCRv5_mobile_det'}:raise ValueError('INVALID_DETECTOR')
        for name in ['PP-DocLayout_plus-L',detector,'korean_PP-OCRv5_mobile_rec']:self.verify('PaddlePaddle/'+name)
        if table:
            for key,name in self.config.get('tableOptions',{}).items():
                if key.endswith('_model_name'):self.verify('PaddlePaddle/'+name)
        verified=time.monotonic()
        self.stage('PP-StructureV3','IMPORT_BEGIN')
        from paddleocr import PPStructureV3
        self.stage('PP-StructureV3','IMPORT_END')
        imported=time.monotonic()
        key=detector+(':table' if table else ':text')
        start=time.monotonic();root=Path(self.config['models'])
        if key not in self.pipelines:
            options=dict(layout_detection_model_name='PP-DocLayout_plus-L',layout_detection_model_dir=str(root/'PP-DocLayout_plus-L'),
                text_detection_model_name=detector,text_detection_model_dir=str(root/detector),
                text_det_limit_side_len=960,text_det_limit_type='max',
                text_recognition_model_name='korean_PP-OCRv5_mobile_rec',text_recognition_model_dir=str(root/'korean_PP-OCRv5_mobile_rec'),
                use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False,
                use_region_detection=False,lang='korean',ocr_version='PP-OCRv5',
                use_formula_recognition=False,use_seal_recognition=False,use_chart_recognition=False,
                use_table_recognition=table,device='cpu',engine='paddle_static',cpu_threads=1,enable_mkldnn=False,mkldnn_cache_capacity=3)
            options.update(self.config.get('tableOptions',{}) if table else {})
            if table:
                # The official table subpipeline has a separate orientation
                # default. Keep the same explicit offline Korean OCR policy.
                from paddlex.inference import load_pipeline_config
                pipeline_config=load_pipeline_config('PP-StructureV3')
                pipeline_config['SubPipelines']['TableRecognition']['SubPipelines']['GeneralOCR']['use_textline_orientation']=False
                options['paddlex_config']=pipeline_config
            self.pipelines[key]=PPStructureV3(**options)
            self.timings.append({'model':'PP-StructureV3:'+key,'loadSeconds':time.monotonic()-start})
        import numpy as np
        inference=time.monotonic()
        result=next(iter(self.pipelines[key].predict(np.asarray(image))))
        self.timings.append({'model':'PP-StructureV3:'+key,'verificationSeconds':verified-checked,'importSeconds':imported-verified,'inferenceSeconds':time.monotonic()-inference})
        exported=result.json
        data=serial(exported.get('res',exported));ocr=data.get('overall_ocr_res',{})
        lines=recognition_lines(ocr)
        layout=data.get('layout_det_res',{}).get('boxes',[])
        parsed=data.get('parsing_res_list',[])
        blocks=[{'type':b['block_label'],'box':list(map(float,b['block_bbox'])),'modelOrder':b.get('block_order')} for b in parsed]
        if not blocks:blocks=[{'type':b['label'],'box':list(map(float,b['coordinate'])),'confidence':float(b['score'])} for b in layout]
        from ocr_pipeline import table_cells
        tables=[{**t,'cells':table_cells(t),'cellGeometryStatus':'RAW_MODEL_COORDINATES_REQUIRE_REVIEW'} for t in data.get('table_res_list',[])]
        # Retain every raw block, footnote and table. Markdown is not the source.
        return lines,{'engine':'PP-StructureV3','detector':detector,'recognizer':'korean_PP-OCRv5_mobile_rec','blocks':blocks,'tables':tables,'raw':data,'untranscribed':[b for b in blocks if b['type'] in {'image','formula','chart'}],'requiresStructureReview':True}

    def tesseract(self,image,psm=3,timeout=60):
        self.verify('tesseract-ocr/tessdata_best')
        import tempfile
        # Produce TXT and coordinates in one LSTM inference, retaining the TXT
        # renderer's actual spacing rather than adding spaces between TSV words.
        scratch=Path(self.config.get('scratch',tempfile.gettempdir()))
        prefix=self.config.get('scratchPrefix','geulbit-ocr-smoke')+'-tess'
        source=scratch/(prefix+'.png');out=scratch/prefix
        files=[source,out.with_suffix('.txt'),out.with_suffix('.tsv')]
        try:
            image.save(source)
            env={**os.environ,'TESSDATA_PREFIX':self.config['tessdata']}
            inference=time.monotonic()
            r=subprocess.run([self.config['tesseract'],str(source),str(out),'-l','kor+eng','--oem','1','--psm',str(psm),'-c','tessedit_create_txt=1','-c','tessedit_create_tsv=1'],env=env,capture_output=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.timings.append({'model':'tesseract_best','psm':psm,'inferenceSeconds':time.monotonic()-inference})
            if r.returncode:raise RuntimeError('TESSERACT_EXECUTION_FAILED')
            text=files[1].read_text(encoding='utf-8')
            rows=list(csv.DictReader(files[2].read_text(encoding='utf-8').splitlines(),delimiter='\t'))
        finally:
            for path in files:path.unlink(missing_ok=True)
        grouped={}
        for row in rows:
            if not row['text'].strip() or float(row['conf'])<0:continue
            key=tuple(row[k] for k in ['block_num','par_num','line_num']);x,y,w,h=[int(row[k]) for k in ['left','top','width','height']]
            grouped.setdefault(key,[]).append((row['text'],[x,y,x+w,y+h],float(row['conf'])))
        raw_lines=[line for line in text.splitlines() if line.strip()]
        return [{'text':raw_lines[i] if len(raw_lines)==len(grouped) else ' '.join(w[0] for w in words),'rawWords':[w[0] for w in words],
                 'words':[{'text':w[0],'box':w[1]} for w in words],
                 'textAlignment':'EXACT_TXT_LINE_COUNT' if len(raw_lines)==len(grouped) else 'UNVERIFIED_WORD_SEQUENCE',
                 'box':[min(w[1][0] for w in words),min(w[1][1] for w in words),max(w[1][2] for w in words),max(w[1][3] for w in words)],'confidence':sum(w[2] for w in words)/len(words),'engine':'tesseract_best'} for i,words in enumerate(grouped.values())]

    def region(self,image,engine,mode='precise'):
        if mode=='standard':
            if engine!='paddle':raise ValueError('STANDARD_MODE_ENGINE')
            lines=self.lightweight(image)
            return {'text':'\n'.join(l['text'] for l in lines),'lines':lines,'engine':'paddle','detector':'PP-OCRv5_mobile_det','alternativeOnly':True}
        if engine in {'tesseract','tesseract-line'}:
            psm=7 if engine=='tesseract-line' else 6
            return {'text':'\n'.join(l['text'] for l in self.tesseract(image,psm=psm)),'engine':engine,'psm':psm,'alternativeOnly':True}
        if engine=='paddle':
            lines,structure=self.structure(image,detector='PP-OCRv5_server_det')
            return {'text':'\n'.join(l['text'] for l in lines),'lines':lines,'engine':engine,'detector':structure['detector'],'alternativeOnly':True}
        if engine!='vl':raise ValueError('INVALID_ENGINE')
        self.verify('PaddlePaddle/PaddleOCR-VL')
        import torch
        from transformers import AutoModelForCausalLM,AutoProcessor
        torch.set_num_threads(4)
        start=time.monotonic();root=self.config.get('vlModelDir') or str(Path(self.config['models'])/'PaddleOCR-VL')
        model=AutoModelForCausalLM.from_pretrained(root,trust_remote_code=True,local_files_only=True,torch_dtype=torch.float32,low_cpu_mem_usage=True,attn_implementation='eager').to('cpu').eval()
        processor=AutoProcessor.from_pretrained(root,trust_remote_code=True,local_files_only=True,use_fast=False)
        loaded=time.monotonic()-start
        messages=[{'role':'user','content':[{'type':'image','image':image},{'type':'text','text':'OCR:'}]}]
        inputs=processor.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt')
        with torch.inference_mode():out=model.generate(**inputs,max_new_tokens=256,do_sample=False,use_cache=True)
        # Only generated tokens; the fixed OCR instruction is never included.
        generated=out[:,inputs['input_ids'].shape[1]:]
        text=processor.batch_decode(generated,skip_special_tokens=True)[0]
        return {'text':text,'engine':'PaddleOCR-VL-0.9B','modelRevision':self.config['vlRevision'],'loadSeconds':loaded,'seconds':time.monotonic()-start,'alternativeOnly':True,'scope':'SELECTED_REGION_NOT_FULL_PAGE_PIPELINE'}


def refine_local(image,page,models):
    """Bounded PSM/crop experiments; every result remains a review alternative."""
    from ocr_pipeline import local_refinement_regions,LITERARY_POLICY
    started=time.monotonic();candidates=[]
    for region in local_refinement_regions(page):
        remaining=LITERARY_POLICY['localBudgetSeconds']-(time.monotonic()-started)
        if remaining<=0:break
        crop=image.crop(region['box']);candidate={**region,'automaticallyApplied':False,'policyVersion':LITERARY_POLICY['version'],'alternatives':[]}
        try:
            lines=models.tesseract(crop,psm=region['psm'],timeout=min(60,remaining))
            candidate['alternatives'].append({'engine':'tesseract_best','psm':region['psm'],'text':'\n'.join(l['text'] for l in lines),'lines':lines,'coordinates':'CROP_LOCAL_PIXELS','modelVersions':models.versions(['tesseract_best'])})
        except Exception as error:candidate['unavailable']='LOCAL_TESSERACT:'+type(error).__name__
        if 'PRIMARY_LINE_MISSING' in region['triggers'] and time.monotonic()-started<LITERARY_POLICY['localBudgetSeconds']:
            # An independent secondary detection found a region. Only this crop
            # is re-detected; upscale is explicit and never changes source pixels.
            scale=2 if crop.height<64 and crop.width*crop.height*4<=LITERARY_POLICY['maxRegionPixels'] else 1
            view=crop.resize((crop.width*scale,crop.height*scale)) if scale!=1 else crop
            try:
                lines=models.lightweight(view)
                candidate['alternatives'].append({'engine':'PaddleOCR_LOCAL_REDETECTION','scale':scale,'text':'\n'.join(l['text'] for l in lines),'lines':lines,'coordinates':'SCALED_CROP_LOCAL_PIXELS','modelVersions':models.versions(['PaddleOCR','PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec'])})
            except Exception as error:candidate['paddleUnavailable']=type(error).__name__
        candidates.append(candidate)
    return {'policy':dict(LITERARY_POLICY),'candidates':candidates,'seconds':time.monotonic()-started,'automaticallyChangedCharacters':0,'selection':'ORIGINAL_PRIMARY_RETAINED_NO_PROVEN_AUTOMATIC_REPLACEMENT_RULE','VLautomatic':False}


def refine_precision(image,page,models):
    """Refine suspicious crops with reused models, never full-page VL voting."""
    from ocr_pipeline import local_refinement_regions,PRECISION_POLICY,precision_crop_view,area,ink_rows
    regions=local_refinement_regions(page)
    # The legacy review-only planner is reused. Low Paddle confidence and absent
    # Tess detection also deserve a crop, but do not themselves permit a change.
    for line in page['lines']:
        if line.get('engine')=='native' or not line.get('includedInDraft'):continue
        triggers=[]
        if line.get('confidence',1)<.90:triggers.append('LOW_PRIMARY_CONFIDENCE')
        if line.get('difference')=='SECONDARY_MISSING':triggers.append('SECONDARY_DETECTION_MISSING')
        if not triggers:continue
        b=line['box'];box=[max(0,b[0]-10),max(0,b[1]-10),min(image.width,b[2]+10),min(image.height,b[3]+10)]
        if area(box)>PRECISION_POLICY['maxRegionPixels'] or any(area([max(box[0],r['box'][0]),max(box[1],r['box'][1]),min(box[2],r['box'][2]),min(box[3],r['box'][3])])/max(1,min(area(box),area(r['box'])))>.7 for r in regions):continue
        regions.append({'id':f'precision-local-{len(regions)+1}','box':box,'lineIds':[line['id']],'triggers':triggers,'psm':7,'status':'EVIDENCE_REQUIRED'})
        if len(regions)>=PRECISION_POLICY['maxLocalRegions']:break
    started=time.monotonic();candidates=[]
    for region in regions[:PRECISION_POLICY['maxLocalRegions']]:
        remaining=PRECISION_POLICY['localBudgetSeconds']-(time.monotonic()-started)
        if remaining<=0:break
        if not ink_rows(image,region['box']):continue
        crop=image.crop(region['box']);view,preprocessing=precision_crop_view(crop)
        candidate={**region,'policyVersion':PRECISION_POLICY['version'],'alternatives':[],'automaticallyApplied':False,'preprocessing':preprocessing}
        scale=2 if view.height<96 and view.width*view.height*4<=PRECISION_POLICY['maxRegionPixels'] else 1
        enlarged=view.resize((view.width*scale,view.height*scale)) if scale!=1 else view
        for engine in ['tesseract_best','PaddleOCR_LOCAL_REDETECTION']:
            if time.monotonic()-started>=PRECISION_POLICY['localBudgetSeconds']:break
            try:
                lines=models.tesseract(view,psm=region['psm'],timeout=max(1,min(30,remaining))) if engine=='tesseract_best' else models.lightweight(enlarged)
                candidate['alternatives'].append({'engine':engine,'psm':region['psm'] if engine=='tesseract_best' else None,'scale':1 if engine=='tesseract_best' else scale,'inverseAffine':preprocessing['inverseAffine'],
                    'text':'\n'.join(l['text'] for l in lines),'lines':lines,'coordinates':'REVERSIBLE_CROP_TO_ORIGINAL_PAGE','modelVersions':models.versions(['tesseract_best'] if engine=='tesseract_best' else ['PaddleOCR','PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec'])})
            except Exception as error:candidate['unavailable']=(candidate.get('unavailable','')+' '+engine+':'+type(error).__name__).strip()
        candidates.append(candidate)
    return {'policy':dict(PRECISION_POLICY),'candidates':candidates,'seconds':time.monotonic()-started,'automaticallyChangedCharacters':0,'selection':'PENDING_IMAGE_SUPPORTED_SELECTION','VLautomatic':False}


def run(request,models=None):
    run_started=time.monotonic()
    from ocr_pipeline import probe,render_page,combine_page,ruled_table_candidate
    config=request['config'];op=request['operation'];mode=request.get('ocrMode','precise')
    if not isinstance(mode,str) or mode not in {'standard','precise'}:raise ValueError('INVALID_OCR_MODE')
    from ocr_pipeline import LITERARY_PROFILES,PRECISION_POLICY
    profile=request.get('ocrProfile','auto') if mode=='precise' else 'auto'
    if not isinstance(profile,str) or profile not in LITERARY_PROFILES:raise ValueError('INVALID_OCR_PROFILE')
    runtime=Path(config['models']).parent
    os.environ.update(HF_HOME=str(runtime/'hf-cache'),HF_MODULES_CACHE=str(runtime/'hf-modules'),PADDLE_HOME=str(runtime/'paddle-cache'),PADDLE_PDX_CACHE_HOME=str(runtime/'paddlex-cache'))
    config['scratch']=request.get('outputRoot',str(Path(request['input']).parent));config['scratchPrefix']=request.get('prefix','geulbit-ocr-smoke')
    models=models or LocalModels(config)
    if op=='probe':return probe(request['input'],max_pages=request.get('maxPages',100),max_bytes=request.get('maxBytes',50*1024*1024))
    if op=='region':
        from PIL import Image
        from ocr_pipeline import prepare_region_view
        with Image.open(request['input']) as im:
            box=request['box'];region,preprocessing=prepare_region_view(im,box,mode=mode,parent_orientation=request.get('parentOrientation'))
        if region.width*region.height>1_500_000:raise ValueError('REGION_PIXEL_LIMIT')
        result=models.region(region,request['engine'],mode=mode)
        calls=['PaddleOCR','PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec'] if mode=='standard' else ['PaddleOCR-VL'] if request['engine']=='vl' else ['tesseract_best'] if request['engine'] in {'tesseract','tesseract-line'} else ['PP-StructureV3','PP-OCRv5_server_det','korean_PP-OCRv5_mobile_rec']
        if result.get('lines'):
            from ocr_pipeline import _page_alternative
            result['lines']=_page_alternative({'box':[0,0,im.width,im.height]},
                {'lines':result['lines'],'inverseAffine':preprocessing['inverseAffineToOriginalPage'],'scale':1})
        return {**result,'preprocessing':preprocessing,'coordinateFrame':'ORIGINAL_PAGE_PIXELS','ocrMode':mode,'modelVersions':models.versions(calls),'modelManifestSha':config.get('manifestSha')}
    if op!='document':raise ValueError('INVALID_OPERATION')
    from ocr_pipeline import validate_input,compose_draft
    info=validate_input(request['input'],max_pages=24)
    validation_seconds=time.monotonic()-run_started
    root=Path(request['outputRoot']);prefix=request['prefix'];pages=[]
    binding={key:request.get(key) for key in ['owner','inputRevisionId','inputSha','fingerprint']};binding['ocrMode']=mode
    if mode=='precise':binding['ocrProfile']=profile;binding['literaryVersion']=PRECISION_POLICY['version'];binding['preprocessingPolicy']=PRECISION_POLICY['preprocessing']
    binding['modelManifestSha']=config.get('manifestSha')
    for index in range(info['pages']):
        if Path(request['cancelFile']).exists():return {'status':'CANCELLED','pages':pages}
        result=root/f'{prefix}-p{index+1:04d}.json';imagefile=root/f'{prefix}-p{index+1:04d}.png'
        if result.exists():
            saved=json.loads(result.read_text(encoding='utf-8'))
            if saved.get('cacheBinding')==binding and imagefile.is_file():pages.append(saved);continue
        start=time.monotonic();image,page=render_page(request['input'],index)
        image.save(imagefile,format='PNG')
        render_seconds=time.monotonic()-start;recognition_started=time.monotonic()
        calls=[];unavailable=[]
        if page['route'] in {'ocr','mixed'} and mode=='standard':
            paddle=models.lightweight(image);calls=['PaddleOCR','PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec']
            output=combine_page(image,page,paddle,[],{'engine':'STANDARD_NO_LAYOUT','blocks':[],'tables':[],'requiresStructureReview':True})
            for line in output['lines']:
                if line['engine']!='native':line['difference']='SINGLE_ENGINE_NO_COMPARISON'
        elif page['route'] in {'ocr','mixed'}:
            from ocr_pipeline import ink_rows,orthogonal_view,restore_original_page_boxes,orientation_verdict
            view=image;orientation={'applied':False,'angle':0,'inverseAffine':[1,0,0,0,1,0],'sourcePreserved':True}
            if page['route']=='ocr' and ink_rows(image,[0,0,image.width,image.height]):
                try:
                    predicted=models.orientation(image);orientation['classification']=predicted;calls.append('PP-LCNet_x1_0_doc_ori')
                    if predicted['angle'] in {90,180,270} and predicted['score']>=.8:
                        rotated,inverse=orthogonal_view(image,predicted['angle'])
                        old=models.lightweight(image);new=models.lightweight(rotated)
                        verdict=orientation_verdict(predicted,old,new,image,rotated);orientation['verification']=verdict
                        if verdict['allowed']:
                            view=rotated;orientation.update(applied=True,angle=predicted['angle'],inverseAffine=inverse)
                        else:orientation['abstention']='ORIENTATION_GAIN_NOT_CORROBORATED'
                except Exception as error:orientation['unavailable']=type(error).__name__
            try:
                table=request.get('table',False) or ruled_table_candidate(view)
                paddle,structure=models.structure(view,table=table);calls+=['PP-StructureV3',config.get('detector','PP-OCRv5_server_det'),'korean_PP-OCRv5_mobile_rec']
                structure['tableRequested']=table
            except Exception as error:
                import traceback;traceback.print_exc()
                paddle=[];structure={'blocks':[],'tables':[],'unavailable':'PP-StructureV3:'+type(error).__name__};unavailable.append(structure['unavailable'])
            try:tess=models.tesseract(view);calls+=['tesseract_best']
            except Exception as error:
                import traceback;traceback.print_exc()
                tess=[];unavailable.append('tesseract:'+type(error).__name__)
            if not paddle and not tess and len(unavailable)>=2:raise RuntimeError('OCR_ENGINES_UNAVAILABLE')
            output=combine_page(view,page,paddle,tess,structure,profile=profile)
            output['localRefinement']=refine_precision(view,output,models)
            from ocr_pipeline import select_precise_draft
            output=select_precise_draft(view,output)
            output['preprocessing']=orientation
            if orientation['applied']:output=restore_original_page_boxes(output,orientation['inverseAffine'],image.size)
        else:
            lines=[{**line,'id':f'line-{i+1}','engine':'native','difference':'NATIVE_PRESERVED'} for i,line in enumerate(page['nativeLines'])]
            output={**page,'lines':lines,'draft':compose_draft(lines),'structure':{'blocks':[],'tables':[]},'width':image.width,'height':image.height}
            if mode=='precise':
                from ocr_pipeline import literary_structure
                for i,line in enumerate(lines):line.update(includedInDraft=True,draftLineIndex=i)
                output['draft']=compose_draft(lines,profile=profile);output['literary']=literary_structure(image,lines,output['draft'],profile)
        output.update(page=index+1,imageFile=imagefile.name,inputSha=request['inputSha'],fingerprint=request['fingerprint'],cacheBinding=binding,calls=calls,unavailable=unavailable,seconds=time.monotonic()-start,ocrMode=mode,modelVersions=models.versions(calls),modelManifestSha=config.get('manifestSha'),timing={'renderAndImageSaveSeconds':render_seconds,'recognitionAndCompositionSeconds':time.monotonic()-recognition_started})
        save_started=time.monotonic()
        atomic(result,output);pages.append(output)
        atomic(request['progressFile'],{'completedPages':len(pages),'totalPages':info['pages'],'pageFiles':[f'{prefix}-p{p["page"]:04d}.json' for p in pages]})
        models.timings.append({'page':index+1,'pageAndProgressSaveSeconds':time.monotonic()-save_started})
        if sum(p.stat().st_size for p in root.glob(prefix+'-*'))>256*1024*1024:raise RuntimeError('DERIVED_FILE_LIMIT')
    return {'status':'REVIEW_READY','completedPages':len(pages),'totalPages':info['pages'],'pageFiles':[f'{prefix}-p{p["page"]:04d}.json' for p in pages],'modelTimings':models.timings,'timing':{'validationSeconds':validation_seconds,'workerRunSeconds':time.monotonic()-run_started}}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--response',required=True)
    args=parser.parse_args();deny_network()
    try:
        request=json.loads(Path(args.request).read_text(encoding='utf-8'));output=run(request);atomic(args.response,output)
    except Exception as error:
        # Trace stays in operator-only worker log, never the public response.
        import traceback
        traceback.print_exc();atomic(args.response,{'status':'FAILED','error':type(error).__name__+':'+str(error)[:160]});sys.exit(1)
