import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { api, errorMessage } from "./api"
import {
  mapSpan,
  paginateText,
  paragraphs,
  utf16Offset,
  type Span,
} from "./book-layout"
import "./library.css"
import BookCover from "./BookCover"

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
  rule?: string
  sourceUrl?: string
  status: string
  startOffset: number | null
  endOffset: number | null
}
type Analysis = { id: string; writingId?: string; findings: Finding[]; disclaimer: string }
type Preferences = {
  theme: "default" | "bookshelf"
  pageAnimation: boolean
  bookTexture: boolean
  reduceMotion?: boolean
  autosaveInterval?: number
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
  onNav,
  onOpenAnalysis,
  section = "dashboard",
  activeAnalysisId = null,
  children,
}: {
  active: boolean
  userName: string
  onNav: (screen: Nav) => void
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
      if (event.key === "Escape") { event.preventDefault(); setDrawerOpen(false) }
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
  const editor = useRef<HTMLTextAreaElement>(null)
  const book = useRef<HTMLDivElement>(null)
  const measure = useRef<HTMLDivElement>(null)
  const modalRef = useRef<HTMLElement>(null)
  const saving = useRef(false)
  const listRequest = useRef(0)
  const inputEdit = useRef<Span | undefined>(undefined)
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
    if (!active) return
    api
      .get<Preferences>("/settings")
      .then((value) => setPrefs({ ...initial, ...value }))
      .catch((e) => setError(errorMessage(e)))
    if (view === "home") void reload()
  }, [active])
  useEffect(() => {
    if (!modal) return
    const previous = document.activeElement as HTMLElement | null
    const trap = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setModal(null)
        return
      }
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
    const serialized = JSON.stringify([
      value.title,
      value.work,
      value.inquiryQuestion,
      value.content,
    ])
    try {
      let result = value
      if (value.id) {
        result = await api.post<Writing>(`/writings/${value.id}/autosave`, {
          content: value.content,
          revisionNumber: value.revisionNumber,
        })
        result = await api.patch<Writing>(`/writings/${value.id}`, {
          title: value.title || "제목 없는 글",
          work: value.work,
          inquiryQuestion: value.inquiryQuestion,
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
          analysisRuns: result.analysisRuns,
          updatedAt: result.updatedAt,
        }))
        current.current = {
          ...current.current,
          id: result.id,
          revisionNumber: result.revisionNumber,
        }
        savedValue.current = serialized
        setSaved("저장 완료")
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
    const edit = inputEdit.current
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
      setAnalysis(await api.get<Analysis>(`/analyses/${id}`))
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
    if (busy || saving.current) return false
    if (
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
  useEffect(() => {
    if (section === "new-analysis") create()
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
    if (!writing.content.trim() || !writing.inquiryQuestion.trim()) {
      setError("본문과 탐구 질문을 입력해 주세요.")
      return
    }
    setBusy(true)
    try {
      const id = await save()
      if (!id) return
      const original = current.current.content
      const submitted = await api.post<{ jobId: string; analysisId: string }>(
        "/analyses",
        { writingId: id, analysisTypes: ["전체 분석"] },
      )
      for (;;) {
        if (!alive.current) return
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
          setSnapshot(original)
          setSpans(
            Object.fromEntries(
              result.findings.map((f) => [
                f.id,
                f.startOffset !== null &&
                f.endOffset !== null &&
                Array.from(original)
                  .slice(f.startOffset, f.endOffset)
                  .join("") === f.current
                  ? { start: f.startOffset, end: f.endOffset }
                  : null,
              ]),
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
  const paras = useMemo(() => paragraphs(writing.content), [writing.content])
  const activePara = Math.max(
    0,
    paras.findIndex((p) => anchor >= p.start && anchor <= p.end),
  )
  const matches = useMemo(() => {
    if (!search) return []
    const points = Array.from(writing.content),
      needle = Array.from(search),
      result: Span[] = []
    for (let i = 0; i <= points.length - needle.length; i++)
      if (
        points[i] === needle[0] &&
        points.slice(i, i + needle.length).join("") === search
      )
        result.push({ start: i, end: i + needle.length })
    return result
  }, [writing.content, search])
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
    const recalc = () => {
      const container = book.current!,
        node = measure.current!
      const count = container.clientWidth >= 700 ? 2 : 1
      setSpread(count)
      node.style.width = `${Math.min(540, container.clientWidth / count - (count === 2 ? 80 : 48))}px`
      const top = container.getBoundingClientRect().top + window.scrollY
      const height = Math.max(
        240,
        Math.min(680, window.innerHeight - Math.min(300, top) - 115),
      )
      setPages(
        paginateText(writing.content, (text) => {
          node.textContent = text
          return node.scrollHeight <= height
        }),
      )
      container.style.setProperty("--page-height", `${height}px`)
    }
    const observer = new ResizeObserver(recalc)
    observer.observe(book.current)
    window.addEventListener("resize", recalc)
    recalc()
    void document.fonts.ready.then(() => {
      if (book.current && measure.current) recalc()
    })
    return () => {
      observer.disconnect()
      window.removeEventListener("resize", recalc)
    }
  }, [view, writing.content])
  const currentPage = Math.max(
    0,
    pages.findIndex(
      (p) =>
        anchor >= p.start &&
        (anchor < p.end || p.end === Array.from(writing.content).length),
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
      (scope !== "현재 문단" ||
        (spans[f.id] &&
          spans[f.id]!.start >= (paras[activePara]?.start || 0) &&
          spans[f.id]!.start <= (paras[activePara]?.end || 0))),
  )
  const groups = group
    ? Object.values(
        filtered.reduce<Record<string, Finding[]>>((out, f) => {
          ;(out[f.rule || f.title] ||= []).push(f)
          return out
        }, {}),
      )
    : filtered.map((f) => [f])
  const validSpan = (f: Finding) => {
    const span = spans[f.id]
    return span &&
      Array.from(writing.content).slice(span.start, span.end).join("") ===
        f.current
      ? span
      : null
  }
  const renderText = (span: Span) => {
    const points = Array.from(writing.content)
    const f = analysis?.findings.find((f) => f.id === selected),
      highlight = f ? validSpan(f) : matches[matchIndex]
    if (
      !highlight ||
      highlight.end <= span.start ||
      highlight.start >= span.end
    )
      return points.slice(span.start, span.end).join("")
    const left = Math.max(span.start, highlight.start),
      right = Math.min(span.end, highlight.end)
    return (
      <>
        {points.slice(span.start, left).join("")}
        <mark>{points.slice(left, right).join("")}</mark>
        {points.slice(right, span.end).join("")}
      </>
    )
  }

  return (
    <div
      className={`gb ${prefs.theme} ${menuCollapsed ? "menu-collapsed" : ""} ${drawerOpen ? "drawer-open" : ""} ${!motion ? "no-motion" : ""} ${
        !prefs.bookTexture ? "no-texture" : ""
      }`}
    >
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
          <div className="nav-line" />
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
              <small>로컬 작업 공간</small>
            </div>
          </div>
        </div>
      </aside>
      <main className="gb-main" inert={Boolean(modal) || drawerOpen}>
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
              <i />이 컴퓨터에 저장
            </span>
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
        {children ? <section className="gb-auxiliary">{children}</section> : view === "home" ? (
          <div className="library-content">
            <div className="library-heading">
              <div>
                <div className="eyebrow">{section === "history" ? "분석 기록" : ""}</div>
                <h1>
                  {section === "history" ? "분석 기록" : prefs.theme === "bookshelf" ? "내 서재" : "내 글"}
                </h1>
                <p>{prefs.theme === "bookshelf" ? "내가 쓴 글을 책으로 읽고 이어서 수정합니다." : "저장한 글을 이어서 작성하고 분석 결과를 확인합니다."}</p>
              </div>
              <button className="gb-primary" onClick={create}>
                <Icon name="plus" />새 글 작성
              </button>
            </div>
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
                      : "첫 번째 책을 기다리는 서재"}
                  </h2>
                  <p>
                    {query
                      ? "다른 제목이나 작품명으로 검색해 보세요."
                      : "새 글을 작성하면 이곳에 당신의 책이 놓입니다."}
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
                <span className="save-status" role="status">
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
                  title="인쇄 대화상자에서 PDF로 저장을 선택하세요"
                  onClick={() => window.print()}
                  disabled={busy}
                >
                  PDF 저장
                </button>
                <button
                  className="gb-outline"
                  onClick={() => void save()}
                  disabled={busy || saving.current}
                >
                  저장
                </button>
                <button
                  className="gb-primary"
                  onClick={() => void analyze()}
                  disabled={busy}
                >
                  {job ? `분석 중 ${job.progress}%` : "분석하기"}
                </button>
              </div>
            </div>
            {job && (
              <div className="job-status" role="status">
                <progress value={job.progress} max={100} />
                {job.step}
                <button
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
                  {paras.map((p, i) => (
                    <button
                      key={i}
                      className={i === activePara ? "selected" : ""}
                      onClick={() => jump(p)}
                    >
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      <p>{p.text.slice(0, 34)}</p>
                    </button>
                  ))}
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
                    <textarea
                      ref={editor}
                      aria-label="에세이 본문"
                      value={writing.content}
                      disabled={busy}
                      onChange={(e) => changeContent(e.target.value)}
                      onSelect={(e) =>
                        setAnchor(
                          Array.from(
                            writing.content.slice(
                              0,
                              e.currentTarget.selectionStart,
                            ),
                          ).length,
                        )
                      }
                      placeholder="첫 문장을 써보세요. 문단은 빈 줄로 구분할 수 있습니다."
                      spellCheck={false}
                    />
                    <div className="editor-footer">
                      <span>
                        {Array.from(writing.content).length.toLocaleString()}자
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
              </section>
              <aside className="feedback-panel">
                <div className="feedback-heading">
                  <Icon name="check" />
                  <h2>분석 피드백</h2>
                  <span>{analysis?.findings.length || 0}</span>
                </div>
                {writing.analysisRuns && writing.analysisRuns.length > 0 && (
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
                    <div className="feedback-filters">
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
                                  setSelected(f.id)
                                  jump(validSpan(f)!)
                                }}
                              >
                                {validSpan(f)
                                  ? "원문으로 이동 ↗"
                                  : "위치 재확인 필요"}
                              </button>
                              <div className="finding-actions">
                                {["confirm", "ignore"].map((action) => (
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
                                    {action === "confirm"
                                      ? "확인했어요"
                                      : "보류할게요"}
                                  </button>
                                ))}
                              </div>
                            </article>
                          ))}
                        </div>
                      ))}
                    </div>
                    <button
                      className="full-analysis"
                      onClick={() => onOpenAnalysis(analysis.id)}
                    >
                      분석 결과 주소 열기 ↗
                    </button>
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
      </main>
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
            onKeyDown={(e) => {
              if (e.key === "Escape") setModal(null)
            }}
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
                <div className="eyebrow">MAKE YOURSELF AT HOME</div>
                <h2>나에게 맞는 글빛</h2>
                <p>같은 글, 같은 기능. 편안한 공간을 선택하세요.</p>
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
                  기존 서버는 작품 자료의 PDF 추출을 지원하지만, 에세이 본문
                  복원 API는 없습니다. 본문 미리보기와 새 책 생성은 연결 전까지
                  사용할 수 없습니다. 스캔 PDF의 복원은 보장하지 않습니다.
                </div>
                <button className="gb-primary" disabled>
                  본문 추출 · 서버 연결 필요
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
