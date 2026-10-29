import { useLayoutEffect, useRef, useState, type RefObject, type ReactNode } from "react"
import type { ArgumentLink } from "./argument-spans"

export default function ArgumentEditorLayer({editor,children,links,onJump,onAnnotation}: {editor: RefObject<HTMLTextAreaElement | null>; children: ReactNode; links: ArgumentLink[]; onJump: (link: ArgumentLink) => void;onAnnotation?:(id:string)=>void}) {
  const layer = useRef<HTMLDivElement>(null)
  const [positions,setPositions] = useState<{id: string; left: number; top: number;note?:boolean}[]>([])
  useLayoutEffect(() => {
    const node=editor.current, mirror=layer.current
    if(!node || !mirror)return
    const sync = () => {
      const style=getComputedStyle(node)
      Object.assign(mirror.style,{width:`${node.clientWidth}px`,padding:style.padding,font:style.font,
        lineHeight:style.lineHeight,letterSpacing:style.letterSpacing,wordSpacing:style.wordSpacing,
        transform:`translate(${-node.scrollLeft}px,${-node.scrollTop}px)`})
      const rect=node.getBoundingClientRect()
      const positions:{id:string;left:number;top:number;note?:boolean}[]=[]
      for(const anchor of mirror.querySelectorAll<HTMLElement>("[data-argument-relation],[data-annotation-id]")) {
        const box=anchor.getBoundingClientRect(),top=box.top-rect.top-19
        const offset=Number(anchor.dataset.argumentOffset ?? 0),extra=Math.max(0,Number(anchor.dataset.argumentCount ?? 1)-1)*26
        if(top>=0 && top+24<=node.clientHeight)positions.push({id:anchor.dataset.annotationId ?? anchor.dataset.argumentRelation!,note:!!anchor.dataset.annotationId,left:Math.max(0,Math.min(node.clientWidth-24-extra,box.left-rect.left+Number(anchor.dataset.annotationOffset ?? 0)))+offset,top})
      }
      const noteRows=new Set<number>()
      const visible=positions.filter(p=>{if(!p.note)return true;const row=Math.round(p.top);if(noteRows.has(row))return false;noteRows.add(row);p.left=1;return true})
      setPositions(old=>JSON.stringify(old)===JSON.stringify(visible) ? old : visible)
    }
    sync();node.addEventListener("scroll",sync)
    const observer=new ResizeObserver(sync);observer.observe(node)
    let active=true;void document.fonts.ready.then(()=>{if(active)sync()})
    return () => {active=false;observer.disconnect();node.removeEventListener("scroll",sync)}
  },[children,editor])
  return <><div className="argument-editor-layer"><div className="argument-editor-mirror" ref={layer}>{children}<span aria-hidden="true">{"\u200b"}</span></div></div><div className="argument-editor-controls">{positions.map(position=>{
    if(position.note)return <button key={position.id} className="annotation-icon" style={{left:position.left,top:position.top,bottom:"auto"}} title="내 주석 열기" aria-label="내 주석 열기" onClick={()=>onAnnotation?.(position.id)}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 2h12v9H7l-4 3v-3H2zM5 5h6M5 8h4" /></svg></button>
    const link=links.find(l=>l.id===position.id)
    return link && <button key={link.id} type="button" className="argument-link" data-relation-id={link.id} style={{left:position.left,top:position.top,bottom:"auto"}} title="연결된 주장으로 이동" aria-label="연결된 주장으로 이동" onClick={()=>onJump(link)}><svg viewBox="0 0 16 16" aria-hidden="true" style={{transform:link.claimSpan.start>link.evidenceSpan.start?"rotate(180deg)":undefined}}><path d="M8 13V3M4 7l4-4 4 4" /></svg></button>
  })}</div></>
}
