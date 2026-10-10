export type Span = { start: number; end: number }

export function paragraphs(text: string): (Span & { text: string })[] {
  const points = Array.from(text)
  const result: (Span & { text: string })[] = []
  let start = 0
  for (let i = 0; i <= points.length; i++) {
    if (i === points.length || (points[i] === "\n" && points[i + 1] === "\n")) {
      if (points.slice(start, i).join("").trim())
        result.push({ start, end: i, text: points.slice(start, i).join("") })
      if (i < points.length) {
        while (points[i + 1] === "\n") i++
        start = i + 1
      }
    }
  }
  return result
}

// Map only ranges proved unchanged by a contiguous edit. Never relocate by quote search.
export function mapSpan(
  before: string,
  after: string,
  span: Span,
  edit?: Span,
): Span | null {
  const a = Array.from(before),
    b = Array.from(after)
  if (before === after) return span
  if (!edit) return null
  const left = edit.start,
    oldEnd = edit.end,
    right = a.length - oldEnd
  if (
    a.slice(0, left).join("") !== b.slice(0, left).join("") ||
    a.slice(oldEnd).join("") !== b.slice(b.length - right).join("")
  )
    return null
  if (span.end <= left) return span
  if (span.start >= oldEnd)
    return {
      start: span.start + b.length - a.length,
      end: span.end + b.length - a.length,
    }
  return null
}

// Every code point belongs to exactly one page; whitespace and long paragraphs are preserved.
export function paginateText(
  text: string,
  fits: (text: string) => boolean,
): Span[] {
  const points = Array.from(text),
    pages: Span[] = []
  let start = 0
  while (start < points.length) {
    let low = start + 1,
      high = Math.min(points.length, start + 4000),
      end = low
    while (low <= high) {
      const mid = Math.floor((low + high) / 2)
      if (fits(points.slice(start, mid).join(""))) {
        end = mid
        low = mid + 1
      } else high = mid - 1
    }
    if (end < points.length) {
      const chunk = points.slice(start, end).join("")
      const boundary = Math.max(
        chunk.lastIndexOf("\n\n"),
        chunk.lastIndexOf(". "),
        chunk.lastIndexOf("。"),
      )
      if (boundary > chunk.length * 0.65)
        end =
          start +
          Array.from(
            chunk.slice(
              0,
              boundary +
                (chunk.slice(boundary, boundary + 2) === "\n\n" ? 2 : 1),
            ),
          ).length
    }
    pages.push({ start, end })
    start = end
  }
  return pages.length ? pages : [{ start: 0, end: 0 }]
}

export function utf16Offset(text: string, point: number) {
  return Array.from(text).slice(0, point).join("").length
}
