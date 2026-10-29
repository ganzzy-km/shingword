import { useEffect, useRef, useState } from 'react'

const steps=[
  {title:'글 입력·가져오기',text:'새 글의 본문을 입력하거나 PDF를 가져오세요.',target:'input'},
  {title:'원작품 선택',text:'원작품·메모에서 사용할 판본을 선택합니다. 원작품 없이도 분석할 수 있습니다.',target:'source'},
  {title:'분석 실행',text:'작성한 글을 저장하고 분석하기를 누르세요. 자동 분석은 내 글과 직접 지정한 관계를 덮어쓰지 않습니다.',target:'analyze'},
  {title:'피드백 보기',text:'실제 분석 결과에서 제안을 고르고 원문 위치와 연결을 확인하세요.',target:'feedback'},
]

export default function WritingTutorial({step,hasAnalysis,canAnalyze,onStep,onAnalyze,onClose,onComplete,onPrepare,returnFocus}:{step:number;hasAnalysis:boolean;canAnalyze:boolean;onStep:(n:number)=>Promise<void>;onAnalyze:()=>Promise<void>;onClose:()=>Promise<void>;onComplete:()=>Promise<void>;onPrepare:(n:number)=>void;returnFocus?:{current:HTMLElement|null}}){
  const dialog=useRef<HTMLDialogElement>(null),previous=useRef<HTMLElement|null>(null)
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  const safeStep=step===3&&!hasAnalysis?2:step
  useEffect(()=>{previous.current=document.activeElement as HTMLElement;dialog.current?.showModal();return()=>{dialog.current?.close();requestAnimationFrame(()=>{const target=returnFocus?.current??previous.current;if(target?.isConnected)target.focus({preventScroll:true})})}},[])
  useEffect(()=>{
    onPrepare(safeStep)
    let node:HTMLElement|null=null
    const locate=()=>{const next=document.querySelector<HTMLElement>(`[data-tour="${steps[safeStep].target}"]`);if(next!==node){node?.classList.remove('tutorial-target');node=next;node?.classList.add('tutorial-target')}}
    const observer=new MutationObserver(locate)
    observer.observe(document.body,{childList:true,subtree:true})
    const frame=requestAnimationFrame(locate)
    return()=>{observer.disconnect();cancelAnimationFrame(frame);node?.classList.remove('tutorial-target')}
  },[safeStep])
  const act=async(fn:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');try{await fn()}catch(e){setError(e instanceof Error?e.message:'안내 상태를 저장하지 못했습니다.')}finally{setBusy(false)}}
  return <dialog ref={dialog} aria-label="글쓰기 사용 안내" className="writing-tutorial" onCancel={e=>{e.preventDefault();void act(onClose)}}>
    <p>{safeStep+1} / 4</p><h2>{steps[safeStep].title}</h2><p>{steps[safeStep].text}</p>
    {error&&<p role="alert">{error}</p>}
    {safeStep===2&&!hasAnalysis&&<p>실제 결과가 준비된 뒤 마지막 단계를 볼 수 있습니다. 글 입력이 필요하면 안내를 건너뛰고 작성하세요.</p>}
    <div className="tools-actions"><button disabled={busy} onClick={()=>void act(onClose)}>건너뛰기</button>
      {safeStep>0&&<button disabled={busy} onClick={()=>void act(()=>onStep(safeStep-1))}>이전</button>}
      {safeStep<2&&<button disabled={busy} onClick={()=>void act(()=>onStep(safeStep+1))}>다음</button>}
      {safeStep===2&&<button disabled={busy||(!hasAnalysis&&!canAnalyze)} onClick={()=>void act(async()=>{if(!hasAnalysis)await onAnalyze();else await onStep(3)})}>{hasAnalysis?'실제 피드백 보기':'실제 분석 실행'}</button>}
      {safeStep===3&&hasAnalysis&&<button disabled={busy} onClick={()=>void act(onComplete)}>완료</button>}
    </div>
  </dialog>
}
