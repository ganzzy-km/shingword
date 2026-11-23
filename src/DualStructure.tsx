import { useEffect, useId, useMemo, useRef, useState } from "react"
import { api, errorMessage } from "./api"
import type { Span } from "./book-layout"
import "./dual-structure.css"

export type StructureView = "s4" | "ai"
export type Role = "CLAIM" | "EVIDENCE"
export type RoleSpan = Span & { role: Role }
type Basis = "EXPLICIT" | "IMPLICIT" | "UNCERTAIN"
type Node = { id: string; role: Role; basis: Basis; spans: (Span & { paragraphId?: string })[] }
type Relation = { sourceId: string; targetId: string; type: "SUPPORTS" | "QUALIFIES"; basis: Basis }
type Result = { nodes: Node[]; relations: Relation[] }
type Paragraph = Span & { id: string }
type ParagraphCounts = { paragraphId: string; claimCount: number; evidenceCount: number; quotationCount: number }
type AiQuotation = Span & { paragraphId: string; quoteId: string }
type AiResult = Result & { paragraphs?: ParagraphCounts[]; quotations?: AiQuotation[] }
type Run = { id: string; model: string; inputUnit?: "paragraph" | "sentence"; status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "REVIEW_REQUIRED"; result: AiResult | null; errorCode: string | null; settings: { manualExclusions: string[]; automaticExclusions: string[] } }
type Quotation = Span & { quote_id: string; status: string; depth: number; delimiter_type: string }
type Comparison = {
  nodes: { status: string; s4: string[]; ai: string[]; start: number }[]
  relations: { status: string; s4: Relation | null; ai: Relation | null }[]
}
type RecordData = {
  versionId: string; versionStatus: "CURRENT" | "STALE"; sourceText: string; bodyHash: string
  paragraphs: Paragraph[]; quotations: Quotation[]; available: boolean; consented: boolean; revocable: boolean; policyVersion: string | null
  ai: Run | null; s4: Result | null; comparison: Comparison | null
  history: { id: string; model: string; status: Run["status"]; createdAt: string }[]
}
type Preview = {
  paragraphs: { id: string; text: string }[]; omittedParagraphIds: string[]; previewHash: string
  policyVersion: string; provider: string; model: string
  policyNotice?: string | null
}

const roles = { CLAIM: "주장 후보", EVIDENCE: "근거 후보" }
const bases = { EXPLICIT: "명시적", IMPLICIT: "암시적", UNCERTAIN: "불확실" }
const relationTypes = { SUPPORTS: "뒷받침", QUALIFIES: "범위·조건 한정" }
const differences: Record<string, string> = {
  SAME_SPAN_ROLE: "같은 구간과 역할", SAME_ROLE_DIFFERENT_SPAN: "같은 역할 · 구간 차이",
  SAME_SPAN_DIFFERENT_ROLE: "같은 구간 · 역할 차이", S4_ONLY: "글빛에서만 탐지", AI_ONLY: "AI에서만 탐지",
}
const errors: Record<string, string> = {
  AI_INTERRUPTED_OR_TIMEOUT: "실행이 중단되었거나 시간이 초과되었습니다.", AI_TIMEOUT: "외부 응답 시간이 초과되었습니다.",
  AI_PROVIDER_REFUSED: "제공업체가 요청 처리를 거부했습니다.", AI_CONSENT_REQUIRED: "외부 전송 동의가 철회되었습니다.",
  STRUCTURE_STALE: "실행 중 글이 바뀌었습니다. 현재 판본을 다시 선택해 주세요.",
  AI_PROTECTED_SOURCE: "보호 자료와 연결되어 실행을 중단했습니다.",
  AI_PARAGRAPH_INVALID: "전송한 문단에서 응답의 구절을 확인할 수 없어 결과를 보류했습니다.",
  AI_QUOTATION_INVALID: "응답의 인용문을 본문에서 확인할 수 없어 결과를 보류했습니다.",
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
      const key = `${span.start}-${span.end}`
      return jump ? <button key={key} type="button" onClick={() => jump(span)}>{text}</button>
        : <span key={key} className="dual-excerpt">{text}</span>
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

function ResultOverview({ result, points, quotationCount }: { result: Result; points: string[]; quotationCount?: number }) {
  const claims = result.nodes.filter(node => node.role === "CLAIM")
  const evidence = result.nodes.filter(node => node.role === "EVIDENCE")
  return <>
    <dl className="dual-counts">
      <div><dt>주장 후보</dt><dd>{claims.length}</dd></div>
      <div><dt>근거 후보</dt><dd>{evidence.length}</dd></div>
      {quotationCount !== undefined && <div><dt>인용문</dt><dd>{quotationCount}</dd></div>}
      <div><dt>연결 관계</dt><dd>{result.relations.length}</dd></div>
    </dl>
    {result.nodes.length > 0 ? <div className="dual-samples">
      {[claims[0], evidence[0]].map(node => node && (
        <Candidate key={node.id} node={{ ...node, spans: node.spans.slice(0, 1) }} points={points} />
      ))}
    </div> : <p>탐지된 주장·근거 후보가 없습니다.</p>}
  </>
}

const paragraphLabel = (id: string) => `${id.slice(1)}문단`

function s4ParagraphCounts(paragraph: Paragraph, s4: Result, quotations: Quotation[]): ParagraphCounts {
  const nodes = s4.nodes.filter(node => node.spans.some(span => span.start < paragraph.end && span.end > paragraph.start))
  return {
    paragraphId: paragraph.id,
    claimCount: nodes.filter(node => node.role === "CLAIM").length,
    evidenceCount: nodes.filter(node => node.role === "EVIDENCE").length,
    quotationCount: quotations.filter(quote => quote.start >= paragraph.start && quote.end <= paragraph.end).length,
  }
}

function ParagraphSummary({ count }: { count: ParagraphCounts }) {
  return <span className="dual-paragraph-counts">
    <span>인용 {count.quotationCount}</span><span>주장 {count.claimCount}</span><span>근거 {count.evidenceCount}</span>
  </span>
}

function AiParagraphDetails({ result, points, jump }: { result: AiResult; points: string[]; jump?: (span: Span) => void }) {
  return result.paragraphs?.map(count => (
    <section key={count.paragraphId} className="dual-paragraph-result">
      <h4>{paragraphLabel(count.paragraphId)}</h4>
      <ParagraphSummary count={count} />
      {result.quotations?.filter(quote => quote.paragraphId === count.paragraphId).map(quote => {
        const text = points.slice(quote.start, quote.end).join("")
        return <div className="dual-candidate" key={quote.quoteId}>
          <span className="dual-role">본문 인용문</span>
          {jump ? <button type="button" onClick={() => jump(quote)}>{text}</button> : <span className="dual-excerpt">{text}</span>}
        </div>
      })}
      {result.nodes.filter(node => node.spans[0]?.paragraphId === count.paragraphId)
        .map(node => <Candidate key={node.id} node={node} points={points} jump={jump} />)}
    </section>
  ))
}

function ParagraphComparison({ record, ai, quotations }: { record: RecordData; ai: ParagraphCounts[]; quotations: Quotation[] }) {
  const aiByParagraph = new Map(ai.map(count => [count.paragraphId, count]))
  const s4 = record.s4
  if (!s4) return null
  return <>
    <h3>문단별 인용·주장·근거</h3>
    <table className="dual-paragraph-table">
      <thead><tr><th scope="col">문단</th><th scope="col">글빛</th><th scope="col">AI</th></tr></thead>
      <tbody>{record.paragraphs.map(paragraph => {
        const count = aiByParagraph.get(paragraph.id)
        return <tr key={paragraph.id}>
          <th scope="row">{paragraphLabel(paragraph.id)}</th>
          <td><ParagraphSummary count={s4ParagraphCounts(paragraph, s4, quotations)} /></td>
          <td>{count ? <ParagraphSummary count={count} /> : "전송 제외"}</td>
        </tr>
      })}</tbody>
    </table>
  </>
}

export default function DualStructurePanel({ mode, setMode, record, loadError, refresh, quoteEnabled, setQuoteEnabled,
  body, prepareVersion, jump, analyzing, analysisId, hasVersion, onShowFeedback }: {
  mode: StructureView; setMode: (mode: StructureView) => void; record: RecordData | null; loadError: string; refresh: (runId?: string) => void
  quoteEnabled: boolean; setQuoteEnabled: (value: boolean) => void; body: string
  prepareVersion: () => Promise<void>; jump: (span: Span) => void
  analyzing: boolean; analysisId?: string; hasVersion: boolean; onShowFeedback: () => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [excluded, setExcluded] = useState<string[]>([])
  const [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const [openComparison, setOpenComparison] = useState<string | null>(null)
  const comparisonId = useId()
  const comparisonHeading = useRef<HTMLHeadingElement>(null)
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
  const kept = preview?.paragraphs.filter(paragraph => !excluded.includes(paragraph.id)) ?? []
  const omitted = run ? new Set([...run.settings.manualExclusions, ...run.settings.automaticExclusions]).size : 0
  const comparison = record?.comparison
  const comparisonKey = `${record?.versionId}/${analysisId}/${run?.id}`
  const canCompare = !!comparison && !analyzing
  const comparisonOpen = canCompare && openComparison === comparisonKey
  const loading = hasVersion && !record && !loadError
  const hasOverview = hasVersion || !!analysisId || analyzing

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
      const next = await api.post<Preview>(`${versionPath(version)}/preview`, { excludeParagraphIds: [] })
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
      const confirmed = excluded.length ? await api.post<Preview>(`${versionPath(version)}/preview`, { excludeParagraphIds: excluded }) : preview
      if (current.current.versionId !== version || current.current.body !== body) return
      if (confirmed.policyVersion !== preview.policyVersion || confirmed.policyNotice !== preview.policyNotice
        || confirmed.model !== preview.model || JSON.stringify(confirmed.paragraphs) !== JSON.stringify(kept)) {
        setPreview(confirmed); setExcluded([]); setReviewed(false)
        return
      }
      if (!record.consented) await api.post("/structure/consent", { granted: true, policyVersion: preview.policyVersion })
      if (current.current.versionId !== version || current.current.body !== body) return
      const started = await api.post<Run>(`${versionPath(version)}/ai`, { excludeParagraphIds: excluded, reviewed: true, previewHash: confirmed.previewHash })
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
  const prepare = async () => {
    setBusy(true); setMessage("")
    try { await prepareVersion() }
    catch (cause) { setMessage(errorMessage(cause)) }
    finally { setBusy(false) }
  }

  return <section className={hasOverview ? "dual-structure" : "dual-structure dual-structure-compact"} aria-label="구조 분석 보기">
    {loadError && <p role="alert">{loadError} <button type="button" className="gb-outline" onClick={() => refresh()}>다시 불러오기</button></p>}
    {message && !preview && <p role="alert">{message}</p>}
    {stale && <p role="status">이전 판본의 구조 결과입니다.</p>}
    {hasOverview ? <>
      <div className="dual-overviews">
        <section className="dual-overview dual-overview-s4" aria-label="글빛 분석" aria-busy={analyzing || loading}>
          <h2>글빛 분석</h2>
          {analyzing ? <p role="status">글빛 분석 중…</p>
            : record?.s4 ? <ResultOverview result={record.s4} points={points} quotationCount={closed.length} />
            : loading ? <p role="status">글빛 결과를 불러오는 중…</p>
            : analysisId ? <p>분석 피드백에서 저장된 결과를 확인할 수 있습니다.</p>
            : <p>분석하기를 누르면 결과가 표시됩니다.</p>}
          {analysisId && !analyzing && <button type="button" className="gb-outline dual-card-action" onClick={onShowFeedback}>글빛 피드백 보기</button>}
        </section>
        <section className="dual-overview dual-overview-ai" aria-label="AI 구조 분석" aria-busy={loading || isPending}>
          <h2>AI 구조 분석</h2>
          {loading && <p role="status">AI 결과를 불러오는 중…</p>}
          {isPending && <p role="status">{run?.status === "QUEUED" ? "AI 분석 대기 중" : "AI가 구조를 분석하고 있습니다."}</p>}
          {record && !stale && !record.available && !run?.result && !isPending && <p>외부 AI 구조 분석이 준비되지 않았습니다.</p>}
          {analyzing && !record && !loading && <p>글이 저장되면 AI 분석을 시작할 수 있습니다.</p>}
          {record?.available && !stale && !run && <p>전송할 문단을 확인한 뒤 인용문과 주장·근거 후보를 분석합니다.</p>}
          {run && (run.status === "FAILED" || run.status === "REVIEW_REQUIRED") && <p role="status">
            {(run.errorCode && errors[run.errorCode]) || (run.status === "REVIEW_REQUIRED" ? "응답의 원문 근거를 확인할 수 없어 결과를 보류했습니다." : "AI 구조 분석을 완료하지 못했습니다.")}
          </p>}
          {run?.result && <ResultOverview result={run.result} points={points} quotationCount={run.result.quotations?.length} />}
          {run?.result && !run.result.paragraphs && <p>이전 문장별 분석 기록입니다. 다시 실행하면 문단별 결과를 볼 수 있습니다.</p>}
          {record && record.history.length > 1 && run && <label className="dual-history">AI 분석 기록 <select value={run.id} onChange={event => refresh(event.target.value)}>
            {record.history.map(item => <option key={item.id} value={item.id}>{new Date(item.createdAt).toLocaleString("ko-KR")} · {item.model}</option>)}
          </select></label>}
          {omitted > 0 && <p>외부 전송에서 {run?.inputUnit === "paragraph" ? "문단" : "문장"} {omitted}개를 제외했습니다.</p>}
          {run?.result && <details className="dual-result-details">
            <summary>{run.result.paragraphs ? "문단별 인용·주장·근거 보기" : "AI 후보·관계 전체 보기"}</summary>
            <p>{run.model} · {run.result.nodes.length}개 후보</p>
            {run.result.paragraphs
              ? <AiParagraphDetails result={run.result} points={points} jump={jumpCurrent} />
              : run.result.nodes.map(node => <Candidate key={node.id} node={node} points={points} jump={jumpCurrent} />)}
            {run.result.relations.length > 0 && <h4>근거에서 주장으로</h4>}
            <Edges relations={run.result.relations} nodes={aiNodes} points={points} jump={jumpCurrent} />
          </details>}
          <div className="dual-card-actions">
            {stale && <button type="button" className="gb-outline" disabled={busy || analyzing || !body.trim()} onClick={prepare}>현재 글 저장 후 판본 선택</button>}
            {record?.available && !stale && !isPending && <button type="button" className={run?.result ? "gb-outline" : "gb-primary"} disabled={busy || analyzing} onClick={showPreview}>
              {run?.result ? "문단별로 다시 분석" : run ? "AI 구조 분석 다시 실행" : "AI 구조 분석 실행"}
            </button>}
            {run?.result && jumpCurrent && <button type="button" className="gb-outline" aria-pressed={mode === "ai"} onClick={() => setMode(mode === "ai" ? "s4" : "ai")}>AI 후보 본문 강조</button>}
          </div>
          {record?.revocable && <button type="button" className="dual-revoke" disabled={busy} onClick={revoke}>외부 전송 동의 철회</button>}
        </section>
      </div>
      <div className="dual-compare-action">
        <p id={`${comparisonId}-hint`}>{canCompare ? "같은 판본에서 구간, 역할, 연결 관계를 나란히 확인하세요." : "같은 판본의 두 분석이 완료되면 대조할 수 있습니다."}</p>
        <button type="button" className="gb-primary dual-compare-button" aria-describedby={`${comparisonId}-hint`}
          aria-expanded={comparisonOpen} aria-controls={comparisonId} disabled={!canCompare}
          onClick={() => {
            setOpenComparison(comparisonOpen ? null : comparisonKey)
            if (!comparisonOpen) requestAnimationFrame(() => comparisonHeading.current?.focus())
          }}>{comparisonOpen ? "대조 접기" : "대조하기"} <span aria-hidden="true">{comparisonOpen ? "↑" : "↓"}</span></button>
      </div>
    </> : <button type="button" className="gb-outline" disabled={!body.trim() || busy} onClick={prepare}>AI 분석용 판본 저장</button>}
    <section id={comparisonId} className="dual-comparison" hidden={!comparisonOpen} aria-labelledby={`${comparisonId}-title`}>
      <h2 id={`${comparisonId}-title`} tabIndex={-1} ref={comparisonHeading}>두 분석 자세히 대조</h2>
      {comparisonOpen && comparison && <>
          {record && run?.result?.paragraphs && <ParagraphComparison record={record} ai={run.result.paragraphs} quotations={closed} />}
          {!comparison.nodes.length && <p>두 분석에서 탐지된 후보가 없습니다.</p>}
          {comparison.nodes.map((row, i) => <article className="dual-difference" key={`${row.start}-${i}`}>
            <h3>{differences[row.status]}</h3>
            <div className="dual-columns">
              {([["글빛", row.s4, s4Nodes], ["AI", row.ai, aiNodes]] as const).map(([label, ids, nodes]) => <div key={label}>
                <strong>{label}</strong>
                {ids.length === 0 ? <span className="dual-excerpt">탐지 없음</span> : ids.map(id => {
                  const node = nodes.get(id)
                  return node && <Candidate key={id} node={node} points={points} jump={jumpCurrent} />
                })}
              </div>)}
            </div>
          </article>)}
          {comparison.relations.length > 0 && <h3>관계 불일치</h3>}
          {comparison.relations.map((item, index) => <div className="dual-difference dual-columns" key={index}>
            {([["글빛", item.s4, s4Nodes], ["AI", item.ai, aiNodes]] as const).map(([label, edge, nodes]) => <div key={label}>
              <strong>{label}</strong>
              {edge ? <Edges relations={[edge]} nodes={nodes} points={points} jump={jumpCurrent} /> : <span className="dual-excerpt">대응 관계 없음</span>}
            </div>)}
          </div>)}
          {!comparison.relations.length && <p>관계 불일치가 없습니다.</p>}
      </>}
    </section>
    {record && (closed.length > 0 || unresolved.length > 0) && <div className="dual-quote-controls">
      {closed.length > 0 && <label><input type="checkbox" checked={quoteEnabled} onChange={event => setQuoteEnabled(event.target.checked)} /> 인용문 강조</label>}
      {unresolved.length > 0 && <details><summary>닫힘 확인이 필요한 따옴표 {unresolved.length}곳</summary>
        <ul>{unresolved.slice(0, 24).map(quote => <li key={quote.quote_id}>
          {jumpCurrent ? <button type="button" onClick={() => jumpCurrent(quote)}>따옴표 {quote.start + 1}번째 문자</button> : `따옴표 ${quote.start + 1}번째 문자`}
        </li>)}</ul>
      </details>}
    </div>}
    <dialog ref={dialog} className="dual-consent" aria-labelledby="dual-consent-title" onCancel={event => { if (busy) event.preventDefault() }} onClose={() => setPreview(null)}>
      {preview && <>
        <h2 id="dual-consent-title">AI 전송 문단 확인</h2>
        <p>{preview.provider}의 {preview.model}에 아래 선택 문단을 전송합니다. 요청에 비용이 발생할 수 있습니다.</p>
        {preview.policyNotice && <p style={{ whiteSpace: "pre-line" }}>{preview.policyNotice}</p>}
        <p>개인 식별 정보나 보호 원문이 남아 있는 문단은 선택을 해제해 주세요.</p>
        {preview.omittedParagraphIds.length > 0 && <p>식별 정보가 감지된 문단 {preview.omittedParagraphIds.length}개를 자동 제외했습니다.</p>}
        <div className="dual-preview-list" role="group" aria-label="전송할 문단">
          {preview.paragraphs.map(paragraph => <label key={paragraph.id}>
            <input type="checkbox" checked={!excluded.includes(paragraph.id)} disabled={busy} onChange={event => {
              const include = event.target.checked
              setExcluded(old => include ? old.filter(id => id !== paragraph.id) : [...old, paragraph.id]); setReviewed(false)
            }} />
            <span><strong>{paragraphLabel(paragraph.id)}</strong><span className="dual-preview-paragraph">{paragraph.text}</span></span>
          </label>)}
        </div>
        <label className="dual-confirm"><input type="checkbox" checked={reviewed} disabled={busy} onChange={event => setReviewed(event.target.checked)} /> 선택한 문단과 비용 안내를 확인했으며 외부 전송에 동의합니다.</label>
        {message && <p role="alert">{message}</p>}
        <div className="dual-dialog-actions">
          <button type="button" className="gb-outline" disabled={busy} onClick={() => dialog.current?.close()}>닫기</button>
          <button type="button" className="gb-primary" disabled={!reviewed || !kept.length || busy} onClick={start}>{busy ? "요청 중…" : "동의하고 분석 실행"}</button>
        </div>
      </>}
    </dialog>
  </section>
}
