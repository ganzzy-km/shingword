import { useEffect, useMemo, useRef, useState } from "react"
import { api, errorMessage } from "./api"
import type { Span } from "./book-layout"
import "./dual-structure.css"

export type StructureView = "s4" | "ai" | "comparison"
export type Role = "CLAIM" | "EVIDENCE"
export type RoleSpan = Span & { role: Role }
type Basis = "EXPLICIT" | "IMPLICIT" | "UNCERTAIN"
type Node = { id: string; role: Role; basis: Basis; spans: (Span & { sentenceId: string })[] }
type Relation = { sourceId: string; targetId: string; type: "SUPPORTS" | "QUALIFIES"; basis: Basis }
type Result = { nodes: Node[]; relations: Relation[] }
type Run = { id: string; model: string; status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "REVIEW_REQUIRED"; result: Result | null; errorCode: string | null; settings: { manualExclusions: string[]; automaticExclusions: string[] } }
type Quotation = Span & { quote_id: string; status: string; depth: number; delimiter_type: string }
type Comparison = {
  nodes: { status: string; s4: string[]; ai: string[]; start: number }[]
  relations: { status: string; s4: Relation | null; ai: Relation | null }[]
}
type RecordData = {
  versionId: string; versionStatus: "CURRENT" | "STALE"; sourceText: string; bodyHash: string
  quotations: Quotation[]; available: boolean; consented: boolean; revocable: boolean; policyVersion: string | null
  ai: Run | null; s4: Result | null; comparison: Comparison | null
  history: { id: string; model: string; status: Run["status"]; createdAt: string }[]
}
type Preview = {
  sentences: { id: string; text: string }[]; omittedSentenceIds: string[]; previewHash: string
  policyVersion: string; provider: string; model: string
}

const views = [["s4", "S4 분석"], ["ai", "AI 구조 분석"], ["comparison", "분석 비교"]] as const
const roles = { CLAIM: "주장 후보", EVIDENCE: "근거 후보" }
const bases = { EXPLICIT: "명시적", IMPLICIT: "암시적", UNCERTAIN: "불확실" }
const relationTypes = { SUPPORTS: "뒷받침", QUALIFIES: "범위·조건 한정" }
const differences: Record<string, string> = {
  SAME_SPAN_ROLE: "같은 구간과 역할", SAME_ROLE_DIFFERENT_SPAN: "같은 역할 · 구간 차이",
  SAME_SPAN_DIFFERENT_ROLE: "같은 구간 · 역할 차이", S4_ONLY: "S4에서만 탐지", AI_ONLY: "AI에서만 탐지",
}
const errors: Record<string, string> = {
  AI_INTERRUPTED_OR_TIMEOUT: "실행이 중단되었거나 시간이 초과되었습니다.", AI_TIMEOUT: "외부 응답 시간이 초과되었습니다.",
  AI_PROVIDER_REFUSED: "제공업체가 요청 처리를 거부했습니다.", AI_CONSENT_REQUIRED: "외부 전송 동의가 철회되었습니다.",
  STRUCTURE_STALE: "실행 중 글이 바뀌었습니다. 현재 판본을 다시 선택해 주세요.",
  AI_PROTECTED_SOURCE: "보호 자료와 연결되어 실행을 중단했습니다.",
}
const pending = (run: Run | null | undefined) => run?.status === "QUEUED" || run?.status === "RUNNING"
const versionPath = (id: string) => `/writing-versions/${encodeURIComponent(id)}/structure`

export function useDualStructure(versionId: string | undefined, s4Id: string | undefined) {
  const key = `${versionId ?? ""}/${s4Id ?? ""}`
  const [loaded, setLoaded] = useState<{ key: string; record: RecordData } | null>(null)
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const [revision, setRevision] = useState(0)
  const [chosen, setChosen] = useState<{ key: string; id: string } | null>(null)
  const selectedRun = chosen?.key === key ? chosen.id : undefined
  const record = loaded?.key === key ? loaded.record : null
  const error = failure?.key === key ? failure.message : ""
  const runId = record?.ai?.id
  const isPending = pending(record?.ai)
  useEffect(() => {
    if (!versionId) return
    let active = true
    const params = new URLSearchParams()
    if (s4Id) params.set("analysisId", s4Id)
    if (selectedRun) params.set("runId", selectedRun)
    const path = versionPath(versionId) + (params.size ? `?${params}` : "")
    api.get<RecordData>(path).then(result => {
      if (!active) return
      setLoaded({ key, record: result })
      setFailure(null)
    }).catch(cause => { if (active) setFailure({ key, message: errorMessage(cause) }) })
    return () => { active = false }
  }, [versionId, s4Id, key, revision, selectedRun])
  useEffect(() => {
    if (!versionId || !runId || !isPending) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const run = await api.get<Run>(`${versionPath(versionId)}/ai/${encodeURIComponent(runId)}`)
        if (!active) return
        if (pending(run)) {
          setLoaded(current => current?.key === key ? { key, record: { ...current.record, ai: run } } : current)
          timer = setTimeout(poll, 800)
        } else {
          setLoaded(current => current?.key === key ? { key, record: { ...current.record, ai: run } } : current)
          setRevision(value => value + 1)
        }
      } catch (cause) {
        if (active) setFailure({ key, message: errorMessage(cause) })
      }
    }
    timer = setTimeout(poll, 500)
    return () => { active = false; clearTimeout(timer) }
  }, [versionId, runId, isPending, key, revision])
  return { record, error, refresh: (id?: string) => {
    if (id) setChosen({ key, id })
    setRevision(value => value + 1)
  } }
}

function Candidate({ node, points, jump }: { node: Node; points: string[]; jump?: (span: Span) => void }) {
  return <div className="dual-candidate">
    <span className={`dual-role dual-role-${node.role.toLowerCase()}`}>{roles[node.role]}</span>
    <small>{bases[node.basis]}</small>
    {node.spans.map(span => {
      const text = points.slice(span.start, span.end).join("")
      return jump ? <button key={span.sentenceId} type="button" onClick={() => jump(span)}>{text}</button>
        : <span key={span.sentenceId} className="dual-excerpt">{text}</span>
    })}
  </div>
}

function Edges({ relations, nodes, points, jump }: { relations: Relation[]; nodes: Map<string, Node>; points: string[]; jump?: (span: Span) => void }) {
  return relations.map((edge, index) => {
    const source = nodes.get(edge.sourceId), target = nodes.get(edge.targetId)
    return source && target && <div className="dual-edge" key={`${edge.sourceId}-${edge.targetId}-${edge.type}-${index}`}>
      <Candidate node={source} points={points} jump={jump} />
      <span>↓ {relationTypes[edge.type]} · {bases[edge.basis]}</span>
      <Candidate node={target} points={points} jump={jump} />
    </div>
  })
}

export default function DualStructurePanel({ mode, setMode, record, loadError, refresh, quoteEnabled, setQuoteEnabled,
  body, prepareVersion, jump }: {
  mode: StructureView; setMode: (mode: StructureView) => void; record: RecordData | null; loadError: string; refresh: (runId?: string) => void
  quoteEnabled: boolean; setQuoteEnabled: (value: boolean) => void; body: string
  prepareVersion: () => Promise<void>; jump: (span: Span) => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [excluded, setExcluded] = useState<string[]>([])
  const [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const dialog = useRef<HTMLDialogElement>(null)
  const current = useRef({ versionId: record?.versionId, body })
  current.current = { versionId: record?.versionId, body }
  const previewVersion = useRef<string | null>(null)
  const run = record?.ai
  const isPending = pending(run)
  const stale = !!record && (record.versionStatus === "STALE" || record.sourceText !== body)
  const points = useMemo(() => Array.from(record?.sourceText ?? ""), [record?.sourceText])
  const aiNodes = useMemo(() => new Map(run?.result?.nodes.map(node => [node.id, node])), [run?.result])
  const s4Nodes = useMemo(() => new Map(record?.s4?.nodes.map(node => [node.id, node])), [record?.s4])
  const jumpCurrent = record?.sourceText === body ? jump : undefined
  const closed = record?.quotations.filter(quote => quote.status === "CLOSED") ?? []
  const unresolved = record?.quotations.filter(quote => quote.status !== "CLOSED") ?? []
  const kept = preview?.sentences.filter(sentence => !excluded.includes(sentence.id)) ?? []
  const omitted = run ? new Set([...run.settings.manualExclusions, ...run.settings.automaticExclusions]).size : 0

  useEffect(() => {
    if (preview && !dialog.current?.open) dialog.current?.showModal()
  }, [preview])
  useEffect(() => {
    dialog.current?.close()
    setPreview(null)
    setMessage("")
  }, [record?.versionId, body])

  const showPreview = async () => {
    if (!record || busy || stale) return
    setBusy(true); setMessage(""); setExcluded([]); setReviewed(false)
    const version = record.versionId
    try {
      const next = await api.post<Preview>(`${versionPath(version)}/preview`, { excludeSentenceIds: [] })
      if (current.current.versionId === version && current.current.body === body) {
        previewVersion.current = version
        setPreview(next)
      }
    } catch (cause) { setMessage(errorMessage(cause)) }
    finally { setBusy(false) }
  }
  const start = async () => {
    if (!record || !preview || !reviewed || busy || stale || previewVersion.current !== record.versionId) return
    setBusy(true); setMessage("")
    const version = record.versionId
    try {
      const confirmed = excluded.length ? await api.post<Preview>(`${versionPath(version)}/preview`, { excludeSentenceIds: excluded }) : preview
      if (current.current.versionId !== version || current.current.body !== body) return
      if (confirmed.policyVersion !== preview.policyVersion || confirmed.model !== preview.model || JSON.stringify(confirmed.sentences) !== JSON.stringify(kept)) {
        setPreview(confirmed); setExcluded([]); setReviewed(false)
        return
      }
      if (!record.consented) await api.post("/structure/consent", { granted: true, policyVersion: preview.policyVersion })
      if (current.current.versionId !== version || current.current.body !== body) return
      const started = await api.post<Run>(`${versionPath(version)}/ai`, { excludeSentenceIds: excluded, reviewed: true, previewHash: confirmed.previewHash })
      dialog.current?.close()
      refresh(started.id)
    } catch (cause) { setMessage(errorMessage(cause)); refresh() }
    finally { setBusy(false) }
  }
  const revoke = async () => {
    setBusy(true); setMessage("")
    try { await api.post("/structure/consent", { granted: false, policyVersion: record?.policyVersion ?? null }); refresh() }
    catch (cause) { setMessage(errorMessage(cause)) }
    finally { setBusy(false) }
  }

  return <section className="dual-structure" aria-label="구조 분석 보기">
    <div className="dual-views" role="group" aria-label="분석 보기 선택">
      {views.map(([id, label]) => <button key={id} type="button" aria-pressed={mode === id} onClick={() => setMode(id)}>{label}</button>)}
    </div>
    {isPending && <p role="status">{run?.status === "QUEUED" ? "AI 분석 대기 중" : "AI가 구조를 분석하고 있습니다."}</p>}
    {record && (closed.length > 0 || unresolved.length > 0) && <div className="dual-quote-controls">
      {closed.length > 0 && <label><input type="checkbox" checked={quoteEnabled} onChange={event => setQuoteEnabled(event.target.checked)} /> 인용문 강조</label>}
      {unresolved.length > 0 && <details><summary>닫힘 확인이 필요한 따옴표 {unresolved.length}곳</summary>
        <ul>{unresolved.slice(0, 24).map(quote => <li key={quote.quote_id}>
          {jumpCurrent ? <button type="button" onClick={() => jumpCurrent(quote)}>따옴표 {quote.start + 1}번째 문자</button> : `따옴표 ${quote.start + 1}번째 문자`}
        </li>)}</ul>
      </details>}
    </div>}
    {mode !== "s4" && <>
      {loadError && <p role="alert">{loadError} <button type="button" onClick={() => refresh()}>다시 불러오기</button></p>}
      {message && !preview && <p role="alert">{message}</p>}
      {stale && <p role="status">이전 판본의 구조 결과입니다.</p>}
      {record && record.history.length > 1 && run && <label>AI 분석 기록 <select value={run.id} onChange={event => refresh(event.target.value)}>
        {record.history.map(item => <option key={item.id} value={item.id}>{new Date(item.createdAt).toLocaleString("ko-KR")} · {item.model}</option>)}
      </select></label>}
      {omitted > 0 && <p>외부 전송에서 문장 {omitted}개를 제외했습니다.</p>}
      {mode === "ai" && <>
        {!record && !loadError && <button type="button" className="gb-outline" disabled={!body.trim() || busy} onClick={async () => {
          setBusy(true); setMessage(""); try { await prepareVersion() } catch (cause) { setMessage(errorMessage(cause)) } finally { setBusy(false) }
        }}>저장 판본 준비</button>}
        {stale && <button type="button" className="gb-outline" disabled={busy || !body.trim()} onClick={async () => {
          setBusy(true); setMessage(""); try { await prepareVersion() } catch (cause) { setMessage(errorMessage(cause)) } finally { setBusy(false) }
        }}>현재 글 저장 후 판본 선택</button>}
        {record && !stale && !record.available && !run?.result && <p>외부 AI 구조 분석이 준비되지 않았습니다.</p>}
        {record?.available && !stale && !isPending && <button type="button" className="gb-outline" disabled={busy} onClick={showPreview}>
          {run?.result ? "전송 문장 바꿔 다시 분석" : run ? "AI 구조 분석 다시 실행" : "AI 구조 분석 실행"}
        </button>}
        {record?.revocable && <button type="button" className="gb-outline dual-revoke" disabled={busy} onClick={revoke}>외부 전송 동의 철회</button>}
        {run && (run.status === "FAILED" || run.status === "REVIEW_REQUIRED") && <p role="status">
          {(run.errorCode && errors[run.errorCode]) || (run.status === "REVIEW_REQUIRED" ? "응답의 원문 근거를 확인할 수 없어 결과를 보류했습니다." : "AI 구조 분석을 완료하지 못했습니다.")}
        </p>}
        {run?.result && <>
          <p>{run.model} · {run.result.nodes.length}개 후보</p>
          {!run.result.nodes.length && <p>탐지된 주장·근거 후보가 없습니다.</p>}
          {run.result.nodes.map(node => <Candidate key={node.id} node={node} points={points} jump={jumpCurrent} />)}
          {run.result.relations.length > 0 && <h3>근거에서 주장으로</h3>}
          <Edges relations={run.result.relations} nodes={aiNodes} points={points} jump={jumpCurrent} />
        </>}
      </>}
      {mode === "comparison" && <>
        {record?.comparison ? <>
          {!record.comparison.nodes.length && <p>두 분석에서 탐지된 후보가 없습니다.</p>}
          {record.comparison.nodes.map((row, i) => <article className="dual-difference" key={`${row.start}-${i}`}>
            <h3>{differences[row.status]}</h3>
            <div className="dual-columns">
              {([["S4", row.s4, s4Nodes], ["AI", row.ai, aiNodes]] as const).map(([label, ids, nodes]) => <div key={label}>
                <strong>{label}</strong>
                {ids.length === 0 ? <span className="dual-excerpt">탐지 없음</span> : ids.map(id => {
                  const node = nodes.get(id)
                  return node && <Candidate key={id} node={node} points={points} jump={jumpCurrent} />
                })}
              </div>)}
            </div>
          </article>)}
          {record.comparison.relations.length > 0 && <h3>관계 불일치</h3>}
          {record.comparison.relations.map((item, index) => <div className="dual-difference dual-columns" key={index}>
            {([["S4", item.s4, s4Nodes], ["AI", item.ai, aiNodes]] as const).map(([label, edge, nodes]) => <div key={label}>
              <strong>{label}</strong>
              {edge ? <Edges relations={[edge]} nodes={nodes} points={points} jump={jumpCurrent} /> : <span className="dual-excerpt">대응 관계 없음</span>}
            </div>)}
          </div>)}
          {!record.comparison.relations.length && <p>관계 불일치가 없습니다.</p>}
        </> : !isPending && <p>같은 판본의 S4 분석과 AI 구조 분석이 완료되면 비교할 수 있습니다.</p>}
      </>}
    </>}
    <dialog ref={dialog} className="dual-consent" aria-labelledby="dual-consent-title" onCancel={event => { if (busy) event.preventDefault() }} onClose={() => setPreview(null)}>
      {preview && <>
        <h2 id="dual-consent-title">AI 전송 문장 확인</h2>
        <p>{preview.provider}의 {preview.model}에 아래 선택 문장을 전송합니다. 요청에 비용이 발생할 수 있습니다.</p>
        <p>개인 식별 정보나 보호 원문이 남아 있는 문장은 선택을 해제해 주세요.</p>
        {preview.omittedSentenceIds.length > 0 && <p>식별 정보가 감지된 {preview.omittedSentenceIds.length}개 문장을 자동 제외했습니다.</p>}
        <div className="dual-preview-list" role="group" aria-label="전송할 문장">
          {preview.sentences.map(sentence => <label key={sentence.id}>
            <input type="checkbox" checked={!excluded.includes(sentence.id)} disabled={busy} onChange={event => {
              const include = event.target.checked
              setExcluded(old => include ? old.filter(id => id !== sentence.id) : [...old, sentence.id]); setReviewed(false)
            }} />
            <span>{sentence.text}</span>
          </label>)}
        </div>
        <label className="dual-confirm"><input type="checkbox" checked={reviewed} disabled={busy} onChange={event => setReviewed(event.target.checked)} /> 선택한 문장과 비용 안내를 확인했으며 외부 전송에 동의합니다.</label>
        {message && <p role="alert">{message}</p>}
        <div className="dual-dialog-actions">
          <button type="button" className="gb-outline" disabled={busy} onClick={() => dialog.current?.close()}>닫기</button>
          <button type="button" className="gb-primary" disabled={!reviewed || !kept.length || busy} onClick={start}>{busy ? "요청 중…" : "동의하고 분석 실행"}</button>
        </div>
      </>}
    </dialog>
  </section>
}
