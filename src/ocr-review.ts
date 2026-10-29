/** Literal review operations; stale offsets never guess a replacement target. */
export function replaceOcrSpan(current: string, recognized: string, start: number, end: number, expected: string, replacement: string): string {
  if (current !== recognized) throw new Error("초안이 바뀌었습니다. 위치를 추측하지 않으므로 본문에서 직접 수정하거나 되돌린 뒤 다시 선택하세요.")
  const points = Array.from(current)
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start || end > points.length || points.slice(start, end).join("") !== expected) throw new Error("원문 위치를 확인할 수 없습니다. 본문에서 직접 수정해 주세요.")
  return points.slice(0, start).join("") + replacement + points.slice(end).join("")
}

export function tableColumnSpan(cell: { columnSpan?: unknown; colSpan?: unknown }): number {
  const value = cell.columnSpan ?? cell.colSpan ?? 1
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 64 ? value : 1
}
