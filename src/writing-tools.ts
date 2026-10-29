import type { Span } from './book-layout'

export type ToolsPreferences = {fontSize:number; lineHeight:number; bodyWidth:number; focus:boolean; tutorial:string; tutorialStep:number; mobileTab:string}
export const toolsDefaults:ToolsPreferences={fontSize:18,lineHeight:1.9,bodyWidth:820,focus:false,tutorial:'UNSEEN',tutorialStep:0,mobileTab:'body'}
export type VersionAnchor={essayVersionId:string;span:Span;quote:string}
export type ToolsVersion={id:string;content:string;writingId?:string}
export type Mark={id:string;kind:'USER_CLAIM'|'USER_EVIDENCE'|'USER_LINK';source:'USER_DEFINED';essayVersionId:string;quote:string;span:Span;revisionNumber:number;originalAnchor:VersionAnchor;metadata:{claimId?:string;evidenceId?:string;classification?:string};resolution:{status:string;span:Span|null}}
export type SourceAnchor={documentId:string;revisionId:string;span:Span;quote:string}
export type SourceItem={id:string;title:string;author:string;genre:string;scope:string;accessMode:string;latestRevisionId:string;favorite:boolean;lastUsed?:string;sourceType:string;isOwner:boolean;ocr?:{reviewAvailable?:boolean}}
export type Card={id:string;documentId?:string;kind:string;sourceType:string;quote:string;interpretation:string;claimText:string;work:string;sourceAnchor:SourceAnchor|null;writingAnchor:VersionAnchor|null;writingResolution?:{status:string;span:Span|null};sourceUnavailable:boolean;claimId?:string;classification:string;revisionNumber:number;clientKey?:string;page:string}
export const groupLabels:Record<string,string>={SUPPORT:'지지 근거',ALTERNATIVE:'다른 해석',COUNTER:'반대 근거',UNSORTED:'미분류'}
export const sourceLabels:Record<string,string>={ORIGINAL:'원작품',REFERENCE:'참고 해설',MY_INTERPRETATION:'내 해석'}
export const kindLabels:Record<string,string>={DIRECT_QUOTE:'직접 인용',SCENE:'장면 요약',NOTE:'메모',CHARACTER:'인물',IMAGE:'이미지',CONFLICT:'갈등',QUESTION:'질문'}
export const cpSlice=(body:string,span:Span)=>Array.from(body).slice(span.start,span.end).join('')
export function selectionAnchor(version:ToolsVersion,body:string,selection:Span):VersionAnchor {
  const points=Array.from(body)
  if(version.content!==body || !Number.isInteger(selection.start) || !Number.isInteger(selection.end) || selection.start<0 || selection.end<=selection.start || selection.end>points.length)throw new Error('저장된 글 버전에서 구간을 다시 선택해 주세요.')
  return {essayVersionId:version.id,span:{...selection},quote:points.slice(selection.start,selection.end).join('')}
}
export function keywordQueries(value:string):string[]{return [...new Set(value.split(/[,\n]/u).map(x=>x.trim()).filter(Boolean))].slice(0,8)}

