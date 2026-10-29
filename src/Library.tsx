import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { api, errorMessage, type AccountSession } from "./api"
import AccountMenu from "./AccountMenu"
import { useEscapeLayer } from "./escape-navigation"
import { PRODUCT_LABEL } from "./product-version"
import {
  mapSpan,
  paginateText,
  paragraphs,
  utf16Offset,
  type Span,
} from "./book-layout"
import "./library.css"
import "./ui-polish.css"
import BookCover from "./BookCover"
import { validatedSpans } from "./feedback-spans"
import { findMultipleTextSpans } from "./text-search"
import WritingTools from "./WritingTools"
import {toolsDefaults, type ToolsPreferences, type ToolsVersion} from "./writing-tools"
import { argumentMarks, type ArgumentCandidate, type ArgumentLink } from "./argument-spans"
import ArgumentText from "./ArgumentText"
import ArgumentEditorLayer from "./ArgumentEditorLayer"
import "./argument-marks.css"
import AnnotationsPanel, { useAnnotations } from "./AnnotationsPanel"
import { bookSelection } from "./user-annotations"
import AnnotationBookLayer from "./AnnotationBookLayer"
import "./v21-polish.css"
import "./mobile-layout.css"
import "./feedback-readability.css"
import "./accessibility.css"

type Writing = {
  id: string
  title: string
  content: string
  inquiryQuestion: string
  work: string
  status: string
  updatedAt: string
  revisionNumber: number
  characterCount: number
  latestAnalysisId?: string
  analysisRuns?: { id: string; createdAt: string; status: string }[]
}
type Finding = {
  id: string
  title: string
  type: string
  current: string
  reason: string
  suggestion?: string | null
  rule?: string
  sourceUrl?: string
  status: string
  startOffset: number | null
  endOffset: number | null
}
type Analysis = { id: string; writingId?: string; sourceVersion?: { id: string; content: string; sha256: string }; findings: Finding[]; disclaimer: string; argumentCandidates?: ArgumentCandidate[]; argumentLinks?: ArgumentLink[]; contextSnapshot?: {essayContext?: {work: string; inquiryQuestion: string}} }
type Preferences = {
  theme: "default" | "bookshelf"
  pageAnimation: boolean
  bookTexture: boolean
  reduceMotion?: boolean
  autosaveInterval?: number
  fontSize?: string
  highContrast?: boolean
}
type Nav = "dashboard" | "new-analysis" | "analysis-results" | "history" | "criteria" | "works" | "rules" | "settings"
const initial: Preferences = {
  theme: "default",
  pageAnimation: true,
  bookTexture: true,
}
const blank: Writing = {
  id: "",
  title: "",
  content: "",
  inquiryQuestion: "",
  work: "",
  status: "임시 저장",
  updatedAt: "",
  revisionNumber: 0,
  characterCount: 0,
}
const bookColor = (id: string) => Array.from(id).reduce((sum, c) => sum + c.charCodeAt(0), 0) % 4
const findingLabel = (type: string) => ({ spelling: "맞춤법", argument: "논증 연결", quotation: "인용문", quote: "인용문", peel: "문단 구성", rubric: "평가 기준" }[type] || type)
const aiContextText = (value: unknown) => {
  if (!value || typeof value !== "object") return "선택 문맥을 확인할 수 없습니다."
  const context = value as {excerpts?: {quote: string}[]; references?: {quote: string}[]}
  return ["내 글의 선택 구절", ...(context.excerpts ?? []).map(e => `「${e.quote}」`),
    ...((context.references?.length ?? 0) > 0 ? ["\n연결된 작품의 선택 구절", ...context.references!.map(e => `「${e.quote}」`)] : [])].join("\n")
}
const date = (value: string) =>
  value
    ? new Date(value).toLocaleDateString("ko-KR", {
        month: "long",
        day: "numeric",
      })
    : "새 글"

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    book: (
      <>
        <path d="M3 4c4-1 6 0 9 2 3-2 5-3 9-2v15c-4-1-6 0-9 2-3-2-5-3-9-2z" />
        <path d="M12 6v15" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    search: (
      <>
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 5 5" />
      </>
    ),
    settings: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="8" cy="7" r="3" />
        <circle cx="16" cy="17" r="3" />
      </>
    ),
    trash: (
      <>
        <path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7" />
      </>
    ),
    arrow: <path d="m9 5 7 7-7 7" />,
    upload: (
      <>
        <path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" />
      </>
    ),
    pen: (
      <>
        <path d="m4 16 12-12 4 4L8 20H4zM13 7l4 4" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    file: (
      <>
        <path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6" />
      </>
    ),
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.file}
    </svg>
  )
}

export default function Library({
  active,
  userName,
  account,
  onLogout,
  onNav,
  onBack,
  onOpenAnalysis,
  section = "dashboard",
  activeAnalysisId = null,
  children,
}: {
  active: boolean
  userName: string
  account: AccountSession
  onLogout: () => Promise<boolean>
  onNav: (screen: Nav) => void
  onBack: () => boolean | Promise<boolean>
  onOpenAnalysis: (id: string) => void
  section?: Nav
  activeAnalysisId?: string | null
  children?: React.ReactNode
}) {
  const [prefs, setPrefs] = useState(initial)
  // Layout preferences contain no essay data and do not extend the server contract.
  const [menuCollapsed, setMenuCollapsed] = useState(() => localStorage.getItem("geulbit.menuCollapsed") === "true")
  const [compactMenu, setCompactMenu] = useState(() => window.matchMedia("(max-width: 1100px)").matches)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [feedbackCollapsed, setFeedbackCollapsed] = useState(false)
  const [toolsPrefs,setToolsPrefs]=useState<ToolsPreferences>(toolsDefaults)
  const [toolsPane,setToolsPane]=useState('body')
  const [manualHighlight,setManualHighlight]=useState<Span|null>(null)
  const [feedbackStatus,setFeedbackStatus]=useState('all')
  const [feedbackSort,setFeedbackSort]=useState('position')
  const [emphasizeSelected,setEmphasizeSelected]=useState(false)
  const toolsDirty=useRef(false)

  const menuRef = useRef<HTMLElement>(null)
  const menuToggle = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1100px)")
    const changed = () => { setCompactMenu(media.matches); setDrawerOpen(false) }
    media.addEventListener("change", changed)
    return () => media.removeEventListener("change", changed)
  }, [])
  const currentPrefs = useRef(prefs)
  currentPrefs.current = prefs
  const [records, setRecords] = useState<Writing[]>([])
  const [listPage, setListPage] = useState(1)
  const [query, setQuery] = useState("")
  const [sort, setSort] = useState("updated-desc")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [view, setView] = useState<"home" | "editor" | "reader">("home")
  useEffect(() => { setDrawerOpen(false) }, [section, view])
  const [modal, setModal] = useState<"settings" | "trash" | "import" | null>(
    null,
  )
  useEffect(() => {
    if (!drawerOpen || modal) return
    const node = menuRef.current!
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    node.querySelector<HTMLButtonElement>("button")?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return
      const buttons = Array.from(node.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"))
      const first = buttons[0], last = buttons[buttons.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    document.addEventListener("keydown", keydown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener("keydown", keydown)
      menuToggle.current?.focus({ preventScroll: true })
    }
  }, [drawerOpen, modal])
  const toggleMenu = () => {
    if (compactMenu) setDrawerOpen(value => !value)
    else setMenuCollapsed(value => {
      localStorage.setItem("geulbit.menuCollapsed", String(!value))
      return !value
    })
  }
  const [writing, setWriting] = useState<Writing>(blank)
  const [saved, setSaved] = useState("")
  const [busy, setBusy] = useState(false)
  const [settingsBusy, setSettingsBusy] = useState(false)
  const [systemReduced, setSystemReduced] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  )
  const [job, setJob] = useState<{
    id: string
    progress: number
    step: string
  } | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [spans, setSpans] = useState<Record<string, Span | null>>({})
  const [snapshot, setSnapshot] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [scope, setScope] = useState("전체 글")
  const [filter, setFilter] = useState("전체 유형")
  const [group, setGroup] = useState(true)
  const [showAllFeedback, setShowAllFeedback] = useState(false)
  const [showAnalysisDetails, setShowAnalysisDetails] = useState(false)
  const [selectedArgument, setSelectedArgument] = useState<string | null>(null)
  const [focusedArgument, setFocusedArgument] = useState<string | null>(null)
  const [argumentContextChanged, setArgumentContextChanged] = useState(false)
  const argumentFlash = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => {if(argumentFlash.current)clearTimeout(argumentFlash.current)}, [])
  useEffect(() => {setSelectedArgument(null);setFocusedArgument(null)}, [analysis?.id, writing.content])
  useEffect(() => setArgumentContextChanged(false), [analysis?.id])
  useEffect(() => setShowAllFeedback(false), [analysis?.id, scope, filter])
  const [search, setSearch] = useState("")
  const [matchIndex, setMatchIndex] = useState(0)
  const [anchor, setAnchor] = useState(0)
  const [returnAnchor, setReturnAnchor] = useState<number | null>(null)
  const [pages, setPages] = useState<Span[]>([{ start: 0, end: 0 }])
  const [spread, setSpread] = useState(1)
  const [turn, setTurn] = useState(0)
  const [opening, setOpening] = useState<string | null>(null)
  const [pdf, setPdf] = useState<File | null>(null)
  const [pdfError, setPdfError] = useState("")
  const [pdfPreview, setPdfPreview] = useState<{previewId: string; text: string; title: string} | null>(null)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [pdfIncludeAi, setPdfIncludeAi] = useState(false)
  const [sourceLinking,setSourceLinking]=useState(false)
  const [documents, setDocuments] = useState<{id: string; title: string; latestRevisionId: string}[]>([])
  const [aiPreview, setAiPreview] = useState<{runId: string; spans: {start: number; end: number; quote: string}[]; references?: {revisionId: string; quote: string}[]; previewHash: string; context: unknown; externalEnabled: boolean; policyVersion?: string} | null>(null)
  const [aiReferences, setAiReferences] = useState<{revisionId: string; title: string}[]>([])
  const [aiReferenceId, setAiReferenceId] = useState("")
  const [aiReferenceQuote, setAiReferenceQuote] = useState("")
  const [aiBusy, setAiBusy] = useState(false)
  const [aiResult, setAiResult] = useState<{id: string; questions: {question: string}[]; status: string} | null>(null)
  const [aiConsent, setAiConsent] = useState(false)
  const [aiNote, setAiNote] = useState("")
  const [aiQuestionType, setAiQuestionType] = useState("ASSUMPTION")
  useEffect(() => {setAiPreview(null);setAiResult(null);setAiConsent(false);setAiNote("");setAiReferences([]);setAiReferenceId("");setAiReferenceQuote("");setShowAnalysisDetails(false)}, [analysis?.id])
  useEffect(() => { if (active) api.get<typeof documents>("/source-documents").then(setDocuments).catch(() => undefined) }, [active])
  const editor = useRef<HTMLTextAreaElement>(null)
  const feedbackPanel = useRef<HTMLElement>(null)
  const [annotationSelection,setAnnotationSelection]=useState<Span|null>(null)
  const [selectedAnnotation,setSelectedAnnotation]=useState<string|null>(null)
  const [annotationFormOpen,setAnnotationFormOpen]=useState(false)
  const annotationDirty=useRef(false)
  const annotations=useAnnotations(writing.id,writing.content,analysis?.sourceVersion)
  useEffect(()=>{setAnnotationSelection(null);setSelectedAnnotation(null);setAnnotationFormOpen(false)},[writing.id])
  const openAnnotation=(id:string)=>{if(annotationDirty.current && !window.confirm("저장하지 않은 주석을 닫고 다른 주석을 열까요?"))return;annotationDirty.current=false;setSelectedAnnotation(id);setAnnotationSelection(null);setAnnotationFormOpen(true);setFeedbackCollapsed(false);const span=annotations.positions[id];if(span)jump(span)}
  const book = useRef<HTMLDivElement>(null)
  useEffect(()=>{
    if(view!=="reader")return
    const changed=()=>{if(book.current){const span=bookSelection(book.current);if(span)setAnnotationSelection(span)}}
    document.addEventListener("selectionchange",changed)
    return()=>document.removeEventListener("selectionchange",changed)
  },[view,analysis?.sourceVersion,writing.content])
  const measure = useRef<HTMLDivElement>(null)
  const modalRef = useRef<HTMLElement>(null)
  useEscapeLayer("modal", !!modal, () => { if (!settingsBusy && !pdfBusy) setModal(null) }, modalRef)
  useEscapeLayer("panel", drawerOpen && !modal, () => setDrawerOpen(false), menuRef, 10)
  const saving = useRef(false)
  const listRequest = useRef(0)
  const inputEdit = useRef<Span | undefined>(undefined)
  const pendingEdits = useRef<{ before: string; after: string; edit?: Span }[] | null>(null)
  const savedValue = useRef("")
  const current = useRef(writing)
  current.current = writing
  const alive = useRef(true)
  useEffect(() => {
    // StrictMode/HMR may run cleanup and setup again on the same instance.
    alive.current = true
    return () => { alive.current = false }
  }, [])
  const motion = prefs.pageAnimation && !prefs.reduceMotion && !systemReduced
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)")
    const changed = () => setSystemReduced(media.matches)
    media.addEventListener("change", changed)
    return () => media.removeEventListener("change", changed)
  }, [])

  const reload = async () => {
    const requestNumber = ++listRequest.current
    setLoading(true)
    try {
      const values = await api.get<Writing[]>(
          `/writings?page=${listPage}&pageSize=12&search=${encodeURIComponent(query)}&sort=${sort}`,
      )
      if (requestNumber !== listRequest.current) return
      setRecords(values)
      setError("")
    } catch (e) {
      if (requestNumber === listRequest.current) setError(errorMessage(e))
    } finally {
      if (requestNumber === listRequest.current) setLoading(false)
    }
  }
  useEffect(() => {
    void reload()
  }, [listPage, query, sort])
  useEffect(() => {
    let current = true, serial = 0
    const refreshSettings = () => {
      const request = ++serial
      void api.get<Preferences>("/settings")
        .then(value => { if (current && request === serial) setPrefs({ ...initial, ...value }) })
        .catch(e => { if (current && request === serial) setError(errorMessage(e)) })
    }
    refreshSettings()
    window.addEventListener("geulbit-settings-updated", refreshSettings)
    if (active && view === "home") void reload()
    return () => { current = false;window.removeEventListener("geulbit-settings-updated", refreshSettings) }
  }, [active])
  useEffect(() => {
    if (!modal) return
    const previous = document.activeElement as HTMLElement | null
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return
      const nodes = modalRef.current?.querySelectorAll<HTMLElement>(
        "button:not(:disabled),input:not(:disabled),select:not(:disabled),a[href]",
      )
      if (!nodes?.length) return
      const first = nodes[0],
        last = nodes[nodes.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", trap)
    return () => {
      document.removeEventListener("keydown", trap)
      previous?.focus()
    }
  }, [modal])
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => {
      if (
        (writing.title || writing.work || writing.inquiryQuestion || writing.content) &&
        JSON.stringify([
          writing.title,
          writing.work,
          writing.inquiryQuestion,
          writing.content,
        ]) !== savedValue.current
      )
        event.preventDefault()
    }
    window.addEventListener("beforeunload", protect)
    return () => window.removeEventListener("beforeunload", protect)
  }, [writing])

  const save = async (): Promise<string | null> => {
    if (saving.current) return null
    saving.current = true
    setSaved("저장 중…")
    const value = current.current
    try {
      let result = value
      if (value.id) {
        result = await api.patch<Writing>(`/writings/${value.id}`, {
          title: value.title || "제목 없는 글",
          work: value.work,
          inquiryQuestion: value.inquiryQuestion,
          content: value.content,
          revisionNumber: value.revisionNumber,
        })
      } else
        result = await api.post<Writing>("/writings", {
          title: value.title || "제목 없는 글",
          work: value.work,
          inquiryQuestion: value.inquiryQuestion,
          content: value.content,
        })
      if (alive.current) {
        setWriting((now) => ({
          ...now,
          id: result.id,
          revisionNumber: result.revisionNumber,
          content: now.content === value.content ? result.content : now.content,
          title: now.title === value.title ? result.title : now.title,
          analysisRuns: result.analysisRuns,
          updatedAt: result.updatedAt,
        }))
        current.current = {
          ...current.current,
          id: result.id,
          revisionNumber: result.revisionNumber,
          content: current.current.content === value.content ? result.content : current.current.content,
          title: current.current.title === value.title ? result.title : current.current.title,
        }
        savedValue.current = JSON.stringify([result.title, result.work, result.inquiryQuestion, result.content])
        setSaved(JSON.stringify([current.current.title, current.current.work, current.current.inquiryQuestion, current.current.content]) === savedValue.current ? "저장 완료" : "새 변경은 저장 대기 중")
        setError("")
      }
      return result.id
    } catch (e) {
      setSaved("저장 실패 · 다시 시도해 주세요")
      setError(errorMessage(e))
      return null
    } finally {
      saving.current = false
    }
  }
  useEffect(() => {
    if (
      (!writing.id && !writing.title && !writing.work && !writing.inquiryQuestion && !writing.content) ||
      busy ||
      JSON.stringify([
        writing.title,
        writing.work,
        writing.inquiryQuestion,
        writing.content,
      ]) === savedValue.current
    )
      return
    setSaved("저장되지 않은 변경")
    const timer = window.setTimeout(
      () => void save(),
      Math.max(10, prefs.autosaveInterval || 60) * 1000,
    )
    return () => window.clearTimeout(timer)
  }, [
    writing.title,
    writing.content,
    writing.work,
    writing.inquiryQuestion,
    writing.id,
    busy,
    prefs.autosaveInterval,
  ])

  const changeContent = (content: string) => {
    setAnnotationSelection(null)
    const edit = inputEdit.current
    annotations.move(writing.content,content,edit)
    if (pendingEdits.current) {
      if (pendingEdits.current.length < 128) pendingEdits.current.push({ before: writing.content, after: content, edit })
      else pendingEdits.current = null
    }
    setSpans((old) =>
      Object.fromEntries(
        Object.entries(old).map(([id, span]) => [
          id,
          span ? mapSpan(writing.content, content, span, edit) : null,
        ]),
      ),
    )
    inputEdit.current = undefined
    setWriting((old) => ({ ...old, content }))
    setSaved("저장되지 않은 변경")
  }
  useEffect(() => {
    const node = editor.current
    if (!node || view !== "editor") return
    const capture = (event: Event) => {
      const type = (event as InputEvent).inputType
      const value = current.current.content
      let start = Array.from(value.slice(0, node.selectionStart)).length,
        end = Array.from(value.slice(0, node.selectionEnd)).length
      if (start === end && type === "deleteContentBackward")
        start = Math.max(0, start - 1)
      if (start === end && type === "deleteContentForward")
        end = Math.min(Array.from(value).length, end + 1)
      inputEdit.current =
        type?.startsWith("history") ||
        (type?.startsWith("delete") &&
          ![
            "deleteContentBackward",
            "deleteContentForward",
            "deleteByCut",
          ].includes(type))
          ? undefined
          : { start, end }
    }
    node.addEventListener("beforeinput", capture)
    return () => node.removeEventListener("beforeinput", capture)
  }, [view])
  const loadAnalysis = async (id: string) => {
    setAnalysis(null)
    setSelected(null)
    setSnapshot(null)
    setSpans({})
    try {
      const result = await api.get<Analysis>(`/analyses/${id}`)
      const source = result.sourceVersion?.content
      setAnalysis(result)
      setSnapshot(source ?? null)
      setSpans(Object.fromEntries(result.findings.map((f) => [f.id,
        source === current.current.content && f.startOffset !== null && f.endOffset !== null &&
        Array.from(source ?? "").slice(f.startOffset, f.endOffset).join("") === f.current
          ? { start: f.startOffset, end: f.endOffset } : null,
      ])))
    } catch (e) {
      setError(errorMessage(e))
    }
  }
  const open = async (record: Writing) => {
    if (busy) return
    setBusy(true)
    setOpening(record.id)
    try {
      const value = await api.get<Writing>(`/writings/${record.id}`)
      setWriting(value)
      current.current = value
      savedValue.current = JSON.stringify([
        value.title,
        value.work,
        value.inquiryQuestion,
        value.content,
      ])
      setSaved("저장 완료")
      setAnchor(0)
      setSearch("")
      setAnalysis(null)
      setSelected(null)
      setSnapshot(null)
      setSpans({})
      setError("")
      if (value.latestAnalysisId) await loadAnalysis(value.latestAnalysisId)
      if (motion && prefs.theme === "bookshelf")
        await new Promise((resolve) => window.setTimeout(resolve, 420))
      setView(prefs.theme === "bookshelf" ? "reader" : "editor")
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setOpening(null)
      setBusy(false)
    }
  }
  const create = () => {
    setWriting(blank)
    current.current = blank
    savedValue.current = ""
    setSaved("아직 저장하지 않음")
    setAnalysis(null)
    setSnapshot(null)
    setSelected(null)
    setSpans({})
    setAnchor(0)
    setSearch("")
    setError("")
    setView("editor")
  }
  const home = async () => {
    if(toolsDirty.current){setError('저장하지 않은 개인 메모가 있습니다. 카드 저장 또는 입력 버리기를 먼저 선택하세요.');return false}
    if (busy || saving.current) return false
    if (
      (writing.id || writing.title || writing.work || writing.inquiryQuestion || writing.content) &&
      JSON.stringify([
        writing.title,
        writing.work,
        writing.inquiryQuestion,
        writing.content,
      ]) !== savedValue.current &&
      !(await save())
    )
      return false
    setView("home")
    void reload()
    return true
  }
  const navigateHome = async () => {
    if (view === "home" || await home()) onNav("dashboard")
  }
  const navigateHistory = async () => {
    if (view === "home" || await home()) onNav("history")
  }
  useEscapeLayer("navigation", active && view !== "home", async () => { if (await home()) await onBack() }, undefined, 10)
  useEffect(() => {
    if (section === "new-analysis" && view === "home") create()
    if (section === "history") void reload()
    if (section !== "analysis-results" || !activeAnalysisId || analysis?.id === activeAnalysisId) return
    let cancelled = false
    void (async () => {
      try {
        const result = await api.get<Analysis>(`/analyses/${activeAnalysisId}`)
        if (cancelled) return
        if (!result.writingId) throw new Error("분석 결과의 원문 연결을 확인할 수 없습니다.")
        if (current.current.id !== result.writingId) {
          const record = await api.get<Writing>(`/writings/${result.writingId}`)
          if (cancelled) return
          await open(record)
        }
        if (!cancelled) {
          await loadAnalysis(activeAnalysisId)
          setView(currentPrefs.current.theme === "bookshelf" ? "reader" : "editor")
        }
      } catch (e) {
        if (!cancelled) setError(errorMessage(e))
      }
    })()
    return () => { cancelled = true }
  }, [section, activeAnalysisId])
  const analyze = async () => {
    if (busy || saving.current) return
    if (!writing.content.trim() || !writing.inquiryQuestion.trim()) {
      setError("본문과 탐구 질문을 입력해 주세요.")
      return
    }
    setBusy(true)
    setJob({id: "", progress: 0, step: "현재 글 저장 및 분석 준비 중"})
    try {
      const id = await save()
      if (!id) return
      const original = current.current.content
      pendingEdits.current = []
      const submitted = await api.post<{ jobId: string; analysisId: string }>(
        "/analyses",
        { writingId: id, content: current.current.content, revisionNumber: current.current.revisionNumber, analysisTypes: ["전체 분석"] },
      )
      const deadline = performance.now() + 180000
      for (;;) {
        if (!alive.current) return
        if (performance.now() > deadline) throw new Error("분석 응답 대기 시간이 초과되었습니다. 기존 결과와 초안을 보존했습니다.")
        const state = await api.get<{
          progress: number
          currentStep: string
          status: string
          errorMessage?: string
        }>(`/analysis-jobs/${submitted.jobId}`)
        setJob({
          id: submitted.jobId,
          progress: state.progress,
          step: state.currentStep,
        })
        if (state.status === "completed") {
          const result = await api.get<Analysis>(
            `/analyses/${submitted.analysisId}`,
          )
          setAnalysis(result)
          const source = result.sourceVersion?.content ?? original
          setSnapshot(source)
          setSpans(
            Object.fromEntries(
              result.findings.map((f) => {
                let span: Span | null = f.startOffset !== null && f.endOffset !== null &&
                  Array.from(source).slice(f.startOffset, f.endOffset).join("") === f.current
                    ? { start: f.startOffset, end: f.endOffset } : null
                let mappedSource = source
                for (const change of pendingEdits.current ?? []) {
                  if (change.before !== mappedSource) { span = null; break }
                  span = span ? mapSpan(change.before, change.after, span, change.edit) : null
                  mappedSource = change.after
                }
                if (mappedSource !== current.current.content) span = null
                return [f.id, span]
              }),
            ),
          )
          const value = await api.get<Writing>(`/writings/${id}`)
          setWriting((now) => ({
            ...now,
            analysisRuns: value.analysisRuns,
            latestAnalysisId: value.latestAnalysisId,
            status: value.status,
          }))
          break
        }
        if (["failed", "cancelled"].includes(state.status))
          throw new Error(state.errorMessage || "분석이 취소되었습니다.")
        await new Promise((resolve) => window.setTimeout(resolve, 600))
      }
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      pendingEdits.current = null
      setBusy(false)
      setJob(null)
    }
  }
  const updatePrefs = async (patch: Partial<Preferences>) => {
    if (settingsBusy) return
    const previous = prefs
    setPrefs((value) => ({ ...value, ...patch }))
    setSettingsBusy(true)
    try {
      const value = await api.patch<Preferences>("/settings", patch)
      setPrefs({ ...initial, ...value })
      setError("")
    } catch (e) {
      setPrefs(previous)
      setError(errorMessage(e))
    } finally {
      setSettingsBusy(false)
    }
  }
  const ensureToolsVersion=async():Promise<ToolsVersion>=>{
    for(let i=0;saving.current&&i<40;i++)await new Promise(resolve=>setTimeout(resolve,50))
    if(saving.current)throw new Error('글 저장이 진행 중입니다. 입력은 보존됩니다. 완료 후 다시 시도해 주세요.')
    const id=await save()
    if(!id)throw new Error('글을 저장하지 못했습니다. 입력을 보존하고 다시 시도해 주세요.')
    const draft=await api.get<Writing>(`/writings/${id}`)
    return await api.post<ToolsVersion>(`/writings/${id}/versions`,{revisionNumber:draft.revisionNumber,name:'사용자 지정 구간'})
  }
  useEffect(()=>setManualHighlight(null),[writing.content,writing.id])
  const contentPoints = useMemo(() => Array.from(writing.content), [writing.content])
  const paras = useMemo(() => paragraphs(writing.content), [writing.content])
  const activePara = Math.max(
    0,
    paras.findIndex((p) => anchor >= p.start && anchor <= p.end),
  )
  const paragraphStart = paras.length > 12 ? Math.max(0, Math.min(activePara - 4, paras.length - 9)) : 0
  const navigationParagraphs = paras.length > 12 ? paras.slice(paragraphStart, paragraphStart + 9) : paras
  const matches = useMemo(() => findMultipleTextSpans(contentPoints, search), [contentPoints, search])
  const jump = (span: Span) => {
    setAnchor(span.start)
    if (view === "editor")
      requestAnimationFrame(() => {
        const node = editor.current
        if (!node) return
        node.focus()
        node.setSelectionRange(
          utf16Offset(writing.content, span.start),
          utf16Offset(writing.content, span.end),
        )
        const before = writing.content.slice(0, node.selectionStart)
        const style = getComputedStyle(node)
        const mirror = document.createElement("div")
        Object.assign(mirror.style, {
          position: "fixed", visibility: "hidden", top: "0", left: "0",
          width: `${node.clientWidth}px`, boxSizing: "border-box", padding: style.padding,
          font: style.font, letterSpacing: style.letterSpacing,
          whiteSpace: "pre-wrap", overflowWrap: "break-word",
        })
        mirror.append(document.createTextNode(before))
        const marker = document.createElement("span")
        marker.textContent = "|"
        mirror.append(marker); document.body.append(mirror)
        node.scrollTop = Math.max(0, marker.offsetTop - node.clientHeight / 3)
        mirror.remove()
      })
  }
  useEffect(() => {
    if (view === "editor") jump({ start: anchor, end: anchor })
  }, [view])
  useLayoutEffect(() => {
    if (view !== "reader" || !book.current || !measure.current) return
    let disposed = false, previousLayout = ""
    const recalc = () => {
      const container = book.current!,
        node = measure.current!
      // Portrait tablets keep one readable page; landscape retains the spread.
      const count = container.clientWidth >= 700 && window.innerWidth > 820 ? 2 : 1
      setSpread(count)
      node.style.width = `${Math.min(540, container.clientWidth / count - (count === 2 ? 80 : 48))}px`
      const top = container.getBoundingClientRect().top + window.scrollY
      const height = Math.max(
        240,
        Math.min(680, window.innerHeight - Math.min(300, top) - 115),
      )
      const layout = `${node.style.width}:${height}`
      if (layout === previousLayout) return
      previousLayout = layout
      setPages(
        paginateText(writing.content, (text) => {
          node.textContent = text
          return node.scrollHeight <= height
        }),
      )
      container.style.setProperty("--page-height", `${height}px`)
    }
    const schedule = () => {
      if (!disposed) recalc()
    }
    const observer = new ResizeObserver(schedule)
    observer.observe(book.current)
    window.addEventListener("resize", schedule)
    recalc()
    void document.fonts.ready.then(() => {
      if (!disposed && book.current && measure.current) { previousLayout = ""; schedule() }
    })
    return () => {
      disposed = true
      observer.disconnect()
      window.removeEventListener("resize", schedule)
    }
  }, [view, writing.content, toolsPrefs.fontSize, toolsPrefs.lineHeight, toolsPrefs.bodyWidth])
  const currentPage = Math.max(
    0,
    pages.findIndex(
      (p) =>
        anchor >= p.start &&
        (anchor < p.end || p.end === contentPoints.length),
    ),
  )
  const first = Math.floor(currentPage / spread) * spread
  const flip = (direction: number) => {
    const next = Math.max(
      0,
      Math.min(pages.length - 1, first + direction * spread),
    )
    if (next === first) return
    setTurn(direction)
    setAnchor(pages[next].start)
  }
  const filtered = (analysis?.findings || []).filter(
    (f) =>
      (filter === "전체 유형" || f.type === filter) &&
      (feedbackStatus === "all" || f.status === feedbackStatus) &&
      (scope !== "현재 문단" ||
        (spans[f.id] &&
          spans[f.id]!.start >= (paras[activePara]?.start || 0) &&
          spans[f.id]!.start <= (paras[activePara]?.end || 0))),
  )
  filtered.sort((a,b)=>feedbackSort==="type" ? a.type.localeCompare(b.type)||a.title.localeCompare(b.title) : feedbackSort==="status" ? a.status.localeCompare(b.status)||(a.startOffset??0)-(b.startOffset??0) : (a.startOffset??Infinity)-(b.startOffset??Infinity))
  const previewFindings = filtered.slice(0, 3)
  const selectedFinding = filtered.find(f => f.id === selected)
  const visibleFindings = showAllFeedback ? filtered : selectedFinding && !previewFindings.includes(selectedFinding)
    ? [...previewFindings, selectedFinding] : previewFindings
  const groups = group
    ? Object.values(
        visibleFindings.reduce<Record<string, Finding[]>>((out, f) => {
          ;(out[f.rule || f.title] ||= []).push(f)
          return out
        }, {}),
      )
    : visibleFindings.map((f) => [f])
  const validSpans = useMemo(
    () => validatedSpans(contentPoints, analysis?.findings ?? [], spans),
    [analysis, spans, contentPoints],
  )
  const validSpan = (f: Finding) => validSpans[f.id] ?? null
  const structure = useMemo(() => {
    const context=analysis?.contextSnapshot?.essayContext
    const changed=argumentContextChanged || (context && (context.work!==writing.work || context.inquiryQuestion!==writing.inquiryQuestion))
    return argumentMarks(contentPoints, changed ? null : snapshot, analysis?.id, analysis?.sourceVersion?.id, analysis?.argumentCandidates, analysis?.argumentLinks)
  }, [contentPoints, snapshot, analysis, argumentContextChanged, writing.work, writing.inquiryQuestion])
  const selectArgument = (id: string) => {
    setManualHighlight(null)
    setSelectedArgument(id)
    const node = structure.candidates.find(c => c.id === id)
    const finding = analysis?.findings.find(f => node && f.startOffset !== null && f.endOffset !== null && f.startOffset < node.span.end && f.endOffset > node.span.start)
    setSelected(finding?.id ?? null)
  }
  const jumpArgument = (link: ArgumentLink) => {
    if (!structure.links.some(l => l.id === link.id)) return
    setReturnAnchor(anchor);selectArgument(link.claimId);setFocusedArgument(link.claimId)
    if(argumentFlash.current)clearTimeout(argumentFlash.current)
    argumentFlash.current=setTimeout(()=>setFocusedArgument(null),1800)
    jump(link.claimSpan)
    if(view === "reader")requestAnimationFrame(()=>{
      const target=Array.from(book.current?.querySelectorAll<HTMLElement>("[data-argument-id]") ?? []).find(node=>node.dataset.argumentId===link.claimId)
      target?.focus({preventScroll:true})
    })
  }
  const renderText = (span: Span) => {
    const f = analysis?.findings.find((f) => f.id === selected),
      highlight = manualHighlight ?? (f ? validSpan(f) : matches[matchIndex])
    return <ArgumentText points={contentPoints} range={span} candidates={structure.candidates} links={structure.links} highlight={highlight} focusedId={emphasizeSelected ? selectedArgument ?? focusedArgument : focusedArgument} onSelect={selectArgument} onJump={jumpArgument} annotations={annotations.marks} selectedAnnotation={selectedAnnotation} onAnnotation={openAnnotation} />
  }

  return (
    <div
      style={{"--writing-font-size":`${toolsPrefs.fontSize}px`,"--writing-line-height":toolsPrefs.lineHeight,"--writing-body-width":`${toolsPrefs.bodyWidth}px`} as React.CSSProperties}
      className={`gb ${prefs.fontSize === "크게" ? "interface-text-large" : prefs.fontSize === "작게" ? "interface-text-small" : ""} ${prefs.highContrast ? "high-contrast" : ""} ${toolsPrefs.focus && view!=="home" && !children ? "is-focus" : ""} ${emphasizeSelected && (selected || selectedArgument || manualHighlight) ? "focus-selection" : ""} ${prefs.theme} ${menuCollapsed ? "menu-collapsed" : ""} ${drawerOpen ? "drawer-open" : ""} ${!motion ? "no-motion" : ""} ${
        !prefs.bookTexture ? "no-texture" : ""
      }`}
    >
      <a className="gb-skip-link" href="#geulbit-content">본문으로 바로 가기</a>
      {drawerOpen && <button className="menu-scrim" aria-label="메뉴 바깥에서 닫기" tabIndex={-1} onClick={() => setDrawerOpen(false)} />}
      <aside id="geulbit-menu" ref={menuRef} className="gb-sidebar" role={drawerOpen ? "dialog" : undefined} aria-modal={drawerOpen || undefined} aria-label="글빛 메뉴" inert={Boolean(modal) || (compactMenu ? !drawerOpen : menuCollapsed)}>
        <button className="menu-close" aria-label="메뉴 닫기" onClick={toggleMenu}><Icon name="close" /></button>
        <button
          className="gb-brand"
          onClick={() => void navigateHome()}
        >
          <span className="brand-symbol">
            <Icon name="book" size={26} />
          </span>
          <span>
            글빛<small>GEULBIT</small>
          </span>
        </button>
        <div className="workspace-label">나의 작업 공간</div>
        <nav aria-label="주 메뉴">
          <button
            className={section === "dashboard" && view === "home" ? "active" : ""}
            onClick={() => void navigateHome()}
          >
            <Icon name="book" />
            {prefs.theme === "bookshelf" ? "내 서재" : "내 글"}
            <span className="nav-dot" />
          </button>
          <button
            onClick={() => {
              if (view === "home") { create(); onNav("new-analysis") }
            }}
            disabled={view !== "home"}
          >
            <Icon name="pen" />새 글 작성
          </button>
          <button className={section === "history" ? "active" : ""} onClick={() => void navigateHistory()}>
            <Icon name="file" />
            분석 기록
          </button>
          <details className="nav-resources" open={["criteria", "works", "rules"].includes(section) ? true : undefined}>
            <summary>자료와 도움말</summary>
          <button className={section === "criteria" ? "active" : ""} onClick={() => onNav("criteria")}>
            <Icon name="file" />
            평가 기준
          </button>
          <button className={section === "works" ? "active" : ""} onClick={() => onNav("works")}>
            <Icon name="book" />
            작품과 근거
          </button>
          <button className={section === "rules" ? "active" : ""} onClick={() => onNav("rules")}>
            <Icon name="check" />
            분석 규칙
          </button>
          </details>
        </nav>
        <div className="sidebar-bottom">
          <button onClick={() => setModal("settings")}>
            <Icon name="settings" />
            화면 설정
          </button>
          <div className="user-block">
            <span>{userName ? userName.slice(0, 1) : "글"}</span>
            <div>
              {userName || "나의 작업 공간"}
              <small>{account.role} · 승인 완료</small>
            </div>
          </div>
        </div>
      </aside>
      <main id="geulbit-content" tabIndex={-1} className="gb-main" inert={Boolean(modal) || drawerOpen}>
        <header className="gb-topbar">
          <button ref={menuToggle} className="menu-toggle" aria-label={(!compactMenu && !menuCollapsed) ? "메뉴 접기" : "메뉴 펼치기"} aria-expanded={compactMenu ? drawerOpen : !menuCollapsed} aria-controls="geulbit-menu" onClick={toggleMenu}>☰</button>
          <span>
            {view === "home" && !children ? (
              section === "history" ? "분석 기록" : prefs.theme === "bookshelf" ? "내 서재" : "내 글"
            ) : (
              <button onClick={() => children ? onNav("dashboard") : void navigateHome()} disabled={busy}>
                {children && view !== "home" ? "← 작성 중인 글로 돌아가기" : "← 서재로 돌아가기"}
              </button>
            )}
          </span>
          <div>
            <span className="local-label">
              <i aria-hidden="true" />개인 글 작업 공간
            </span>
            <AccountMenu account={account} onAdmin={() => onNav("settings")} onLogout={async () => {
              if (view !== "home" && !await home()) return false
              return onLogout()
            }} />
            <button
              className="icon-btn"
              aria-label="화면 설정"
              onClick={() => setModal("settings")}
            >
              <Icon name="settings" />
            </button>
          </div>
        </header>
        {error && (
          <div className="gb-error" role="alert">
            {error}
            <button onClick={() => setError("")} aria-label="오류 안내 닫기">
              ×
            </button>
          </div>
        )}
        <div className="writing-workspace" data-pane={toolsPane}>
        <WritingTools key={account.id} active={active} account={account} view={children?'home':view} writingId={writing.id} writingRevision={writing.revisionNumber} bodySaved={savedValue.current!=="" && JSON.parse(savedValue.current)[3]===writing.content} body={writing.content} cursor={anchor} selection={annotationSelection} hasAnalysis={!children&&!!analysis} analyzing={!!job} ensureVersion={ensureToolsVersion} onJump={span=>{setManualHighlight(span);setSelected(null);jump(span)}} onNew={()=>{if(view==='home')create();else setView('editor');if(children)onNav('new-analysis')}} onAnalyze={async()=>{await analyze()}} onPreferences={setToolsPrefs} onPane={setToolsPane} onFocus={focus=>{if(focus)setView('editor')}} onDirtyChange={dirty=>{toolsDirty.current=dirty}} onContextChanged={()=>setArgumentContextChanged(true)} onSearch={value=>{setSearch(value);setSelected(null);setManualHighlight(null);setMatchIndex(0)}} onFeedback={()=>{setFeedbackCollapsed(false);requestAnimationFrame(()=>feedbackPanel.current?.scrollIntoView({block:'start'}))}}/>
        {children ? <section className="gb-auxiliary">
          <header className="auxiliary-heading">
            <div className="eyebrow">{section === "settings" ? "내 작업 환경" : "자료와 도움말"}</div>
            <h1>{{criteria: "평가 기준", works: "작품과 근거", rules: "분석 규칙", settings: "설정과 운영"}[section as "criteria" | "works" | "rules" | "settings"]}</h1>
            <p>{{criteria: "글을 쓸 때 참고할 평가 기준을 모아 두세요.", works: "작품 자료와 인용 근거를 확인하고 내 글에 연결하세요.", rules: "어떤 기준으로 글을 살펴보는지, 분석의 범위와 한계를 확인하세요.", settings: "화면과 분석 환경을 조정하고 데이터 관리 안내를 확인하세요."}[section as "criteria" | "works" | "rules" | "settings"]}</p>
          </header>
          {children}</section> : view === "home" ? (
          <div className="library-content">
            <div className="library-heading">
              <div>
                <div className="eyebrow">{section === "history" ? "다시 살펴보는 나의 글" : "내 글"}</div>
                <h1>
                  {section === "history" ? "분석 기록" : prefs.theme === "bookshelf" ? "내 서재" : "내 글"}
                </h1>
                <p>{prefs.theme === "bookshelf" ? "내가 쓴 글을 책으로 읽고 이어서 수정합니다." : "저장한 글을 이어서 작성하고 분석 결과를 확인합니다."}</p>
              </div>
              <button className="gb-primary" onClick={create}>
                <Icon name="plus" />새 글 작성
              </button>
            </div>
            {section !== "history" && <ol className="writing-journey" aria-label="글빛 사용 순서">
              <li><span aria-hidden="true">01</span><div><strong>생각을 적어요</strong><small>새 글을 쓰거나 이어서 작성</small></div></li>
              <li><span aria-hidden="true">02</span><div><strong>글을 살펴봐요</strong><small>분석 제안을 확인하고 수정</small></div></li>
              <li><span aria-hidden="true">03</span><div><strong>책으로 읽어요</strong><small>다시 읽고 PDF로 보관</small></div></li>
            </ol>}
            <div className="library-tools">
              <div className="library-tabs">
                <button className="selected" onClick={() => setQuery("")}>
                  모든 글{" "}
                  <span>
                    {records.length}
                    {records.length === 12 ? "+" : ""}
                  </span>
                </button>
                <button onClick={() => setModal("import")}>
                  PDF 가져오기
                  <Icon name="upload" size={15} />
                </button>
              </div>
              <div className="library-search">
                <label>
                  <Icon name="search" size={17} />
                  <input
                    aria-label="책 검색"
                    placeholder="제목이나 작품으로 검색"
                    value={query}
                    onChange={(e) => {
                      setQuery(e.target.value)
                      setListPage(1)
                    }}
                  />
                </label>
                <select
                  aria-label="책 정렬"
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value)
                    setListPage(1)
                  }}
                >
                  <option value="updated-desc">최근 수정순</option>
                  <option value="updated-asc">오래된 순</option>
                </select>
              </div>
            </div>
            <div className="shelf-caption">
              <span>
                {prefs.theme === "bookshelf"
                  ? "책장에서 꺼내 읽기"
                  : "내가 쓴 글"}
              </span>
              <span>
                {prefs.theme === "bookshelf"
                  ? "책을 선택하면 펼쳐집니다"
                  : "글을 선택하면 이어서 작성할 수 있습니다"}
              </span>
            </div>
            <div className={`shelves ${records.length === 0 ? "empty" : ""}`}>
              {loading ? (
                <div className="empty-library" role="status">
                  서재를 불러오는 중…
                </div>
              ) : records.length === 0 ? (
                <div className="empty-library">
                  <div className="empty-book">
                    <Icon name="book" size={42} />
                  </div>
                  <h2>
                    {query
                      ? "검색 결과가 없습니다"
                      : "저장한 글이 없습니다."}
                  </h2>
                  <p>
                    {query
                      ? "다른 제목이나 작품명으로 검색해 보세요."
                      : "새 글 작성에서 본문을 입력하세요."}
                  </p>
                  <button className="gb-primary" onClick={create}>
                    <Icon name="plus" />첫 글 작성하기
                  </button>
                </div>
              ) : (
                <div className="books-grid">
                  {records.map((record) => {
                    const color = bookColor(record.id)
                    return (
                      <button
                        key={record.id}
                        className={`book-item color-${color} ${
                          opening === record.id ? "opening" : ""
                        }`}
                        disabled={busy}
                        aria-pressed={opening === record.id}
                        onClick={() => void open(record)}
                      >
                        {prefs.theme === "bookshelf" ? <BookCover title={record.title} work={record.work} /> : <span className="essay-card-icon"><Icon name="file" size={28} /></span>}
                        <div className="book-meta">
                          <span
                            className={
                              record.latestAnalysisId
                                ? "status completed"
                                : "status"
                            }
                          >
                            <i />
                            {record.latestAnalysisId
                              ? "분석 기록 있음"
                              : "작성 중"}
                          </span>
                          <span>{date(record.updatedAt)}</span>
                          <h3>{record.title || "제목 없는 글"}</h3>
                          <p>
                            {record.characterCount.toLocaleString()}자 ·{" "}
                            {record.work || "에세이"}
                          </p>
                          <span className="card-continue">{prefs.theme === "bookshelf" ? "책 펼치기" : "이어서 쓰기"}<span aria-hidden="true">↗</span></span>
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
            <div className="library-bottom">
              <div>
                <Icon name="book" size={18} />
                <span>{prefs.theme === "bookshelf" ? "책의 색상은 글의 점수와 관계가 없습니다." : "저장한 글과 분석 기록"}</span>
              </div>
              <div className="list-paging">
                <button
                  disabled={listPage === 1 || loading}
                  onClick={() => setListPage((p) => p - 1)}
                >
                  이전
                </button>
                <span>{listPage}</span>
                <button
                  disabled={records.length < 12 || loading}
                  onClick={() => setListPage((p) => p + 1)}
                >
                  다음
                </button>
              </div>
              <button className="trash-link" onClick={() => setModal("trash")}>
                <Icon name="trash" size={18} />
                휴지통 및 만료 안내
              </button>
            </div>
            <div className="library-note">
              <div>
                <span className="note-number">01</span>
                <div>
                  <h3>분석 규칙과 데이터 안내</h3>
                  <p>분석의 범위와 한계를 확인하세요. 만료 안내는 서버 정책이 연결된 경우에 표시됩니다.</p>
                </div>
              </div>
              <button onClick={() => onNav("rules")}>
                분석 규칙 살펴보기 <Icon name="arrow" size={16} />
              </button>
            </div>
          </div>
        ) : (
          <div className="writing-content">
            <div className="writing-heading">
              <div>
                <div className="eyebrow">
                  {view === "reader" ? "책 읽기" : "글쓰기"}
                </div>
                <h1>{writing.title || "제목 없는 글"}</h1>
                <span className="save-status" data-state={saved.includes("실패") ? "error" : saved === "저장 완료" ? "saved" : "pending"} role="status">
                  {saved} · 현재 초안
                </span>
              </div>
              <div className="writing-actions">
                {view === "reader" && <button className="gb-outline" aria-expanded={!feedbackCollapsed} onClick={() => setFeedbackCollapsed(value => !value)}>{feedbackCollapsed ? "피드백 펼치기" : "피드백 접기"}</button>}
                <button
                  className="gb-outline"
                  onClick={() => {
                    setView(view === "editor" ? "reader" : "editor")
                  }}
                  disabled={busy}
                >
                  <Icon name={view === "editor" ? "book" : "pen"} />
                  {view === "editor" ? "책으로 읽기" : "편집하기"}
                </button>
                <button
                  className="gb-outline"
                  title={analysis ? "선택한 분석 버전의 보고서를 내려받습니다" : "분석을 완료하면 PDF를 내려받을 수 있습니다"}
                  onClick={async () => { if (!analysis) return; try { const blob = await api.download(`/analyses/${analysis.id}/pdf?includeAi=${pdfIncludeAi}`); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href=url; link.download="geulbit-report.pdf"; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); } catch (e) { setError(errorMessage(e)); } }}
                  disabled={busy || !analysis}
                >
                  PDF 저장
                </button>
                <details className="writing-more">
                  <summary>더 보기</summary>
                  <div className="writing-more-content">

                <label style={{fontSize: 12}}><input type="checkbox" checked={pdfIncludeAi} onChange={e => setPdfIncludeAi(e.target.checked)} />질문·메모 포함</label>
                <label style={{display: "flex", flexDirection: "column", maxWidth: 180, fontSize: 12, gap: 4}}>자료 판본 연결<select style={{maxWidth: "100%"}} aria-label="자료 판본 연결" defaultValue="" disabled={sourceLinking||busy||saving.current} onChange={async e => { const node=e.currentTarget,revisionId=node.value; if (!revisionId||sourceLinking) return; setSourceLinking(true);try { const id=await save(); if(!id)throw new Error('글 저장 완료 후 다시 선택해 주세요.');await api.post(`/writings/${id}/documents`, {revisionId});setArgumentContextChanged(true); } catch (error) { setError(errorMessage(error)); }finally{setSourceLinking(false);node.value=''} }}><option value="">선택한 판본을 분석에 사용</option>{documents.map(d => <option key={d.id} value={d.latestRevisionId}>{d.title}</option>)}</select></label>
                <button
                  className="gb-outline"
                  onClick={() => void save()}
                  disabled={busy || saving.current}
                >
                  저장
                </button>
                  </div>
                </details>
                <button
                  className="gb-primary"
                  data-tour="analyze" onClick={() => void analyze()}
                  disabled={busy}
                >
                  {job ? `분석 중 ${job.progress}%` : "분석하기"}
                </button>
              </div>
            </div>
            {job && (
              <div className="job-status" role="status">
                <strong>분석 진행 중</strong><progress aria-label="전체 분석 진행률" value={job.progress} max={100} />
                {job.step}
                <button
                  disabled={!job.id}
                  onClick={() =>
                    void api
                      .post(`/analysis-jobs/${job.id}/cancel`)
                      .catch((e) => setError(errorMessage(e)))
                  }
                >
                  취소 요청
                </button>
              </div>
            )}
            <div className="document-search">
              <Icon name="search" size={18} />
              <input
                aria-label="본문 검색"
                placeholder="본문에서 찾기"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value)
                  setMatchIndex(0)
                  setSelected(null)
                }}
              />
              <span>
                {matches.length
                  ? `${Math.min(matchIndex + 1, matches.length)} / ${matches.length}`
                  : "0개"}
              </span>
              {[-1, 1].map((dir) => (
                <button
                  key={dir}
                  aria-label={dir < 0 ? "이전 검색 결과" : "다음 검색 결과"}
                  disabled={!matches.length}
                  onClick={() => {
                    const i =
                      (matchIndex + dir + matches.length) % matches.length
                    setMatchIndex(i)
                    setSelected(null)
                    jump(matches[i])
                  }}
                >
                  {dir < 0 ? "↑" : "↓"}
                </button>
              ))}
              {returnAnchor !== null && (
                <button
                  onClick={() => {
                    jump({ start: returnAnchor, end: returnAnchor })
                    setReturnAnchor(null)
                  }}
                >
                  이전 편집 위치로
                </button>
              )}
            </div>
            <div
              className={`desk-grid ${view === "reader" ? "reader-grid" : ""} ${view === "reader" && feedbackCollapsed ? "feedback-collapsed" : ""}`}
            >
              <aside className="paragraph-nav">
                <h2>
                  문단 탐색 <span>{paras.length}</span>
                </h2>
                <div>
                  {paras.length > 12 && <label className="paragraph-jump">문단 바로 이동<select aria-label="문단 바로 이동" value={activePara} onChange={e => jump(paras[Number(e.target.value)])}>{paras.map((p, i) => <option key={i} value={i}>{i + 1} / {paras.length} · {p.text.slice(0, 18)}</option>)}</select></label>}
                  {navigationParagraphs.map((p, index) => {
                    const i = paragraphStart + index
                    return (
                    <button
                      key={i}
                      className={i === activePara ? "selected" : ""}
                      onClick={() => jump(p)}
                    >
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      <p>{p.text.slice(0, 34)}</p>
                    </button>
                  )})}
                </div>
              </aside>
              <section className="document-column">
                {view === "editor" ? (
                  <div className="editor-paper" key="editor">
                    <div className="essay-fields">
                      <label>
                        제목
                        <input
                          value={writing.title}
                          maxLength={240}
                          disabled={busy}
                          onChange={(e) =>
                            setWriting((w) => ({ ...w, title: e.target.value }))
                          }
                          placeholder="글의 제목을 입력하세요"
                        />
                      </label>
                      <label>
                        작품
                        <input
                          value={writing.work}
                          maxLength={240}
                          disabled={busy}
                          onChange={(e) =>
                            setWriting((w) => ({ ...w, work: e.target.value }))
                          }
                          placeholder="작품명 (선택)"
                        />
                      </label>
                      <label className="question-field">
                        탐구 질문
                        <input
                          value={writing.inquiryQuestion}
                          maxLength={5000}
                          disabled={busy}
                          onChange={(e) =>
                            setWriting((w) => ({
                              ...w,
                              inquiryQuestion: e.target.value,
                            }))
                          }
                          placeholder="이 글에서 탐구하고 싶은 질문"
                        />
                      </label>
                    </div>
                    <div className="argument-editor">
                    <textarea
                      ref={editor}
                      data-tour="input"
                      aria-label="에세이 본문"
                      value={writing.content}
                      disabled={busy}
                      onChange={(e) => changeContent(e.target.value)}
                      onSelect={(e) => {
                        const point=Array.from(writing.content.slice(0,e.currentTarget.selectionStart)).length
                        const end=Array.from(writing.content.slice(0,e.currentTarget.selectionEnd)).length
                        if(end>point)setAnnotationSelection({start:point,end})
                        setAnchor(point)
                        const candidate=structure.candidates.find(c=>c.span.start<=point && point<c.span.end)
                        if(candidate)setSelectedArgument(candidate.id)
                      }}
                      placeholder="첫 문장을 써보세요. 문단은 빈 줄로 구분할 수 있습니다."
                      spellCheck={false}
                    />
                    <ArgumentEditorLayer editor={editor} links={structure.links} onJump={jumpArgument} onAnnotation={openAnnotation}><ArgumentText points={contentPoints} range={{start:0,end:contentPoints.length}} candidates={structure.candidates} links={structure.links} focusedId={emphasizeSelected ? selectedArgument ?? focusedArgument : focusedArgument} highlight={manualHighlight ?? (selected ? validSpans[selected] : matches[matchIndex])} mirror onSelect={selectArgument} onJump={jumpArgument} annotations={annotations.marks} selectedAnnotation={selectedAnnotation} /></ArgumentEditorLayer>
                    </div>
                    <div className="editor-footer">
                      <span>
                        {contentPoints.length.toLocaleString()}자
                        · {paras.length}문단
                      </span>
                      <span>하나의 연속된 문서</span>
                    </div>
                  </div>
                ) : (
                  <>
                    <div
                      className="reading-book"
                      key="reader"
                      ref={book}
                      onMouseUp={()=>{if(book.current){const span=bookSelection(book.current);if(span)setAnnotationSelection(span)}}}
                      onTouchEnd={()=>{window.setTimeout(()=>{if(book.current){const span=bookSelection(book.current);if(span)setAnnotationSelection(span)}},0)}}
                      tabIndex={0}
                      aria-label="책 본문. 좌우 방향키로 페이지 이동"
                      onKeyDown={(e) => {
                        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                          e.preventDefault()
                          flip(e.key === "ArrowRight" ? 1 : -1)
                        }
                      }}
                    >
                      <div
                        ref={measure}
                        className="page-measure"
                        aria-hidden="true"
                      />
                      <div
                        className={`spread pages-${spread} turn-${turn}`}
                        key={`${first}-${spread}`}
                        onAnimationEnd={() => setTurn(0)}
                      >
                        {pages.slice(first, first + spread).map((p, i) => (
                          <article className="reading-page" key={p.start} data-start={p.start} data-end={p.end}>
                            <div className="page-running">
                              <span>{writing.title || "제목 없는 글"}</span>
                              <span>글빛</span>
                            </div>
                            <div className="page-body">
                              {writing.content
                                ? renderText(p)
                                : "아직 본문이 없습니다. 편집하기에서 글을 작성해 주세요."}
                            </div>
                            <span className="page-number">{first + i + 1}</span>
                            <AnnotationBookLayer onOpen={openAnnotation} />
                            <div className="page-markers">
                              {(analysis?.findings || [])
                                .filter((f) => {
                                  const s = validSpan(f)
                                  return (
                                    s && s.start >= p.start && s.start < p.end
                                  )
                                })
                                .map((f) => (
                                  <button
                                    key={f.id}
                                    aria-label={`피드백: ${f.title}`}
                                    onClick={() => {
                                      setFeedbackCollapsed(false)
                                      setSelected(f.id)
                                      setAnchor(validSpan(f)!.start)
                                    }}
                                  >
                                    •
                                  </button>
                                ))}
                            </div>
                          </article>
                        ))}
                      </div>
                    </div>
                    <div
                      className="page-controls"
                      onTouchStart={(e) => {
                        e.currentTarget.dataset.x = String(e.touches[0].clientX)
                      }}
                      onTouchEnd={(e) => {
                        const delta =
                          e.changedTouches[0].clientX -
                          Number(e.currentTarget.dataset.x)
                        if (
                          Math.abs(delta) > 50 &&
                          !window.getSelection()?.toString()
                        )
                          flip(delta < 0 ? 1 : -1)
                      }}
                    >
                      <button
                        aria-label="이전 페이지"
                        disabled={first === 0}
                        onClick={() => flip(-1)}
                      >
                        ←
                      </button>
                      <span>
                        {first + 1}
                        {spread === 2 && first + 1 < pages.length
                          ? `–${Math.min(first + 2, pages.length)}`
                          : ""}{" "}
                        / {pages.length} 페이지
                        <small>아래 탐색 영역을 밀어서 넘길 수 있습니다</small>
                      </span>
                      <button
                        aria-label="다음 페이지"
                        disabled={first + spread >= pages.length}
                        onClick={() => flip(1)}
                      >
                        →
                      </button>
                    </div>
                  </>
                )}
                {annotationSelection && <div className="annotation-selection-bar" role="toolbar" aria-label="선택 구절 주석"><span>{contentPoints.slice(annotationSelection.start,annotationSelection.end).join("")}</span><button className="gb-outline annotation-add" onClick={()=>{if(annotationDirty.current && !window.confirm("저장하지 않은 주석을 닫고 새 주석을 작성할까요?"))return;annotationDirty.current=false;setSelectedAnnotation(null);setAnnotationFormOpen(true);setFeedbackCollapsed(false)}}>주석 추가</button></div>}
              </section>
              <aside data-tour="feedback" ref={feedbackPanel} className="feedback-panel" aria-label="분석 결과와 내 주석" tabIndex={-1} aria-busy={!!job}>
                <AnnotationsPanel writingId={writing.id} body={writing.content} version={analysis?.sourceVersion} selection={annotationFormOpen ? annotationSelection : null} notes={annotations.notes} positions={annotations.positions} selectedId={selectedAnnotation} error={annotations.error} onAccept={note=>{if(!annotations.accept(note))return;setSelectedAnnotation(note.id);setAnnotationFormOpen(true);setAnnotationSelection(null)}} onRemove={annotations.remove} onJump={openAnnotation} onDirtyChange={dirty=>{annotationDirty.current=dirty}} onClose={()=>{annotationDirty.current=false;setSelectedAnnotation(null);setAnnotationSelection(null);setAnnotationFormOpen(false)}} />
                {job && <div className="version-notice" role="status"><strong>글을 분석하고 있습니다…</strong><p>{job.step}</p><progress aria-label="분석 진행률" value={job.progress} max={100} /><p>완료되면 새 결과가 표시됩니다. 이전 결과는 보존됩니다.</p></div>}
                <div className="feedback-heading">
                  <Icon name="check" />
                  <h2>분석 피드백</h2>
                  <span>{analysis?.findings.length || 0}</span>
                </div>
                {analysis && <><div className="argument-legend"><span className="argument-claim">주장 후보</span><span className="argument-evidence">근거 후보</span><span>↑ 연결된 앞부분 주장으로 이동</span></div><p className="feedback-intro">문장 역할과 연결은 구조적 후보이며 논리적 타당성을 확정하지 않습니다.</p></>}
                {structure.stale && <p className="version-notice" role="status">본문 또는 문맥이 바뀌어 주장·근거 표시를 숨겼습니다. 재분석하면 새 관계를 표시합니다.</p>}
                {selectedArgument && structure.candidates.some(c=>c.id===selectedArgument) && <section className="version-notice argument-relation" aria-label="주장과 근거 연결"><h3>주장·근거 후보 연결</h3>{structure.links.filter(l=>l.claimId===selectedArgument || l.evidenceId===selectedArgument).length === 0 ? <p>이 후보에 연결할 문맥 신호가 충분하지 않습니다.</p> : structure.links.filter(l=>l.claimId===selectedArgument || l.evidenceId===selectedArgument).map(l=><div key={l.id}><p><strong>주장 후보</strong> {structure.candidates.find(c=>c.id===l.claimId)?.quote}</p><p><strong>근거 후보</strong> {structure.candidates.find(c=>c.id===l.evidenceId)?.quote}</p>{l.explanationText && <p><strong>인용 뒤 연결 설명</strong> {l.explanationText}</p>}<p>공통 주제어: {l.sharedNouns.join(", ") || "같은 작품을 명시한 문맥"} · {l.confidence === "STRONG_SIGNALS" ? "여러 연결 신호" : "연결 검토 필요"}</p><button className="gb-outline" onClick={()=>jumpArgument(l)}>연결된 주장으로 이동</button></div>)}</section>}
                {writing.analysisRuns && writing.analysisRuns.length > 0 && (
                  <details className="feedback-options">
                    <summary>이전 분석 보기</summary>
                  <label className="version-select">
                    분석 기록
                    <select
                      aria-label="분석 버전 선택"
                      value={analysis?.id || ""}
                      onChange={(e) => void loadAnalysis(e.target.value)}
                    >
                      {writing.analysisRuns.map((run, i) => (
                        <option key={run.id} value={run.id}>
                          분석 {writing.analysisRuns!.length - i} ·{" "}
                          {date(run.createdAt)} · {run.status}
                        </option>
                      ))}
                    </select>
                  </label>
                  </details>
                )}
                {analysis ? (
                  <>
                    <div className="version-notice">
                      {snapshot === null
                        ? "이전 분석 · 원문 버전 연결이 없어 위치를 재확인해야 합니다."
                        : snapshot !== writing.content
                          ? "분석 이후 초안이 변경되었습니다. 수정된 구절은 재분석이 필요합니다."
                          : "현재 세션에서 분석한 본문입니다. 규칙 기반 결과는 최종 판단이 아닙니다."}
                    </div>
                    <p className="feedback-intro">{showAllFeedback ? "전체 제안을 살펴보고 필요한 것만 적용하세요." : "먼저 살펴볼 제안입니다. 판단과 수정은 직접 선택하세요."}</p>
                    <details className="feedback-options">
                      <summary>피드백 찾기·필터</summary>
                    <div className="feedback-filters">
                      <label>처리 상태<select aria-label="피드백 처리 상태" value={feedbackStatus} onChange={e=>setFeedbackStatus(e.target.value)}><option value="all">모든 처리 상태</option>{[...new Set(analysis.findings.map(f=>f.status))].map(value=><option key={value} value={value}>{({open:'미처리',applied:'반영',ignored:'유지',accepted:'수용',dismissed:'제외'} as Record<string,string>)[value]??value}</option>)}</select></label>
                      <label>정렬<select aria-label="피드백 정렬" value={feedbackSort} onChange={e=>setFeedbackSort(e.target.value)}><option value="position">본문 위치순</option><option value="type">유형순</option><option value="status">처리 상태순</option></select></label>
                      <label><input type="checkbox" checked={emphasizeSelected} onChange={e=>setEmphasizeSelected(e.target.checked)}/>선택한 피드백·관계 중심 강조</label>
                      <select
                        aria-label="피드백 범위"
                        value={scope}
                        onChange={(e) => setScope(e.target.value)}
                      >
                        <option>전체 글</option>
                        <option>현재 문단</option>
                      </select>
                      <select
                        aria-label="피드백 유형"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        <option>전체 유형</option>
                        {[...new Set(analysis.findings.map((f) => f.type))].map(
                          (type) => (
                            <option key={type} value={type}>{findingLabel(type)}</option>
                          ),
                        )}
                      </select>
                      <label>
                        <input
                          type="checkbox"
                          checked={group}
                          onChange={(e) => setGroup(e.target.checked)}
                        />
                        반복 피드백 묶기
                      </label>
                    </div>
                    </details>
                    <div className="feedback-cards">
                      {groups.length === 0 && (
                        <p className="panel-empty">
                          이 범위의 피드백이 없습니다.
                        </p>
                      )}
                      {groups.map((items) => (
                        <div className="finding-group" key={items[0].id}>
                          {items.length > 1 && (
                            <div className="group-label">
                              같은 규칙 · {items.length}곳
                            </div>
                          )}
                          {items.map((f) => (
                            <article
                              key={f.id}
                              className={`feedback-card ${
                                selected === f.id ? "selected" : ""
                              }`}
                            >
                              <span className="finding-type">
                                {findingLabel(f.type)} ·{" "}
                                {f.status === "confirmed"
                                  ? "확인함"
                                  : f.status === "ignored"
                                    ? "보류함"
                                    : "확인 필요"}
                              </span>
                              <h3>{f.title}</h3>
                              <blockquote>
                                {f.current || "전체 글 관련 피드백"}
                              </blockquote>
                              <p>{f.reason}</p>
                              {f.suggestion && <p className="version-notice"><strong>수정 제안: </strong>{f.current} → {f.suggestion}</p>}
                              {f.rule && (
                                <div className="rule-source">
                                  규칙 출처: {f.rule}
                                  {f.sourceUrl && (
                                    <a
                                      href={f.sourceUrl}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      {" "}
                                      출처 ↗
                                    </a>
                                  )}
                                </div>
                              )}
                              <button
                                className="quote-jump"
                                disabled={!validSpan(f)}
                                onClick={() => {
                                  setReturnAnchor(anchor)
                                  setManualHighlight(null)
                                  setSelected(f.id)
                                  jump(validSpan(f)!)
                                }}
                              >
                                {validSpan(f)
                                  ? "원문으로 이동 ↗"
                                  : "위치 재확인 필요"}
                              </button>
                              {selected === f.id && <button className="gb-outline" style={{display: "block", maxWidth: "100%", marginBottom: 8, fontSize: 12, padding: "8px 12px"}} disabled={f.startOffset == null || f.endOffset == null} onClick={async () => { try {
                                const spans = [{start: f.startOffset!, end: f.endOffset!, quote: f.current}];
                                const [preview, status, references] = await Promise.all([api.post<{previewHash: string; context: unknown; externalEnabled: boolean}>(`/analyses/${analysis.id}/ai/preview`, {spans, questionType: aiQuestionType}), api.get<{policyVersion?: string}>("/ai/status"), api.get<typeof aiReferences>(`/analyses/${analysis.id}/ai/references`)]);
                                setAiReferences(references);setAiReferenceId("");setAiReferenceQuote("");
                                setAiPreview({...preview, runId: analysis.id, spans, policyVersion: status.policyVersion}); setAiResult(null); setAiConsent(false);
                              } catch (e) { setError(errorMessage(e)); } }}>심화 질문 문맥 확인</button>}
                              <details className="feedback-options"><summary>이 제안에 반응하기</summary>
                              <div className="finding-actions" style={{ flexWrap: "wrap", columnGap: 12, rowGap: 8 }}>
                                {["confirm", "fixed", "ignore", "incorrect"].map((action) => (
                                  <button
                                    key={action}
                                    onClick={async () => {
                                      try {
                                        const updated = await api.post<Finding>(
                                          `/findings/${f.id}/actions`,
                                          { action },
                                        )
                                        setAnalysis((old) =>
                                          old
                                            ? {
                                                ...old,
                                                findings: old.findings.map(
                                                  (item) =>
                                                    item.id === f.id
                                                      ? updated
                                                      : item,
                                                ),
                                              }
                                            : old,
                                        )
                                      } catch (e) {
                                        setError(errorMessage(e))
                                      }
                                    }}
                                  >
                                    {{ confirm: "확인함", fixed: "수정함", ignore: "이번에는 적용하지 않음", incorrect: "제안이 맞지 않음" }[action]}
                                  </button>
                                ))}
                              </div>
                              </details>
                            </article>
                          ))}
                        </div>
                      ))}
                    </div>
                    {filtered.length > 3 && <button className="gb-outline feedback-show-all" aria-expanded={showAllFeedback} onClick={() => setShowAllFeedback(value => !value)}>{showAllFeedback ? "핵심 제안만 보기" : `전체 제안 ${filtered.length}개 보기`}</button>}
                    {aiPreview && <details className="feedback-options"><summary>연결된 작품 구절 참고 (선택)</summary><p>이 분석에 연결한 작품 판본만 선택할 수 있습니다. 아래에 정확한 구절을 붙여 넣고 문맥을 확인하세요. 작품 전체나 연결되지 않은 자료는 보내지 않습니다.</p>
                      <label>참고 작품<select aria-label="AI 참고 작품" disabled={aiBusy} value={aiReferenceId} onChange={e => {setAiReferenceId(e.target.value);setAiReferenceQuote("");setAiConsent(false);setAiResult(null)}}><option value="">내가 쓴 글만 참고</option>{aiReferences.map(r => <option key={r.revisionId} value={r.revisionId}>{r.title}</option>)}</select></label>
                      {aiReferenceId && <textarea aria-label="AI 참고 작품 구절" maxLength={500} disabled={aiBusy} value={aiReferenceQuote} onChange={e => {setAiReferenceQuote(e.target.value);setAiConsent(false);setAiResult(null)}} placeholder="선택한 판본에 있는 구절을 정확히 붙여 넣어 주세요." />}
                      <button className="gb-outline" disabled={aiBusy || (!!aiReferenceId && !aiReferenceQuote.trim())} onClick={async () => {setAiBusy(true);setAiConsent(false);setAiResult(null);try {const references=aiReferenceId ? [{revisionId: aiReferenceId, quote: aiReferenceQuote}] : [];const preview=await api.post<{previewHash:string;context:unknown;externalEnabled:boolean}>(`/analyses/${aiPreview.runId}/ai/preview`, {spans:aiPreview.spans,questionType:aiQuestionType,references});setAiPreview({...aiPreview,...preview,references})}catch(e){setError(errorMessage(e))}finally{setAiBusy(false)}}}>참고 구절 문맥 반영</button>
                    </details>}
                    {aiPreview && <section className="version-notice"><h3>선택 구간 심화 질문</h3><label>질문 유형<select aria-label="질문 유형" value={aiQuestionType} onChange={async e => {const type=e.target.value;try {const preview=await api.post<{previewHash:string;context:unknown;externalEnabled:boolean}>(`/analyses/${aiPreview.runId}/ai/preview`,{spans:aiPreview.spans,questionType:type,references:aiPreview.references ?? []});setAiQuestionType(type);setAiPreview({...aiPreview,...preview});setAiResult(null);setAiConsent(false)}catch(error){setError(errorMessage(error))}}}>{Object.entries({ASSUMPTION:"전제와 연결 고리",CONCEPT:"개념 구분",CAUSALITY:"인과 검토",EVIDENCE:"근거의 성격",COUNTEREXAMPLE:"범위와 반례"}).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><p>{aiPreview.externalEnabled ? "승인된 외부 제공자에 아래 선택 구간을 전송합니다." : "외부 전송은 꺼져 있습니다. 로컬 질문만 사용할 수 있습니다."}</p><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere"}}>{aiContextText(aiPreview.context)}</pre><label><input type="checkbox" checked={aiConsent} onChange={e => setAiConsent(e.target.checked)} />이 문맥과 별도 AI 동의 정책을 확인했습니다.</label><button className="gb-outline" disabled={aiBusy || !aiConsent || !aiPreview.policyVersion || JSON.stringify(aiPreview.references ?? []) !== JSON.stringify(aiReferenceId ? [{revisionId: aiReferenceId, quote: aiReferenceQuote}] : [])} onClick={async () => { try {
                      setAiBusy(true); await api.post("/ai/consent", {granted: true, policyVersion: aiPreview.policyVersion});
                      setAiResult(await api.post(`/analyses/${aiPreview.runId}/ai/questions`, {spans: aiPreview.spans, questionType: aiQuestionType, previewHash: aiPreview.previewHash, references: aiPreview.references ?? []}));
                    } catch (e) { setError(errorMessage(e)); } finally { setAiBusy(false); } }}>질문 생성</button>{!aiPreview.policyVersion && <p>동의 정책 확정 전에는 질문을 생성할 수 없습니다.</p>}{aiResult && <><p>{aiResult.status === "PROVIDER_VALIDATED" ? "선택 구절에 대한 심화 질문입니다." : aiResult.status === "INSUFFICIENT_CONTEXT" ? "질문을 만들기에 문맥이 부족합니다." : "외부 전송 없이 로컬 질문을 제안합니다."}</p>{aiResult.questions.map((q,i) => <p key={i}>{q.question}</p>)}<textarea aria-label="생각 메모" value={aiNote} onChange={e => setAiNote(e.target.value)} /><button className="gb-outline" onClick={async () => { try { await api.patch(`/ai/interactions/${aiResult.id}/note`, {note: aiNote}); } catch(e) { setError(errorMessage(e)); } }}>생각 메모 저장</button></>}<button className="gb-outline" onClick={() => {setAiPreview(null);setAiResult(null);setAiConsent(false);setAiNote("");}}>닫기</button></section>}
                    <button
                      className="full-analysis"
                      aria-expanded={showAnalysisDetails}
                      onClick={() => setShowAnalysisDetails(value => !value)}
                    >
                      {showAnalysisDetails ? "분석 요약 닫기" : "분석 요약 보기"}
                    </button>
                    {showAnalysisDetails && <section className="version-notice" aria-label="분석 요약"><h3>이 분석의 범위와 결과</h3><p>전체 피드백 {analysis.findings.length}개 · 맞춤법 {analysis.findings.filter(f => f.type === "spelling").length}개 · 구조·인용 {analysis.findings.filter(f => f.type !== "spelling").length}개</p><p>{analysis.disclaimer}</p><button className="gb-outline" onClick={() => {setShowAllFeedback(true);setFilter("전체 유형");setScope("전체 글")}}>모든 피드백 보기</button></section>}
                  </>
                ) : (
                  <div className="panel-empty">
                    <Icon name="file" size={32} />
                    <h3>내 글을 한 번 더 살펴보기</h3>
                    <p>
                      본문과 탐구 질문을 작성한 후<br />
                      분석하기를 눌러 주세요.
                    </p>
                    <span>규칙 기반 분석 · 자동 AI 전송 없음</span>
                  </div>
                )}
              </aside>
            </div>
          </div>
        )}
        </div>
      </main>
      {!children && view !== "home" && (analysis || job || annotations.notes.length > 0) && <nav className="mobile-work-nav" aria-label="글 작업 바로 이동" inert={Boolean(modal) || drawerOpen}>
        <button onClick={() => {
          if(view === "editor") {editor.current?.scrollIntoView({block:"center",behavior:"auto"});jump({start:anchor,end:anchor})}
          else book.current?.scrollIntoView({block:"start",behavior:"auto"})
        }}><Icon name="book" size={18} /><span>본문</span></button>
        <button onClick={() => {setFeedbackCollapsed(false);requestAnimationFrame(() => {feedbackPanel.current?.scrollIntoView({block:"start",behavior:"auto"});feedbackPanel.current?.focus({preventScroll:true})})}}>
          <Icon name="check" size={18} /><span>{job ? "분석 중…" : "분석 결과"}</span><small>{job ? `${job.progress}%` : analysis?.findings.length || 0}</small>
        </button>
        {(annotations.notes.length > 0 || annotationFormOpen) && <button onClick={() => {setFeedbackCollapsed(false);requestAnimationFrame(() => {const node=feedbackPanel.current?.querySelector<HTMLElement>(".annotations-panel");node?.scrollIntoView({block:"start",behavior:"auto"});node?.querySelector<HTMLButtonElement>("button")?.focus({preventScroll:true})})}}>
          <span aria-hidden="true">▤</span><span>내 주석</span><small>{annotations.notes.length}</small>
        </button>}
      </nav>}
      <section className="pdf-print">
        <h1>{writing.title || "제목 없는 글"}</h1>
        <p>글빛 · 현재 초안 · {writing.work}</p>
        <h2>탐구 질문</h2>
        <p>{writing.inquiryQuestion}</p>
        <h2>본문</h2>
        <div className="print-body">{writing.content}</div>
        {analysis && (
          <>
            <h2>분석 기록</h2>
            <p>
              분석 ID: {analysis.id}. 현재 초안과 분석 당시 본문은 다를 수
              있습니다. 이 PDF는 원래 버전이나 분석 위치의 복원을 보장하지
              않습니다.
            </p>
            {analysis.findings.map((f) => (
              <article key={f.id}>
                <h3>{f.title}</h3>
                <blockquote>{f.current}</blockquote>
                <p>{f.reason}</p>
                <p>규칙 출처: {f.rule || "제공되지 않음"}</p>
              </article>
            ))}
          </>
        )}
      </section>
      {opening && motion && prefs.theme === "bookshelf" && (
        <div className={`book-transition color-${bookColor(opening)}`} aria-hidden="true">
          <div className="transition-pages">
            <div className="transition-cover book-cover">
              <span>GEULBIT · ESSAY</span>
              <h2>{records.find((record) => record.id === opening)?.title}</h2>
              <Icon name="book" size={34} />
            </div>
          </div>
        </div>
      )}
      {modal && (
        <div
          className="gb-modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setModal(null)
          }}
        >
          <section
            ref={modalRef}
            className="gb-modal"
            role="dialog"
            aria-modal="true"
            aria-label={
              modal === "settings"
                ? "화면 설정"
                : modal === "trash"
                  ? "휴지통 및 만료 안내"
                  : "PDF 가져오기"
            }
          >
            <button
              autoFocus
              className="modal-close icon-btn"
              aria-label="닫기"
              onClick={() => setModal(null)}
            >
              <Icon name="close" />
            </button>
            {modal === "settings" ? (
              <>
                <h2>화면 설정</h2>
                <div className="theme-options">
                  {(["default", "bookshelf"] as const).map((theme) => (
                    <button
                      key={theme}
                      disabled={settingsBusy}
                      className={prefs.theme === theme ? "selected" : ""}
                      aria-pressed={prefs.theme === theme}
                      onClick={() => void updatePrefs({ theme })}
                    >
                      <div className={`theme-preview ${theme}`}>
                        <Icon
                          name={theme === "default" ? "pen" : "book"}
                          size={32}
                        />
                      </div>
                      <strong>
                        {theme === "default" ? "기본 테마" : "책장 테마"}
                      </strong>
                      <small>
                        {theme === "default"
                          ? "밝고 편안한 글쓰기 공간"
                          : "책을 꺼내 읽는 개인 서재"}
                      </small>
                    </button>
                  ))}
                </div>
                {([
                  ["pageAnimation", "책 선택과 페이지 넘김 애니메이션"],
                  ["bookTexture", "책장 장식과 질감"],
                ] as const).map(([key, label]) => (
                  <label className="preference" key={key}>
                    <span>{label}</span>
                    <input
                      type="checkbox"
                      disabled={settingsBusy}
                      checked={prefs[key]}
                      onChange={(e) =>
                        void updatePrefs({ [key]: e.target.checked })
                      }
                    />
                  </label>
                ))}
                <small className="settings-note">
                  운영체제의 움직임 줄이기 설정을 함께 적용합니다.
                </small>
                <button
                  className="gb-outline"
                  onClick={() => {
                    setModal(null)
                    onNav("settings")
                  }}
                >
                  분석·접근성·데이터 설정 열기
                </button>
                <small className="settings-note" data-product-version>{PRODUCT_LABEL}</small>
              </>
            ) : modal === "trash" ? (
              <>
                <div className="trash-art">
                  <Icon name="trash" size={44} />
                </div>
                <h2>휴지통 및 만료 안내</h2>
                <p>
                  삭제된 원본과 분석 기록은 이곳에 별도로 보관하지 않습니다.
                  삭제된 글을 다시 열거나 복원할 수 없습니다.
                </p>
                <div className="version-notice">
                  현재 로컬 서버에는 7일 자동 만료 계약이 제공되지 않습니다.
                  삭제 예정 시각을 임의로 표시하지 않습니다.
                </div>
                <p>
                  보관한 PDF가 있다면 가져오기 지원 범위를 확인할 수 있습니다.
                </p>
                <button
                  className="gb-primary"
                  onClick={() => setModal("import")}
                >
                  <Icon name="upload" />
                  PDF 가져오기
                </button>
              </>
            ) : (
              <>
                <div className="eyebrow">FROM PAPER TO YOUR LIBRARY</div>
                <h2>PDF에서 새 책 만들기</h2>
                <p>보관한 파일을 확인하고 새로운 글로 재구성합니다.</p>
                <ol className="import-steps">
                  <li className="active">1 파일 확인</li>
                  <li>2 본문 검토</li>
                  <li>3 새 책 생성</li>
                </ol>
                <label className="upload-zone">
                  <Icon name="upload" size={32} />
                  <strong>{pdf ? pdf.name : "PDF 파일을 선택하세요"}</strong>
                  <span>
                    {pdf
                      ? `${(pdf.size / 1024 / 1024).toFixed(2)} MB · 파일 확인됨`
                      : "PDF 형식 · 현재 서버 제한 50 MB"}
                  </span>
                  <input
                    type="file"
                    accept="application/pdf,.pdf"
                    onChange={async (e) => {
                      const file = e.target.files?.[0]
                      setPdf(null)
                      setPdfPreview(null)
                      setPdfError("")
                      if (!file) return
                      if (
                        !file.name.toLowerCase().endsWith(".pdf") ||
                        file.size > 50 * 1024 * 1024
                      ) {
                        setPdfError("50 MB 이하의 PDF를 선택해 주세요.")
                        return
                      }
                      const header = new TextDecoder().decode(
                        await file.slice(0, 5).arrayBuffer(),
                      )
                      if (header !== "%PDF-") {
                        setPdfError("유효한 PDF 파일이 아닙니다.")
                        return
                      }
                      setPdf(file)
                    }}
                  />
                </label>
                {pdfError && (
                  <p role="alert" className="gb-error">
                    {pdfError}
                  </p>
                )}
                <div className="version-notice">
                  추출한 본문을 확인하고 수정한 뒤 새 책으로 저장하세요. 과거 분석은 복원하지 않습니다. 스캔 PDF는 지원하지 않습니다.
                </div>
                {pdfPreview && <label>추출한 본문 확인<textarea aria-label="추출한 본문" value={pdfPreview.text} onChange={e => setPdfPreview({...pdfPreview, text: e.target.value})} style={{width: "100%", minHeight: 180}} /></label>}
                <button className="gb-primary" disabled={!pdf || pdfBusy} onClick={async () => {
                  setPdfBusy(true); setPdfError("");
                  try {
                    if (!pdfPreview) {
                      const form = new FormData(); form.append("file", pdf!);
                      setPdfPreview(await api.post<{previewId: string; text: string; title: string}>("/pdf-import/preview", form));
                    } else {
                      const result = await api.post<Writing>("/pdf-import/confirm", {...pdfPreview, content: pdfPreview.text, confirmed: true});
                      setModal(null); setPdfPreview(null); setPdf(null); await reload();
                      setWriting(result); setView(prefs.theme === "bookshelf" ? "reader" : "editor");
                      savedValue.current = JSON.stringify([result.title, result.work, result.inquiryQuestion, result.content]);
                    }
                  } catch (e) { setPdfError(errorMessage(e)); }
                  finally { setPdfBusy(false); }
                }}>
                  {pdfBusy ? "처리 중…" : pdfPreview ? "확인한 본문으로 새 책 만들기" : "본문 추출"}
                </button>
                <p className="settings-note">
                  과거 분석과 계정 권한은 PDF에서 복원하지 않습니다.
                </p>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
