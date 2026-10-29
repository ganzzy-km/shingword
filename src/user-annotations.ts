import { mapSpan, type Span } from "./book-layout"
export type UserAnnotation = {id:string;writingId:string;essayVersionId:string;span:Span;quote:string;content:string;revisionNumber:number;createdAt:string;updatedAt:string;originalAnchor:{essayVersionId:string;span:Span;quote:string}}
export type AnnotationMark = {id:string;span:Span}
export function verifiedAnnotationSpan(note:UserAnnotation, source:string | undefined, current:string):Span|null {
  const points=Array.from(source ?? "")
  return source===current && Number.isInteger(note.span.start) && Number.isInteger(note.span.end) && note.span.start>=0 && note.span.start<note.span.end && note.span.end<=points.length && points.slice(note.span.start,note.span.end).join("")===note.quote ? note.span : null
}
export function moveAnnotation(before:string,after:string,span:Span|null,quote:string,edit?:Span):Span|null {
  if(!span)return null
  const next=mapSpan(before,after,span,edit)
  return next && Array.from(after).slice(next.start,next.end).join("")===quote ? next : null
}

/** Selection uses DOM text offsets, never substring searching (repeated quotes are safe). */
export function bookSelection(root:HTMLElement):Span|null {
  const selection=window.getSelection()
  if(!selection || selection.isCollapsed || selection.rangeCount!==1)return null
  const range=selection.getRangeAt(0)
  function position(node:Node,offset:number):number|null {
    const fragment=(node.nodeType===Node.ELEMENT_NODE ? node as Element : node.parentElement)?.closest<HTMLElement>(".argument-fragment[data-start]")
    if(!fragment || !root.contains(fragment))return null
    const prefix=document.createRange();prefix.selectNodeContents(fragment);prefix.setEnd(node,offset)
    return Number(fragment.dataset.start)+Array.from(prefix.toString()).length
  }
  const start=position(range.startContainer,range.startOffset),end=position(range.endContainer,range.endOffset)
  return start!==null && end!==null && start<end ? {start,end} : null
}
