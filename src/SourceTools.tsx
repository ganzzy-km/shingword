import {useEffect,useLayoutEffect,useRef,useState} from 'react'
import {api,errorMessage,type AccountSession} from './api'
import {utf16Offset,type Span} from './book-layout'
import {cpSlice,selectionAnchor,groupLabels,sourceLabels,kindLabels,type SourceItem,type SourceAnchor,type Card,type Mark,type ToolsVersion} from './writing-tools'
import './writing-tools.css'

type Publication={id:string;documentId:string;revisionId:string;title:string;state:string;rightsBasis:string;revisionNumber:number;isOwner:boolean;canReview:boolean;history:{state:string;reason?:string}[]}
type Props={account:AccountSession;section?:'source'|'notes';writingId?:string;writingRevision?:number;writingSaved?:boolean;body?:string;cursor?:number;selection?:Span|null;ensureVersion?:()=>Promise<ToolsVersion>;marks?:Mark[];onJump?:(span:Span)=>void;onRestoreContext?:(span:Span)=>void;onContextChanged?:()=>void;onDirtyChange?:(dirty:boolean)=>void}
type Revision={id:string;content:string;hash:string;revisionNumber:number}
const base='/writing-tools'

export default function SourceTools({account,section='source',writingId,writingRevision,writingSaved=true,body='',cursor=0,selection,ensureVersion,marks=[],onJump,onRestoreContext,onContextChanged,onDirtyChange}:Props){
  const [items,setItems]=useState<SourceItem[]>([]),[selected,setSelected]=useState<SourceItem|null>(null),[revision,setRevision]=useState<Revision|null>(null)
  const [query,setQuery]=useState(''),[scope,setScope]=useState(''),[access,setAccess]=useState(''),[genre,setGenre]=useState(''),[favorite,setFavorite]=useState(false),[recent,setRecent]=useState(false)
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false)
  const [sourceSpan,setSourceSpan]=useState<Span>({start:0,end:0}),[kwic,setKwic]=useState(''),[hits,setHits]=useState<{span:Span;quote:string;context:string;contextStart:number}[]>([])
  const [readerRestore,setReaderRestore]=useState<{revisionId:string;start:number;end:number;scrollFraction?:number;focus:boolean}|null>(null)
  const [comparisons,setComparisons]=useState<(SourceAnchor&{title:string;context:string})[]>([])
  const [cards,setCards]=useState<Card[]>([]),[cardFilter,setCardFilter]=useState(''),[kind,setKind]=useState('NOTE'),[sourceType,setSourceType]=useState('MY_INTERPRETATION')
  const [evidence,setEvidence]=useState(''),[interpretation,setInterpretation]=useState(''),[claimText,setClaimText]=useState(''),[claimId,setClaimId]=useState(''),[classification,setClassification]=useState('UNSORTED')
  const [editing,setEditing]=useState<Card|null>(null),[cardSource,setCardSource]=useState<SourceAnchor|null>(null),[diff,setDiff]=useState<unknown>(null)
  const [dirty,setDirty]=useState(false),[clientKey,setClientKey]=useState(()=>crypto.randomUUID())
  const [requests,setRequests]=useState<Publication[]>([]),[rights,setRights]=useState(''),[delegate,setDelegate]=useState(false),[reviewed,setReviewed]=useState<string[]>([]),[reason,setReason]=useState(''),[delegated,setDelegated]=useState<{requestId:string;content?:string;revisionId:string;accessMode:string}|null>(null)
  const [attached,setAttached]=useState<{revisionId:string;title:string;available:boolean}[]>([])
  const [claimFilter,setClaimFilter]=useState('')
  const reader=useRef<HTMLTextAreaElement>(null),selectedRef=useRef(selected),revisionRef=useRef(revision),alive=useRef(true)
  const stateQueue=useRef(Promise.resolve())
  const catalogRequest=useRef(0)
  const scrollTimer=useRef<ReturnType<typeof setTimeout>|null>(null),spanRef=useRef(sourceSpan)
  spanRef.current=sourceSpan
  useEffect(()=>()=>{if(scrollTimer.current)clearTimeout(scrollTimer.current)},[])
  selectedRef.current=selected;revisionRef.current=revision
  useLayoutEffect(()=>{const node=reader.current;if(!node||!revision||readerRestore?.revisionId!==revision.id)return;if(readerRestore.focus)node.focus({preventScroll:true});node.setSelectionRange(utf16Offset(revision.content,readerRestore.start),utf16Offset(revision.content,readerRestore.end));node.scrollTop=readerRestore.scrollFraction!==undefined?readerRestore.scrollFraction*Math.max(0,node.scrollHeight-node.clientHeight):Math.max(0,(cpSlice(revision.content,{start:0,end:readerRestore.start}).split('\n').length-3)*27)},[revision?.id,readerRestore])
  const run=async(fn:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');setMessage('');try{await fn()}catch(e){setError(errorMessage(e))}finally{if(alive.current)setBusy(false)}}
  const catalog=async()=>{
    const request=++catalogRequest.current
    const params=new URLSearchParams({q:query,scope,access,genre,favorite:favorite?'1':'',recent:recent?'1':''})
    const result=await api.get<SourceItem[]>(base+'/sources?'+params);if(request===catalogRequest.current&&alive.current)setItems(result)
  }
  const loadCards=async()=>{setCards(await api.get<Card[]>(base+'/cards'+(writingId?'?writingId='+writingId:'')))}
  const loadRequests=async()=>{setRequests(await api.get<Publication[]>(base+'/publication-requests'))}
  const loadAttached=async()=>{if(writingId)setAttached(await api.get<typeof attached>(base+'/writings/'+writingId+'/sources'));else setAttached([])}
  useEffect(()=>{alive.current=true;void Promise.all([catalog(),loadCards(),loadRequests(),loadAttached()]).catch(e=>setError(errorMessage(e)));return()=>{alive.current=false}},[account.id,writingId])
  useEffect(()=>{let current=true;if(!writingSaved)return;void api.get<Card[]>(base+'/cards'+(writingId?'?writingId='+writingId:'')).then(values=>{if(current)setCards(values)}).catch(e=>{if(current)setError(errorMessage(e))});return()=>{current=false}},[writingId,writingRevision,writingSaved])
  useEffect(()=>{onDirtyChange?.(dirty);const warn=(e:BeforeUnloadEvent)=>{if(dirty)e.preventDefault()};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirty])
  useEffect(()=>{
    const guard=(e:Event)=>{if(dirty){e.preventDefault();setError('저장하지 않은 메모가 있습니다. 카드 저장 또는 입력 버리기를 먼저 선택하세요.')}}
    window.addEventListener('geulbit-before-navigation',guard)
    return()=>window.removeEventListener('geulbit-before-navigation',guard)
  },[dirty])
  useEffect(()=>{
    const check=async()=>{
      const current=selectedRef.current,r=revisionRef.current
      if(current&&r){try{await api.get(`/source-documents/${current.id}/revisions/${r.id}`)}catch{setRevision(null);setComparisons([]);setCardSource(null);setError('자료 이용 권한 또는 선택 판본이 바뀌었습니다. 원문을 다시 선택해 주세요.')}}
      void loadCards().catch(()=>undefined)
    }
    window.addEventListener('focus',check);return()=>window.removeEventListener('focus',check)
  },[writingId])
  const updateSourceState=(id:string,data:Record<string,unknown>)=>{
    const pending=stateQueue.current.then(async()=>{const old=await api.get<{revisionNumber:number}>(base+'/sources/'+id+'/state');return api.patch(base+'/sources/'+id+'/state',{revisionNumber:old.revisionNumber,data})})
    stateQueue.current=pending.then(()=>undefined,()=>undefined)
    return pending
  }
  const savePosition=(item:SourceItem,r:Revision,offset:number,openCardId?:string,restoredScroll?:number)=>{const node=reader.current;const scrollFraction=restoredScroll??(node?.dataset.revisionId===r.id?node.scrollTop/Math.max(1,node.scrollHeight-node.clientHeight):undefined);return updateSourceState(item.id,{revisionId:r.id,offset,...(scrollFraction!==undefined?{scrollFraction:Math.max(0,Math.min(1,scrollFraction))}:{}),...(openCardId?{openCardId}:{}),...(writingId?{writingId,essayOffset:Math.min(cursor,Array.from(body).length)}:{})})}
  const open=async(item:SourceItem,rid=item.latestRevisionId,position?:Span)=>{
    if(scrollTimer.current)clearTimeout(scrollTimer.current)
    setSelected(item);setRevision(null);setReaderRestore(null);setHits([]);setSourceSpan({start:0,end:0});setDiff(null);setDelegated(null)
    const state=await api.get<{revisionNumber:number;data:{revisionId?:string;offset?:number;scrollFraction?:number;openCardId?:string;writingId?:string;essayOffset?:number;essayBodySha256?:string}}>(base+'/sources/'+item.id+'/state')
    if(item.accessMode==='MATCH_ONLY'){setMessage('이 자료는 서버 인용 대조만 허용합니다. 원문 열람·문맥 검색·구절 비교는 제공하지 않습니다.');return}
    const exact=position?rid:state.data.revisionId||rid
    const r=await api.get<Revision>(`/source-documents/${item.id}/revisions/${exact}`)
    const offset=position?.start??Math.min(state.data.offset??0,Array.from(r.content).length)
    setReaderRestore({revisionId:r.id,start:offset,end:position?.end??offset,scrollFraction:position?undefined:state.data.scrollFraction,focus:!!position});setRevision(r)
    setSourceSpan(position??{start:offset,end:offset})
    if(!position&&state.data.writingId===writingId&&state.data.essayOffset!==undefined&&onRestoreContext){
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body)))).map(x=>x.toString(16).padStart(2,'0')).join('')
      if(digest===state.data.essayBodySha256)onRestoreContext({start:state.data.essayOffset,end:state.data.essayOffset})
    }
    await savePosition(item,r,offset,undefined,position?undefined:state.data.scrollFraction??0)
    if(state.data.openCardId&&!dirty){const card=await api.get<Card>(base+'/cards/'+state.data.openCardId);fillCard(card)}
  }
  const takeAnchor=():SourceAnchor=>{
    if(!selected||!revision||sourceSpan.end<=sourceSpan.start)throw new Error('열람 가능한 판본에서 구절을 선택해 주세요.')
    const quote=cpSlice(revision.content,sourceSpan)
    if(Array.from(quote).length>2000)throw new Error('한 카드에는 2,000자 이하의 구절을 선택해 주세요.')
    return {documentId:selected.id,revisionId:revision.id,span:{...sourceSpan},quote}
  }
  const resetCard=()=>{setEditing(null);setEvidence('');setInterpretation('');setClaimText('');setClaimId('');setClassification('UNSORTED');setCardSource(null);setKind('NOTE');setSourceType('MY_INTERPRETATION');setClientKey(crypto.randomUUID());setDirty(false);setDiff(null)}
  const fillCard=(c:Card)=>{setEditing(c);setEvidence(c.quote);setInterpretation(c.interpretation);setClaimText(c.claimText);setClaimId(c.claimId??'');setClassification(c.classification);setCardSource(c.sourceAnchor);setKind(c.kind);setSourceType(c.sourceType);setDirty(false);setDiff(null)}
  const saveCard=async()=>{
    let writingAnchor=editing?.writingAnchor??undefined
    let ownerWriting=writingId
    if(ensureVersion&&body.trim()){const v=await ensureVersion();ownerWriting=v.writingId??writingId;if(selection)writingAnchor=selectionAnchor(v,body,selection)}
    const payload={kind,sourceType,quote:evidence,interpretation,claimText,claimId:claimId||null,classification,
      documentId:cardSource?.documentId??editing?.documentId??selected?.id,sourceAnchor:cardSource??undefined,writingId:ownerWriting||undefined,writingAnchor}
    const saved=editing?await api.patch<Card>(base+'/cards/'+editing.id,{...payload,revisionNumber:editing.revisionNumber}):await api.post<Card>(base+'/cards',{...payload,clientKey})
    fillCard(saved);await loadCards();setMessage('개인 카드가 저장되었습니다.')
    if(selected&&revision&&selected.id===saved.documentId)await savePosition(selected,revision,sourceSpan.start,saved.id)
  }
  const useSource=async()=>{
    if(!selected||!ensureVersion)throw new Error('글을 먼저 저장해 주세요.')
    const v=await ensureVersion();const ownerWriting=writingId??v.writingId
    if(!ownerWriting)throw new Error('글 저장 후 판본 연결을 다시 눌러 주세요.')
    await api.post('/writings/'+ownerWriting+'/documents',{revisionId:revision?.id??selected.latestRevisionId})
    await loadAttached();onContextChanged?.();setMessage('선택한 불변 판본을 글에 연결했습니다.')
  }
  const visibleCards=cards.filter(c=>(!selected||c.documentId===selected.id)&&(!cardFilter||c.kind===cardFilter)&&(!claimFilter||(claimFilter==='unassigned'?!c.claimId:c.claimId===claimFilter)))
  const jumpCardSource=async(c:Card)=>{
    if(!c.sourceAnchor||c.sourceUnavailable)throw new Error('이 원문 구간에 접근할 수 없습니다.')
    const list=await api.get<SourceItem[]>(base+'/sources');const item=list.find(x=>x.id===c.sourceAnchor!.documentId)
    if(!item)throw new Error('자료 접근이 철회되었습니다.')
    await open(item,c.sourceAnchor.revisionId,c.sourceAnchor.span)
  }
  const compare=async()=>{
    const a=takeAnchor();const source=await api.get<Revision>(`/source-documents/${a.documentId}/revisions/${a.revisionId}`)
    if(cpSlice(source.content,a.span)!==a.quote)throw new Error('선택 구간과 판본이 일치하지 않습니다.')
    setComparisons(old=>[...old.filter(x=>!(x.revisionId===a.revisionId&&x.span.start===a.span.start&&x.span.end===a.span.end)),{...a,title:selected!.title,context:cpSlice(source.content,{start:Math.max(0,a.span.start-35),end:Math.min(Array.from(source.content).length,a.span.end+35)})}].slice(-4))
  }
  const decide=async(r:Publication,state:string)=>{await api.patch(base+'/publication-requests/'+r.id,{revisionNumber:r.revisionNumber,state,reviewConfirmed:reviewed.includes(r.id),reason});setDelegated(null);await Promise.all([loadRequests(),catalog()]);setMessage('공개 신청 상태를 저장했습니다.')}
  return <section className="source-tools" aria-label="원작품과 개인 메모" aria-busy={busy}>
    {error&&<p role="alert" className="tools-error">{error}</p>}{message&&<p role="status">{message}</p>}
    <details open={section==='source'} className="tools-catalog"><summary>자료 검색·즐겨찾기·최근 사용</summary>
      <form onSubmit={e=>{e.preventDefault();void run(catalog)}} className="tools-form">
        <label>제목·작가·장르 검색<input aria-label="자료 검색어" value={query} onChange={e=>setQuery(e.target.value)} maxLength={100}/></label>
        <div className="tools-actions"><label>공개 범위<select aria-label="자료 공개 범위" value={scope} onChange={e=>setScope(e.target.value)}><option value="">전체</option><option value="PUBLIC">공용</option><option value="PRIVATE">개인</option></select></label>
        <label>이용 범위<select aria-label="자료 이용 범위" value={access} onChange={e=>setAccess(e.target.value)}><option value="">전체</option><option>MATCH_ONLY</option><option>VIEW</option><option>DOWNLOAD</option></select></label>
        <label>장르<select aria-label="자료 장르" value={genre} onChange={e=>setGenre(e.target.value)}><option value="">전체</option>{['소설','시','희곡','비평문','에세이','기타'].map(x=><option key={x}>{x}</option>)}</select></label></div>
        <div className="tools-actions"><label><input type="checkbox" checked={favorite} onChange={e=>setFavorite(e.target.checked)}/>즐겨찾기만</label><label><input type="checkbox" checked={recent} onChange={e=>setRecent(e.target.checked)}/>최근 사용순</label><button disabled={busy}>자료 검색</button></div>
      </form>
      <ul className="tools-source-list">{items.map(item=><li key={item.id} className={selected?.id===item.id?'selected':''}>
        <button disabled={busy} onClick={()=>void run(()=>open(item))} aria-pressed={selected?.id===item.id}><strong>{item.title}</strong><small>{item.scope==='PUBLIC'?'공용':'개인'} · {item.author||'작가 미상'} · {item.genre} · {item.accessMode}</small></button>
        <button disabled={busy} aria-label={item.title+' 즐겨찾기'} aria-pressed={item.favorite} onClick={()=>void run(async()=>{await updateSourceState(item.id,{favorite:!item.favorite});await catalog()})}>{item.favorite?'★':'☆'}</button>
      </li>)}</ul>{!items.length&&<p>조회할 수 있는 자료가 없습니다.</p>}
    </details>
    {selected&&<section aria-label="선택한 원작품" className="tools-source-reader">
      <h3>{selected.title}</h3><p>{selected.author} · {selected.genre} · {revision?.id??selected.latestRevisionId}</p>
      <div className="tools-actions">{ensureVersion&&<button disabled={busy} onClick={()=>void run(useSource)}>이 판본을 분석에 연결</button>}<button disabled={busy||dirty} onClick={()=>{setSelected(null);setRevision(null);setCardSource(null)}}>자료 선택 해제</button></div>
      {revision?<><label>원작품 본문<textarea ref={reader} data-revision-id={revision.id} readOnly aria-label="원작품 본문" value={revision.content} onSelect={e=>{const n=e.currentTarget;setSourceSpan({start:Array.from(n.value.slice(0,n.selectionStart)).length,end:Array.from(n.value.slice(0,n.selectionEnd)).length})}} onScroll={()=>{if(scrollTimer.current)clearTimeout(scrollTimer.current);scrollTimer.current=setTimeout(()=>{void savePosition(selected,revision,spanRef.current.start).catch(e=>setError(errorMessage(e)))},200)}} onBlur={()=>{if(revision&&selected)void savePosition(selected,revision,spanRef.current.start).catch(e=>setError(errorMessage(e)))}}/></label>
        <div className="tools-actions"><label>원문 시작<input aria-label="원문 시작" type="number" min={0} max={Array.from(revision.content).length} value={sourceSpan.start} onBlur={()=>void savePosition(selected,revision,spanRef.current.start).catch(e=>setError(errorMessage(e)))} onChange={e=>setSourceSpan(s=>({...s,start:Number(e.target.value)}))}/></label><label>원문 끝<input aria-label="원문 끝" type="number" min={0} max={Array.from(revision.content).length} value={sourceSpan.end} onBlur={()=>void savePosition(selected,revision,spanRef.current.start).catch(e=>setError(errorMessage(e)))} onChange={e=>setSourceSpan(s=>({...s,end:Number(e.target.value)}))}/></label></div>
        <div className="tools-actions"><button disabled={busy||sourceSpan.end<=sourceSpan.start} onClick={()=>void run(async()=>{const a=takeAnchor();setCardSource(a);setEvidence(a.quote);setSourceType(selected.sourceType);setKind('DIRECT_QUOTE');setDirty(true);setMessage('선택한 판본 구절을 카드에 담았습니다.')})}>구절을 카드에 담기</button><button disabled={busy||sourceSpan.end<=sourceSpan.start} onClick={()=>void run(compare)}>구절 비교에 추가</button></div>
        <form onSubmit={e=>{e.preventDefault();void run(async()=>{const result=await api.post<{hits:typeof hits}>(base+'/sources/'+selected.id+'/search',{revisionId:revision.id,query:kwic});setHits(result.hits)})}}><label>원문 문맥 검색<input value={kwic} maxLength={100} onChange={e=>setKwic(e.target.value)} aria-label="원문 문맥 검색어"/></label><button disabled={busy||!kwic}>문맥 검색</button></form>
        <ul>{hits.map(h=><li key={h.span.start}><button disabled={busy} onClick={()=>void run(()=>open(selected,revision.id,h.span))}>{h.context} · [{h.span.start}, {h.span.end})</button></li>)}</ul>
      </>:<p>원문 열람이 허용되지 않거나 판본을 불러오는 중입니다. 제한 자료의 전문은 제공하지 않습니다.</p>}
      {selected.isOwner&&selected.scope==='PRIVATE'&&<details><summary>이 판본의 공용 등록 신청</summary><label>공개 이용 권리 근거<textarea aria-label="공개 이용 권리 근거" value={rights} maxLength={2000} onChange={e=>setRights(e.target.value)}/></label><label><input type="checkbox" checked={delegate} onChange={e=>setDelegate(e.target.checked)}/>공개 권리를 확인했으며 이 특정 판본의 관리자 검토를 위임합니다.</label><button disabled={busy||!delegate||rights.trim().length<10} onClick={()=>void run(async()=>{await api.post(base+'/publication-requests',{documentId:selected.id,revisionId:revision?.id??selected.latestRevisionId,rightsBasis:rights,rightsConfirmed:true,delegateReview:true});setDelegate(false);await loadRequests();setMessage('공용 등록 검토를 신청했습니다.')})}>공용 등록 신청</button></details>}
    </section>}
    {attached.length>0&&<section aria-label="연결한 판본"><h3>분석에 연결한 판본</h3>{attached.length>=3&&<p role="status">작품을 3개 이상 선택하면 분석 시간이 길어지고 작품별 근거를 구분하는 정확도가 낮아질 수 있습니다.</p>}<ul>{attached.map(x=><li key={x.revisionId}>{x.title}<small>{x.revisionId}</small><button disabled={busy} onClick={()=>void run(async()=>{await api.delete(base+'/writings/'+writingId+'/sources/'+x.revisionId);await loadAttached();onContextChanged?.()})}>판본 연결 해제</button></li>)}</ul></section>}
    {comparisons.length>0&&<section aria-label="원문 구절 비교"><h3>원문 구절 비교</h3><div className="tools-comparisons">{comparisons.map((x,i)=><article key={x.revisionId+':'+x.span.start}><h4>{x.title}</h4><p>{x.context}</p><blockquote>{x.quote}</blockquote><small>{x.revisionId} · [{x.span.start},{x.span.end})</small><button disabled={busy} onClick={()=>void run(async()=>{const r=await api.get<Revision>(`/source-documents/${x.documentId}/revisions/${x.revisionId}`);if(cpSlice(r.content,x.span)!==x.quote)throw new Error('판본 구간 불일치');const item=items.find(d=>d.id===x.documentId)??(await api.get<SourceItem[]>(base+'/sources')).find(d=>d.id===x.documentId);if(!item)throw new Error('자료 접근 철회');await open(item,x.revisionId,x.span)})}>원문 위치</button><button onClick={()=>setComparisons(v=>v.filter((_,n)=>n!==i))}>비교에서 빼기</button></article>)}</div></section>}
    <section aria-label="근거 해석 주장 메모" className="tools-card-editor">
      <h3>{editing?'카드 수정':'근거 → 내 해석 → 주장'}</h3><p>일부 항목만 입력해도 개인 메모로 저장할 수 있습니다.</p>
      <div className="tools-actions"><label>카드 분류<select aria-label="카드 분류" value={kind} onChange={e=>{setKind(e.target.value);setDirty(true)}}>{Object.entries(kindLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label><label>출처 유형<select aria-label="카드 출처 유형" value={sourceType} onChange={e=>{setSourceType(e.target.value);setDirty(true)}}>{Object.entries(sourceLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label></div>
      {cardSource&&<p>고정 판본 {cardSource.revisionId} · [{cardSource.span.start},{cardSource.span.end}) <button onClick={()=>{setCardSource(null);setDirty(true)}}>원문 구간 연결 해제</button></p>}
      <label>근거·장면<textarea aria-label="근거 장면 메모" value={evidence} maxLength={2000} onChange={e=>{setEvidence(e.target.value);setDirty(true)}}/></label>
      <label>내 해석<textarea aria-label="내 해석 메모" value={interpretation} maxLength={5000} onChange={e=>{setInterpretation(e.target.value);setDirty(true)}}/></label>
      <label>주장·질문<textarea aria-label="주장 질문 메모" value={claimText} maxLength={5000} onChange={e=>{setClaimText(e.target.value);setDirty(true)}}/></label>
      {marks.some(x=>x.kind==='USER_CLAIM')&&<label>주장별 근거 묶음<select aria-label="메모 연결 주장" value={claimId} onChange={e=>{setClaimId(e.target.value);setDirty(true)}}><option value="">특정 주장 없음</option>{marks.filter(x=>x.kind==='USER_CLAIM').map(x=><option key={x.id} value={x.id}>{x.quote}</option>)}</select></label>}
      <label>내 근거 분류<select aria-label="내 근거 분류" value={classification} onChange={e=>{setClassification(e.target.value);setDirty(true)}}>{Object.entries(groupLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
      <div className="tools-actions"><button disabled={busy||!(evidence.trim()||interpretation.trim()||claimText.trim())} onClick={()=>void run(saveCard)}>카드 저장</button><button disabled={busy} onClick={resetCard}>{dirty?'입력 버리고 새 카드':'새 카드'}</button>{dirty&&<span role="status">저장하지 않은 메모</span>}</div>
    </section>
    <section aria-label="저장한 개인 카드"><h3>개인 카드·작품별 노트</h3><label>노트 종류<select aria-label="노트 종류 필터" value={cardFilter} onChange={e=>setCardFilter(e.target.value)}><option value="">전체</option>{Object.entries(kindLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
      {marks.some(x=>x.kind==='USER_CLAIM')&&<label>주장별 카드<select aria-label="주장별 카드 필터" value={claimFilter} onChange={e=>setClaimFilter(e.target.value)}><option value="">모든 주장</option><option value="unassigned">특정 주장 없음</option>{marks.filter(x=>x.kind==='USER_CLAIM').map(x=><option key={x.id} value={x.id}>{x.quote}</option>)}</select></label>}
      {Object.entries(groupLabels).map(([group,label])=>{const values=visibleCards.filter(c=>c.classification===group);return values.length>0&&<section key={group}><h4>{label} · 사용자 분류</h4>{values.map(c=><article className="tools-note" key={c.id}><p><strong>{kindLabels[c.kind]}</strong> · {sourceLabels[c.sourceType]} · {c.work}</p>{c.sourceUnavailable&&<p>원문 접근 제한 · 개인 메모만 표시합니다.</p>}<blockquote>{c.quote}</blockquote><p>{c.interpretation}</p><p>{c.claimText}</p>{c.writingResolution?.status==='NEEDS_REVIEW'&&<p>NEEDS_REVIEW · 글 수정 후 구간 재확인 필요</p>}<div className="tools-actions"><button disabled={busy||dirty} onClick={()=>fillCard(c)}>카드 열기</button><button disabled={busy||!c.sourceAnchor||c.sourceUnavailable} onClick={()=>void run(()=>jumpCardSource(c))}>카드 원문으로 이동</button><button disabled={busy||!c.writingAnchor||!onJump||c.writingResolution?.status==='NEEDS_REVIEW'} onClick={()=>{const s=c.writingResolution?.span??c.writingAnchor?.span;if(s)onJump?.(s)}}>에세이 근거로 이동</button><button disabled={busy} onClick={()=>void run(async()=>setDiff(await api.post(base+'/cards/'+c.id+'/quotation-diff',{})))}>직접 인용 대조</button><button disabled={busy} onClick={()=>void run(async()=>{await api.delete(base+'/cards/'+c.id,{revisionNumber:c.revisionNumber});if(editing?.id===c.id)resetCard();await loadCards()})}>개인 카드 삭제</button></div></article>)}</section>})}
      {visibleCards.length===0&&<p>이 범위의 저장된 개인 카드가 없습니다.</p>}{diff!==null&&<pre className="tools-diff" aria-label="인용 차이 결과">{JSON.stringify(diff,null,2)}</pre>}
    </section>
    <details className="tools-publications"><summary>공용 등록 신청·검토 {requests.length}건</summary>
      <label>거절 사유<input aria-label="공개 신청 거절 사유" value={reason} onChange={e=>setReason(e.target.value)} maxLength={1000}/></label>
      {requests.map(r=><article key={r.id} className="tools-note"><h4>{r.title}</h4><p>{r.state} · 판본 {r.revisionId}</p><p>{r.rightsBasis}</p><p>{r.history.at(-1)?.reason}</p>
        {r.canReview&&<><button disabled={busy} onClick={()=>void run(async()=>setDelegated(await api.get(base+'/publication-requests/'+r.id+'/revision')))}>위임된 판본 검토</button><label><input type="checkbox" checked={reviewed.includes(r.id)} onChange={e=>setReviewed(v=>e.target.checked?[...v,r.id]:v.filter(x=>x!==r.id))}/>권리 근거와 신청한 특정 판본을 검토했습니다.</label><div className="tools-actions"><button disabled={busy||!reviewed.includes(r.id)} onClick={()=>void run(()=>decide(r,'APPROVED'))}>공용 신청 승인</button><button disabled={busy||!reason.trim()} onClick={()=>void run(()=>decide(r,'REJECTED'))}>공용 신청 거절</button></div></>}
        {(r.isOwner||account.role==='ADMIN')&&r.state!=='WITHDRAWN'&&<button disabled={busy} onClick={()=>void run(()=>decide(r,'WITHDRAWN'))}>{r.state==='APPROVED'?'신청 자료 공개 중지':'신청 철회'}</button>}
      </article>)}{delegated&&<section aria-label="위임 판본 검토"><p>{delegated.revisionId} · {delegated.accessMode}</p>{delegated.content?<pre>{delegated.content}</pre>:<p>원문 열람이 허용되지 않는 자료입니다.</p>}<button onClick={()=>setDelegated(null)}>검토 원문 닫기</button></section>}
    </details>
  </section>
}
