import type { Span } from "./book-layout"

export type ArgumentCandidate = {
  id: string; analysisRunId: string; essayVersionId: string; span: Span; quote: string
  roles: ("CLAIM_CANDIDATE" | "EVIDENCE_CANDIDATE")[]; signals: string[]
}
export type ArgumentLink = {
  id: string; analysisRunId: string; essayVersionId: string; claimId: string; evidenceId: string
  claimSpan: Span; evidenceSpan: Span; signals: string[]; sharedNouns: string[]
  confidence: "STRONG_SIGNALS" | "REVIEW_SIGNALS"
  direction?: "EVIDENCE_TO_CLAIM"; textOrder?: "CLAIM_FIRST" | "EVIDENCE_FIRST"
  approvalRoute?: "R1_DIRECT_REFERENCE"
  directReference?: {form:string;kind:string;span:Span;assessment:string;reasons:string[];meaning:string}
  followingExplanation?:{sentenceNumber:number;span:Span};explanationText?:string
}
export function argumentMarks(points: string[], source: string | null, runId: string | undefined, versionId: string | undefined, candidates: ArgumentCandidate[] = [], links: ArgumentLink[] = []) {
  const stale = !!candidates.length && (source === null || points.join("") !== source)
  if (stale || !runId || !versionId) return { candidates: [], links: [], stale }
  const nodes = candidates.filter(c => c.analysisRunId === runId && c.essayVersionId === versionId &&
    Number.isInteger(c.span.start) && Number.isInteger(c.span.end) && c.span.start >= 0 && c.span.start < c.span.end && c.span.end <= points.length &&
    points.slice(c.span.start, c.span.end).join("") === c.quote && c.roles.length > 0 &&
    c.roles.every(r => r === "CLAIM_CANDIDATE" || r === "EVIDENCE_CANDIDATE"))
  const byId = new Map(nodes.map(c => [c.id, c]))
  const seen = new Set<string>(), pairs = new Set<string>()
  const relations = links.filter(l => {
    const claim = byId.get(l.claimId), evidence = byId.get(l.evidenceId)
    const valid = l.analysisRunId === runId && l.essayVersionId === versionId && !!claim && !!evidence && l.claimId !== l.evidenceId &&
      claim.roles.includes("CLAIM_CANDIDATE") && evidence.roles.includes("EVIDENCE_CANDIDATE") &&
      (claim.span.end <= evidence.span.start || evidence.span.end <= claim.span.start) && l.claimSpan.start === claim.span.start && l.claimSpan.end === claim.span.end &&
      l.evidenceSpan.start === evidence.span.start && l.evidenceSpan.end === evidence.span.end &&
      ["STRONG_SIGNALS", "REVIEW_SIGNALS"].includes(l.confidence) && (l.direction === undefined || l.direction === "EVIDENCE_TO_CLAIM")
    const pair = JSON.stringify([l.claimId,l.evidenceId])
    if (!valid || seen.has(l.id) || pairs.has(pair)) return false
    seen.add(l.id); pairs.add(pair); return true
  })
  return { candidates: nodes, links: relations, stale }
}

export function argumentSegments(points: string[], range: Span, candidates: ArgumentCandidate[], links: ArgumentLink[], highlight?: Span | null, annotations: {id:string;span:Span}[] = []) {
  const cuts = new Set([range.start, range.end])
  for(const note of annotations) if(note.span.start<range.end && note.span.end>range.start) {
    cuts.add(Math.max(range.start,note.span.start));cuts.add(Math.min(range.end,note.span.end))
  }
  const relevant = candidates.filter(c => c.span.start < range.end && c.span.end > range.start)
  for (const c of relevant) { cuts.add(Math.max(range.start, c.span.start)); cuts.add(Math.min(range.end, c.span.end)) }
  if (highlight && highlight.start < range.end && highlight.end > range.start) {
    cuts.add(Math.max(range.start, highlight.start)); cuts.add(Math.min(range.end, highlight.end))
  }
  const boundaries = [...cuts].sort((a,b) => a-b)
  // Sentences do not overlap; a linear sweep avoids N² work on long essays.
  relevant.sort((a,b) => a.span.start-b.span.start)
  const outgoing = new Map<string, ArgumentLink[]>()
  for (const link of links) outgoing.set(link.evidenceId, [...(outgoing.get(link.evidenceId) ?? []), link])
  let cursor = 0
  return boundaries.slice(0,-1).map((start,i) => {
    const end = boundaries[i+1]
    while (cursor < relevant.length && relevant[cursor].span.end <= start) cursor++
    const candidate = relevant[cursor]?.span.start <= start && relevant[cursor]?.span.end >= end ? relevant[cursor] : undefined
    return { start, end, text: points.slice(start,end).join(""), candidate,
      highlighted: !!highlight && highlight.start <= start && highlight.end >= end,
      arrows: candidate?.span.end === end ? outgoing.get(candidate.id) ?? [] : [] }
  })
}
