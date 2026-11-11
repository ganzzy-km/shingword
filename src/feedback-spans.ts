import type { Span } from "./book-layout"

// Validate each mapped anchor once per text/result change. Never search by
// quote text: repeated passages must retain their original mapped identity.
export function validatedSpans(
  points: readonly string[],
  findings: readonly { id: string; current: string }[],
  spans: Record<string, Span | null>,
): Record<string, Span | null> {
  const result: Record<string, Span | null> = Object.create(null)
  for (const finding of findings) {
    const span = spans[finding.id]
    result[finding.id] = span && Number.isInteger(span.start) && Number.isInteger(span.end)
      && span.start >= 0 && span.end > span.start && span.end <= points.length
      && points.slice(span.start, span.end).join("") === finding.current ? span : null
  }
  return result
}
