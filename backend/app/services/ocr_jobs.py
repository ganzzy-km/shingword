"""Durable OCR jobs using existing OcrRun/AppSetting and the upload outbox."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from flask import current_app
from ..extensions import db
from ..models import AppSetting,OcrRun,SourceDocument,DocumentRevision,User

ACTIVE={'queued','running'}
TERMINAL={'REVIEW_READY','ALTERNATIVE_READY','CONFIRMED','FAILED','CANCELLED','EXPIRED'}
_threads_lock=threading.Lock()
_probe_capacity=threading.BoundedSemaphore(2)


class OcrCapacityError(ValueError):pass


def digest(data):return hashlib.sha256(data).hexdigest()


def config():
    name=current_app.config.get('OCR_LOCAL_CONFIG') or os.getenv('OCR_LOCAL_CONFIG','') or os.getenv('GEULBIT_OCR_CONFIG','')
    if not name:return None
    path=Path(name)
    if not path.is_absolute() or not path.is_file():raise ValueError('OCR_CONFIG_UNAVAILABLE')
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('manifest') and digest(Path(value['manifest']).read_bytes())!=value.get('manifestSha'):raise ValueError('OCR_MANIFEST_MISMATCH')
    for field in ['python','models','tesseract','tessdata']:
        if not Path(value[field]).is_absolute() or not Path(value[field]).exists():raise ValueError('OCR_COMPONENT_UNAVAILABLE')
    processor=b''.join(Path(__file__).with_name(n).read_bytes() for n in ['ocr_pipeline.py','ocr_models.py'])
    value['fingerprint']=digest(path.read_bytes()+processor)
    return value


def root():return Path(current_app.config['UPLOAD_FOLDER']).resolve()


def local_file(name):
    if not isinstance(name,str) or not name or Path(name).name!=name or ':' in name or '/' in name or '\\' in name:raise ValueError('UNSAFE_OCR_FILE')
    value=root()/name
    if value.is_symlink() or not value.resolve().is_relative_to(root()):raise ValueError('UNSAFE_OCR_FILE')
    return value


def row(job_id):
    run=db.session.get(OcrRun,job_id);data=db.session.get(AppSetting,'ocr_job:'+job_id)
    if not run or run.target_type!='source-v2' or not data:return None,None
    return run,data


def lock_document(item):
    db.session.execute(db.update(SourceDocument).where(SourceDocument.id==item.id).values(updated_at=SourceDocument.updated_at))
    db.session.refresh(item)


def valid(run,meta):
    from ..v2.privacy_lifecycle import document_expired
    doc=db.session.get(SourceDocument,run.target_id);user=db.session.get(User,meta['owner'])
    return bool(doc and user and user.status=='ACTIVE' and doc.owner_id==meta['owner'] and doc.stored_name==meta['originalFile']
                and doc.scope==meta['scope'] and doc.access_mode in {'VIEW','DOWNLOAD'} and not document_expired(doc))


def create_job(doc,revision_id,*,operation='document',parent=None,box=None,engine=None,table=False,mode='precise',profile='auto'):
    if not isinstance(mode,str) or mode not in {'standard','precise'}:raise ValueError('INVALID_OCR_MODE')
    if mode=='standard':
        # Read/confirm old jobs without inventing a new standard document path.
        # A restricted old region remains bound to its owned historical parent.
        prior,record=row(parent) if operation=='region' and parent else (None,None)
        if (not prior or not record or prior.target_id!=doc.id or prior.target_type!='source-v2'
            or record.value.get('owner')!=doc.owner_id or record.value.get('operation')!='document'
            or record.value.get('ocrMode')!='standard' or engine!='paddle'):
            raise ValueError('OCR_MODE_RETIRED')
    from .ocr_pipeline import LITERARY_PROFILES
    if not isinstance(profile,str) or profile not in LITERARY_PROFILES:raise ValueError('INVALID_OCR_PROFILE')
    if mode=='standard':profile='auto'
    cfg=config()
    if not cfg:raise ValueError('OCR_NOT_CONFIGURED')
    pending=OcrRun.query.filter(OcrRun.target_type=='source-v2',OcrRun.status.in_(list(ACTIVE)))
    if pending.count()>=8 or pending.join(SourceDocument,OcrRun.target_id==SourceDocument.id).filter(SourceDocument.owner_id==doc.owner_id).count()>=2:raise OcrCapacityError('OCR_QUEUE_FULL')
    data={'owner':doc.owner_id,'originalFile':doc.stored_name,'scope':doc.scope,'inputRevisionId':revision_id,
          'inputSha':digest(local_file(doc.stored_name).read_bytes()),'fingerprint':cfg['fingerprint'],
          'operation':operation,'ocrMode':mode,'ocrProfile':profile,'modelManifestSha':cfg.get('manifestSha'),'draftVersion':1,'drafts':{},'pages':[],'files':[],
          'totalPages':doc.page_count,'completedPages':0,'parent':parent,'box':box,'engine':engine,'table':table,
          'createdAt':datetime.now(timezone.utc).isoformat()}
    from ..v2.privacy_lifecycle import document_deadline
    due=document_deadline(doc);data['retentionDeadline']=due.isoformat() if due else None
    run=OcrRun(target_type='source-v2',target_id=doc.id,status='queued',language='kor+eng');db.session.add(run);db.session.flush()
    name='ocr-'+run.id;data['prefix']=name
    data['files']=[name+s for s in ['-request.json','-response.json','-progress.json','-cancel','-worker.log']]
    data['files']+=[name+'-tess'+s for s in ['.png','.txt','.tsv']]
    if operation=='document':
        data['files']+=[f'{name}-p{i:04d}{suffix}' for i in range(1,doc.page_count+1) for suffix in ['.png','.json']]
    data['files']+=[name+'-region.json'] if operation=='region' else []
    data['files']+=[n+'.tmp' for n in data['files'] if n.endswith('.json')]
    db.session.add(AppSetting(key='ocr_job:'+run.id,value=data));db.session.flush()
    return run


def inspect_upload(data,filename):
    cfg=config()
    if not cfg:return None
    directory=root();directory.mkdir(parents=True,exist_ok=True)
    if not _probe_capacity.acquire(blocking=False):raise OcrCapacityError('OCR_PROBE_BUSY')
    key='ocr-probe-'+uuid.uuid4().hex;names=[key+'-input',key+'-request.json',key+'-response.json']
    try:
        local_file(names[0]).write_bytes(data)
        request={'operation':'probe','config':cfg,'input':str(local_file(names[0])),'maxPages':current_app.config.get('PDF_MAX_PAGES',100),'maxBytes':current_app.config['MAX_CONTENT_LENGTH']}
        local_file(names[1]).write_text(json.dumps(request),encoding='utf-8')
        result=subprocess.Popen([cfg['python'],str(Path(__file__).with_name('ocr_models.py')),'--request',str(local_file(names[1])),'--response',str(local_file(names[2]))],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|4,env=worker_env())
        close_job=process_job(result,2*1024**3)
        try:result.wait(timeout=30)
        finally:
            close_job()
            if result.poll() is None:result.kill();result.wait(timeout=5)
        output=json.loads(local_file(names[2]).read_text(encoding='utf-8'))
        if result.returncode or output.get('status')=='FAILED':raise ValueError(output.get('error','INVALID_FILE'))
        if (output['needsOcr'] or not output['nativeText'].strip()) and output['pages']>24:raise ValueError('OCR_PAGE_LIMIT')
        return output
    finally:
        for name in names:local_file(name).unlink(missing_ok=True)
        _probe_capacity.release()


def worker_env():
    return {**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK':'True','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'}


def process_memory(pid):
    if os.name!='nt':return 0
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:return 0
    try:
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        fn=ctypes.WinDLL('psapi').GetProcessMemoryInfo
        fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        fn(handle,ctypes.byref(counters),counters.cb)
        return counters.WorkingSetSize
    finally:kernel.CloseHandle(handle)


def region_worker_input(page,rect,engine,mode):
    # Only owned-parent worker metadata supplies orientation. Public POST body
    # remains page/box/engine; no new client trust boundary or model call.
    import copy
    return {'input':str(local_file(page['imageFile'])),'box':list(rect),'engine':engine,
            'parentOrientation':copy.deepcopy(page.get('preprocessing')) if mode=='precise' else None}


def host_memory():
    """Physical availability and commit headroom are different Windows counters."""
    if os.name!='nt':return {'available':False}
    import ctypes
    from ctypes import wintypes
    class Performance(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable','SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize']]+[(n,wintypes.DWORD) for n in ['HandleCount','ProcessCount','ThreadCount']]
    info=Performance();info.cb=ctypes.sizeof(info)
    fn=ctypes.WinDLL('psapi',use_last_error=True).GetPerformanceInfo;fn.argtypes=[ctypes.POINTER(Performance),wintypes.DWORD]
    if not fn(ctypes.byref(info),info.cb):return {'available':False}
    return {'available':True,'physicalTotalBytes':info.PhysicalTotal*info.PageSize,'physicalAvailableBytes':info.PhysicalAvailable*info.PageSize,'commitTotalBytes':info.CommitTotal*info.PageSize,'commitLimitBytes':info.CommitLimit*info.PageSize,'commitAvailableBytes':(info.CommitLimit-info.CommitTotal)*info.PageSize}


def process_private_bytes(pid):
    if os.name!='nt':return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage']]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.restype=wintypes.HANDLE;kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:return None
    try:
        c=Counters();c.cb=ctypes.sizeof(c);fn=ctypes.WinDLL('psapi').GetProcessMemoryInfo;fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        return c.PrivateUsage if fn(handle,ctypes.byref(c),c.cb) else None
    finally:kernel.CloseHandle(handle)


def vl_admission(cfg=None,snapshot=None):
    cfg=cfg if cfg is not None else config();host=snapshot if snapshot is not None else host_memory();result={'allowed':False,'host':host,'reason':'RESOURCE_EVIDENCE_REQUIRED'}
    try:
        pin=cfg['resourceEvidence'];p=Path(pin['path'])
        if not p.is_absolute() or digest(p.read_bytes())!=pin['sha256']:return result
        evidence=json.loads(p.read_text(encoding='utf-8'))
        vl=evidence['vlPeakJobCommitBytes'];s4_private=evidence['s4PeakPrivateCommitBytes'];s4_rss=evidence.get('s4ObservedPeakRssBytes',s4_private)
        if evidence['status']!='PASS' or any(not isinstance(n,int) or isinstance(n,bool) or n<=0 for n in [vl,s4_private,s4_rss]):return result
        # RSS is not private commit. Use its larger prior observation only as a
        # conservative reserve floor, never label it a commit measurement.
        s4=max(s4_private,s4_rss)
        # A transparent proportional reserve over measured peaks, not a new
        # arbitrary GiB hard cap. Existing JobObject limits remain authoritative.
        margin=(vl+s4+3)//4;required=vl+s4+margin
        result.update(evidenceSha=pin['sha256'],vlPeakJobCommitBytes=vl,s4PeakPrivateCommitBytes=s4_private,s4ObservedPeakRssBytes=s4_rss,s4ReserveBytes=s4,reserveBytes=margin,requiredAvailableBytes=required)
        if not host.get('available'):result['reason']='HOST_MEMORY_UNAVAILABLE';return result
        result['allowed']=min(host['physicalAvailableBytes'],host['commitAvailableBytes'])>=required
        result['reason']='RESOURCE_BUDGET_AVAILABLE' if result['allowed'] else 'INSUFFICIENT_HOST_RAM_OR_COMMIT'
    except (KeyError,ValueError,TypeError,OSError):pass
    return result


def process_job(process,limit_bytes=8*1024**3):
    """Hard Windows commit limit and kill-on-parent-exit, scoped to this child."""
    if os.name!='nt':raise RuntimeError('WINDOWS_JOB_REQUIRED')
    import ctypes
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_=[('PerProcessUserTimeLimit',ctypes.c_int64),('PerJobUserTimeLimit',ctypes.c_int64),('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
    class IO(ctypes.Structure):_fields_=[(n,ctypes.c_uint64) for n in ['ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount']]
    class Extended(ctypes.Structure):_fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.QueryInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateJobObjectW(None,None);limits=Extended()
    limits.BasicLimitInformation.LimitFlags=0x2000|0x100|0x400 # kill on close + process/job memory
    limits.ProcessMemoryLimit=limit_bytes;limits.JobMemoryLimit=limit_bytes+1024**3
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,wintypes.HANDLE(int(process._handle))):
        if handle:kernel.CloseHandle(handle)
        process.terminate();process.wait(timeout=5);raise RuntimeError('WORKER_ISOLATION_FAILED')
    # Popen was created suspended: assign before the venv launcher can spawn the
    # real Python interpreter. All descendants then inherit the same JobObject.
    resume=ctypes.WinDLL('ntdll').NtResumeProcess;resume.argtypes=[wintypes.HANDLE]
    if resume(wintypes.HANDLE(int(process._handle)))!=0:
        kernel.CloseHandle(handle);raise RuntimeError('WORKER_RESUME_FAILED')
    def close():kernel.CloseHandle(handle)
    def memory():
        counters=Extended()
        if not kernel.QueryInformationJobObject(handle,9,ctypes.byref(counters),ctypes.sizeof(counters),None):return 0
        return counters.PeakJobMemoryUsed
    def cpu_seconds():
        class Accounting(ctypes.Structure):
            _fields_=[(n,ctypes.c_int64) for n in ['TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime']]+[(n,wintypes.DWORD) for n in ['TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses']]
        counters=Accounting()
        if not kernel.QueryInformationJobObject(handle,1,ctypes.byref(counters),ctypes.sizeof(counters),None):return None
        return (counters.TotalUserTime+counters.TotalKernelTime)/10_000_000
    close.memory=memory
    close.cpu_seconds=cpu_seconds
    return close


def release_worker(process,close_job):
    """Bounded cleanup, including failures before JobObject attachment returns."""
    errors=[];running=True
    try:running=process.poll() is None
    except Exception as error:errors.append(error)
    if running:
        try:process.terminate()
        except Exception as error:errors.append(error)
        try:process.wait(timeout=5)
        except Exception as error:
            errors.append(error)
            try:process.kill()
            except Exception as error:errors.append(error)
            try:process.wait(timeout=5)
            except Exception as error:errors.append(error)
    if close_job:
        try:close_job()
        except Exception as error:errors.append(error)
    # Cleanup failures must not replace a monitor/DB error. Never log messages
    # or command lines, which can contain paths or document information.
    for error in errors:
        current_app.logger.warning('OCR worker cleanup error: %s',type(error).__name__)


def execute(app,job_id):
    preparation_started=time.monotonic()
    with app.app_context():
        run,record=row(job_id)
        if not run or run.status!='queued':return
        meta=dict(record.value);cfg=config()
        queued_at=datetime.fromisoformat(meta['createdAt'])
        # Legacy retry records do not have a separate re-enqueue timestamp.
        queue_seconds=max(0,(datetime.now(timezone.utc)-queued_at).total_seconds()) if not meta.get('retries') else None
        if not valid(run,meta) or cfg['fingerprint']!=meta['fingerprint']:
            run.status='EXPIRED';db.session.commit();return
        if digest(local_file(meta['originalFile']).read_bytes())!=meta['inputSha']:
            run.status='FAILED';run.error_message='입력 파일 무결성을 확인해 주세요.';db.session.commit();return
        if meta['operation']=='region' and meta['engine']=='vl':
            admission=vl_admission(cfg)
            if not admission['allowed']:
                run.status='FAILED';run.error_message='VL 실행에 필요한 호스트 메모리 여유를 확인할 수 없습니다. 원본과 초안은 보존됩니다.'
                record.value={**meta,'failureCode':'RESOURCE_UNAVAILABLE','resourceAdmission':admission};db.session.commit();return
            meta['resourceAdmission']=admission
        lock_document(db.session.get(SourceDocument,run.target_id));run.status='running';meta['workerPid']=None
        record.value=meta;db.session.commit();db.session.remove()
        request={'operation':meta['operation'],'ocrMode':meta.get('ocrMode','precise'),'ocrProfile':meta.get('ocrProfile','auto'),'config':cfg,'input':str(local_file(meta['originalFile'])),'inputSha':meta['inputSha'],
                 'owner':meta['owner'],'inputRevisionId':meta['inputRevisionId'],
                 'outputRoot':str(root()),'prefix':meta['prefix'],'fingerprint':meta['fingerprint'],
                 'cancelFile':str(local_file(meta['prefix']+'-cancel')),'progressFile':str(local_file(meta['prefix']+'-progress.json')),'table':meta['table']}
        if meta['operation']=='region':
            _,parent=row(meta['parent']);pages=parent.value['pages']
            page=next(p for p in pages if p['page']==meta['box']['page'])
            request.update(region_worker_input(page,meta['box']['rect'],meta['engine'],meta.get('ocrMode','precise')))
        request_path=local_file(meta['prefix']+'-request.json');response_path=local_file(meta['prefix']+'-response.json')
        request_path.write_text(json.dumps(request),encoding='utf-8');response_path.unlink(missing_ok=True)
        preparation_seconds=time.monotonic()-preparation_started
        started=time.monotonic();peak=0;reason=None;host_samples=[{'seconds':0,**host_memory()}]
        with local_file(meta['prefix']+'-worker.log').open('wb') as log:
            process=subprocess.Popen([cfg['python'],str(Path(__file__).with_name('ocr_models.py')),'--request',str(request_path),'--response',str(response_path)],stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|4,env=worker_env())
            memory_limit=(2 if meta.get('ocrMode')=='standard' else 8)*1024**3
            close_job=None
            try:
                close_job=process_job(process,memory_limit)
                while process.poll() is None:
                    time.sleep(.35);peak=max(peak,close_job.memory())
                    if time.monotonic()-started-host_samples[-1]['seconds']>=2 and len(host_samples)<128:
                        sample={'seconds':round(time.monotonic()-started,3),**host_memory()};host_samples.append(sample)
                        if meta['operation']=='region' and meta['engine']=='vl' and (not sample.get('available') or min(sample['physicalAvailableBytes'],sample['commitAvailableBytes'])<meta['resourceAdmission']['reserveBytes']):reason='HOST_MEMORY_PRESSURE';process.terminate();break
                    db.session.remove();run,record=row(job_id)
                    if not run or run.status=='CANCELLED' or not valid(run,record.value):reason='CANCELLED';process.terminate();break
                    if time.monotonic()-started>(240 if meta['operation']=='region' else 1800):reason='TIME_BUDGET';process.terminate();break
                    if peak>memory_limit:reason='MEMORY_BUDGET';process.terminate();break
                    if local_file(meta['prefix']+'-worker.log').stat().st_size>8*1024*1024:reason='LOG_BUDGET';process.terminate();break
                    progress=local_file(meta['prefix']+'-progress.json')
                    if progress.is_file():
                        value=json.loads(progress.read_text(encoding='utf-8'))
                        if value['completedPages']!=record.value['completedPages']:
                            lock_document(db.session.get(SourceDocument,run.target_id));db.session.refresh(record)
                            record.value={**record.value,'completedPages':value['completedPages']};db.session.commit()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                peak=max(peak,close_job.memory());cpu=close_job.cpu_seconds()
            finally:release_worker(process,close_job)
        db.session.remove();run,record=row(job_id)
        if not run:
            # Deletion may have run while inference was finishing. This child is
            # now reaped: remove only its already registered derived file names.
            for name in meta['files']:
                if name.startswith(meta['prefix']+'-'):local_file(name).unlink(missing_ok=True)
            return
        lock_document(db.session.get(SourceDocument,run.target_id))
        if reason=='CANCELLED' or run.status=='CANCELLED' or not valid(run,record.value):
            run.status='CANCELLED';db.session.commit();return
        result=json.loads(response_path.read_text(encoding='utf-8')) if response_path.is_file() else {}
        value={**record.value,'peakWorkerBytes':peak,'seconds':time.monotonic()-started,'cpuSeconds':cpu,'exitCode':process.returncode,'hostMemorySamples':host_samples+[{'seconds':round(time.monotonic()-started,3),**host_memory()}]}
        value['timing']={'queueWaitSeconds':queue_seconds,'serverPreparationSeconds':preparation_seconds,**result.get('timing',{})}
        if reason or process.returncode or result.get('status')=='FAILED':
            run.status='FAILED';run.error_message='OCR 처리에 실패했습니다. 완료된 페이지는 보존됩니다. 다시 실행할 수 있습니다.'
            value['failureCode']=reason or 'MODEL_FAILED'
        elif meta['operation']=='region':
            run.status='ALTERNATIVE_READY';value['alternative']=result
        else:
            pages=[json.loads(local_file(n).read_text(encoding='utf-8')) for n in result['pageFiles']]
            run.status='REVIEW_READY';value.update(pages=pages,completedPages=len(pages),modelTimings=result['modelTimings'])
        saving=time.monotonic();record.value=value;db.session.commit()
        # Observe the commit without a second metadata write that could race
        # with a user's subsequent draft edit or confirmation.
        committed=time.monotonic()-saving
        try:
            with local_file(meta['prefix']+'-worker.log').open('a',encoding='utf-8') as log:
                log.write('\n'+json.dumps({'event':'OCR_RESULT_COMMIT','seconds':committed})+'\n')
        except OSError:pass  # A diagnostic write must not invalidate saved work.


def kick(app=None):
    app=app or current_app._get_current_object()
    if app.config.get('OCR_AUTOSTART',True) is False or not config():return
    with _threads_lock:
        thread=app.extensions.get('ocr_thread')
        if thread and thread.is_alive():return
        thread=threading.Thread(target=_loop,args=(app,),name='geulbit-ocr-coordinator',daemon=True)
        app.extensions['ocr_thread']=thread;thread.start()


def _loop(app):
    with app.app_context():
        # Single local heavy worker, also across duplicate web processes.
        import msvcrt
        lockfile=root()/'.ocr-worker.lock';lockfile.parent.mkdir(parents=True,exist_ok=True)
        with lockfile.open('a+b') as lock:
            if lockfile.stat().st_size==0:lock.write(b'0');lock.flush()
            lock.seek(0)
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:return
            try:
                # Acquiring the process-wide worker lock proves no previous
                # coordinator is still processing these runs. Keep page files.
                for stale in OcrRun.query.filter_by(target_type='source-v2',status='running').all():
                    stale.status='FAILED';stale.error_message='Worker가 중단되었습니다. 완료 페이지를 유지하고 재개할 수 있습니다.'
                db.session.commit()
                while True:
                    db.session.remove()
                    pending=OcrRun.query.filter_by(target_type='source-v2',status='queued').order_by(OcrRun.created_at).first()
                    if not pending:break
                    identifier=pending.id;db.session.remove()
                    try:execute(app,identifier)
                    except Exception:
                        db.session.rollback();run,_=row(identifier)
                        if run:run.status='FAILED';run.error_message='OCR 작업이 중단되었습니다. 완료 페이지를 보존했습니다.';db.session.commit()
            finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def derived_files_for_delete(doc):
    """Called inside existing document deletion transaction; physical outbox later."""
    files=[]
    for run in OcrRun.query.filter_by(target_type='source-v2',target_id=doc.id):
        _,record=row(run.id)
        if record:
            local_file(record.value['prefix']+'-cancel').touch()
            files+=record.value['files'];db.session.delete(record)
        db.session.delete(run)
    return files
