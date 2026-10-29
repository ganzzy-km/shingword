import {useEffect,useRef,useState} from 'react'
import {api,errorMessage,type AccountSession} from './api'
import {useEscapeLayer} from './escape-navigation'
import type {Span} from './book-layout'
import SourceTools from './SourceTools'
import WritingTutorial from './WritingTutorial'
import {findMultipleTextSpans} from './text-search'
import {toolsDefaults,selectionAnchor,cpSlice,groupLabels,type Mark,type ToolsPreferences,type ToolsVersion} from './writing-tools'
import './writing-tools.css'

type Props={active:boolean;account:AccountSession;view:string;writingId:string;writingRevision:number;bodySaved:boolean;body:string;cursor:number;selection:Span|null;hasAnalysis:boolean;analyzing:boolean;
  ensureVersion:()=>Promise<ToolsVersion>;onJump:(span:Span)=>void;onNew:()=>void;onAnalyze:()=>Promise<void>;
  onPreferences:(p:ToolsPreferences)=>void;onPane:(pane:string)=>void;onFocus:(focus:boolean)=>void;onDirtyChange:(dirty:boolean)=>void;onContextChanged:()=>void;onSearch:(query:string)=>void;onFeedback:()=>void}
type Envelope={revisionNumber:number;data:ToolsPreferences;offerTutorial?:boolean}

export default function WritingTools(props:Props){
  const {active,account,view,writingId,body,selection,hasAnalysis,analyzing,ensureVersion,onJump}=props
  const [prefs,setPrefs]=useState<Envelope>({revisionNumber:0,data:toolsDefaults}),prefRef=useRef(prefs),queue=useRef(Promise.resolve())
  const [ready,setReady]=useState(false),[tutorial,setTutorial]=useState(false),[pane,setPane]=useState('body'),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  const [storedMarks,setMarks]=useState<Mark[]>([]),[claimId,setClaimId]=useState(''),[evidenceId,setEvidenceId]=useState(''),[group,setGroup]=useState('UNSORTED')
  const marks=props.bodySaved?storedMarks:storedMarks.map(m=>({...m,resolution:{status:'NEEDS_REVIEW',span:null}}))
  const [keywords,setKeywords]=useState(''),[range,setRange]=useState<Span>({start:0,end:0}),[sourceDirty,setSourceDirty]=useState(false)
  const panel=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null)
  const tutorialTrigger=useRef<HTMLButtonElement>(null)
  prefRef.current=prefs
  const update=(patch:Partial<ToolsPreferences>)=>{
    const pending=queue.current.then(async()=>{
      const old=prefRef.current
      const next=await api.patch<Envelope>('/writing-tools/preferences',{revisionNumber:old.revisionNumber,data:patch})
      const merged={...next,data:{...toolsDefaults,...next.data}}
      prefRef.current=merged;setPrefs(merged)
    })
    queue.current=pending.catch(()=>undefined)
    return pending
  }
  useEffect(()=>{if(!active)return;let alive=true;void api.get<Envelope>('/writing-tools/preferences').then(v=>{if(alive){const next={...v,data:{...toolsDefaults,...v.data}};prefRef.current=next;setPrefs(next);setReady(true);setTutorial(!!v.offerTutorial);if(v.offerTutorial)void update({tutorial:'ACTIVE'}).catch(e=>setError(errorMessage(e)))}}).catch(e=>setError(errorMessage(e)));return()=>{alive=false}},[active,account.id])
  useEffect(()=>{if(ready)props.onPreferences(prefs.data)},[prefs,ready])
  useEffect(()=>{if(selection)setRange(selection)},[selection])
  useEffect(()=>{props.onDirtyChange(sourceDirty)},[sourceDirty])
  const loadMarks=async()=>{if(writingId)setMarks(await api.get<Mark[]>('/writing-tools/writings/'+writingId+'/marks'));else setMarks([])}
  useEffect(()=>{let current=true;if(!writingId){setMarks([]);return}if(!props.bodySaved)return;void api.get<Mark[]>('/writing-tools/writings/'+writingId+'/marks').then(values=>{if(current)setMarks(values)}).catch(e=>{if(current)setError(errorMessage(e))});return()=>{current=false}},[writingId,props.writingRevision,props.bodySaved,hasAnalysis,pane])
  const setPanel=(next:string)=>{
    if(sourceDirty&&next!==pane){setError('저장하지 않은 메모가 있습니다. 카드 저장 또는 입력 버리기를 먼저 선택하세요.');return}
    setPane(next);props.onPane(next)
    if(next==='body')requestAnimationFrame(()=>trigger.current?.focus())
  }
  const jumpTo=(span:Span)=>{
    if(window.matchMedia('(max-width:820px)').matches&&sourceDirty){setError('저장하지 않은 메모를 먼저 저장해 주세요.');return}
    onJump(span)
    if(window.matchMedia('(max-width:820px)').matches)setPanel('body')
  }
  useEscapeLayer('panel',active&&view!=='home'&&pane!=='body',()=>setPanel('body'),panel,5)
  useEscapeLayer('panel',active&&view!=='home'&&prefs.data.focus&&pane==='body',()=>{void update({focus:false}).catch(e=>setError(errorMessage(e)));props.onFocus(false)},undefined,-5)
  const run=async(fn:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');try{await fn()}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
  const addRole=async(kind:string)=>{
    const v=await ensureVersion(),a=selectionAnchor(v,body,range),id=writingId||v.writingId
    if(!id)throw new Error('글을 저장해 주세요.')
    const value=await api.post<Mark>('/writing-tools/writings/'+id+'/marks',{kind,anchor:a})
    if(kind==='USER_CLAIM')setClaimId(value.id);else setEvidenceId(value.id)
    setMarks(await api.get<Mark[]>('/writing-tools/writings/'+id+'/marks'))
  }
  const change=async(mark:Mark,patch:Record<string,unknown>)=>{await api.patch('/writing-tools/marks/'+mark.id,{revisionNumber:mark.revisionNumber,...patch});await loadMarks()}
  const hits=findMultipleTextSpans(Array.from(body),keywords).slice(0,200)
  if(!active)return null
  return <section className="writing-tools" aria-label="글쓰기 도구">
    <div className="tools-toolbar" data-tour="source">
      {view!=='home'&&<><div className="tools-actions" aria-label="글 작업 탭">{[['body','본문'],['source','원작품'],['notes','개인 메모'],['relations','직접 관계'],['search','핵심어 검색']].map(([id,label])=><button key={id} ref={id==='source'?trigger:undefined} disabled={busy} aria-pressed={pane===id} onClick={()=>setPanel(id)}>{label}</button>)}</div>
      <div className="tools-actions"><button aria-pressed={prefs.data.focus} onClick={()=>void run(async()=>{const next=!prefs.data.focus;await update({focus:next});props.onFocus(next)})}>{prefs.data.focus?'집중 모드 끝내기':'집중 편집'}</button>
        <details><summary>본문 보기 설정</summary><div className="tools-actions">
          <label>본문 크기<input aria-label="본문 크기" type="range" min={14} max={28} step={1} value={prefs.data.fontSize} onChange={e=>void update({fontSize:Number(e.target.value)}).catch(e=>setError(errorMessage(e)))}/>{prefs.data.fontSize}px</label>
          <label>줄 간격<select aria-label="본문 줄 간격" value={prefs.data.lineHeight} onChange={e=>void update({lineHeight:Number(e.target.value)}).catch(e=>setError(errorMessage(e)))}>{[1.4,1.6,1.8,1.9,2.1,2.4].map(x=><option key={x} value={x}>{x}</option>)}</select></label>
          <label>본문 폭<select aria-label="본문 폭" value={prefs.data.bodyWidth} onChange={e=>void update({bodyWidth:Number(e.target.value)}).catch(e=>setError(errorMessage(e)))}>{[520,680,820,960,1100].map(x=><option key={x} value={x}>{x}px</option>)}</select></label>
        </div></details></div></>}
      <button ref={tutorialTrigger} disabled={!ready||busy} onClick={()=>void run(async()=>{await update({tutorial:'ACTIVE',tutorialStep:0});setTutorial(true)})}>사용 안내 다시 보기</button>
      {error&&<p role="alert">{error}</p>}
    </div>
    {view!=='home'&&pane!=='body'&&<div className="tools-content" ref={panel} tabIndex={-1} aria-label="자료와 메모 패널"><div className="tools-actions"><h2>{({source:'원작품',notes:'개인 메모',relations:'직접 관계',search:'핵심어 검색'} as Record<string,string>)[pane]}</h2><button onClick={()=>setPanel('body')}>도구 패널 닫기</button></div>
      {(pane==='source'||pane==='notes')&&<SourceTools key={account.id} account={account} section={pane==='source'?'source':'notes'} writingId={writingId||undefined} writingRevision={props.writingRevision} writingSaved={props.bodySaved} body={body} cursor={props.cursor} selection={selection} ensureVersion={ensureVersion} marks={marks} onJump={props.bodySaved?jumpTo:undefined} onRestoreContext={props.bodySaved?props.onJump:undefined} onContextChanged={props.onContextChanged} onDirtyChange={setSourceDirty}/>}
      {pane==='relations'&&<section className="manual-arguments" aria-label="사용자 지정 논증"><p>USER_DEFINED · 내가 지정한 구조입니다. S4 자동 승인과 별도로 저장합니다.</p>
        <div className="tools-actions"><label>글 구간 시작<input aria-label="직접 구간 시작" type="number" min={0} max={Array.from(body).length} value={range.start} onChange={e=>setRange(r=>({...r,start:Number(e.target.value)}))}/></label><label>글 구간 끝<input aria-label="직접 구간 끝" type="number" min={0} max={Array.from(body).length} value={range.end} onChange={e=>setRange(r=>({...r,end:Number(e.target.value)}))}/></label></div>
        <blockquote>{cpSlice(body,range)}</blockquote><div className="tools-actions"><button disabled={busy||range.end<=range.start} onClick={()=>void run(()=>addRole('USER_CLAIM'))}>선택을 직접 주장으로</button><button disabled={busy||range.end<=range.start} onClick={()=>void run(()=>addRole('USER_EVIDENCE'))}>선택을 직접 근거로</button></div>
        <label>연결할 주장<select aria-label="연결할 직접 주장" value={claimId} onChange={e=>setClaimId(e.target.value)}><option value="">선택</option>{marks.filter(x=>x.kind==='USER_CLAIM').map(x=><option key={x.id} value={x.id}>{x.quote}</option>)}</select></label>
        <label>연결할 근거<select aria-label="연결할 직접 근거" value={evidenceId} onChange={e=>setEvidenceId(e.target.value)}><option value="">선택</option>{marks.filter(x=>x.kind==='USER_EVIDENCE').map(x=><option key={x.id} value={x.id}>{x.quote}</option>)}</select></label>
        <label>직접 관계 분류<select aria-label="직접 관계 분류" value={group} onChange={e=>setGroup(e.target.value)}>{Object.entries(groupLabels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
        <button disabled={busy||!claimId||!evidenceId} onClick={()=>void run(async()=>{await api.post('/writing-tools/writings/'+writingId+'/links',{claimId,evidenceId,classification:group});await loadMarks()})}>근거 → 주장 연결 저장</button>
        <div>{marks.filter(x=>x.kind!=='USER_LINK').map(m=><article key={m.id} className="tools-note"><h3>{m.kind==='USER_CLAIM'?'직접 주장':'직접 근거'}</h3><blockquote>{m.quote}</blockquote><p>{m.resolution.status} · [{m.span.start}, {m.span.end})</p><div className="tools-actions"><button disabled={!m.resolution.span} onClick={()=>m.resolution.span&&jumpTo(m.resolution.span)}>직접 구간으로 이동</button><button disabled={busy} onClick={()=>void run(()=>change(m,{kind:m.kind==='USER_CLAIM'?'USER_EVIDENCE':'USER_CLAIM'}))}>직접 역할 변경</button><button disabled={busy||range.end<=range.start} onClick={()=>void run(async()=>{const v=await ensureVersion();await change(m,{anchor:selectionAnchor(v,body,range)})})}>선택 구간으로 재연결</button><button disabled={busy} onClick={()=>void run(async()=>{await api.delete('/writing-tools/marks/'+m.id,{revisionNumber:m.revisionNumber});await loadMarks()})}>직접 지정 해제</button></div></article>)}</div>
        <div>{marks.filter(x=>x.kind==='USER_LINK').map(m=><article key={m.id} className="tools-note"><h3>USER_DEFINED · 근거 → 주장</h3><p>{m.resolution.status} · {groupLabels[m.metadata.classification??'UNSORTED']}</p><p>근거: {marks.find(x=>x.id===m.metadata.evidenceId)?.quote??'해제된 구간'}</p><p>주장: {marks.find(x=>x.id===m.metadata.claimId)?.quote??'해제된 구간'}</p><div className="tools-actions"><button disabled={m.resolution.status==='NEEDS_REVIEW'} onClick={()=>{const c=marks.find(x=>x.id===m.metadata.claimId);if(c?.resolution.span)jumpTo(c.resolution.span)}}>연결한 직접 주장으로 이동</button><select aria-label="저장한 직접 관계 분류" value={m.metadata.classification??'UNSORTED'} onChange={e=>void run(()=>change(m,{classification:e.target.value}))}>{Object.entries(groupLabels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select><button disabled={busy} onClick={()=>void run(async()=>{await api.delete('/writing-tools/marks/'+m.id,{revisionNumber:m.revisionNumber});await loadMarks()})}>직접 관계 해제</button></div></article>)}</div>
      </section>}
      {pane==='search'&&<section aria-label="내 글 핵심어"><label>복수 핵심어<input aria-label="복수 핵심어" value={keywords} maxLength={500} placeholder="쉼표로 구분 · 최대 8개" onChange={e=>{setKeywords(e.target.value);props.onSearch(e.target.value)}}/></label><p>정확한 문자열 · {hits.length}개 위치{hits.length===200?' (앞 200개 표시)':''}</p>{hits.map((s,i)=><button className="keyword-hit" key={s.start+':'+s.end+':'+i} onClick={()=>jumpTo(s)}>{cpSlice(body,{start:Math.max(0,s.start-25),end:s.start})}<mark>{cpSlice(body,s)}</mark>{cpSlice(body,{start:s.end,end:Math.min(Array.from(body).length,s.end+25)})}<small>[{s.start}, {s.end})</small></button>)}</section>}
    </div>}
    {tutorial&&ready&&<WritingTutorial returnFocus={tutorialTrigger} step={prefs.data.tutorialStep} hasAnalysis={hasAnalysis&&!analyzing} canAnalyze={!!body.trim()&&!analyzing} onPrepare={n=>{if(n===0)props.onNew();if(n===1)setPanel('source');if(n===3)props.onFeedback()}} onStep={async n=>{await update({tutorialStep:n})}} onAnalyze={async()=>{await props.onAnalyze();await update({tutorialStep:3})}} onClose={async()=>{await update({tutorial:'SKIPPED'});setTutorial(false)}} onComplete={async()=>{if(!hasAnalysis)throw new Error('실제 결과를 먼저 확인하세요.');await update({tutorial:'COMPLETED',tutorialStep:3});setTutorial(false)}}/>}
  </section>
}
