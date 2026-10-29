import { useEffect, useRef, useState } from "react"
import { api, ApiError, errorMessage } from "./api"
import { useEscapeLayer } from "./escape-navigation"
import { moveAnnotation, verifiedAnnotationSpan, type UserAnnotation, type AnnotationMark } from "./user-annotations"
import type { Span } from "./book-layout"
import "./annotations.css"

export function useAnnotations(writingId:string,body:string,version?:{id:string;content:string}) {
  const [notes,setNotes]=useState<UserAnnotation[]>([])
  const [positions,setPositions]=useState<Record<string,Span|null>>({})
  const [error,setError]=useState("")
  const generation=useRef(0),current=useRef(body),previous=useRef(body)
  const currentWriting=useRef(writingId);currentWriting.current=writingId
  current.current=body
  useEffect(()=>{
    const n=++generation.current;setNotes([]);setPositions({});setError("");previous.current=body
    if(!writingId)return
    void Promise.all([api.get<UserAnnotation[]>(`/writings/${writingId}/annotations`),api.get<{id:string;content:string}[]>(`/writings/${writingId}/versions`)]).then(([items,versions])=>{
      if(n!==generation.current)return
      setNotes(items);setPositions(Object.fromEntries(items.map(note=>[note.id,verifiedAnnotationSpan(note,versions.find(v=>v.id===note.essayVersionId)?.content,current.current)])))
    }).catch(e=>{if(n===generation.current)setError(errorMessage(e))})
    return ()=>{generation.current++}
  },[writingId])
  useEffect(()=>{
    const before=previous.current;previous.current=body
    if(before===body)return
    setPositions(old=>Object.fromEntries(notes.map(note=>[note.id,moveAnnotation(before,body,old[note.id] ?? null,note.quote)])))
  },[body,notes])
  function accept(note:UserAnnotation) {
    if(note.writingId!==currentWriting.current)return false
    const previousNote=notes.find(n=>n.id===note.id)
    const sameAnchor=previousNote && previousNote.essayVersionId===note.essayVersionId && previousNote.span.start===note.span.start && previousNote.span.end===note.span.end && previousNote.quote===note.quote
    setNotes(old=>old.some(x=>x.id===note.id) ? old.map(x=>x.id===note.id ? note : x) : [...old,note])
    setPositions(old=>({...old,[note.id]:sameAnchor ? old[note.id] ?? null : verifiedAnnotationSpan(note,version?.id===note.essayVersionId ? version.content : undefined,current.current)}))
    return true
  }
  function move(before:string,after:string,edit?:Span) {
    previous.current=after
    setPositions(old=>Object.fromEntries(notes.map(note=>[note.id,moveAnnotation(before,after,old[note.id] ?? null,note.quote,edit)])))
  }
  function remove(id:string){setNotes(old=>old.filter(n=>n.id!==id));setPositions(old=>{const next={...old};delete next[id];return next})}
  return {notes,positions,error,accept,move,remove,marks:notes.flatMap(n=>positions[n.id] ? [{id:n.id,span:positions[n.id]!}] : []) as AnnotationMark[]}
}

export default function AnnotationsPanel({writingId,body,version,selection,notes,positions,selectedId,error,onAccept,onRemove,onJump,onClose,onDirtyChange}: {
  writingId:string;body:string;version?:{id:string;content:string};selection:Span|null;notes:UserAnnotation[];positions:Record<string,Span|null>;selectedId:string|null;error:string
  onAccept:(n:UserAnnotation)=>void;onRemove:(id:string)=>void;onJump:(id:string)=>void;onClose:()=>void
  onDirtyChange:(dirty:boolean)=>void
}) {
  const selected=notes.find(n=>n.id===selectedId)
  const [text,setText]=useState(""),[message,setMessage]=useState(""),[busy,setBusy]=useState(false),[confirm,setConfirm]=useState(false)
  const [expired,setExpired]=useState(false)
  const input=useRef<HTMLTextAreaElement>(null),dirty=useRef(false)
  const panel=useRef<HTMLElement>(null)
  useEscapeLayer(confirm ? "modal" : "panel", !!(selection || selected), () => {
    if(busy)return
    if(confirm){setConfirm(false);return}
    if(!dirty.current || window.confirm("저장하지 않은 주석을 닫을까요?"))onClose()
  },panel)
  useEffect(()=>{setText(selected?.content ?? "");setConfirm(false);dirty.current=false;onDirtyChange(false);if(selectedId)input.current?.focus()},[selectedId,writingId])
  useEffect(()=>{if(selection && !selectedId)input.current?.focus()},[selection,selectedId])
  const canAnchor=!!version && version.content===body && !!selection && selection.start<selection.end
  async function save(relink=false) {
    if(!text.trim() || busy)return
    setBusy(true);setMessage("");setExpired(false)
    try {
      const anchor=canAnchor ? {essayVersionId:version!.id,span:selection!,quote:Array.from(body).slice(selection!.start,selection!.end).join("")} : {}
      if((!selected || relink) && !canAnchor)throw new Error("현재 본문을 분석한 뒤 구절을 다시 선택해 주세요.")
      const note=selected ? await api.patch<UserAnnotation>(`/annotations/${selected.id}`,{content:text,revisionNumber:selected.revisionNumber,...(relink ? anchor : {})},true) : await api.post<UserAnnotation>(`/writings/${writingId}/annotations`,{content:text,...anchor},true)
      dirty.current=false;onDirtyChange(false);onAccept(note);setMessage("주석 저장 완료")
    }catch(e){setExpired(e instanceof ApiError && e.status===401);setMessage(e instanceof ApiError && e.status===409 ? "다른 창에서 변경된 주석입니다. 입력을 보존했습니다. 다시 열기 전에 내용을 복사하세요." : e instanceof ApiError && e.status===401 ? "로그인 세션이 만료되었습니다. 입력을 보존했습니다." : errorMessage(e))}
    finally{setBusy(false)}
  }
  if(!notes.length && !selection && !error)return null
  return <section ref={panel} className="annotations-panel" aria-label="내 주석"><h3>내 주석 <small>{notes.length}</small></h3>
    {error && <p role="alert">{error}</p>}
    {(selection || selected) && <div className="annotation-form">
      <blockquote>{selected?.quote ?? Array.from(body).slice(selection!.start,selection!.end).join("")}</blockquote>
      {selected && canAnchor && <p>다시 연결할 구절: 「{Array.from(body).slice(selection!.start,selection!.end).join("")}」</p>}
      <label>주석 내용<textarea ref={input} aria-label="주석 내용" maxLength={5000} value={text} onChange={e=>{dirty.current=true;onDirtyChange(true);setText(e.target.value)}} /></label>
      <div className="annotation-actions"><button className="gb-primary" disabled={busy || !text.trim() || (!selected && !canAnchor)} onClick={()=>void save()}>주석 저장</button><button className="gb-outline" onClick={()=>{if(!dirty.current || window.confirm("저장하지 않은 주석을 닫을까요?"))onClose()}}>닫기</button>
      {selected && canAnchor && <button className="gb-outline" disabled={busy} onClick={()=>void save(true)}>선택 구절에 다시 연결</button>}
      {selected && <button className="gb-outline" disabled={busy} onClick={()=>setConfirm(true)}>주석 삭제</button>}</div>
      {!selected && !canAnchor && <p>현재 본문을 분석한 뒤 주석을 추가할 수 있습니다.</p>}
      {confirm && <div role="alertdialog" aria-label="주석 삭제 확인"><p>이 주석을 삭제할까요?</p><button className="gb-outline" disabled={busy} onClick={async()=>{setBusy(true);try{await api.delete(`/annotations/${selected!.id}`,{revisionNumber:selected!.revisionNumber,confirmation:"삭제"});onRemove(selected!.id);onClose()}catch(e){setMessage(errorMessage(e))}finally{setBusy(false)}}}>삭제 확인</button><button className="gb-outline" onClick={()=>setConfirm(false)}>취소</button></div>}
    </div>}
    {message && <p role="status">{message}</p>}
    {expired && <a href="/api/auth/login" target="_blank" rel="noopener noreferrer">새 탭에서 다시 로그인</a>}
    <ul>{notes.map(n=><li key={n.id}><button className="annotation-list-item" aria-pressed={n.id===selectedId} disabled={busy} onClick={()=>onJump(n.id)}><strong>{n.content}</strong><span>{positions[n.id] ? n.essayVersionId===version?.id ? "정상 연결" : "이전 분석 버전에 연결된 주석 · 위치 확인됨" : "현재 본문에서 위치 확인 필요"}</span><small>{n.quote}</small></button></li>)}</ul>
  </section>
}
