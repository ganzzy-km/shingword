import type { Span } from "./book-layout"

// Preserve overlapping matches and code-point addresses without temporary slices.
export function findTextSpans(points: readonly string[], query: string): Span[] {
  const needle = Array.from(query), result: Span[] = []
  if (!needle.length) return result
  for (let i = 0; i <= points.length - needle.length; i++) {
    let j = 0
    while (j < needle.length && points[i + j] === needle[j]) j++
    if (j === needle.length) result.push({ start: i, end: i + needle.length })
  }
  return result
}

// Multiple explicit strings, never a semantic/inflection match. Single-string API stays unchanged.
export function findMultipleTextSpans(points: readonly string[], query: string): Span[] {
  const queries=[...new Set(query.split(/[,\n]/u).map(x=>x.trim()).filter(Boolean))].slice(0,8)
  const unique=new Map<string,Span>()
  for(const q of queries)for(const s of findTextSpans(points,q))unique.set(`${s.start}:${s.end}`,s)
  return [...unique.values()].sort((a,b)=>a.start-b.start||a.end-b.end)
}
