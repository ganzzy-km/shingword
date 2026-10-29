import {useLayoutEffect,useRef,useState} from "react"
export default function AnnotationBookLayer({onOpen}: {onOpen:(id:string)=>void}) {
  const layer=useRef<HTMLDivElement>(null),[positions,setPositions]=useState<{id:string;top:number}[]>([])
  useLayoutEffect(()=>{
    const page=layer.current?.closest<HTMLElement>(".reading-page")
    if(!page)return
    function sync(){
      const box=page!.getBoundingClientRect(),rows=new Set<number>(),items:{id:string;top:number}[]=[]
      for(const anchor of page!.querySelectorAll<HTMLElement>(".page-body [data-annotation-id]")) {
        const top=Math.max(0,anchor.getBoundingClientRect().top-box.top-18),row=Math.round(top)
        if(!rows.has(row)){rows.add(row);items.push({id:anchor.dataset.annotationId!,top})}
      }
      setPositions(old=>JSON.stringify(old)===JSON.stringify(items) ? old : items)
    }
    sync();const observer=new ResizeObserver(sync);observer.observe(page)
    let active=true;void document.fonts.ready.then(()=>{if(active)sync()})
    return()=>{active=false;observer.disconnect()}
  })
  return <div className="annotation-book-layer" ref={layer}>{positions.map(p=><button key={p.id} className="annotation-icon" style={{left:2,top:p.top,bottom:"auto"}} title="내 주석 열기" aria-label="내 주석 열기" onClick={()=>onOpen(p.id)}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 2h12v9H7l-4 3v-3H2zM5 5h6M5 8h4" /></svg></button>)}</div>
}
