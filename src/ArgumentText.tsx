import { argumentSegments, type ArgumentCandidate, type ArgumentLink } from "./argument-spans"
import type { Span } from "./book-layout"

export default function ArgumentText({points, range, candidates, links, highlight, focusedId, mirror = false, onSelect, onJump, annotations = [], selectedAnnotation, onAnnotation}: {
  points: string[]; range: Span; candidates: ArgumentCandidate[]; links: ArgumentLink[]; highlight?: Span | null
  focusedId: string | null; mirror?: boolean; onSelect: (id: string) => void; onJump: (link: ArgumentLink) => void
  annotations?: {id:string;span:Span}[]; selectedAnnotation?:string|null;onAnnotation?:(id:string)=>void
}) {
  return <>{argumentSegments(points,range,candidates,links,highlight,annotations).map(segment => {
    const c=segment.candidate, claim=c?.roles.includes("CLAIM_CANDIDATE"), evidence=c?.roles.includes("EVIDENCE_CANDIDATE")
    const interactive = !!c && !mirror
    return <span key={segment.start}>
      <span data-argument-id={c?.id} data-start={segment.start} data-end={segment.end}
        className={`argument-fragment ${annotations.some(n=>n.id===selectedAnnotation && n.span.start<=segment.start && n.span.end>=segment.end) ? "annotation-focused" : ""} ${claim ? "argument-claim" : ""} ${evidence ? "argument-evidence" : ""} ${c?.id === focusedId ? "argument-focused" : ""} ${segment.highlighted ? "argument-selected" : ""}`}
        aria-hidden={mirror || undefined} role={interactive ? "button" : undefined} tabIndex={interactive ? 0 : undefined}
        aria-label={interactive ? `${claim ? "주장" : "근거"} 후보: ${c.quote}` : undefined}
        onClick={interactive ? () => onSelect(c.id) : undefined}
        onKeyDown={interactive ? e => {if(e.key === "Enter" || e.key === " "){e.preventDefault();onSelect(c.id)}} : undefined}>
        {segment.highlighted ? <mark>{segment.text}</mark> : segment.text}
      </span>
      {annotations.filter(n=>n.span.end===segment.end).map(note=><span key={note.id} className="annotation-anchor" data-annotation-id={note.id} />)}
      {segment.arrows.map((link,index) => <span key={link.id} className="argument-arrow-anchor" data-argument-relation={link.id} data-argument-offset={index*26} data-argument-count={segment.arrows.length} style={!mirror&&segment.arrows.length>1?{width:26}:undefined}>{!mirror && <button type="button" className="argument-link" data-relation-id={link.id} title="연결된 주장으로 이동" aria-label="연결된 주장으로 이동" onClick={() => onJump(link)}>
        <svg viewBox="0 0 16 16" aria-hidden="true" style={{transform:link.claimSpan.start>link.evidenceSpan.start?"rotate(180deg)":undefined}}><path d="M8 13V3M4 7l4-4 4 4" /></svg>
      </button>}</span>)}
    </span>
  })}</>
}
