"""Synthetic, TLS loopback-only 20/40-user API load; summaries contain no bodies."""
import json,time,statistics,concurrent.futures,sys,ctypes
from ctypes import wintypes
from pathlib import Path
import requests,urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
def memory():
    class Memory(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD),('peak',ctypes.c_size_t),('rss',ctypes.c_size_t),('pagedPeak',ctypes.c_size_t),('paged',ctypes.c_size_t),('nonpagedPeak',ctypes.c_size_t),('nonpaged',ctypes.c_size_t),('pagefile',ctypes.c_size_t),('pagefilePeak',ctypes.c_size_t)]
    kernel=ctypes.windll.kernel32;kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE;kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x410,False,int(sys.argv[1]));info=Memory();info.cb=ctypes.sizeof(info)
    api=ctypes.windll.psapi.GetProcessMemoryInfo;api.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD];api.restype=wintypes.BOOL
    try:
        if not api(handle,ctypes.byref(info),info.cb):raise RuntimeError('MEMORY_MEASUREMENT_FAILED')
        return {'rssBytes':info.rss,'peakRssBytes':info.peak}
    finally:kernel.CloseHandle(handle)
base='https://127.0.0.1:8767';samples=[];users=[];errors=[];measurements=[]
def call(s,method,path,body=None,headers=None):
    begin=time.perf_counter();r=s.request(method,base+path,json=body,headers=headers,verify=False,timeout=30)
    elapsed=(time.perf_counter()-begin)*1000
    if not r.ok:raise RuntimeError(str(r.status_code)+' '+path)
    return r.json().get('data'),elapsed
for n in range(40):
    s=requests.Session();s.verify=False;s.get(base+'/__qa__/session/load-'+str(n).zfill(2),timeout=20)
    session,_=call(s,'GET','/api/auth/session');h={'X-CSRF-Token':session['csrfToken']}
    w,_=call(s,'POST','/api/writings',{'title':'synthetic load '+str(n),'content':'가상 부하 검사. 😀'},h)
    users.append((s,h,w))
def task(t):
    s,h,w=t
    _,read=call(s,'GET','/api/writings/'+w['id']);_,save=call(s,'PATCH','/api/writings/'+w['id'],{'revisionNumber':w['revisionNumber'],'content':w['content']},h)
    return [read,save]
start=time.monotonic();initial=memory();last_report=start;cycles=0
with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
    while time.monotonic()-start<300:
        count=20 if cycles%2==0 else 40;beg=time.monotonic()
        for future in [pool.submit(task,t) for t in users[:count]]:
            try:samples.extend(future.result())
            except Exception as e:errors.append(str(e))
        cycles+=1
        if cycles in [1,2]:measurements.append({'concurrency':count,'burstMs':round((time.monotonic()-beg)*1000,1)})
        if cycles%10==0:
            s,h,w=users[cycles%40];size=10000 if (cycles//10)%2 else 30000;body=('가상의 인물은 나무를 보았다. 나는 의미가 있다고 생각했다. 😀\n\n'*1000)[:size]
            w,save=call(s,'PATCH','/api/writings/'+w['id'],{'revisionNumber':w['revisionNumber'],'content':body},h);users[cycles%40]=(s,h,w)
            ids,_=call(s,'POST','/api/analyses',{'writingId':w['id'],'content':body,'revisionNumber':w['revisionNumber']},h);beg=time.perf_counter()
            for _ in range(100):
                job,_=call(s,'GET','/api/analysis-jobs/'+ids['jobId'])
                if job['status']=='completed':break
                if job['status']=='failed':raise RuntimeError('ANALYSIS_FAILED')
                time.sleep(.1)
            result,lookup=call(s,'GET','/api/analyses/'+ids['analysisId']);assert result['sourceVersion']['content']==body
            beg_pdf=time.perf_counter();pdf=s.get(base+'/api/analyses/'+ids['analysisId']+'/pdf',verify=False,timeout=30);assert pdf.status_code==200 and pdf.content.startswith(b'%PDF-')
            measurements.append({'codePoints':len(body),'saveMs':round(save,1),'analysisMs':round((beg_pdf-beg)*1000,1),'lookupMs':round(lookup,1),'pdfMs':round((time.perf_counter()-beg_pdf)*1000,1)})
        if time.monotonic()-last_report>=45:
            print(json.dumps({'elapsedSeconds':round(time.monotonic()-start),'requests':len(samples),'errors':len(errors)}),flush=True);last_report=time.monotonic()
        time.sleep(max(0,2-(time.monotonic()-beg)))
final=memory();ordered=sorted(samples)
evidence={'durationSeconds':round(time.monotonic()-start,1),'syntheticUsers':40,'concurrency':[20,40],'requests':len(samples),'errors':errors,'p50Ms':round(statistics.median(samples),1),'p95Ms':round(ordered[int(len(ordered)*.95)],1),'initialMemory':initial,'finalMemory':final,'measurements':measurements}
Path('artifacts/ui-v2/api-load.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8');print(json.dumps(evidence),flush=True)
if errors:raise SystemExit(1)
