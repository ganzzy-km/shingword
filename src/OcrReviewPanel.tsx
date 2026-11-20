import { useEffect, useRef, useState } from "react"
import { api, errorMessage } from "./api"
import { replaceOcrSpan, tableColumnSpan } from "./ocr-review"

type Line = { id: string; text: string; box: number[]; engine: string; difference: string; includedInDraft?: boolean; draftLineIndex?: number | null; stanzaGapCandidateBefore?: boolean; secondary?: { text: string } | null; alignment?: { kind: string }; segmentationOnly?: boolean }
type Literary = { requestedProfile: string; effectiveProfile: string; physicalLines: { lineId: string; span: number[]; indentRatio: number; kind: string }[]; boundaries: { id: string; beforeLineId: string; position: number; kind: string; reasons: string[]; automaticallyApplied?: boolean }[]; lineWrapCandidates?: { id: string; fromLineId: string; toLineId: string; start: number; end: number; expected: string; leftText: string; rightText: string }[] }
type LocalRefinement = { candidates: { id: string; box: number[]; lineIds: string[]; triggers: string[]; psm: number; unavailable?: string; alternatives: { engine: string; text: string; scale?: number; psm?: number }[] }[]; automaticallyChangedCharacters: number }
type Precision = { before: { text: string }; changedCharacters: number; decisions: { regionId: string; lineIds: string[]; status: string; reason: string; changes: { lineId: string; before: string; after: string; reason?: string }[] }[] }
type Page = { page: number; width: number; height: number; imageUrl: string; draft: string; recognizedText: string; lines: Line[]; unavailable: string[]; literary?: Literary | null; localRefinement?: LocalRefinement | null; precision?: Precision | null; lineMap?: { lineId: string; start?: number; end?: number }[]; structure: { blocks: { type: string }[]; tables: { cells?: { row: number; column: number; rowSpan: number; columnSpan?: number; colSpan?: number; text: string }[] }[] } }
type Job = { id: string; documentId: string; status: string; ocrMode: "standard" | "precise"; error?: string; draftVersion: number; inputRevisionId: string; confirmedRevisionId?: string; completedPages: number; totalPages: number; pages: Page[]; alternative?: { text: string; engine: string } }
const button = "min-h-11 rounded-lg border border-[#CBD5E1] px-4 py-2 text-sm disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-[#087F8C]"
const active = new Set(["queued", "running"])
const states: Record<string, string> = { queued: "처리 대기", running: "인식 중", REVIEW_READY: "검수 대기", CONFIRMED: "확정 완료", FAILED: "처리 실패", failed: "중단됨", CANCELLED: "취소됨", EXPIRED: "기한 만료" }
const profileNames: Record<string, string> = { auto: "장르 미지정", poetry: "시", prose: "소설·산문", drama: "희곡", commentary: "문학 해설", other: "기타" }
const differences: Record<string, string> = { FORMULA_REGION_SEPARATE: "수식 영역 · 원본에서 별도 확인", TEXT_DIFFERENCE: "인식 불일치", SECONDARY_MISSING: "Tesseract 누락 후보", PRIMARY_MISSING: "Paddle 누락 후보", AGREEMENT: "두 엔진 일치", NATIVE_PRESERVED: "텍스트 직접 추출", SINGLE_ENGINE_NO_COMPARISON: "일반 인식 · 비교 미실행" }

export default function OcrReviewPanel({ documentId, accessMode, onClose, onSaved }: { documentId: string; accessMode: string; onClose: () => void; onSaved: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const image = useRef<HTMLImageElement>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [number, setNumber] = useState(1)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [draftBaseVersion, setDraftBaseVersion] = useState(0)
  const initialized = useRef("")
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [filter, setFilter] = useState("all")
  const [engine, setEngine] = useState("vl")
  const [box, setBox] = useState([0, 0, 0, 0])
  const [selecting, setSelecting] = useState(false)
  const anchor = useRef<number[] | null>(null)
  const [selectedLine, setSelectedLine] = useState<string | null>(null)
  const [alternativeJob, setAlternativeJob] = useState<string | null>(null)
  const [alternative, setAlternative] = useState<Job["alternative"]>(undefined)
  const [undo, setUndo] = useState<Record<string, string[]>>({})
  const [confirming, setConfirming] = useState(false)
  const generation = useRef(0)
  const currentDocument = useRef(documentId)
  currentDocument.current = documentId
  const refreshDocument = useRef<() => Promise<void>>(async () => {})
  const page = job?.pages.find(p => p.page === number)
  const editable = job?.status === "REVIEW_READY"
  const load = () => refreshDocument.current()
  useEffect(() => {
    if (!dialog.current?.open) dialog.current?.showModal()
    const epoch = ++generation.current
    let alive = true, timer: ReturnType<typeof setTimeout> | undefined
    let pending: Promise<void> | null = null
    const current = () => alive && generation.current === epoch && currentDocument.current === documentId
    initialized.current = ""
    setJob(null);setNumber(1);setDrafts({});setDraftBaseVersion(0);setDirty(false);setBusy(false);setError("");setNotice("");setUndo({})
    setAlternativeJob(null);setAlternative(undefined);setSelectedLine(null);setBox([0, 0, 0, 0]);setConfirming(false)
    const refresh = (afterPending = false): Promise<void> => {
      if (!current()) return Promise.resolve()
      clearTimeout(timer)
      // Explicit refreshes after retry/cancel/confirm need a fresh response,
      // while scheduled progress requests share an existing in-flight read.
      if (pending) return afterPending ? pending.then(() => refresh()) : pending
      pending = (async () => {
        try {
          const value = await api.get<Job>(`/source-documents/${documentId}/ocr`)
          if (!current()) return
          setJob(value)
          if (initialized.current !== value.id && value.pages.length) {
            setEngine(value.ocrMode === "standard" ? "paddle" : "vl")
            initialized.current = value.id
            setDrafts(Object.fromEntries(value.pages.map(p => [String(p.page), p.draft])))
            setDraftBaseVersion(value.draftVersion)
          }
          if (active.has(value.status)) timer = setTimeout(() => void refresh(), 1800)
        } catch (cause) {
          if (current()) { setError(errorMessage(cause));timer = setTimeout(() => void refresh(), 1800) }
        } finally { pending = null }
      })()
      return pending
    }
    refreshDocument.current = () => refresh(true)
    void refresh()
    return () => { alive = false;generation.current++;clearTimeout(timer);refreshDocument.current = async () => {} }
  }, [documentId])
  useEffect(() => {
    if (!alternativeJob) return
    const epoch = generation.current
    let alive = true, timer: ReturnType<typeof setTimeout> | undefined
    const current = () => alive && generation.current === epoch && currentDocument.current === documentId
    const check = async () => {
      try {
        const value = await api.get<Job>(`/ocr-jobs/${alternativeJob}`)
        if (!current()) return
        if (value.status === "ALTERNATIVE_READY") { setAlternative(value.alternative);setAlternativeJob(null);setNotice("재인식 결과를 원본과 비교한 뒤 초안에 반영하세요.") }
        else if (!active.has(value.status)) { setAlternativeJob(null);setError(value.error || "선택한 엔진을 실행하지 못했습니다. 기존 초안은 유지됩니다.") }
        else timer = setTimeout(() => void check(), 1500)
      } catch (cause) { if (current()) { setError(errorMessage(cause));setAlternativeJob(null) } }
    }
    void check()
    return () => { alive = false;clearTimeout(timer) }
  }, [alternativeJob, documentId])
  const request = async (task: () => Promise<void>) => {
    const epoch = generation.current
    setBusy(true);setError("");setNotice("")
    try { await task() } catch (cause) { if (generation.current === epoch) setError(errorMessage(cause)) } finally { if (generation.current === epoch) setBusy(false) }
  }
  const save = async () => {
    if (!job) return
    const epoch = generation.current
    const updated = await api.patch<Job>(`/ocr-jobs/${job.id}/draft`, { expectedDraftVersion: draftBaseVersion, pages: drafts })
    if (generation.current !== epoch || currentDocument.current !== documentId) return
    setJob(updated);setDraftBaseVersion(updated.draftVersion);setDirty(false);setNotice("검수 초안을 저장했습니다.")
  }
  const write = (text: string) => {
    const key = String(number),old = drafts[key] ?? page?.draft ?? ""
    if (old === text) return
    setUndo(history => ({ ...history, [key]: [...(history[key] ?? []), old].slice(-20) }))
    setDrafts(d => ({ ...d, [key]: text }));setDirty(true);setConfirming(false)
  }
  const locate = (lineId: string) => {
    const line = page?.lines.find(l => l.id === lineId)
    if (!line) return
    setBox(line.box);setSelectedLine(line.id);setAlternative(undefined)
    image.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
  }
  const apply = (text: string, lineId = selectedLine) => {
    if (!page) return
    const current = drafts[String(number)] ?? page.draft
    const selected = page.lines.find(l => l.id === lineId)
    const mapped = page.lineMap?.find(l => l.lineId === lineId)
    if (mapped?.start != null && mapped.end != null && current === page.recognizedText) {
      const points = Array.from(current)
      if (points.slice(mapped.start, mapped.end).join("") !== selected?.text.normalize("NFC")) { setError("위치를 추측하지 않으므로 원본과 대조해 직접 수정해 주세요.");return }
      write(points.slice(0, mapped.start).join("") + text + points.slice(mapped.end).join(""));setNotice("선택한 대안을 초안에 반영했습니다. 원문 확정 전 원본과 대조하세요.");return
    }
    const lineIndex = selected?.draftLineIndex ?? -1
    const lines = current.split("\n")
    if (lineIndex >= 0 && current === page.recognizedText) {
      if (lines[lineIndex] !== selected!.text.normalize("NFC")) { setError("선택한 줄이 이미 편집되었습니다. 대안과 비교해 본문을 직접 수정해 주세요.");return }
      lines[lineIndex] = text;write(lines.join("\n"))
    } else write(current + (current ? "\n" : "") + text)
    setNotice("선택한 대안만 초안에 반영했습니다. 아직 원문 판본은 변경되지 않았습니다.")
  }
  const position = (e: React.PointerEvent) => {
    const bounds = image.current?.getBoundingClientRect()
    if (!page || !bounds) return [0, 0]
    return [Math.max(0, Math.min(page.width, (e.clientX - bounds.left) / bounds.width * page.width)), Math.max(0, Math.min(page.height, (e.clientY - bounds.top) / bounds.height * page.height))]
  }
  return <dialog ref={dialog} onCancel={e => { if (confirming) { e.preventDefault();setConfirming(false) } else if (dirty) { e.preventDefault();setError("입력한 검수 내용을 임시 저장한 뒤 닫아 주세요.") } else onClose() }} onClose={onClose} aria-labelledby="ocr-review-title" className="m-auto w-[calc(100%_-_1rem)] max-w-6xl max-h-[94vh] overflow-auto rounded-xl bg-white p-4 sm:p-6 text-[#17212B]">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <h2 id="ocr-review-title" className="text-xl font-semibold">원문 OCR 검수</h2>
      <button className={button} onClick={() => { if (dirty) setError("검수 내용을 임시 저장한 뒤 닫아 주세요.");else onClose() }}>닫기</button>
    </header>
    <p role="status" className="my-3 text-sm text-[#475569]">{job ? `${job.ocrMode === "standard" ? "일반 OCR" : "고정밀 OCR"} · ${states[job.status] || job.status}` : "불러오는 중"} · {job?.completedPages ?? 0}/{job?.totalPages ?? 0}페이지</p>
    {error && <p role="alert" className="my-3 text-sm text-[#C62828]">{error}</p>}
    {notice && <p role="status" className="my-3 text-sm text-[#087F8C]">{notice}</p>}
    {job?.error && <p className="my-3 text-sm text-[#C62828]">{job.error}</p>}
    {job && <div className="mb-4 flex flex-wrap gap-2">
      {active.has(job.status) && <button className={button} disabled={busy} onClick={() => void request(async () => { await api.post(`/ocr-jobs/${job.id}/cancel`, {});await load() })}>작업 취소</button>}
      {["FAILED", "failed", "interrupted", "CANCELLED"].includes(job.status) && <button className={button} disabled={busy} onClick={() => void request(async () => { await api.post(`/ocr-jobs/${job.id}/retry`, {});await load() })}>완료 페이지 유지하고 재개</button>}
      {job.pages.map(p => <button key={p.page} disabled={!!alternativeJob} aria-pressed={number === p.page} className={button} onClick={() => { setNumber(p.page);setSelectedLine(null);setBox([0, 0, 0, 0]);setAlternative(undefined) }}>{p.page}쪽</button>)}
    </div>}
    {page && <>
      <div className="grid gap-5 lg:grid-cols-2">
        <section aria-label="원본 페이지" className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2"><h3 className="font-semibold">원본 {number}쪽</h3><button className={button} aria-pressed={selecting} disabled={!editable} onClick={() => setSelecting(v => !v)}>{selecting ? "영역 선택 중" : "영역 선택"}</button></div>
          <div className="max-h-[62vh] overflow-auto rounded-lg border bg-[#F8FAFC]">
            <div className="relative inline-block max-w-full align-top" style={{ touchAction: selecting ? "none" : "auto" }}
              onPointerDown={e => { if (!selecting || alternativeJob) return;anchor.current = position(e);e.currentTarget.setPointerCapture(e.pointerId);setSelectedLine(null) }}
              onPointerMove={e => { if (!anchor.current) return;const p = position(e),a = anchor.current;setBox([Math.min(a[0], p[0]), Math.min(a[1], p[1]), Math.max(a[0], p[0]), Math.max(a[1], p[1])]) }}
              onPointerUp={() => { anchor.current = null;setSelecting(false) }} onPointerCancel={() => { anchor.current = null;setSelecting(false) }}>
              <img ref={image} src={page.imageUrl} alt={`원본 ${number}페이지`} draggable={false} className="block h-auto max-w-full" />
              {box[2] > box[0] && <div aria-hidden="true" className="pointer-events-none absolute border-2 border-[#087F8C] bg-[#087F8C]/10" style={{ left: `${box[0] / page.width * 100}%`, top: `${box[1] / page.height * 100}%`, width: `${(box[2] - box[0]) / page.width * 100}%`, height: `${(box[3] - box[1]) / page.height * 100}%` }} />}
            </div>
          </div>
          <div className="my-3 grid grid-cols-4 gap-2">{box.map((value, i) => <label key={i} className="text-xs">{["왼쪽", "위쪽", "오른쪽", "아래쪽"][i]}<input aria-label={`영역 ${["왼쪽", "위쪽", "오른쪽", "아래쪽"][i]}`} type="number" min={0} value={Math.round(value)} disabled={!editable || !!alternativeJob} onChange={e => { setSelectedLine(null);setAlternative(undefined);setBox(old => old.map((n, j) => i === j ? Number(e.target.value) : n)) }} className="mt-1 w-full rounded border p-2 text-sm" /></label>)}</div>
          <div className="flex flex-wrap gap-2"><select aria-label="재인식 엔진" value={engine} onChange={e => setEngine(e.target.value)} className="rounded-lg border p-2 text-sm"><option value="paddle">한국어 Paddle</option>{job?.ocrMode !== "standard" && <><option value="tesseract">Tesseract best · 문단 PSM6</option><option value="tesseract-line">Tesseract best · 한 줄 PSM7</option><option value="vl">PaddleOCR-VL 정밀</option></>}</select>
            <button className={button} disabled={!editable || busy || !!alternativeJob || box[2] <= box[0] || box[3] <= box[1]} onClick={() => void request(async () => { const epoch = generation.current;const child = await api.post<{ id: string }>(`/ocr-jobs/${job!.id}/region`, { page: number, box, engine });if (generation.current !== epoch || currentDocument.current !== documentId) return;setAlternative(undefined);setAlternativeJob(child.id) })}>{alternativeJob ? "선택 영역 처리 중…" : "선택 영역 재인식"}</button>
          </div>
          {alternative && <div className="mt-3 space-y-2 rounded-lg border p-3"><p className="text-sm">{alternative.engine} 대안</p><pre className="whitespace-pre-wrap break-words text-sm leading-7">{alternative.text}</pre><button className={button} disabled={!editable} onClick={() => apply(alternative.text)}>{page.lines.some(l => l.id === selectedLine && l.draftLineIndex != null) && (drafts[String(number)] ?? page.draft) === page.recognizedText ? "선택한 줄에 반영" : "초안 끝에 추가"}</button></div>}
        </section>
        <section aria-label="검수 초안" className="min-w-0 space-y-3">
          <h3 className="font-semibold">검수 초안</h3>
          <p className="text-sm leading-6 text-[#64748B]">원본의 글줄·띄어쓰기·시의 연을 확인하세요. {job?.ocrMode === "standard" ? "일반 인식 결과를 원본과 대조해 검수하세요." : "두 엔진의 결과는 대안입니다."} 확정 전에는 분석 원문으로 사용하지 않습니다.</p>
          <textarea aria-label="페이지 검수 텍스트" value={drafts[String(number)] ?? page.draft} disabled={!editable || busy} onChange={e => write(e.target.value)} onSelect={e => { const input = e.currentTarget;if (input.value !== page.recognizedText) return;const at = Array.from(input.value.slice(0, input.selectionStart)).length;const line = page.lineMap?.find(l => l.start != null && l.end != null && l.start <= at && at < l.end);if (line) { const source = page.lines.find(l => l.id === line.lineId);if (source) { setBox(source.box);setSelectedLine(source.id) } } }} rows={15} className="w-full resize-y rounded-lg border p-3 font-inherit text-base leading-8" />
          <button className={button} disabled={!editable || busy || !(undo[String(number)]?.length)} onClick={() => { const key = String(number),history = undo[key] ?? [];if (!history.length) return;setDrafts(d => ({ ...d, [key]: history[history.length - 1] }));setUndo(d => ({ ...d, [key]: history.slice(0, -1) }));setDirty(true);setConfirming(false);setNotice("직전 편집으로 되돌렸습니다. 확정 판본은 변경되지 않았습니다.") }}>직전 편집 되돌리기</button>
          {page.precision && <details className="rounded-lg border p-3 text-sm"><summary>자동 초안 변경 비교 · {page.precision.changedCharacters}자 차이</summary><p className="my-2 leading-6">이미지 영역과 국소 재인식을 확인한 변경입니다. 원문 확정 전 원본과 대조하세요. 근거가 부족한 대안은 적용하지 않았습니다.</p><div className="grid gap-3 sm:grid-cols-2"><div><h4>선택 전</h4><pre className="whitespace-pre-wrap break-words leading-7">{page.precision.before.text}</pre></div><div><h4>자동 초안</h4><pre className="whitespace-pre-wrap break-words leading-7">{page.recognizedText}</pre></div></div><button className={button} disabled={!editable || busy || (drafts[String(number)] ?? page.draft) === page.precision.before.text} onClick={() => write(page.precision!.before.text)}>선택 전 초안으로 되돌리기</button>{page.precision.decisions.filter(d => d.status === "APPLIED").map(d => <div className="mt-3 border-t pt-2" key={d.regionId}><p title={d.reason}>이미지·재인식 대조로 반영</p>{d.changes.map((c, i) => <div key={i}><button className="text-[#087F8C] underline" onClick={() => locate(c.lineId)}>원본 영역 확인</button><p className="whitespace-pre-wrap leading-7">변경 전: {c.before || "누락"}</p><p className="whitespace-pre-wrap leading-7">변경 후: {c.after}</p></div>)}</div>)}</details>}
          {page.literary && <details className="rounded-lg border p-3 text-sm" open><summary>좌표 기반 구조 검수 · {profileNames[page.literary.requestedProfile] || "장르 미지정"}</summary><p className="my-2 leading-6 text-[#64748B]">인식 당시 행과 상대 들여쓰기입니다. 화면 간격을 공백 문자로 바꾸지 않습니다. 연·문단 경계는 확인 후 직접 반영하세요.</p><div aria-label="좌표 기반 구조 미리보기" className="max-h-64 overflow-auto rounded bg-[#F8FAFC] p-3">{page.literary.physicalLines.map(item => <div key={item.lineId} style={{ paddingInlineStart: `${Math.min(.6, item.indentRatio) * 100}%` }} className="whitespace-pre-wrap break-words leading-8"><span>{page.lines.find(l => l.id === item.lineId)?.text}</span>{item.kind !== "PHYSICAL_LINE" && <small className="ml-2 text-[#64748B]">{item.kind === "SPEAKER_CANDIDATE" ? "화자 경계 후보" : "지문 후보"}</small>}</div>)}</div>{page.literary.boundaries.map(boundary => <div key={boundary.id} className="mt-3 flex flex-wrap items-center gap-2"><span>{boundary.beforeLineId} · {boundary.kind === "STANZA" ? "연" : boundary.kind === "PARAGRAPH" ? "문단" : "구조"} 경계 검토</span>{["STANZA", "PARAGRAPH"].includes(boundary.kind) && <button className={button} disabled={boundary.automaticallyApplied || !editable || busy || (drafts[String(number)] ?? page.draft) !== page.recognizedText} onClick={() => { const points = Array.from(page.recognizedText),pos = boundary.position;if (points[pos - 1] !== "\n" || points[pos - 2] === "\n") { setError("이미 반영됐거나 위치를 확인할 수 없는 경계입니다.");return }write(points.slice(0, pos).join("") + "\n" + points.slice(pos).join(""));setNotice("선택한 경계에만 빈 줄을 반영했습니다. 원본을 확인하고 저장하세요.") }}>{boundary.kind === "STANZA" ? "연" : "문단"} 경계 빈 줄 반영</button>}</div>)}</details>}
          {page.localRefinement && <details className="rounded-lg border p-3 text-sm"><summary>국소 재인식 대안 {page.localRefinement.candidates.length}곳 · 이미지 근거로 선별</summary>{page.localRefinement.candidates.map(candidate => <div key={candidate.id} className="mt-3 space-y-2 border-t pt-3"><button className="text-[#087F8C] underline" onClick={() => { setBox(candidate.box);setSelectedLine(candidate.lineIds.length === 1 ? candidate.lineIds[0] : null) }}>{candidate.lineIds.join(", ")} · {candidate.triggers.join(" / ")}</button>{candidate.alternatives.map((alt, i) => <div key={i}><p>{alt.engine} {alt.psm ? `PSM${alt.psm}` : ""}{alt.scale ? ` · ${alt.scale}배 크롭` : ""}</p><pre className="whitespace-pre-wrap break-words leading-7">{alt.text}</pre>{candidate.lineIds.length === 1 && <button className={button} disabled={!editable || busy || (drafts[String(number)] ?? page.draft) !== page.recognizedText || !page.lineMap?.some(m => m.lineId === candidate.lineIds[0] && m.start != null)} onClick={() => apply(alt.text, candidate.lineIds[0])}>이 줄 대안 선택</button>}</div>)}{candidate.lineIds.length !== 1 && <p>줄 분할·합침 대안은 원본과 대조해 위 초안을 직접 수정하세요.</p>}{candidate.unavailable && <p>이 영역 재인식 미완료 · 원래 인식을 보존했습니다.</p>}</div>)}</details>}
          <label className="flex items-center gap-2 text-sm">글줄 표시<select value={filter} onChange={e => setFilter(e.target.value)} className="rounded border p-2"><option value="all">전체</option><option value="difference">불일치</option><option value="missing">누락 후보</option></select></label>
          {!!page.literary?.lineWrapCandidates?.length && <details className="rounded-lg border p-3 text-sm" data-testid="ocr-print-wrap-review"><summary>인쇄 줄바꿈 연결 검토 · {page.literary.lineWrapCandidates.length}곳</summary><p className="my-2 leading-6 text-[#64748B]">같은 본문 영역에서 이어진 글줄입니다. 실제 문단이면 그대로 두세요. 원본을 확인한 뒤 연결 방법을 직접 선택할 수 있습니다. 본문이 바뀐 뒤에는 위치를 추측하지 않습니다.</p>{page.literary.lineWrapCandidates.map(wrap => <div key={wrap.id} className="mt-3 space-y-2 border-t pt-3"><button className="text-[#087F8C] underline" onClick={() => locate(wrap.fromLineId)}>원본 글줄 확인</button><pre className="whitespace-pre-wrap break-words leading-7">{wrap.leftText + "\n" + wrap.rightText}</pre><div className="flex flex-wrap gap-2">{[{ name: "공백으로 이어쓰기", value: " " }, { name: "붙여 이어쓰기", value: "" }].map(choice => <button key={choice.name} className={button} disabled={!editable || busy || !!alternativeJob || (drafts[String(number)] ?? page.draft) !== page.recognizedText} onClick={() => { try { const current = drafts[String(number)] ?? page.draft;write(replaceOcrSpan(current, page.recognizedText, wrap.start, wrap.end, wrap.expected, choice.value));setNotice("선택한 인쇄 줄바꿈만 연결했습니다. 원본과 대조한 뒤 저장하세요.") } catch (cause) { setError(errorMessage(cause)) } }}>{choice.name}</button>)}</div></div>)}</details>}
          <div className="max-h-64 space-y-2 overflow-auto">{page.lines.filter(l => filter === "all" || (filter === "missing" ? l.difference.includes("MISSING") : l.difference !== "AGREEMENT" && l.difference !== "NATIVE_PRESERVED")).map(line => <div key={line.id} className="rounded-lg border p-3 text-sm leading-6">
            <button disabled={!!alternativeJob} className="text-left text-[#087F8C] underline" onClick={() => { setBox(line.box);setSelectedLine(line.id);setAlternative(undefined) }}>{line.id} · {line.segmentationOnly ? "줄 분할 대안" : differences[line.difference] || line.difference}{line.alignment && line.alignment.kind !== "1:1" ? ` · ${line.alignment.kind} 대응 검토` : ""}{line.stanzaGapCandidateBefore ? " · 연/문단 경계 후보" : ""}</button>
            <p className="whitespace-pre-wrap">{line.text}</p>
            {line.includedInDraft === false && !line.segmentationOnly && line.difference !== "FORMULA_REGION_SEPARATE" && <button className={button} disabled={!editable} onClick={() => write((drafts[String(number)] ?? page.draft) + "\n" + line.text)}>누락 후보를 초안 끝에 추가</button>}
            {line.secondary && line.secondary.text !== line.text && <><p className="mt-1 whitespace-pre-wrap text-[#64748B]">Tesseract: {line.secondary.text}</p><button className={button} disabled={!editable || (!!line.alignment && line.alignment.kind !== "1:1")} onClick={() => { const current = drafts[String(number)] ?? page.draft;const parts = current.split("\n"),i = line.draftLineIndex ?? -1;if (i < 0 || current !== page.recognizedText || parts[i] !== line.text.normalize("NFC")) { setError("이미 수정한 페이지입니다. 위치를 추측하지 않으므로 원본과 대안을 보고 직접 수정해 주세요.");return }parts[i] = line.secondary!.text;write(parts.join("\n")) }}>이 대안 선택</button></>}
          </div>)}</div>
          <p className="text-xs leading-5 text-[#64748B]">구조 영역 {page.structure.blocks.length}개 · 표 {page.structure.tables.length}개. 그림·수식과 불명확한 표 셀은 원본에서 확인하세요.</p>
          {page.structure.tables.map((table, i) => table.cells?.length ? <details key={i} className="rounded-lg border p-3 text-sm"><summary>표 {i + 1} 셀 인식 대안</summary><p className="my-2 text-xs text-[#64748B]">원본과 비교하고, 수정할 내용과 읽기 순서는 위 검수 초안에 반영하세요.</p><div className="max-w-full overflow-x-auto"><table className="w-full border-collapse"><tbody>{[...new Set(table.cells.map(c => c.row))].sort((a, b) => a - b).map(row => <tr key={row}>{table.cells!.filter(c => c.row === row).sort((a, b) => a.column - b.column).map((cell, j) => <td key={j} rowSpan={cell.rowSpan} colSpan={tableColumnSpan(cell)} className="border p-2 whitespace-pre-wrap">{cell.text}</td>)}</tr>)}</tbody></table></div></details> : null)}
          {page.unavailable.length > 0 && <p className="text-sm text-[#C62828]">실행되지 않은 구성: {page.unavailable.join(", ")}</p>}
        </section>
      </div>
      <footer className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t pt-4">
        <button className={button} disabled={!editable || busy || !dirty} onClick={() => void request(save)}>임시 저장</button>
        <button className={`${button} bg-[#087F8C] text-white`} disabled={!editable || busy || dirty || !!alternativeJob} onClick={() => setConfirming(true)}>원문 확정</button>
        {job?.status === "CONFIRMED" && accessMode === "DOWNLOAD" && <><a className={button} href={`/api/ocr-jobs/${job.id}/export/txt`} download>TXT 다운로드</a><a className={button} href={`/api/ocr-jobs/${job.id}/export/json`} download>구조 JSON 다운로드</a></>}
      </footer>
      {confirming && <div className="mt-3 flex flex-wrap items-center justify-end gap-3 rounded-lg bg-[#F8FAFC] p-3"><p className="text-sm">검수한 내용을 새 불변 판본으로 저장할까요?</p><button className={button} onClick={() => setConfirming(false)}>돌아가기</button><button className={button} disabled={busy} onClick={() => void request(async () => { const epoch = generation.current;await api.post(`/ocr-jobs/${job!.id}/confirm`, { expectedDraftVersion: draftBaseVersion, expectedRevisionId: job!.inputRevisionId });if (generation.current !== epoch || currentDocument.current !== documentId) return;setConfirming(false);setNotice("원문 판본을 확정했습니다.");await load();if (generation.current === epoch && currentDocument.current === documentId) onSaved() })}>확정 저장</button></div>}
    </>}
  </dialog>
}
