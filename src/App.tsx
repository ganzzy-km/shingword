import { useEffect, useRef, useState } from "react"
import { api, ApiError, errorMessage, resetApiSession, type AccountSession } from "./api"
import Library from "./Library"
import SourceTools from "./SourceTools"
import TextSourceDialog from "./TextSourceDialog"
import OcrReviewPanel from "./OcrReviewPanel"
import OcrModeDialog, { type OcrMode } from "./OcrModeDialog"
import { useEscapeLayer } from "./escape-navigation"

// ─── Types ────────────────────────────────────────────────────────────────────
type Screen = "dashboard" | "new-analysis" | "analysis-results" | "history" | "criteria" | "works" | "rules" | "settings"

type BadgeType = "error" | "warning" | "success" | "info" | "purple" | "draft" | "done" | "neutral"
type FindingType = "error" | "warning" | "purple" | "info"
type SentenceRole = "주장" | "근거" | "설명" | "효과" | "탐구 질문 연결" | "분류되지 않음"
type Confidence = "높음" | "보통" | "낮음"

interface WorkspaceConfig {
  userName: string
  workspaceName: string
}

interface DashboardData {
  summary: {
    rubrics: number
    sources: number
    ocrPending: number
    drafts: number
  }
  latestAnalysis: {
    id: string
    writingId: string
    status: string
    metrics: Record<string, {
      value: number | null
      description: string
    }>
  } | null
  ocrPending: {
    id: string
    name: string
    pages: number
    date: string
  }[]
  recentRecords: {
    id: string
    date: string
    title: string
    work: string
    status: string
  }[]
}

interface RubricData {
  id: string
  fileId?: string | null
  name: string
  status: string
  pages: number
  cards: number
  date: string
  ocrText?: string | null
  correctedText?: string | null
  ocrConfidence?: number | null
  originalName?: string | null
  mimeType?: string | null
  size?: number
  ocr?: OcrInfo | null
  ocrPages?: OcrPageData[]
  items?: {
    id: string
    name: string
    description: string
    checkType: string
    sourceLocation: string
    position: number
  }[]
}
interface SourceData {
  id: string
  title: string
  author: string
  originalName: string
  status: string
  pages: number
  cards: number
  date: string
  scope?: "PUBLIC" | "PRIVATE"
  canManageScope?: boolean
  latestRevisionId?: string
  accessMode?: "MATCH_ONLY" | "VIEW" | "DOWNLOAD"
  documentType?: string
  mimeType?: string
  size?: number
  ocr?: OcrInfo | null
  pageData?: OcrPageData[]
}
interface OcrInfo {
  status: string
  jobId?: string | null
  reviewAvailable?: boolean
  label: string
  message: string
  language: string
  updatedAt: string
}
interface OcrPageData {
  page?: number
  pageNumber?: number
  originalText?: string | null
  correctedText?: string | null
  text?: string | null
  confidence?: number | null
  extractionMethod?: string
  method?: string
  status?: string
}
interface OcrDialogModel {
  kind: "rubric" | "source"
  id: string
  fileName: string
  mimeType: string
  pageCount: number
  status: string
  statusCode: string
  reason: string
  previewUrl: string
  pages: {
    pageNumber: number
    text: string
    confidence?: number | null
    method: string
  }[]
}
interface SourceDeleteTarget {
  kind: "source"
  item: SourceData
}
interface QuoteDeleteTarget {
  kind: "quote"
  item: QuoteData
}
type WorksDeleteTarget = SourceDeleteTarget | QuoteDeleteTarget
interface QuoteData {
  id: string
  quote: string
  work: string
  author: string
  page: string
  verificationStatus: string
}
interface RecordData {
  id: string
  title: string
  work: string
  status: string
  updatedAt: string
  revisionNumber: number
  latestAnalysisId?: string | null
  analysisRuns?: {
    id: string
    status: string
    metrics: AnalysisData["metrics"]
    createdAt: string
  }[]
}
interface HistoryRow extends RecordData {
  rowKey: string
  analysisId: string | null
  analysisCreatedAt: string
  analysisStatus: string
  analysisVersion: string
  analysisMetrics: AnalysisData["metrics"]
}
interface LinguisticConceptData {
  group?: string | null
  expression: string
}
interface LinguisticQuotationData {
  text: string
  speaker?: string
  action?: string
}
interface AnalysisData {
  id: string
  writingId: string
  status: string
  createdAt: string
  writing?: {
    title: string
    work: string
    inquiryQuestion: string
  } | null
  metrics: Record<string, {
    value: number | null
    calculable: boolean
    description: string
  }>
  disclaimer: string
  details?: {
    linguisticAnalysis?: {
      analyzer: string
      analyzerError?: string | null
      morphologicalConfidence?: number | null
      quotations: {
        text: string
        start: number
        end: number
        quoteType: string
        depth: number
      }[]
      sentences: {
        sentenceNumber: number
        morphology: {
          mainVerb: string
          polarity: string
          tense: string
          aspect: string
          modality: string
          causative: boolean
          passive: boolean
          confidence: number
          lemmas: string[]
          analyzer: string
        }
        semanticRoles: {
          subject: string[]
          target: string[]
          recipient: string[]
          predicate: string
          concepts: LinguisticConceptData[]
          quotation?: LinguisticQuotationData[] | null
        }
      }[]
      heuristicNotice: string
    }
    dictionaryVerification?: {
      status: string
      verifiedWords: number
      checkedWords: number
      notice?: string | null
      scoreAffected: boolean
      source: string
    }
  }
  sentences: {
    id: string
    paragraphNumber: number
    sentenceNumber: number
    text: string
    autoRole: SentenceRole
    userRole?: SentenceRole
    confidence?: number
    rationale: string
  }[]
  argumentLinks: {
    id: string
    claimSentenceId: string
    evidenceSentenceId: string
    claimText: string
    evidenceText: string
    score: number
    status: string
    details: Record<string, unknown>
  }[]
  peelResults: {
    id: string
    paragraphNumber: number
    elements: Partial<Record<"P" | "E1" | "E2" | "L", string>>
    rationale: string
    guidance: string
  }[]
  findings: {
    id: string
    type: string
    severity: string
    title: string
    current: string
    suggestion?: string
    reason: string
    rule?: string
    confidence?: number
    status: string
    metadata: Record<string, unknown>
  }[]
}

interface WritingData extends RecordData {
  author: string
  inquiryQuestion: string
  content: string
  revisionNumber: number
}

interface RuleData {
  id: string
  name: string
  pattern: string
  replacement: string
  status: string
  explanation: string
  clause: string
  autoFixable: boolean
  contextRequired: boolean
  categoryLabel: string
  scope: string
  active: boolean
  version: string
  incorrectExamples: string[]
  correctExamples: string[]
  exceptionExamples: string[]
  primaryReference: {
    reference: { title: string; pdfPageCount: number }
    location: { pdfPages: number[] }
    normsCatalogue: { provisionCount: number }
  } | null
  source: {
    name: string
    url: string
    checkedAt: string | null
  } | null
}

interface SettingsData {
  autosaveInterval: number
  argumentLinkThreshold: number
  quoteSimilarityThreshold: number
  defaultAnalysisType: string
  allowBulkSpellingFix: boolean
  lowOcrConfidenceThreshold: number
  ocrLanguage: string
  imageZoom: number
  ocrPreprocessing: boolean
  fontSize: string
  highContrast: boolean
  reduceMotion: boolean
  nonColorStatus: boolean
  lastBackupAt?: string | null
}

interface DictionaryStatusData {
  status: string
  available: boolean
  checkedAt?: string | null
  notice?: string | null
}

interface BadgeProps {
  type: BadgeType
  label: string
}

interface EmptyStateProps {
  title: string
  desc: string
}

interface NavButtonProps {
  id: Screen
  label: string
  d: string
}

interface HeaderProps {
  title: string
  subtitle?: string
}

const DEFAULT_WORKSPACE: WorkspaceConfig = {
  userName: "",
  workspaceName: "글빛 작업 공간",
}

function clearGlbitStorage() {
  if (typeof window === "undefined") return

  for (const storage of [window.localStorage, window.sessionStorage]) {
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const key = storage.key(index)
      if (key && /^(glbit|geulbit)([.:_-]|$)/i.test(key)) storage.removeItem(key)
    }
  }
}

interface Finding {
  type: FindingType
  title: string
  current: string
  suggestion?: string
  reason: string
  rule?: string
  confidence: Confidence
}

// ─── Static data (module scope) ───────────────────────────────────────────────
const NAV_ITEMS = [
  {
    id: "dashboard" as Screen,
    label: "홈",
    d: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6",
  },
  { id: "new-analysis" as Screen, label: "새 글 분석", d: "M12 4v16m8-8H4" },
  {
    id: "criteria" as Screen,
    label: "평가 기준 자료",
    d: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2",
  },
  {
    id: "works" as Screen,
    label: "작품 및 인용 자료",
    d: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
  },
  {
    id: "history" as Screen,
    label: "분석 기록",
    d: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  },
  {
    id: "rules" as Screen,
    label: "규칙 및 출처",
    d: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  },
] as const

const SCREEN_TITLES: Partial<Record<Screen, {
  title: string
  subtitle?: string
}>> = {
  dashboard: { title: "홈" },
  "new-analysis": {
    title: "새 글 분석",
    subtitle: "분석할 글을 단계별로 입력해 주세요.",
  },
  "analysis-results": { title: "분석 결과" },
  history: { title: "분석 기록" },
  criteria: { title: "평가 기준 자료" },
  works: { title: "작품 및 인용 자료" },
  rules: { title: "규칙 및 출처" },
  settings: { title: "설정" },
}

const BADGE_STYLE: Record<BadgeType, string> = {
  error: "bg-[#FDECEC] text-[#C62828] border-[#C62828]/20",
  warning: "bg-[#FFF4E5] text-[#B45309] border-[#B45309]/20",
  success: "bg-[#E9F7EF] text-[#237A45] border-[#237A45]/20",
  done: "bg-[#E9F7EF] text-[#237A45] border-[#237A45]/20",
  info: "bg-[#EAF3FC] text-[#2563A6] border-[#2563A6]/20",
  purple: "bg-[#F3EDFF] text-[#6D3FC0] border-[#6D3FC0]/20",
  draft: "bg-[#F1F5F9] text-[#475569] border-[#CBD5E1]",
  neutral: "bg-[#F1F5F9] text-[#475569] border-[#CBD5E1]",
}

const FINDING_BG: Record<FindingType, string> = {
  error: "border-[#C62828]/30 bg-[#FDECEC]",
  warning: "border-[#B45309]/30 bg-[#FFF4E5]",
  purple: "border-[#6D3FC0]/30 bg-[#F3EDFF]",
  info: "border-[#2563A6]/30 bg-[#EAF3FC]",
}

const FINDING_BADGE: Record<FindingType, {
  type: BadgeType
  label: string
}> = {
  error: { type: "error", label: "명백한 오류" },
  warning: { type: "warning", label: "수정 권장" },
  purple: { type: "purple", label: "확인 필요" },
  info: { type: "info", label: "정보" },
}

const ROLE_STYLE: Record<SentenceRole, string> = {
  주장: "bg-[#102A43] text-white",
  근거: "bg-[#087F8C] text-white",
  설명: "bg-[#2563A6] text-white",
  효과: "bg-[#6D3FC0] text-white",
  "탐구 질문 연결": "bg-[#237A45] text-white",
  "분류되지 않음": "bg-[#E2E8F0] text-[#475569]",
}

const UNDERLINE: Record<FindingType, string> = {
  error: "decoration-[#C62828] decoration-wavy underline underline-offset-3",
  warning:
    "decoration-[#B45309] decoration-dashed underline underline-offset-3",
  purple: "decoration-[#6D3FC0] decoration-double underline underline-offset-3",
  info: "decoration-[#2563A6] underline underline-offset-3",
}

const STATUS_LABEL: Record<string, string> = {
  done: "분석 완료",
  warning: "수정 중",
  draft: "임시 저장",
}

const DASHBOARD_SUMMARY = [
  {
    label: "저장된 평가 기준",
    value: "0개",
    link: "criteria" as Screen,
    color: "#087F8C",
    bg: "#F0FAF9",
    d: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2",
  },
  {
    label: "저장된 작품 자료",
    value: "0개",
    link: "works" as Screen,
    color: "#2563A6",
    bg: "#EAF3FC",
    d: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
  },
  {
    label: "OCR 확인 필요",
    value: "0개",
    link: "criteria" as Screen,
    color: "#B45309",
    bg: "#FFF4E5",
    d: "M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18",
  },
  {
    label: "진행 중인 글",
    value: "0개",
    link: "new-analysis" as Screen,
    color: "#6D3FC0",
    bg: "#F3EDFF",
    d: "M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z",
  },
] as const

const DASHBOARD_METRICS: {
  label: string
  value: number
  desc: string
}[] = []

const DASHBOARD_HISTORY: {
  date: string
  title: string
  work: string
  status: BadgeType
  peel: string
}[] = []

const OCR_PENDING: {
  name: string
  pages: string
  date: string
}[] = []

const ANALYSIS_TABS = [
  { id: "all" as const, label: "전체", count: 0 },
  { id: "argument" as const, label: "논증 구조", count: 0 },
  { id: "criteria" as const, label: "평가 기준", count: 0 },
  { id: "citation" as const, label: "인용문", count: 0 },
  { id: "spelling" as const, label: "맞춤법", count: 0 },
]

const RESULT_METRICS: {
  label: string
  value: string
  color: string
  bg: string
}[] = []

const SENTENCES: {
  id: number
  text: string
  role: SentenceRole
  finding?: FindingType
}[] = []

const FINDINGS: Record<number, Finding> = {}

const CRITERIA_FILES: {
  name: string
  status: BadgeType
  statusLabel: string
  cards: number
  pages: number
  date: string
}[] = []

const WORKS_FILES: {
  name: string
  pages: number
  status: BadgeType
  statusLabel: string
  cards: number
}[] = []

const CITATIONS: {
  quote: string
  work: string
  author: string
  page: string
  chapter: string
}[] = []

const RULES_LIST = [
  {
    name: "의존 명사 '수'의 띄어쓰기",
    clause: "한글 맞춤법 제42항",
    conf: "높음" as const,
    date: "2026.07.01",
    wrong: "할수 있다",
    right: "할 수 있다",
    desc: "의존 명사 '수'는 앞말과 띄어 씁니다.",
  },
  {
    name: "'며칠'의 표기",
    clause: "한글 맞춤법 제27항",
    conf: "높음" as const,
    date: "2026.07.01",
    wrong: "몇일",
    right: "며칠",
    desc: "날짜를 나타내는 말은 '며칠'로 적습니다.",
  },
  {
    name: "'로서'와 '로써' 구분",
    clause: "어문 규범 일반",
    conf: "보통" as const,
    date: "2026.07.01",
    wrong: "로써(자격)",
    right: "로서(자격), 로써(수단)",
    desc: "'로서'는 자격, '로써'는 수단이나 도구를 나타냅니다.",
  },
] as const

const HISTORY_ROWS: {
  date: string
  title: string
  work: string
  version: string
  status: BadgeType
  peel: string
  modified: string
}[] = []

const PEEL_STATUS: {
  label: string
  status: string
  desc: string
}[] = []

const ANALYSIS_STEPS = [
  "기본 정보",
  "분석 자료 선택",
  "글 입력",
  "분석 설정 및 실행",
] as const

const ANALYSIS_TYPES = [
  {
    label: "전체 분석",
    desc: "아래 모든 분석 항목을 포함합니다.",
    checked: true,
  },
  {
    label: "논증 구조",
    desc: "주장, 근거, 설명, 효과와 탐구 질문 연결을 확인합니다.",
    checked: false,
  },
  {
    label: "평가 기준",
    desc: "선택한 교사 평가 기준의 객관적으로 확인 가능한 항목을 검사합니다.",
    checked: false,
  },
  {
    label: "인용문",
    desc: "학생 글의 인용문을 등록된 근거 카드와 비교합니다.",
    checked: false,
  },
  {
    label: "맞춤법",
    desc: "로컬에 등록된 기본 맞춤법 규칙을 이용해 명백한 오류와 확인할 표현을 찾습니다.",
    checked: false,
  },
] as const

const SETTINGS_SECTIONS = [
  "작업 공간",
  "분석 설정",
  "OCR 설정",
  "접근성",
  "데이터 관리",
] as const

const BACKUP_ACTIONS = [
  {
    label: "내 자료 백업 파일 만들기",
    desc: "모든 자료와 분석 기록을 파일로 저장합니다.",
    btn: "백업 파일 만들기",
  },
  {
    label: "백업 파일에서 복원하기",
    desc: "이전에 만든 백업 파일로 자료를 복원합니다.",
    btn: "복원하기",
  },
  {
    label: "전체 자료 내보내기",
    desc: "모든 자료를 CSV 또는 JSON 형식으로 내보냅니다.",
    btn: "내보내기",
  },
] as const

const INITIAL_TEXT = ""

// ─── Primitive components ─────────────────────────────────────────────────────
const INPUT_CLS =
  "w-full h-12 px-4 rounded-lg border border-[#CBD5E1] text-[16px] text-[#17212B] placeholder:text-[#AAB4C3] focus:outline-none focus:ring-2 focus:ring-[#087F8C] focus:border-[#087F8C] transition-colors"
const OUTLINE_BTN =
  "rounded-lg border border-[#CBD5E1] text-[#475569] hover:bg-[#F8FAFC] transition-colors font-medium"
const ICON_BTN =
  "w-9 h-9 flex items-center justify-center rounded-lg text-[#64748B] hover:bg-[#F1F5F9] transition-colors"
const CARD_CLS =
  "bg-white border border-[#E2E8F0] rounded-xl shadow-[0_1px_3px_rgba(16,42,67,0.06)]"

function SvgIcon({
  d,
  cls = "w-5 h-5",
  sw = 1.8,
}: {
  d: string
  cls?: string
  sw?: number
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={sw}
      className={cls}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={d} />
    </svg>
  )
}

function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <div
      className="rounded-xl flex items-center justify-center shrink-0"
      style={{ width: size, height: size, background: "#102A43" }}
    >
      <svg
        viewBox="0 0 24 24"
        style={{ width: size * 0.56, height: size * 0.56 }}
        fill="none"
      >
        <path
          d="M7 7h10M7 11h7M7 15h5"
          stroke="#16A3A6"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle cx="17" cy="14.5" r="2.5" fill="#16A3A6" opacity="0.75" />
      </svg>
    </div>
  )
}

const BADGE_ICON: Partial<Record<BadgeType, string>> = {
  error: "M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z",
  warning:
    "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  success: "M5 13l4 4L19 7",
  done: "M5 13l4 4L19 7",
  info: "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
}

function Badge({ type, label }: BadgeProps) {
  const iconD = BADGE_ICON[type]
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[13px] font-semibold leading-5 ${BADGE_STYLE[type]}`}
    >
      {iconD && (
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={type === "success" || type === "done" ? 2.5 : 1.8}
          className="w-3 h-3"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d={iconD} />
        </svg>
      )}
      {label}
    </span>
  )
}

function MetricBar({
  label,
  value,
  desc,
}: {
  label: string
  value: number
  desc: string
}) {
  const color = value >= 70 ? "#087F8C" : value >= 50 ? "#B45309" : "#C62828"
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between items-center">
        <span className="text-[14px] font-semibold text-[#334155]">
          {label}
        </span>
        <span className="text-[14px] font-semibold" style={{ color }}>
          {value}%
        </span>
      </div>
      <div className="h-2 bg-[#E2E8F0] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${value}%`, backgroundColor: color }}
        />
      </div>
      <p className="text-[13px] text-[#64748B]">{desc}</p>
    </div>
  )
}

function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="p-3 rounded-lg bg-[#F0FAF9] border border-[#DDF5F3] flex items-start gap-2">
      <span className="text-[#087F8C] shrink-0 mt-0.5">
        <SvgIcon
          d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          cls="w-4 h-4"
        />
      </span>
      <p className="text-[13px] text-[#334155] leading-6">{children}</p>
    </div>
  )
}

function Card({
  className = "",
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return <div className={`${CARD_CLS} ${className}`}>{children}</div>
}

function EmptyState({ title, desc }: EmptyStateProps) {
  return (
    <div className="min-h-40 flex flex-col items-center justify-center text-center px-6 py-8">
      <span className="w-11 h-11 rounded-full bg-[#F1F5F9] text-[#8492A6] flex items-center justify-center mb-3">
        <SvgIcon d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </span>
      <p className="text-[16px] font-semibold text-[#334155]">{title}</p>
      <p className="text-[14px] text-[#8492A6] mt-1">{desc}</p>
    </div>
  )
}

function Label({
  required,
  optional,
  children,
}: {
  required?: boolean
  optional?: boolean
  children: React.ReactNode
}) {
  return (
    <label className="block text-[15px] font-semibold text-[#334155] mb-1.5">
      {children}
      {required && <span className="text-[#C62828] ml-0.5"> *</span>}
      {optional && (
        <span className="ml-2 text-[13px] font-normal text-[#8492A6]">
          선택 사항
        </span>
      )}
    </label>
  )
}

function PrimaryBtn({
  buttonRef,
  onClick,
  disabled,
  className = "",
  children,
}: {
  buttonRef?: React.Ref<HTMLButtonElement>
  onClick?: () => void
  disabled?: boolean
  className?: string
  children: React.ReactNode
}) {
  return (
    <button
      ref={buttonRef}
      onClick={onClick}
      disabled={disabled}
      className={`gb-aux-primary rounded-lg text-white font-semibold transition-opacity hover:opacity-90 active:opacity-80 disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
      style={{ background: "var(--green, #087F8C)" }}
    >
      {children}
    </button>
  )
}

function SaveStatus() {
  return (
    <div className="flex items-center gap-1.5 text-[12px] text-[#64748B]">
      <span className="text-[#087F8C]">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          className="w-3.5 h-3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" />
        </svg>
      </span>
      <span>방금 저장됨</span>
    </div>
  )
}

function FileRow({
  name,
  pages,
  date,
  cards,
  status,
  statusLabel,
  onPreview,
  onDelete,
  onOcr,
  scope,
  onScopeChange,
  scopeBusy = false,
}: {
  name: string
  pages: number
  date: string
  cards?: number
  status: BadgeType
  statusLabel: string
  onPreview?: () => void
  onDelete?: () => void
  onOcr?: () => void
  scope?: "PUBLIC" | "PRIVATE"
  onScopeChange?: () => void
  scopeBusy?: boolean
}) {
  return (
    <div className={`${CARD_CLS} p-4 sm:p-5 flex flex-wrap sm:flex-nowrap items-center gap-3 sm:gap-4`}>
      <div className="w-10 h-10 rounded-lg bg-[#F0FAF9] flex items-center justify-center shrink-0 text-[#087F8C]">
        <SvgIcon d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <p className="text-[15px] font-semibold text-[#17212B] truncate">
            {name}
          </p>
          <Badge type={status} label={statusLabel} />
          {scope && <span className="text-[12px] text-[#64748B]">{scope === "PUBLIC" ? "공용" : "개인"}</span>}
        </div>
        <p className="text-[13px] text-[#64748B]">
          {pages}페이지 · {date} 업로드{cards ? ` · 카드 ${cards}개` : ""}
        </p>
      </div>
      <div className="flex flex-wrap gap-2 shrink-0 w-full sm:w-auto justify-end">
        {onScopeChange && <button onClick={onScopeChange} disabled={scopeBusy} className={`h-9 px-3 text-[14px] disabled:opacity-40 ${OUTLINE_BTN}`}>{scopeBusy ? "처리 중..." : scope === "PUBLIC" ? "공개 중지" : "공용으로 전환"}</button>}
        {onOcr && (
          <button
            onClick={onOcr}
            className="h-9 px-4 rounded-lg border border-[#B45309] text-[#B45309] text-[14px] font-semibold hover:bg-[#FFF4E5] transition-colors"
          >
            추출 글 확인
          </button>
        )}
        <button
          onClick={onPreview}
          disabled={!onPreview}
          className={`h-9 px-4 text-[14px] disabled:opacity-40 ${OUTLINE_BTN}`}
        >
          미리보기
        </button>
        <button
          onClick={onDelete}
          disabled={!onDelete}
          aria-label={`${name} 삭제`}
          className={`h-9 px-3 text-[14px] disabled:opacity-40 ${OUTLINE_BTN}`}
        >
          삭제
        </button>
      </div>
    </div>
  )
}

function OcrDialog({
  model,
  busy,
  error,
  onChangePage,
  onRun,
  onSave,
  onClose,
}: {
  model: OcrDialogModel
  busy: boolean
  error: string
  onChangePage: (pageNumber: number, text: string) => void
  onRun: () => void
  onSave: () => void
  onClose: () => void
}) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const busyRef = useRef(busy)
  const closeRef = useRef(onClose)
  busyRef.current = busy
  closeRef.current = onClose
  const titleId = `ocr-dialog-title-${model.kind}-${model.id}`
  const descriptionId = `ocr-dialog-description-${model.kind}-${model.id}`
  const dialogRef = useRef<HTMLDivElement>(null)
  useEscapeLayer("modal", true, () => { if (!busyRef.current) closeRef.current() }, dialogRef)
  const canRun = model.kind !== "rubric" && ["needs_ocr", "unavailable", "failed", "partial"].includes(
    model.statusCode,
  )
  const hasText = model.pages.some((page) => page.text.trim().length > 0)
  const fileType =
    model.mimeType === "application/pdf"
      ? "PDF"
      : model.mimeType === "image/png"
        ? "PNG 이미지"
        : model.mimeType === "image/jpeg"
          ? "JPG 이미지"
          : model.mimeType.includes("wordprocessingml")
            ? "DOCX"
            : model.mimeType === "text/plain"
              ? "텍스트 문서"
              : model.mimeType || "알 수 없음"

  useEffect(() => {
    cancelRef.current?.focus()
  }, [model.id])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 p-3 sm:p-6 flex items-center justify-center"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="bg-white rounded-2xl shadow-[0_12px_32px_rgba(16,42,67,0.18)] w-full max-w-[760px] max-h-[92vh] overflow-hidden flex flex-col"
      >
        <div className="px-5 sm:px-7 py-5 border-b border-[#E2E8F0]">
          <h2 id={titleId} className="text-[20px] font-bold text-[#17212B]">
            {model.kind === "rubric" ? "추출 글 확인" : "OCR 실행 및 결과 확인"}
          </h2>
          <p id={descriptionId} className="text-[14px] text-[#64748B] mt-1">
            원본과 추출 글을 비교한 뒤 필요한 부분을 수정해 주세요.
          </p>
        </div>
        <div className="p-5 sm:p-7 overflow-y-auto space-y-5">
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3 text-[14px]">
            <div>
              <dt className="text-[#64748B]">파일명</dt>
              <dd className="font-semibold text-[#17212B] break-all">
                {model.fileName}
              </dd>
            </div>
            <div>
              <dt className="text-[#64748B]">파일 형식</dt>
              <dd className="font-semibold text-[#17212B]">{fileType}</dd>
            </div>
            <div>
              <dt className="text-[#64748B]">페이지 수</dt>
              <dd className="font-semibold text-[#17212B]">
                {model.pageCount}페이지
              </dd>
            </div>
            <div>
              <dt className="text-[#64748B]">처리 예상 범위</dt>
              <dd className="font-semibold text-[#17212B]">
                텍스트가 없는 페이지 또는 이미지 영역
              </dd>
            </div>
          </dl>
          <div className="rounded-xl border border-[#B45309]/25 bg-[#FFF4E5] p-4">
            <p className="text-[13px] font-semibold text-[#8A5200] mb-1">
              OCR이 필요한 이유
            </p>
            <p className="text-[14px] leading-6 text-[#5F4315]">
              {busy ? "문서에서 글자를 추출하고 있습니다." : model.reason}
            </p>
          </div>
          <a
            href={model.previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-flex h-10 items-center px-4 text-[14px] ${OUTLINE_BTN}`}
          >
            원본 미리보기
          </a>
          {hasText && (
            <div className="space-y-4">
              {model.pages.map((page) => (
                <div key={page.pageNumber}>
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                    <label
                      htmlFor={`ocr-page-${model.kind}-${model.id}-${page.pageNumber}`}
                      className="text-[14px] font-semibold text-[#334155]"
                    >
                      {model.pageCount > 1
                        ? `${page.pageNumber}쪽 추출 글`
                        : "추출 글"}
                    </label>
                    <span className="text-[12px] text-[#64748B]">
                      {page.method === "native_text"
                        ? "원문 텍스트"
                        : "OCR 결과"}
                      {page.confidence != null
                        ? ` · 신뢰도 ${Math.round(page.confidence)}%`
                        : ""}
                    </span>
                  </div>
                  <textarea
                    id={`ocr-page-${model.kind}-${model.id}-${page.pageNumber}`}
                    value={page.text}
                    onChange={(event) =>
                      onChangePage(page.pageNumber, event.target.value)
                    }
                    rows={model.pageCount > 1 ? 7 : 12}
                    className="w-full min-h-32 resize-y rounded-xl border border-[#CBD5E1] px-4 py-3 text-[15px] leading-7 text-[#17212B] focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
                  />
                </div>
              ))}
              <p className="text-[13px] leading-5 text-[#64748B]">
                OCR 결과는 오인식될 수 있습니다. 따옴표, 하이픈·대시, 괄호와 쪽
                번호를 원본 미리보기와 비교해 주세요.
              </p>
            </div>
          )}
          {error && (
            <p role="alert" className="text-[14px] text-[#C62828]">
              {error}
            </p>
          )}
        </div>
        <div className="px-5 sm:px-7 py-4 border-t border-[#E2E8F0] flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
          <button
            ref={cancelRef}
            onClick={onClose}
            disabled={busy}
            className={`h-11 px-5 text-[15px] disabled:opacity-50 ${OUTLINE_BTN}`}
          >
            취소
          </button>
          {canRun && (
            <PrimaryBtn
              onClick={onRun}
              disabled={busy}
              className="h-11 px-5 text-[15px] disabled:opacity-50"
            >
              {busy ? "OCR 처리 중..." : "OCR 실행"}
            </PrimaryBtn>
          )}
          {hasText && (
            <PrimaryBtn
              onClick={onSave}
              disabled={busy}
              className="h-11 px-5 text-[15px] disabled:opacity-50"
            >
              수정 내용 저장
            </PrimaryBtn>
          )}
        </div>
      </div>
    </div>
  )
}

function ConfirmDialog({
  title,
  description,
  confirmLabel,
  busy = false,
  requiredText,
  inputValue = "",
  onInputChange,
  onConfirm,
  onClose,
  errorText,
}: {
  title: string
  description: string
  confirmLabel: string
  busy?: boolean
  requiredText?: string
  inputValue?: string
  onInputChange?: (value: string) => void
  onConfirm: () => void
  onClose: () => void
  errorText?: string
}) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const busyRef = useRef(busy)
  const closeRef = useRef(onClose)
  busyRef.current = busy
  closeRef.current = onClose
  const allowed = !requiredText || inputValue === requiredText
  const titleId = `confirm-dialog-${confirmLabel.replace(/\s/g, "-")}`
  const dialogRef = useRef<HTMLDivElement>(null)
  useEscapeLayer("modal", true, () => { if (!busyRef.current) closeRef.current() }, dialogRef)

  useEffect(() => {
    cancelRef.current?.focus()
  }, [titleId])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 p-4 flex items-center justify-center"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-white rounded-2xl shadow-[0_12px_32px_rgba(16,42,67,0.18)] w-full max-w-[480px] p-6 sm:p-8"
      >
        <h2 id={titleId} className="text-[20px] font-bold text-[#17212B]">
          {title}
        </h2>
        <p className="text-[15px] text-[#475569] leading-7 mt-3">
          {description}
        </p>
        {errorText && <p role="alert" className="text-[14px] text-[#C62828] mt-3">{errorText}</p>}
        {requiredText && (
          <div className="mt-5">
            <label className="block text-[14px] font-semibold text-[#334155] mb-1.5">
              확인을 위해 <span className="text-[#C62828]">{requiredText}</span>
              를 입력해 주세요.
            </label>
            <input
              value={inputValue}
              onChange={(event) => onInputChange?.(event.target.value)}
              className="w-full h-11 px-4 rounded-lg border border-[#CBD5E1] text-[16px] focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
            />
          </div>
        )}
        <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end mt-6">
          <button
            ref={cancelRef}
            onClick={onClose}
            disabled={busy}
            className={`h-11 px-5 text-[15px] disabled:opacity-50 ${OUTLINE_BTN}`}
          >
            취소
          </button>
          <button
            onClick={onConfirm}
            disabled={busy || !allowed}
            className="h-11 px-5 rounded-lg bg-[#C62828] text-white text-[15px] font-semibold hover:bg-[#A91F1F] disabled:opacity-40"
          >
            {busy ? "처리 중..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({
  current,
  onNav,
  workspace,
}: {
  current: Screen
  onNav: (s: Screen) => void
  workspace: WorkspaceConfig
}) {
  const SETTINGS_D =
    "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z"

  function NavBtn({ id, label, d }: NavButtonProps) {
    const active = current === id
    return (
      <button
        onClick={() => onNav(id)}
        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors relative group ${
          active
            ? "bg-[#F0FAF9] text-[#102A43] font-semibold"
            : "text-[#475569] hover:bg-[#F8FAFC] hover:text-[#102A43]"
        }`}
      >
        {active && (
          <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-[#087F8C]" />
        )}
        <span
          className={
            active
              ? "text-[#087F8C]"
              : "text-[#8492A6] group-hover:text-[#475569]"
          }
        >
          <SvgIcon d={d} />
        </span>
        <span className="text-[15px]">{label}</span>
      </button>
    )
  }

  return (
    <aside className="w-64 shrink-0 flex flex-col border-r border-[#E2E8F0] bg-white h-screen sticky top-0">
      <div className="px-5 py-5 border-b border-[#E2E8F0]">
        <LogoMark size={36} />
      </div>

      <nav className="flex-1 py-4 px-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <NavBtn key={item.id} id={item.id} label={item.label} d={item.d} />
        ))}
      </nav>

      <div className="border-t border-[#E2E8F0] p-3 space-y-1">
        <NavBtn id="settings" label="설정" d={SETTINGS_D} />
        <div className="mt-1 p-3 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0]">
          <div className="flex items-start justify-between gap-2 mb-2">
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-[#17212B] truncate">
                {workspace.workspaceName}
              </p>
              <SaveStatus />
            </div>
            <span className="text-[#8492A6] shrink-0 mt-0.5">
              <SvgIcon
                d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
                cls="w-4 h-4"
              />
            </span>
          </div>
          <p className="text-[12px] text-[#8492A6] mb-2.5">
            마지막 저장: 오후 4:23
          </p>
          <button
            className={`w-full flex items-center justify-center gap-1.5 h-8 text-[13px] ${OUTLINE_BTN}`}
          >
            <SvgIcon
              d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"
              cls="w-4 h-4"
            />
            데이터 백업
          </button>
        </div>
      </div>
    </aside>
  )
}

// ─── Header ───────────────────────────────────────────────────────────────────
function Header({ title, subtitle }: HeaderProps) {
  return (
    <header className="h-14 border-b border-[#E2E8F0] bg-white flex items-center px-6 gap-4 sticky top-0 z-10">
      <div className="flex-1">
        <h1 className="text-[17px] font-semibold text-[#17212B]">{title}</h1>
        {subtitle && <p className="text-[13px] text-[#64748B]">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">
        <button className={ICON_BTN}>
          <SvgIcon d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </button>
        <button className={`${ICON_BTN} relative`}>
          <SvgIcon d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[#087F8C]" />
        </button>
      </div>
    </header>
  )
}

// ─── Main Layout ──────────────────────────────────────────────────────────────
function MainLayout({
  screen,
  onNav,
  workspace,
  children,
}: {
  screen: Screen
  onNav: (s: Screen) => void
  workspace: WorkspaceConfig
  children: React.ReactNode
}) {
  const { title = "", subtitle } = SCREEN_TITLES[screen] ?? {}
  return (
    <div className="flex h-screen bg-[#F8FAFC] overflow-hidden">
      <Sidebar current={screen} onNav={onNav} workspace={workspace} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header title={title} subtitle={subtitle} />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}

// ─── Dashboard ────────────────────────────────────────────────────────────────
function DashboardScreen({
  onNav,
  onOpenAnalysis,
  workspace,
}: {
  onNav: (s: Screen) => void
  onOpenAnalysis: (id: string) => void
  workspace: WorkspaceConfig
}) {
  const hasName = workspace.userName.trim().length > 0
  const [data, setData] = useState<DashboardData | null>(null)
  const [loadError, setLoadError] = useState("")

  useEffect(() => {
    api
      .get<DashboardData>("/dashboard")
      .then(setData)
      .catch((error) => setLoadError(errorMessage(error)))
  }, [])

  const counts = data?.summary
  const summary = DASHBOARD_SUMMARY.map((card, index) => ({
    ...card,
    value: `${[counts?.rubrics ?? 0, counts?.sources ?? 0, counts?.ocrPending ?? 0, counts?.drafts ?? 0][index]}개`,
  }))
  const latestMetrics = data?.latestAnalysis?.metrics ?? {}

  return (
    <div className="p-8 max-w-[1184px] mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          {hasName ? (
            <>
              <h2 className="text-[28px] font-bold text-[#17212B]">
                안녕하세요, {workspace.userName}님
              </h2>
              <p className="text-[16px] text-[#64748B] mt-1">
                오늘도 문학 분석 글을 완성해 보세요.
              </p>
            </>
          ) : (
            <>
              <h2 className="text-[28px] font-bold text-[#17212B]">
                글빛에 오신 것을 환영합니다.
              </h2>
              <p className="text-[16px] text-[#64748B] mt-1">
                평가 기준과 작품 자료를 등록하고 첫 글 분석을 시작해 보세요.
              </p>
            </>
          )}
        </div>
        <PrimaryBtn
          onClick={() => onNav("new-analysis")}
          className="flex items-center gap-2 px-6 py-3 text-[17px]"
        >
          <SvgIcon d="M12 4v16m8-8H4" /> 새 글 분석 시작
        </PrimaryBtn>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
        {summary.map((card) => (
          <button
            key={card.label}
            onClick={() => onNav(card.link)}
            className={`${CARD_CLS} p-5 text-left hover:border-[#CBD5E1] transition-colors group`}
          >
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center mb-3"
              style={{ background: card.bg }}
            >
              <span style={{ color: card.color }}>
                <SvgIcon d={card.d} />
              </span>
            </div>
            <p className="text-[28px] font-bold text-[#17212B]">{card.value}</p>
            <p className="text-[14px] text-[#64748B] mt-0.5">{card.label}</p>
            <span
              className="flex items-center gap-1 text-[13px] font-semibold mt-3 group-hover:gap-2 transition-all"
              style={{ color: card.color }}
            >
              바로가기 <SvgIcon d="M9 5l7 7-7 7" cls="w-4 h-4" />
            </span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <Card className="lg:col-span-3 p-6">
          {data?.latestAnalysis ? (
            <>
              <div className="flex items-start justify-between mb-5">
                <h3 className="text-[18px] font-semibold text-[#17212B]">
                  최근 분석 결과
                </h3>
                <button
                  onClick={() => onOpenAnalysis(data.latestAnalysis!.id)}
                  className="text-[14px] font-semibold text-[#087F8C] hover:underline"
                >
                  결과 보기
                </button>
              </div>
              <div className="space-y-5">
                {Object.entries(latestMetrics)
                  .filter(
                    ([, metric]) =>
                      typeof metric.value === "number" && metric.value <= 100,
                  )
                  .slice(0, 4)
                  .map(([label, metric]) => (
                    <MetricBar
                      key={label}
                      label={label}
                      value={metric.value ?? 0}
                      desc={metric.description}
                    />
                  ))}
              </div>
              <div className="mt-5">
                <InfoNote>
                  이 수치는 교사의 평가 점수가 아니라 글의 구조를 점검하기 위한
                  참고 정보입니다.
                </InfoNote>
              </div>
            </>
          ) : (
            <EmptyState
              title="아직 분석 결과가 없습니다"
              desc="새 글 분석을 완료하면 최근 결과가 여기에 표시됩니다."
            />
          )}
        </Card>

        <Card className="lg:col-span-2 p-6">
          <h3 className="text-[18px] font-semibold text-[#17212B] mb-1">
            OCR 확인 필요
          </h3>
          <p className="text-[14px] text-[#64748B] mb-4">
            확인 전 자료는 분석에 사용할 수 없습니다.
          </p>
          {(data?.ocrPending.length ?? 0) > 0 ? (
            <div className="space-y-3">
              {data!.ocrPending.map((f) => (
                <div
                  key={f.id}
                  className="p-4 rounded-lg border border-[#FFF4E5] bg-[#FFFBF5]"
                >
                  <div className="flex items-start gap-3">
                    <span className="text-[#B45309] shrink-0 mt-0.5">
                      <SvgIcon d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-[14px] font-semibold text-[#17212B] truncate">
                        {f.name}
                      </p>
                      <p className="text-[13px] text-[#64748B]">
                        {f.pages}페이지 ·{" "}
                        {new Date(f.date).toLocaleDateString("ko-KR")}
                      </p>
                    </div>
                  </div>
                  <button className="mt-3 w-full h-9 rounded-lg border border-[#B45309] text-[#B45309] text-[14px] font-semibold hover:bg-[#FFF4E5] transition-colors">
                    확인하기
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="확인할 자료가 없습니다"
              desc="OCR 확인이 필요한 자료가 생기면 여기에 표시됩니다."
            />
          )}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E2E8F0]">
          <h3 className="text-[18px] font-semibold text-[#17212B]">
            최근 분석 기록
          </h3>
          <button
            onClick={() => onNav("history")}
            className="text-[14px] font-semibold text-[#087F8C] hover:underline"
          >
            전체 보기
          </button>
        </div>
        {(data?.recentRecords.length ?? 0) > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                  {[
                    "날짜",
                    "글 제목",
                    "작품명",
                    "분석 상태",
                    "PEEL 충족률",
                    "",
                  ].map((h) => (
                    <th
                      key={h}
                      className="px-5 py-3 text-left text-[13px] font-semibold text-[#64748B]"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data!.recentRecords.map((row) => (
                  <tr
                    key={row.id}
                    className="border-b border-[#F1F5F9] hover:bg-[#F8FAFC] transition-colors"
                  >
                    <td className="px-5 py-4 text-[14px] text-[#64748B]">
                      {new Date(row.date).toLocaleDateString("ko-KR")}
                    </td>
                    <td className="px-5 py-4 text-[15px] font-medium text-[#17212B]">
                      {row.title}
                    </td>
                    <td className="px-5 py-4 text-[14px] text-[#475569]">
                      {row.work}
                    </td>
                    <td className="px-5 py-4">
                      <Badge
                        type={row.status === "분석 완료" ? "done" : "draft"}
                        label={row.status}
                      />
                    </td>
                    <td className="px-5 py-4 text-[15px] font-semibold text-[#17212B]">
                      -
                    </td>
                    <td className="px-5 py-4">
                      <button
                        onClick={() => onNav("history")}
                        className="text-[14px] font-medium text-[#087F8C] hover:underline"
                      >
                        보기
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="분석 기록이 없습니다"
            desc="분석을 시작하면 저장된 기록을 여기서 확인할 수 있습니다."
          />
        )}
      </Card>
      {loadError && (
        <p role="alert" className="text-[14px] text-[#C62828]">
          {loadError}
        </p>
      )}
    </div>
  )
}

// ─── Analysis Results ─────────────────────────────────────────────────────────
function AnalysisResultsScreen({
  analysisId,
  onOpenAnalysis,
}: {
  analysisId: string | null
  onOpenAnalysis: (id: string) => void
}) {
  const [activeTab, setActiveTab] = useState("all")
  const [selected, setSelected] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisData | null>(null)
  const [loadError, setLoadError] = useState("")
  const [saving, setSaving] = useState(false)
  const [reanalyzing, setReanalyzing] = useState(false)
  const [reanalyzeProgress, setReanalyzeProgress] = useState(0)
  const [comparison, setComparison] = useState<{
    left: {
      name: string
      content: string
    }
    right: {
      name: string
      content: string
    }
  } | null>(null)

  const loadResult = async () => {
    if (!analysisId) return
    try {
      const data = await api.get<AnalysisData>(`/analyses/${analysisId}`)
      setResult(data)
      setSelected((current) =>
        current && data.sentences.some((sentence) => sentence.id === current)
          ? current
          : (data.sentences[0]?.id ?? null),
      )
      setLoadError("")
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }

  useEffect(() => {
    void loadResult()
  }, [analysisId])

  const selectedSentence = result?.sentences.find(
    (sentence) => sentence.id === selected,
  )
  const linguisticSentence =
    result?.details?.linguisticAnalysis?.sentences.find(
      (sentence) =>
        sentence.sentenceNumber === selectedSentence?.sentenceNumber,
    )
  const dictionaryVerification = result?.details?.dictionaryVerification
  const selectedPeel = selectedSentence
    ? result?.peelResults.find(
        (peel) => peel.paragraphNumber === selectedSentence.paragraphNumber,
      )
    : null
  const selectedArgumentLink = selectedSentence
    ? result?.argumentLinks.find(
        (link) =>
          link.claimSentenceId === selectedSentence.id ||
          link.evidenceSentenceId === selectedSentence.id,
      )
    : null
  const finding = selectedSentence
    ? result?.findings.find(
        (item) =>
          selectedSentence.text.includes(item.current) ||
          item.current.includes(selectedSentence.text),
      )
    : null
  const findingType = (item: AnalysisData["findings"][number]): FindingType =>
    item.severity === "error"
      ? "error"
      : item.type === "citation"
        ? "purple"
        : item.type === "argument"
          ? "info"
          : "warning"
  const confidenceLabel = (value?: number): Confidence =>
    value == null || value < 0.5 ? "낮음" : value < 0.8 ? "보통" : "높음"
  const metricColors = [
    { color: "#087F8C", bg: "#F0FAF9" },
    { color: "#2563A6", bg: "#EAF3FC" },
    { color: "#6D3FC0", bg: "#F3EDFF" },
    { color: "#237A45", bg: "#E9F7EF" },
  ]
  const metrics = Object.entries(result?.metrics ?? {}).map(
    ([label, metric], index) => ({
      label,
      value:
        metric.value == null
          ? "계산 불가"
          : label.endsWith("수")
            ? `${metric.value}개`
            : `${metric.value}%`,
      ...metricColors[index % metricColors.length],
    }),
  )
  const tabs = ANALYSIS_TABS.map((tab) => ({
    ...tab,
    count:
      tab.id === "all"
        ? (result?.findings.length ?? 0)
        : (result?.findings.filter((item) => item.type === tab.id).length ?? 0),
  }))
  const visibleSentences = (result?.sentences ?? []).filter((sentence) => {
    if (activeTab === "all") return true
    return result?.findings.some(
      (item) =>
        item.type === activeTab &&
        (sentence.text.includes(item.current) ||
          item.current.includes(sentence.text)),
    )
  })

  const actOnFinding = async (action: "apply" | "confirm" | "ignore") => {
    if (!finding || saving) return
    setSaving(true)
    try {
      if (action === "apply") await api.post(`/findings/${finding.id}/apply`)
      else await api.post(`/findings/${finding.id}/actions`, { action })
      await loadResult()
    } catch (error) {
      setLoadError(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const loadComparison = async () => {
    if (!result) return
    try {
      const versions = await api.get<{
        id: string
        name: string
        isOriginal: boolean
      }[]>(`/writings/${result.writingId}/versions`)
      const left = versions.find((version) => version.isOriginal) ?? versions[0]
      const right = versions[versions.length - 1]
      if (!left || !right || left.id === right.id) {
        setLoadError(
          "수정 제안을 적용한 뒤 원문과 수정문을 비교할 수 있습니다.",
        )
        return
      }
      setComparison(
        await api.get(`/writing-versions/${left.id}/compare/${right.id}`),
      )
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }

  const reanalyzeWriting = async () => {
    if (!result || reanalyzing) return
    setReanalyzing(true)
    setReanalyzeProgress(0)
    setLoadError("")
    try {
      const started = await api.post<{
        analysisId: string
        jobId: string
      }>("/analyses", {
        writingId: result.writingId,
        analysisTypes: ["전체 분석"],
      })
      for (;;) {
        const job = await api.get<{
          analysisId: string
          status: string
          progress: number
          errorMessage?: string
        }>(`/analysis-jobs/${started.jobId}`)
        setReanalyzeProgress(job.progress)
        if (job.status === "completed") {
          onOpenAnalysis(job.analysisId)
          return
        }
        if (job.status === "failed" || job.status === "cancelled") {
          throw new Error(job.errorMessage || "다시 분석하지 못했습니다.")
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500))
      }
    } catch (error) {
      setLoadError(errorMessage(error))
    } finally {
      setReanalyzing(false)
    }
  }

  if (!analysisId || (!result && !loadError)) {
    return (
      <div className="p-8 max-w-[1184px] mx-auto">
        <Card>
          <EmptyState
            title={
              analysisId
                ? "분석 결과를 불러오는 중입니다"
                : "분석 결과가 없습니다"
            }
            desc={
              analysisId
                ? "잠시만 기다려 주세요."
                : "글 분석을 완료하면 문장별 결과와 수정 제안이 표시됩니다."
            }
          />
        </Card>
      </div>
    )
  }

  if (!result)
    return (
      <div className="p-8 max-w-[1184px] mx-auto">
        <Card>
          <EmptyState
            title="분석 결과를 불러오지 못했습니다"
            desc={loadError}
          />
        </Card>
      </div>
    )

  return (
    <div className="flex flex-col h-full">
      {comparison && (
        <div className="fixed inset-0 z-50 bg-black/40 p-6 flex items-center justify-center">
          <Card className="w-full max-w-[1000px] max-h-[86vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-[#E2E8F0] flex items-center justify-between">
              <h2 className="text-[18px] font-bold text-[#17212B]">
                원문과 수정문 비교
              </h2>
              <button
                onClick={() => setComparison(null)}
                className={`h-9 px-4 text-[14px] ${OUTLINE_BTN}`}
              >
                닫기
              </button>
            </div>
            <div className="grid grid-cols-2 min-h-0 overflow-y-auto">
              {[comparison.left, comparison.right].map((version, index) => (
                <div
                  key={index}
                  className={`p-6 ${
                    index === 0 ? "border-r border-[#E2E8F0]" : ""
                  }`}
                >
                  <p className="text-[14px] font-semibold text-[#64748B] mb-3">
                    {version.name}
                  </p>
                  <pre className="whitespace-pre-wrap font-sans text-[15px] leading-7 text-[#334155]">
                    {version.content}
                  </pre>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
      <div className="px-6 py-4 bg-white border-b border-[#E2E8F0]">
        <div className="max-w-[1184px] mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Badge type="done" label="분석 완료" />
              <span className="text-[14px] text-[#64748B]">
                {result.writing?.title || "제목 없는 글"} ·{" "}
                {new Date(result.createdAt).toLocaleString("ko-KR")}
              </span>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => void reanalyzeWriting()}
                disabled={reanalyzing}
                className={`h-9 px-4 text-[14px] ${OUTLINE_BTN} disabled:opacity-60`}
              >
                {reanalyzing
                  ? `다시 분석 중 ${reanalyzeProgress}%`
                  : "현재 글 다시 분석"}
              </button>
              <button
                onClick={() => void loadComparison()}
                className={`h-9 px-4 text-[14px] ${OUTLINE_BTN}`}
              >
                원문과 수정문 비교
              </button>
              <span className="h-9 px-4 flex items-center text-[13px] text-[#64748B]">
                결과 자동 저장됨
              </span>
            </div>
          </div>

          <div className="flex gap-3 overflow-x-auto pb-1">
            {metrics.map((m) => (
              <div
                key={m.label}
                className="shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg border"
                style={{ background: m.bg, borderColor: m.color + "30" }}
              >
                <span
                  className="text-[15px] font-bold"
                  style={{ color: m.color }}
                >
                  {m.value}
                </span>
                <span className="text-[13px] text-[#334155]">{m.label}</span>
              </div>
            ))}
          </div>

          <p className="text-[13px] text-[#64748B] mt-2 flex items-center gap-1.5">
            <span className="text-[#087F8C]">
              <SvgIcon
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                cls="w-4 h-4"
              />
            </span>
            {result.disclaimer}
          </p>

          <div className="flex flex-wrap gap-2 mt-3">
            <span className="px-3 py-1.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-[13px] text-[#475569]">
              형태소 분석 신뢰도:{" "}
              {result.details?.linguisticAnalysis?.morphologicalConfidence ==
              null
                ? "계산 불가"
                : `${Math.round(result.details.linguisticAnalysis.morphologicalConfidence * 100)}%`}
            </span>
            <span className="px-3 py-1.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-[13px] text-[#475569]">
              보호된 직접 인용문:{" "}
              {result.details?.linguisticAnalysis?.quotations.length ?? 0}개
            </span>
            <span
              className={`px-3 py-1.5 rounded-lg border text-[13px] ${
                dictionaryVerification?.status === "available"
                  ? "bg-[#E9F7EF] border-[#237A45]/20 text-[#237A45]"
                  : "bg-[#FFF4E5] border-[#B45309]/20 text-[#8A4B08]"
              }`}
            >
              공식 사전 보조 검증:{" "}
              {dictionaryVerification?.status === "available"
                ? "사용 가능"
                : "제한됨"}
            </span>
          </div>
          {dictionaryVerification?.status !== "available" &&
            dictionaryVerification?.notice && (
              <p className="text-[13px] text-[#8A4B08] mt-2">
                {dictionaryVerification.notice} 나머지 분석 결과와 의미 점수에는
                감점하지 않았습니다.
              </p>
            )}

          <div className="flex gap-1 mt-4">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-[14px] font-medium transition-colors ${
                  activeTab === tab.id
                    ? "bg-[#087F8C] text-white"
                    : "text-[#475569] hover:bg-[#F1F5F9]"
                }`}
              >
                {tab.label}
                <span
                  className={`text-[12px] px-1.5 py-0.5 rounded-full ${
                    activeTab === tab.id
                      ? "bg-white/20 text-white"
                      : "bg-[#E2E8F0] text-[#64748B]"
                  }`}
                >
                  {tab.count}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Left: annotated text */}
        <div className="flex-[58] border-r border-[#E2E8F0] overflow-y-auto p-6">
          <div className="max-w-[680px] space-y-4">
            {visibleSentences.map((s) => {
              const isSelected = selected === s.id
              const related = result.findings.find(
                (item) =>
                  s.text.includes(item.current) ||
                  item.current.includes(s.text),
              )
              const isConfirmed =
                related?.status === "confirmed" || related?.status === "applied"
              const role = s.userRole || s.autoRole || "분류되지 않음"
              const decoration = related ? findingType(related) : null
              return (
                <div
                  key={s.id}
                  onClick={() => setSelected(s.id)}
                  className={`flex gap-3 p-3 rounded-lg cursor-pointer transition-colors border-l-2 ${
                    isSelected
                      ? "bg-[#F0FAF9] border-[#087F8C]"
                      : "hover:bg-[#F8FAFC] border-transparent"
                  } ${isConfirmed ? "bg-[#E9F7EF]/50" : ""}`}
                >
                  <div className="flex flex-col items-center gap-1 shrink-0 pt-0.5">
                    <span className="text-[11px] text-[#AAB4C3] font-mono">
                      {s.sentenceNumber}
                    </span>
                    <span
                      className={`text-[11px] px-1.5 py-0.5 rounded font-semibold whitespace-nowrap ${ROLE_STYLE[role]}`}
                    >
                      {role}
                    </span>
                  </div>
                  <p
                    className={`text-[16px] leading-7 text-[#334155] ${
                      decoration && !isConfirmed ? UNDERLINE[decoration] : ""
                    } ${isConfirmed ? "text-[#237A45]" : ""}`}
                  >
                    {s.text}
                    {isConfirmed && (
                      <span className="ml-2 text-[#237A45] inline-flex items-center gap-1 text-[13px] font-semibold">
                        확인 완료{" "}
                        <SvgIcon d="M5 13l4 4L19 7" cls="w-4 h-4" sw={2.5} />
                      </span>
                    )}
                  </p>
                </div>
              )
            })}
          </div>
        </div>

        {/* Right: finding detail */}
        <div className="flex-[42] overflow-y-auto p-5">
          {selectedSentence ? (
            <div className="space-y-3">
              {finding ? (
                <div
                  className={`p-5 rounded-xl border ${FINDING_BG[findingType(finding)]}`}
                >
                  <div className="flex items-center gap-2 mb-3">
                    <Badge {...FINDING_BADGE[findingType(finding)]} />
                    <span className="text-[15px] font-semibold text-[#17212B]">
                      {finding.title}
                    </span>
                  </div>
                  <div className="space-y-2 mb-3">
                    <div className="bg-white/70 rounded-lg p-3">
                      <p className="text-[12px] font-semibold text-[#64748B] mb-1">
                        현재 표현
                      </p>
                      <p className="text-[15px] text-[#17212B] font-medium">
                        {finding.current}
                      </p>
                    </div>
                    {finding.suggestion && (
                      <div className="bg-white/70 rounded-lg p-3">
                        <p className="text-[12px] font-semibold text-[#64748B] mb-1">
                          수정 제안
                        </p>
                        <p
                          className="text-[15px] font-medium"
                          style={{ color: "#237A45" }}
                        >
                          {finding.suggestion}
                        </p>
                      </div>
                    )}
                  </div>
                  <div className="bg-white/70 rounded-lg p-3 mb-3">
                    <p className="text-[12px] font-semibold text-[#64748B] mb-1">
                      판정 이유
                    </p>
                    <p className="text-[15px] text-[#334155] leading-6">
                      {finding.reason}
                    </p>
                  </div>
                  {finding.rule && (
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-[13px] text-[#64748B]">
                        관련 규정:
                      </span>
                      <button className="text-[13px] text-[#2563A6] font-semibold hover:underline">
                        {finding.rule}
                      </button>
                    </div>
                  )}
                  <div className="flex items-center gap-2 mb-4">
                    <span className="text-[13px] text-[#64748B]">
                      판정 신뢰도
                    </span>
                    <Badge
                      type={
                        confidenceLabel(finding.confidence) === "높음"
                          ? "success"
                          : confidenceLabel(finding.confidence) === "보통"
                            ? "warning"
                            : "neutral"
                      }
                      label={confidenceLabel(finding.confidence)}
                    />
                  </div>
                  <div className="flex gap-2">
                    {finding.suggestion &&
                      finding.status !== "applied" &&
                      !finding.metadata.contextRequired &&
                      !finding.metadata.protectedQuote && (
                        <PrimaryBtn
                          onClick={() => void actOnFinding("apply")}
                          disabled={saving}
                          className="flex-1 h-10 text-[14px]"
                        >
                          수정 적용
                        </PrimaryBtn>
                      )}
                    <button
                      onClick={() => void actOnFinding("confirm")}
                      disabled={saving}
                      className={`flex-1 h-10 px-3 text-[14px] ${OUTLINE_BTN}`}
                    >
                      확인 완료
                    </button>
                    <button
                      onClick={() => void actOnFinding("ignore")}
                      disabled={saving}
                      className={`h-10 px-3 text-[14px] ${OUTLINE_BTN}`}
                    >
                      무시
                    </button>
                  </div>
                </div>
              ) : (
                <Card className="p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Badge type="success" label="별도 수정 제안 없음" />
                    <span className="text-[13px] text-[#64748B]">
                      {selectedSentence.sentenceNumber}번 문장
                    </span>
                  </div>
                  <p className="text-[14px] leading-6 text-[#334155]">
                    {selectedSentence.rationale ||
                      "이 문장에서는 자동 수정이 필요한 항목이 발견되지 않았습니다."}
                  </p>
                </Card>
              )}

              {linguisticSentence && (
                <Card className="p-4">
                  <p className="text-[13px] font-semibold text-[#64748B] mb-3">
                    형태소·의미 역할
                  </p>
                  <div className="grid grid-cols-2 gap-2 text-[13px]">
                    <p>
                      <span className="text-[#64748B]">기본형</span>
                      <br />
                      <span className="font-semibold text-[#334155]">
                        {linguisticSentence.morphology.mainVerb || "확인 필요"}
                      </span>
                    </p>
                    <p>
                      <span className="text-[#64748B]">극성·양태</span>
                      <br />
                      <span className="font-semibold text-[#334155]">
                        {linguisticSentence.morphology.polarity} ·{" "}
                        {linguisticSentence.morphology.modality}
                      </span>
                    </p>
                    <p>
                      <span className="text-[#64748B]">주체</span>
                      <br />
                      <span className="font-semibold text-[#334155]">
                        {linguisticSentence.semanticRoles.subject.join(", ") ||
                          "추출되지 않음"}
                      </span>
                    </p>
                    <p>
                      <span className="text-[#64748B]">대상</span>
                      <br />
                      <span className="font-semibold text-[#334155]">
                        {linguisticSentence.semanticRoles.target.join(", ") ||
                          "추출되지 않음"}
                      </span>
                    </p>
                  </div>
                  <p className="mt-3 text-[12px] text-[#64748B]">
                    형태소 신뢰도{" "}
                    {Math.round(linguisticSentence.morphology.confidence * 100)}
                    % · 사동{" "}
                    {linguisticSentence.morphology.causative ? "있음" : "없음"}{" "}
                    · 피동{" "}
                    {linguisticSentence.morphology.passive ? "있음" : "없음"}
                  </p>
                </Card>
              )}

              {selectedArgumentLink && (
                <Card className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-[13px] font-semibold text-[#64748B]">
                      주장·근거 연결
                    </p>
                    <Badge
                      type={
                        selectedArgumentLink.score >= 7 ? "success" : "warning"
                      }
                      label={`${selectedArgumentLink.score}/9점`}
                    />
                  </div>
                  <p className="text-[13px] text-[#334155] leading-5">
                    <span className="font-semibold">주장:</span>{" "}
                    {selectedArgumentLink.claimText}
                  </p>
                  <p className="text-[13px] text-[#334155] leading-5 mt-1">
                    <span className="font-semibold">근거:</span>{" "}
                    {selectedArgumentLink.evidenceText}
                  </p>
                </Card>
              )}

              <Card className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-[13px] font-semibold text-[#64748B]">
                    PEEL 구조 상태
                  </p>
                  <span className="text-[12px] text-[#64748B]">
                    {selectedPeel
                      ? `${selectedPeel.paragraphNumber}문단 기준`
                      : "판정 자료 없음"}
                  </span>
                </div>
                <div className="flex gap-3">
                  {[
                    { key: "P" as const, label: "P", desc: "주장" },
                    { key: "E1" as const, label: "E", desc: "근거" },
                    { key: "E2" as const, label: "E", desc: "설명" },
                    { key: "L" as const, label: "L", desc: "연결" },
                  ].map((element) => {
                    const satisfied =
                      selectedPeel?.elements[element.key] === "충족"
                    return (
                      <div key={element.key} className="flex-1 text-center">
                        <div
                          className={`w-8 h-8 rounded-full flex items-center justify-center mx-auto mb-1 text-[14px] font-bold ${
                            satisfied
                              ? "bg-[#E9F7EF] text-[#237A45]"
                              : "bg-[#FFF4E5] text-[#B45309]"
                          }`}
                          title={
                            selectedPeel
                              ? selectedPeel.elements[element.key] ||
                                "보완 필요"
                              : "판정 자료 없음"
                          }
                        >
                          {element.label}
                        </div>
                        <p className="text-[11px] text-[#64748B]">
                          {element.desc}
                        </p>
                      </div>
                    )
                  })}
                </div>
                {selectedPeel && (
                  <div className="mt-3 pt-3 border-t border-[#E2E8F0] text-[13px] leading-5">
                    <p className="text-[#334155]">{selectedPeel.rationale}</p>
                    {selectedPeel.guidance && (
                      <p className="text-[#8A4B08] mt-1">
                        보완 안내: {selectedPeel.guidance}
                      </p>
                    )}
                  </div>
                )}
              </Card>
            </div>
          ) : (
            <div className="h-48 flex flex-col items-center justify-center text-center">
              <span className="text-[#CBD5E1] mb-3">
                <SvgIcon d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </span>
              <p className="text-[15px] font-medium text-[#AAB4C3]">
                문장을 선택하면 분석 결과가 표시됩니다
              </p>
            </div>
          )}
          {loadError && (
            <p role="alert" className="mt-4 text-[14px] text-[#C62828]">
              {loadError}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Criteria ─────────────────────────────────────────────────────────────────
function CriteriaScreen() {
  const rubricStatus = (value: string) => ["확인 완료", "등록 완료"].includes(value) ? "확인 완료" : ["확인 필요", "OCR 확인 필요"].includes(value) ? "확인 필요" : value
  const [items, setItems] = useState<RubricData[]>([])
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("")
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState("")
  const [ocrDialog, setOcrDialog] = useState<OcrDialogModel | null>(null)
  const [ocrBusy, setOcrBusy] = useState(false)
  const [ocrError, setOcrError] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<RubricData | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    try {
      setItems(await api.get<RubricData[]>("/rubrics?pageSize=100"))
      setLoadError("")
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }
  useEffect(() => {
    void load()
  }, [])

  const upload = async (file?: File) => {
    if (!file) return
    const form = new FormData()
    form.append("file", file)
    setBusy(true)
    try {
      await api.post("/rubrics", form)
      await load()
    } catch (error) {
      setLoadError(errorMessage(error))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const remove = async () => {
    if (!deleteTarget) return
    try {
      await api.delete(`/rubrics/${deleteTarget.id}`)
      await load()
      setDeleteTarget(null)
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }

  const openOcr = async (item: RubricData) => {
    try {
      const detail = await api.get<RubricData>(`/rubrics/${item.id}`)
      const statusCode =
        detail.ocr?.status ??
        (detail.correctedText?.trim() || detail.ocrText?.trim() ? "not_required" :
        (detail.status.includes("환경")
          ? "unavailable"
          : detail.status.includes("실패")
            ? "failed"
            : "completed"))
      setOcrError("")
      setOcrDialog({
        kind: "rubric",
        id: detail.id,
        fileName: detail.originalName || detail.name,
        mimeType: detail.mimeType || "application/octet-stream",
        pageCount: detail.pages || 1,
        status: detail.status,
        statusCode,
        reason:
          detail.ocr?.message ||
          (statusCode === "unavailable"
            ? "이미지에서 글자를 읽으려면 서버 컴퓨터의 한글 OCR 환경이 필요합니다."
            : "추출 결과를 원본과 비교해 확인해야 합니다."),
        previewUrl: detail.fileId
          ? `/api/files/rubrics/${detail.fileId}`
          : `/api/files/rubrics/${detail.id}`,
        pages:
          detail.correctedText || detail.ocrText
            ? [
                {
                  pageNumber: 1,
                  text: detail.correctedText ?? detail.ocrText ?? "",
                  confidence: undefined,
                  method: statusCode === "not_required" ? "native_text" : "ocr",
                },
              ]
            : [],
      })
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }

  const runOcr = async () => {
    if (!ocrDialog || ocrBusy) return
    setOcrBusy(true)
    setOcrError("")
    try {
      const detail = await api.post<RubricData>(`/rubrics/${ocrDialog.id}/ocr`)
      const extractedPages = detail.ocrPages ?? []
      setOcrDialog((current) =>
        current
          ? {
              ...current,
              status: detail.status,
              statusCode: detail.ocr?.status ?? current.statusCode,
              reason: detail.ocr?.message ?? current.reason,
              pageCount: detail.pages || current.pageCount,
              pages: extractedPages.length
                ? extractedPages
                    .filter((page) => (page.text ?? "").length > 0)
                    .map((page) => ({
                      pageNumber: page.page ?? page.pageNumber ?? 1,
                      text: page.text ?? "",
                      confidence: page.confidence,
                      method: page.method ?? "ocr",
                    }))
                : detail.correctedText || detail.ocrText
                  ? [
                      {
                        pageNumber: 1,
                        text: detail.correctedText ?? detail.ocrText ?? "",
                        confidence: detail.ocrConfidence,
                        method: "ocr",
                      },
                    ]
                  : [],
            }
          : current,
      )
      await load()
    } catch (error) {
      setOcrError(errorMessage(error))
    } finally {
      setOcrBusy(false)
    }
  }

  const saveOcr = async () => {
    if (!ocrDialog || ocrBusy) return
    setOcrBusy(true)
    setOcrError("")
    try {
      await api.patch(`/rubrics/${ocrDialog.id}`, {
        correctedText: ocrDialog.pages.map((page) => page.text).join("\n\n"),
        confirm: true,
      })
      await load()
      setOcrDialog(null)
    } catch (error) {
      setOcrError(errorMessage(error))
    } finally {
      setOcrBusy(false)
    }
  }

  const visible = items.filter(
    (item) =>
      item.name.toLowerCase().includes(search.toLowerCase()) &&
      (!status || rubricStatus(item.status) === status),
  )
  const badge = (value: string): BadgeType =>
    rubricStatus(value) === "확인 완료"
      ? "success"
      : rubricStatus(value) === "확인 필요" || value.includes("OCR")
        ? "warning"
        : value.includes("실패") || value.includes("환경")
          ? "error"
          : "neutral"

  return (
    <div className="p-3 sm:p-8 max-w-[1184px] mx-auto space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "전체 평가 기준 자료", value: `${items.length}개` },
          {
            label: "사용 가능한 기준 카드",
              value: `${items.filter((file) => rubricStatus(file.status) === "확인 완료").reduce((sum, file) => sum + file.cards, 0)}개`,
          },
          {
            label: "사용자 확인 필요",
            value: `${items.filter((file) => rubricStatus(file.status) === "확인 필요" || file.status.includes("OCR")).length}개`,
            highlight: true,
          },
          {
            label: "사람의 판단 필요 기준",
            value: `${items.reduce((sum, file) => sum + (file.items?.filter((criterion) => criterion.checkType === "사람의 판단 필요").length ?? 0), 0)}개`,
          },
        ].map((s) => (
          <div
            key={s.label}
            className={`p-5 rounded-xl border ${
              s.highlight
                ? "border-[#B45309]/30 bg-[#FFF4E5]"
                : "bg-white border-[#E2E8F0]"
            } shadow-[0_1px_3px_rgba(16,42,67,0.06)]`}
          >
            <p className="text-[24px] font-bold text-[#17212B]">{s.value}</p>
            <p className="text-[14px] text-[#64748B] mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2 min-w-0">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="파일명 검색..."
            className="h-10 px-4 rounded-lg border border-[#CBD5E1] text-[15px] w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
          />
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="h-10 px-3 rounded-lg border border-[#CBD5E1] text-[15px] text-[#475569] bg-white focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
          >
            <option value="">OCR 상태 전체</option>
            <option value="확인 완료">확인 완료</option>
            <option value="확인 필요">확인 필요</option>
            <option value="OCR 실행 환경 필요">실행 환경 필요</option>
            <option value="OCR 일부 완료">일부 완료</option>
            <option value="처리 실패">처리 실패</option>
          </select>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,text/plain,.pdf,.txt"
          className="hidden"
          onChange={(event) => void upload(event.target.files?.[0])}
        />
        <PrimaryBtn
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="flex items-center gap-2 h-10 px-5 text-[15px]"
        >
          <SvgIcon d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />{" "}
          자료 업로드
        </PrimaryBtn>
      </div>

      <p className="text-sm leading-7 text-[#64748B]">텍스트가 포함된 PDF·UTF-8 TXT를 등록하고 추출 글을 확인하세요. 스캔 자료의 OCR은 작품과 근거에서 이용할 수 있습니다.</p>
      <div className="space-y-3">
        {visible.length > 0 ? (
          visible.map((item) => (
            <FileRow
              key={item.id}
              name={item.name}
              pages={item.pages}
              date={new Date(item.date).toLocaleDateString("ko-KR")}
              cards={item.cards || undefined}
              status={badge(item.status)}
              statusLabel={rubricStatus(item.status)}
              onPreview={
                item.fileId
                  ? () =>
                      window.open(
                        `/api/files/rubrics/${item.fileId}`,
                        "_blank",
                        "noopener,noreferrer",
                      )
                  : undefined
              }
              onDelete={() => setDeleteTarget(item)}
              onOcr={item.correctedText?.trim() || item.ocrText?.trim() ? () => void openOcr(item) : undefined}
            />
          ))
        ) : (
          <Card>
            <EmptyState
              title="등록된 평가 기준이 없습니다"
              desc="자료 업로드 버튼으로 평가 기준 파일을 추가해 주세요."
            />
          </Card>
        )}
      </div>
      {loadError && (
        <p role="alert" className="text-[14px] text-[#C62828]">
          {loadError}
        </p>
      )}
      {ocrDialog && (
        <OcrDialog
          model={ocrDialog}
          busy={ocrBusy}
          error={ocrError}
          onChangePage={(pageNumber, text) =>
            setOcrDialog((current) =>
              current
                ? {
                    ...current,
                    pages: current.pages.map((page) =>
                      page.pageNumber === pageNumber ? { ...page, text } : page,
                    ),
                  }
                : current,
            )
          }
          onRun={() => void runOcr()}
          onSave={() => void saveOcr()}
          onClose={() => {
            if (!ocrBusy) setOcrDialog(null)
          }}
        />
      )}
      {deleteTarget && (
        <ConfirmDialog
          title="평가 기준을 삭제할까요?"
          description={`'${deleteTarget.name}' 자료와 연결된 OCR 결과가 삭제됩니다.`}
          confirmLabel="삭제"
          onConfirm={() => void remove()}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  )
}

// ─── New Analysis ─────────────────────────────────────────────────────────────
function NewAnalysisScreen({
  onNav,
  onOpenAnalysis,
}: {
  onNav: (s: Screen) => void
  onOpenAnalysis: (id: string) => void
}) {
  const [step, setStep] = useState(1)
  const [title, setTitle] = useState("")
  const [work, setWork] = useState("")
  const [author, setAuthor] = useState("")
  const [question, setQuestion] = useState("")
  const [text, setText] = useState(INITIAL_TEXT)
  const [writingId, setWritingId] = useState<string | null>(null)
  const [revisionNumber, setRevisionNumber] = useState(0)
  const [saveMessage, setSaveMessage] = useState("")
  const [formError, setFormError] = useState("")
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobProgress, setJobProgress] = useState(0)
  const [jobStep, setJobStep] = useState("")

  const writingPayload = (status = "임시 저장") => ({
    title,
    work,
    author,
    inquiryQuestion: question,
    content: text,
    status,
    revisionNumber,
  })

  const saveDraft = async () => {
    setBusy(true)
    try {
      const saved = writingId
        ? await api.patch<WritingData>(
            `/writings/${writingId}`,
            writingPayload(),
          )
        : await api.post<WritingData>("/writings", writingPayload())
      setWritingId(saved.id)
      setRevisionNumber(saved.revisionNumber)
      setSaveMessage("방금 저장됨")
      setFormError("")
      return saved.id
    } catch (error) {
      setFormError(errorMessage(error))
      return null
    } finally {
      setBusy(false)
    }
  }

  const continueFromBasics = async () => {
    if (!title.trim() || !work.trim() || !question.trim()) {
      setFormError("글 제목, 작품명, 탐구 질문을 모두 입력해 주세요.")
      return
    }
    if (await saveDraft()) setStep(3)
  }

  useEffect(() => {
    if (!writingId || step !== 3) return
    const timer = window.setTimeout(async () => {
      try {
        const saved = await api.post<WritingData>(
          `/writings/${writingId}/autosave`,
          { content: text, revisionNumber },
        )
        setRevisionNumber(saved.revisionNumber)
        setSaveMessage("자동 저장됨")
        setFormError("")
      } catch (error) {
        setFormError(errorMessage(error))
      }
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [text, writingId, step])

  const waitForAnalysis = async (id: string) => {
    for (;;) {
      const job = await api.get<{
        analysisId: string
        status: string
        progress: number
        currentStep: string
        errorMessage?: string
      }>(`/analysis-jobs/${id}`)
      setJobProgress(job.progress)
      setJobStep(job.currentStep)
      if (job.status === "completed") {
        onOpenAnalysis(job.analysisId)
        return
      }
      if (job.status === "failed" || job.status === "cancelled")
        throw new Error(job.errorMessage || "분석 작업이 완료되지 않았습니다.")
      await new Promise((resolve) => window.setTimeout(resolve, 500))
    }
  }

  const startAnalysis = async () => {
    setBusy(true)
    try {
      const id = writingId ?? (await saveDraft())
      if (!id) return
      const saved = await api.patch<WritingData>(`/writings/${id}`, writingPayload("분석 준비"))
      setRevisionNumber(saved.revisionNumber)
      const job = await api.post<{
        analysisId: string
        jobId: string
      }>("/analyses", { writingId: id, content: text, revisionNumber: saved.revisionNumber, analysisTypes: ["전체 분석"] })
      setJobId(job.jobId)
      setJobProgress(0)
      await waitForAnalysis(job.jobId)
    } catch (error) {
      setFormError(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const cancelAnalysis = async () => {
    if (!jobId) return
    try {
      await api.post(`/analysis-jobs/${jobId}/cancel`)
      setFormError("분석 취소를 요청했습니다.")
    } catch (error) {
      setFormError(errorMessage(error))
    }
  }

  return (
    <div className="p-8 max-w-[900px] mx-auto">
      {/* Step indicator */}
      <div className="flex items-center mb-10">
        {ANALYSIS_STEPS.map((s, i) => (
          <div key={s} className="flex items-center flex-1">
            <div className="flex items-center gap-2.5">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-[13px] font-bold transition-colors ${
                  i + 1 < step
                    ? "bg-[#087F8C] text-white"
                    : i + 1 === step
                      ? "bg-[#102A43] text-white"
                      : "bg-[#E2E8F0] text-[#8492A6]"
                }`}
              >
                {i + 1 < step ? (
                  <SvgIcon d="M5 13l4 4L19 7" cls="w-4 h-4" sw={2.5} />
                ) : (
                  i + 1
                )}
              </div>
              <span
                className={`text-[14px] font-medium whitespace-nowrap ${
                  i + 1 === step ? "text-[#17212B]" : "text-[#8492A6]"
                }`}
              >
                {s}
              </span>
            </div>
            {i < ANALYSIS_STEPS.length - 1 && (
              <div
                className={`flex-1 h-px mx-3 ${
                  i + 1 < step ? "bg-[#087F8C]" : "bg-[#E2E8F0]"
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {step === 1 && (
        <Card className="p-8">
          <h2 className="text-[20px] font-bold text-[#17212B] mb-6">
            기본 정보 입력
          </h2>
          <div className="space-y-5">
            <div>
              <Label required>글 제목</Label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className={INPUT_CLS}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label required>작품명</Label>
                <input
                  value={work}
                  onChange={(e) => setWork(e.target.value)}
                  className={INPUT_CLS}
                />
              </div>
              <div>
                <Label>작가</Label>
                <input
                  value={author}
                  onChange={(e) => setAuthor(e.target.value)}
                  className={INPUT_CLS}
                />
              </div>
            </div>
            <div>
              <Label required>탐구 질문</Label>
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                rows={2}
                className="w-full px-4 py-3 rounded-lg border border-[#CBD5E1] text-[16px] focus:outline-none focus:ring-2 focus:ring-[#087F8C] resize-none"
              />
              <p className="text-[13px] text-[#64748B] mt-1.5 flex items-center gap-1.5">
                <span className="text-[#087F8C]">
                  <SvgIcon
                    d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    cls="w-4 h-4"
                  />
                </span>
                탐구 질문은 문단과 글 전체가 중심 주제에 연결되어 있는지 확인할
                때 사용됩니다.
              </p>
            </div>
          </div>
          <div className="flex justify-end gap-3 mt-8">
            <button
              onClick={() => onNav("dashboard")}
              className={`h-12 px-6 text-[16px] ${OUTLINE_BTN}`}
            >
              취소
            </button>
            <button
              onClick={() => void saveDraft()}
              disabled={busy}
              className={`h-12 px-6 text-[16px] disabled:opacity-40 ${OUTLINE_BTN}`}
            >
              임시 저장
            </button>
            <PrimaryBtn
              onClick={() => void continueFromBasics()}
              disabled={busy}
              className="h-12 px-8 text-[16px]"
            >
              다음 단계
            </PrimaryBtn>
          </div>
        </Card>
      )}

      {step === 3 && (
        <Card className="overflow-hidden">
          <div className="px-6 py-4 border-b border-[#E2E8F0] flex items-center justify-between">
            <div>
              <p className="text-[15px] font-semibold text-[#17212B]">
                {title}
              </p>
              <p className="text-[12px] text-[#64748B]">
                {saveMessage || "저장 대기 중"}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => void cancelAnalysis()}
                disabled={!jobId}
                className={`h-8 px-3 text-[13px] disabled:opacity-40 ${OUTLINE_BTN}`}
              >
                실행 취소
              </button>
              <button className={`h-8 px-3 text-[13px] ${OUTLINE_BTN}`}>
                문단 구분 표시
              </button>
            </div>
          </div>
          <div className="flex">
            <div className="flex-1">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="w-full min-h-[360px] p-6 text-[16px] leading-8 text-[#17212B] resize-none focus:outline-none"
              />
              <div className="px-6 py-4 border-t border-[#E2E8F0] bg-[#F8FAFC] flex gap-6 text-[14px] text-[#64748B]">
                <span>
                  글자 수:{" "}
                  <strong className="text-[#17212B]">
                    {text.length.toLocaleString()}자
                  </strong>
                </span>
                <span>
                  문단 수:{" "}
                  <strong className="text-[#17212B]">
                    {text.split("\n\n").filter(Boolean).length}문단
                  </strong>
                </span>
                <span>
                  직접 인용 추정:{" "}
                  <strong className="text-[#17212B]">0개</strong>
                </span>
              </div>
            </div>
            <div className="w-52 shrink-0 border-l border-[#E2E8F0] p-4">
              <p className="text-[13px] font-semibold text-[#334155] mb-3">
                작성 안내
              </p>
              <div className="space-y-3 text-[13px] text-[#64748B] leading-5">
                {[
                  "주장은 무엇을 보여 주는지 분명하게 작성해 보세요.",
                  "근거 뒤에는 그 표현의 의미와 효과를 설명해 보세요.",
                  "문단의 마지막에는 탐구 질문과의 연결을 확인해 보세요.",
                ].map((t) => (
                  <p key={t} className="p-2.5 bg-[#F0FAF9] rounded-lg">
                    {t}
                  </p>
                ))}
              </div>
            </div>
          </div>
          <div className="flex justify-between items-center px-6 py-4 border-t border-[#E2E8F0] bg-[#F8FAFC]">
            <button
              onClick={() => setStep(1)}
              className={`h-11 px-5 text-[15px] ${OUTLINE_BTN}`}
            >
              이전 단계
            </button>
            <div className="flex gap-3">
              <button
                onClick={() => void saveDraft()}
                disabled={busy}
                className={`h-11 px-5 text-[15px] disabled:opacity-40 ${OUTLINE_BTN}`}
              >
                임시 저장
              </button>
              <PrimaryBtn
                onClick={async () => {
                  if (await saveDraft()) setStep(4)
                }}
                disabled={busy || !text.trim()}
                className="h-11 px-6 text-[15px]"
              >
                다음 단계
              </PrimaryBtn>
            </div>
          </div>
        </Card>
      )}

      {step === 4 && (
        <Card className="p-8">
          <h2 className="text-[20px] font-bold text-[#17212B] mb-6">
            분석 설정
          </h2>
          <div className="grid grid-cols-2 gap-4 mb-8">
            {ANALYSIS_TYPES.map((item) => (
              <div
                key={item.label}
                className={`p-4 rounded-xl border-2 cursor-pointer transition-colors ${
                  item.checked
                    ? "border-[#087F8C] bg-[#F0FAF9]"
                    : "border-[#E2E8F0] hover:border-[#CBD5E1]"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={`w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 mt-0.5 ${
                      item.checked
                        ? "border-[#087F8C] bg-[#087F8C]"
                        : "border-[#CBD5E1]"
                    }`}
                  >
                    {item.checked && (
                      <SvgIcon d="M5 13l4 4L19 7" cls="w-4 h-4" sw={2.5} />
                    )}
                  </div>
                  <div>
                    <p className="text-[15px] font-semibold text-[#17212B]">
                      {item.label}
                    </p>
                    <p className="text-[13px] text-[#64748B] mt-0.5 leading-5">
                      {item.desc}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="p-5 bg-[#F8FAFC] rounded-xl border border-[#E2E8F0] mb-6">
            <p className="text-[14px] font-semibold text-[#64748B] mb-3">
              분석 전 최종 확인
            </p>
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-[14px]">
              {[
                ["글 제목", title],
                ["작품명", work],
                ["글자 수", `${text.length.toLocaleString()}자`],
                ["선택한 평가 기준", "선택 안 함"],
                ["선택한 작품 자료", "선택 안 함"],
                ["분석 종류", "전체 분석"],
              ].map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-[#64748B] shrink-0">{k}:</span>
                  <span className="font-medium text-[#17212B] truncate">
                    {v}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="flex justify-between">
            <button
              onClick={() => setStep(3)}
              className={`h-12 px-6 text-[16px] ${OUTLINE_BTN}`}
            >
              이전 단계
            </button>
            <PrimaryBtn
              onClick={() => void startAnalysis()}
              disabled={busy || !text.trim()}
              className="h-12 px-10 text-[17px]"
            >
              {busy ? `분석 중 ${jobProgress}%` : "분석 시작"}
            </PrimaryBtn>
          </div>
          {jobStep && busy && (
            <div className="mt-4">
              <div className="h-2 rounded-full bg-[#E2E8F0] overflow-hidden">
                <div
                  className="h-full bg-[#087F8C] transition-all"
                  style={{ width: `${jobProgress}%` }}
                />
              </div>
              <p className="text-[13px] text-[#64748B] mt-2">{jobStep}</p>
            </div>
          )}
        </Card>
      )}
      {formError && (
        <p role="alert" className="mt-4 text-[14px] text-[#C62828]">
          {formError}
        </p>
      )}
    </div>
  )
}

// ─── History ──────────────────────────────────────────────────────────────────
function HistoryScreen({
  onNav,
  onOpenAnalysis,
}: {
  onNav: (s: Screen) => void
  onOpenAnalysis: (id: string) => void
}) {
  const [records, setRecords] = useState<RecordData[]>([])
  const [titleSearch, setTitleSearch] = useState("")
  const [workSearch, setWorkSearch] = useState("")
  const [status, setStatus] = useState("")
  const [loadError, setLoadError] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<RecordData | null>(null)

  const load = async () => {
    try {
      setRecords(await api.get<RecordData[]>("/records?pageSize=100"))
      setLoadError("")
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }
  useEffect(() => {
    void load()
  }, [])
  const historyRows = records.flatMap<HistoryRow>((record): HistoryRow[] => {
    const runs = record.analysisRuns ?? []
    if (!runs.length) {
      return [
        {
          ...record,
          rowKey: `${record.id}:draft`,
          analysisId: null,
          analysisCreatedAt: record.updatedAt,
          analysisStatus: record.status,
          analysisVersion: `글 ${record.revisionNumber || 1}판`,
          analysisMetrics: {},
        },
      ]
    }
    return runs.map((run, index) => ({
      ...record,
      rowKey: `${record.id}:${run.id}`,
      analysisId: run.id,
      analysisCreatedAt: run.createdAt,
      analysisStatus:
        run.status === "completed"
          ? "분석 완료"
          : run.status === "processing"
            ? "분석 중"
            : "분석 실패",
      analysisVersion: `분석 ${runs.length - index}회`,
      analysisMetrics: run.metrics ?? {},
    }))
  })
  const visible = historyRows.filter(
    (row) =>
      row.title.toLowerCase().includes(titleSearch.toLowerCase()) &&
      row.work.toLowerCase().includes(workSearch.toLowerCase()) &&
      (!status || row.analysisStatus === status),
  )
  const badge = (value: string): BadgeType =>
    value === "분석 완료"
      ? "done"
      : value === "수정 중" || value === "분석 중"
        ? "warning"
        : "draft"
  const remove = async () => {
    if (!deleteTarget) return
    try {
      await api.delete(`/records/${deleteTarget.id}`, {
        confirmation: deleteTarget.title || "삭제",
      })
      await load()
      setDeleteTarget(null)
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }

  return (
    <div className="p-8 max-w-[1184px] mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <input
          value={titleSearch}
          onChange={(event) => setTitleSearch(event.target.value)}
          placeholder="글 제목 검색..."
          className="h-10 px-4 rounded-lg border border-[#CBD5E1] text-[15px] w-56 focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
        />
        <input
          value={workSearch}
          onChange={(event) => setWorkSearch(event.target.value)}
          placeholder="작품명 검색..."
          className="h-10 px-4 rounded-lg border border-[#CBD5E1] text-[15px] w-44 focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
        />
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-10 px-3 rounded-lg border border-[#CBD5E1] text-[15px] text-[#475569] bg-white focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
        >
          <option value="">상태 전체</option>
          <option>분석 완료</option>
          <option>수정 중</option>
          <option>임시 저장</option>
        </select>
      </div>
      <Card className="overflow-hidden">
        {visible.length > 0 ? (
          <table className="w-full">
            <thead>
              <tr className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                <th className="px-4 py-3 w-10">
                  <input type="checkbox" className="accent-[#087F8C]" />
                </th>
                {[
                  "분석 날짜",
                  "글 제목",
                  "작품명",
                  "버전",
                  "상태",
                  "PEEL 충족률",
                  "마지막 수정",
                  "",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-[13px] font-semibold text-[#64748B]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr
                  key={row.rowKey}
                  className="border-b border-[#F1F5F9] hover:bg-[#F8FAFC] transition-colors"
                >
                  <td className="px-4 py-4">
                    <input type="checkbox" className="accent-[#087F8C]" />
                  </td>
                  <td className="px-4 py-4 text-[14px] text-[#64748B]">
                    {new Date(row.analysisCreatedAt).toLocaleDateString(
                      "ko-KR",
                    )}
                  </td>
                  <td className="px-4 py-4 text-[15px] font-medium text-[#17212B]">
                    {row.title || "제목 없는 글"}
                  </td>
                  <td className="px-4 py-4 text-[14px] text-[#475569]">
                    {row.work}
                  </td>
                  <td className="px-4 py-4 text-[14px] text-[#64748B]">
                    {row.analysisVersion}
                  </td>
                  <td className="px-4 py-4">
                    <Badge
                      type={badge(row.analysisStatus)}
                      label={row.analysisStatus}
                    />
                  </td>
                  <td className="px-4 py-4 text-[15px] font-semibold text-[#17212B]">
                    {row.analysisMetrics["PEEL 충족률"]?.value == null
                      ? "-"
                      : `${row.analysisMetrics["PEEL 충족률"].value}%`}
                  </td>
                  <td className="px-4 py-4 text-[14px] text-[#64748B]">
                    {new Date(row.updatedAt).toLocaleString("ko-KR")}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap">
                    <button
                      disabled={
                        !row.analysisId || row.analysisStatus !== "분석 완료"
                      }
                      onClick={() =>
                        row.analysisId && onOpenAnalysis(row.analysisId)
                      }
                      className="text-[14px] text-[#087F8C] font-medium hover:underline disabled:text-[#AAB4C3] disabled:no-underline"
                    >
                      결과 다시 보기
                    </button>
                    <button
                      onClick={() => setDeleteTarget(row)}
                      className="ml-3 text-[14px] text-[#C62828] hover:underline"
                    >
                      글 삭제
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState
            title="분석 기록이 없습니다"
            desc="새 글 분석을 완료하거나 임시 저장하면 기록이 표시됩니다."
          />
        )}
      </Card>
      {loadError && (
        <p role="alert" className="text-[14px] text-[#C62828]">
          {loadError}
        </p>
      )}
      {deleteTarget && (
        <ConfirmDialog
          title="글과 모든 분석 기록을 삭제할까요?"
          description={`'${deleteTarget.title || "제목 없는 글"}' 글과 연결된 모든 분석 회차가 삭제됩니다.`}
          confirmLabel="삭제"
          onConfirm={() => void remove()}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  )
}

// ─── Works ────────────────────────────────────────────────────────────────────
function SourcePreview({ value, onClose }: { value: { id: string; title: string; content: string; accessMode?: string }; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog ref={dialog} onCancel={onClose} onClose={onClose} aria-label="자료 본문 미리보기" className="w-[calc(100%_-_2rem)] max-w-4xl max-h-[90vh] rounded-xl bg-white p-5 overflow-auto"><div className="flex justify-between gap-3"><h2>{value.title}</h2>{value.accessMode === "DOWNLOAD" && <a className={OUTLINE_BTN} href={`/api/files/source/${value.id}`}>원본 다운로드</a>}<button autoFocus className={OUTLINE_BTN} onClick={onClose}>닫기</button></div><pre className="whitespace-pre-wrap break-words text-sm leading-7 mt-5">{value.content}</pre></dialog>
}

function WorksScreen({ account }: { account: AccountSession }) {
  const [textEntry, setTextEntry] = useState(false)
  const [ocrModeOpen, setOcrModeOpen] = useState(false)
  const uploadButton = useRef<HTMLButtonElement>(null)
  const ocrMode = useRef<OcrMode>("precise")
  const ocrProfile = useRef("auto")
  const [ocrReview, setOcrReview] = useState<{ id: string; accessMode: string } | null>(null)
  const [publicReference, setPublicReference] = useState(false)
  const [previewText, setPreviewText] = useState<{ id: string; title: string; content: string; accessMode?: string } | null>(null)
  const [tab, setTab] = useState<"works" | "citations">("works")
  const [works, setWorks] = useState<SourceData[]>([])
  const [quotes, setQuotes] = useState<QuoteData[]>([])
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState("")
  const [scopeTarget, setScopeTarget] = useState<SourceData | null>(null)
  const [scopeBusy, setScopeBusy] = useState(false)
  const [scopeError, setScopeError] = useState("")
  const [scopeMessage, setScopeMessage] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<WorksDeleteTarget | null>(
    null,
  )
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    try {
      const [sourceData, quoteData] = await Promise.all([
        api.get<SourceData[]>("/source-documents?pageSize=100"),
        api.get<QuoteData[]>("/quote-cards?pageSize=100"),
      ])
      setWorks(sourceData)
      setQuotes(quoteData)
      setLoadError("")
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }
  useEffect(() => {
    void load()
  }, [])

  const upload = async (file?: File) => {
    if (!file) return
    const form = new FormData()
    form.append("file", file)
    form.append("ocrMode", ocrMode.current)
    form.append("ocrProfile", ocrProfile.current)
    if (publicReference) {
      form.append("scope", "PUBLIC")
      form.append("documentType", "REFERENCE")
      form.append("accessMode", "DOWNLOAD")
      form.append("rightsConfirmed", "true")
      form.append("rightsInfo", "2026-10-11 사용자 제공 PDF 전체 공용 등록·활용 승인. 별도 공식 라이선스 검증 아님.")
    }
    setBusy(true)
    try {
      const saved = await api.post<SourceData>("/source-documents", form)
      await load()
      if (saved.ocr?.reviewAvailable) setOcrReview({ id: saved.id, accessMode: saved.accessMode ?? "VIEW" })
    } catch (error) {
      setLoadError(errorMessage(error))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const removeSource = async (item: SourceData) => {
    try {
      await api.delete(`/source-documents/${item.id}`)
      await load()
      setDeleteTarget(null)
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }

  const changeScope = async () => {
    if (!scopeTarget || scopeBusy) return
    setScopeBusy(true)
    setScopeError("")
    try {
      const saved = await api.patch<SourceData>(`/source-documents/${scopeTarget.id}/scope`, {
        scope: scopeTarget.scope === "PUBLIC" ? "PRIVATE" : "PUBLIC",
        expectedRevisionId: scopeTarget.latestRevisionId,
      })
      // Update only after server confirmation; failed requests keep the old row.
      setWorks(current => current.map(item => item.id === saved.id ? saved : item))
      setScopeMessage(saved.scope === "PUBLIC" ? "공용으로 전환했습니다." : "공개를 중지했습니다.")
      setScopeTarget(null)
    } catch (error) {
      setScopeError(errorMessage(error))
    } finally {
      setScopeBusy(false)
    }
  }

  const removeQuote = async (item: QuoteData) => {
    try {
      await api.delete(`/quote-cards/${item.id}`)
      await load()
      setDeleteTarget(null)
    } catch (error) {
      setLoadError(errorMessage(error))
    }
  }
  const badge = (value: string): BadgeType =>
    value.includes("완료") || value.includes("등록")
      ? "success"
      : value.includes("OCR")
        ? "warning"
        : "error"

  return (
    <div className="p-3 sm:p-8 max-w-[1184px] mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 bg-[#F1F5F9] p-1 rounded-lg">
          {(["works", "citations"] as const).map((t, i) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-5 py-2 rounded-lg text-[15px] font-medium transition-colors ${
                tab === t
                  ? "bg-white text-[#17212B] shadow-sm"
                  : "text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {i === 0 ? "작품 자료" : "인용문 근거 카드"}
            </button>
          ))}
        </div>
        <details className="writing-library-tools"><summary>자료 검색·개인 노트·공용 등록 신청</summary><SourceTools key={account.id} account={account}/></details>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,text/plain,image/png,image/jpeg,image/tiff,.pdf,.txt,.png,.jpg,.jpeg,.tif,.tiff"
          className="hidden"
          onChange={(event) => void upload(event.target.files?.[0])}
        />
        <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setTextEntry(true)} disabled={busy} className={`h-11 px-5 text-[15px] ${OUTLINE_BTN}`}>
          텍스트 직접 입력
        </button>
        <PrimaryBtn
          buttonRef={uploadButton}
          onClick={() => setOcrModeOpen(true)}
          disabled={busy}
          className="flex items-center gap-2 h-10 px-5 text-[15px]"
        >
          <SvgIcon d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />{" "}
          자료 업로드
        </PrimaryBtn>
        </div>
      </div>

      <p className="text-sm text-[#64748B]">글을 직접 입력하거나 PDF·TXT·인쇄 이미지를 개인 작품 자료로 등록하세요. 스캔 자료는 OCR 검수 후 원문을 확정합니다.</p>
      {textEntry && <TextSourceDialog onClose={() => setTextEntry(false)} onSaved={() => { setTextEntry(false); void load() }} />}
      {ocrModeOpen && <OcrModeDialog returnFocus={uploadButton} onClose={() => setOcrModeOpen(false)} onChoose={(mode, profile) => { ocrMode.current = mode;ocrProfile.current = profile;setOcrModeOpen(false);fileRef.current?.click() }} />}
      {ocrReview && <OcrReviewPanel documentId={ocrReview.id} accessMode={ocrReview.accessMode} onClose={() => setOcrReview(null)} onSaved={() => void load()} />}
      {account.role === "ADMIN" && account.email === "ps25090@onedu.jje.go.kr" && <label className="flex gap-2 text-sm items-center"><input type="checkbox" checked={publicReference} onChange={e => setPublicReference(e.target.checked)} />제공한 규범집 전체를 공용 참고자료로 등록 (승인된 PDF만)</label>}
      {previewText && <SourcePreview value={previewText} onClose={() => setPreviewText(null)} />}
      {tab === "works" && (
        <div className="space-y-3">
          {works.length > 0 ? (
            works.map((item) => (
              <FileRow
                key={item.id}
                name={item.title || item.originalName}
                pages={item.pages}
                date={new Date(item.date).toLocaleDateString("ko-KR")}
                cards={item.cards || undefined}
                status={badge(item.status)}
                statusLabel={item.status}
                scope={item.scope}
                scopeBusy={scopeBusy}
                onScopeChange={account.role === "ADMIN" && item.canManageScope ? () => { setScopeError(""); setScopeMessage(""); setScopeTarget(item) } : undefined}
                onPreview={item.accessMode === "MATCH_ONLY" ? undefined : () => {
                  if (item.ocr?.reviewAvailable) { setOcrReview({ id: item.id, accessMode: item.accessMode ?? "VIEW" }); return }
                  void api.get<SourceData & { content?: string }>(`/source-documents/${item.id}`).then(detail => {
                    setPreviewText({ id: detail.id, title: detail.title, content: detail.content ?? "", accessMode: detail.accessMode })
                  }).catch(error => setLoadError(errorMessage(error)))
                }}
                onDelete={item.scope === "PUBLIC" && account.role !== "ADMIN" ? undefined : () => setDeleteTarget({ kind: "source", item })}
              />
            ))
          ) : (
            <Card>
              <EmptyState
                title="등록된 작품 자료가 없습니다"
                desc="텍스트 직접 입력 또는 자료 업로드로 작품을 추가해 주세요."
              />
            </Card>
          )}
        </div>
      )}
      {tab === "citations" && (
        <div className="space-y-3">
          {quotes.length > 0 ? (
            quotes.map((c) => (
              <Card key={c.id} className="p-5">
                <blockquote className="text-[16px] font-medium text-[#17212B] leading-7 border-l-2 border-[#087F8C] pl-4 mb-3">
                  {c.quote}
                </blockquote>
                <div className="flex items-center gap-4 text-[13px] text-[#64748B]">
                  <span className="font-medium text-[#334155]">{c.work}</span>
                  <span>{c.author}</span>
                  <span>{c.page}</span>
                  <Badge
                    type={
                      c.verificationStatus === "확인 완료"
                        ? "success"
                        : "warning"
                    }
                    label={c.verificationStatus}
                  />
                  <button
                    onClick={() => setDeleteTarget({ kind: "quote", item: c })}
                    className="ml-auto text-[#C62828] font-medium hover:underline"
                  >
                    삭제
                  </button>
                </div>
              </Card>
            ))
          ) : (
            <Card>
              <EmptyState
                title="등록된 인용문 카드가 없습니다"
                desc="작품 자료에서 인용문 근거 카드를 만들어 주세요."
              />
            </Card>
          )}
        </div>
      )}
      {loadError && (
        <p role="alert" className="text-[14px] text-[#C62828]">
          {loadError}
        </p>
      )}
      {scopeMessage && <p role="status" className="text-[14px] text-[#087F8C]">{scopeMessage}</p>}
      {scopeTarget && <ConfirmDialog
        title={scopeTarget.scope === "PUBLIC" ? "자료 공개를 중지할까요?" : "공용으로 전환할까요?"}
        description={`‘${scopeTarget.title || scopeTarget.originalName}’ 자료${scopeTarget.scope === "PUBLIC" ? "를 일반 사용자의 목록과 새 선택에서 제외합니다." : "의 확인된 판본을 로그인한 사용자에게 제공합니다."} 원문 열람·다운로드 범위는 바뀌지 않습니다.`}
        confirmLabel={scopeTarget.scope === "PUBLIC" ? "공개 중지" : "공용으로 전환"}
        busy={scopeBusy}
        errorText={scopeError}
        onConfirm={() => void changeScope()}
        onClose={() => { if (!scopeBusy) setScopeTarget(null) }}
      />}
      {deleteTarget && (
        <ConfirmDialog
          title={
            deleteTarget.kind === "source"
              ? "작품 자료를 삭제할까요?"
              : "인용문 근거 카드를 삭제할까요?"
          }
          description={
            deleteTarget.kind === "source"
              ? `'${deleteTarget.item.title}' 자료와 연결되지 않은 판본이 삭제됩니다. 서버가 사용 중인 자료의 삭제는 차단합니다.`
              : "선택한 인용문 근거 카드가 삭제됩니다."
          }
          confirmLabel="삭제"
          onConfirm={() =>
            void (deleteTarget.kind === "source"
              ? removeSource(deleteTarget.item)
              : removeQuote(deleteTarget.item))
          }
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  )
}

// ─── Rules ────────────────────────────────────────────────────────────────────
function RulesScreen() {
  const [view, setView] = useState<"detectors" | "reference">("detectors")
  const [sel, setSel] = useState(0)
  const [rules, setRules] = useState<RuleData[]>([])
  const [loadError, setLoadError] = useState("")
  useEffect(() => {
    api
      .get<RuleData[]>("/rules")
      .then(setRules)
      .catch((error) => setLoadError(errorMessage(error)))
  }, [])
  const r = rules[sel]
  const reference = rules.find((rule) => rule.primaryReference)?.primaryReference
  const checkedDate = (value: string | null | undefined) => {
    if (!value) return "확인일 미등록"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? "확인일 미등록" : date.toLocaleDateString("ko-KR")
  }
  return (
    <div className="p-3 sm:p-8 max-w-[1184px] mx-auto space-y-5">
      {reference && (
        <Card className="p-4 text-[14px] text-[#334155] leading-6">
          <p className="font-semibold">기본 규범 자료: {reference.reference.title}</p>
          <p>문화체육관광부 한글 맞춤법과 국립국어원 규정 해설을 담은 제공 자료집 · {reference.reference.pdfPageCount}쪽 · {reference.normsCatalogue.provisionCount}개 규정</p>
          <p className="text-[#64748B]">규정 원문과 해설을 기본 근거로 사용합니다. 문맥·허용 표기·예외를 확인한 규칙만 자동 탐지하며, 모든 규정을 자동 검사하는 것은 아닙니다.</p>
        </Card>
      )}
      <div className="flex flex-wrap gap-2" aria-label="규칙 보기 선택">
        <button className="px-4 py-2 rounded-lg border border-[#E2E8F0]" aria-pressed={view === "detectors"} onClick={() => setView("detectors")}>자동 탐지 후보 {rules.length}개</button>
        <button className="px-4 py-2 rounded-lg border border-[#E2E8F0]" aria-pressed={view === "reference"} onClick={() => setView("reference")}>전체 규범 원문 134개</button>
      </div>
      {view === "reference" ? <NormsReferencePanel /> : (
      <div className="flex flex-col lg:flex-row gap-5">
        <Card className="w-full lg:w-72 shrink-0 max-h-[640px] overflow-y-auto">
          {rules.map((rule, i) => (
            <button
              key={rule.id}
              onClick={() => setSel(i)}
              className={`w-full text-left px-4 py-4 border-b border-[#F1F5F9] transition-colors ${
                i === sel
                  ? "bg-[#F0FAF9] border-l-2 border-[#087F8C]"
                  : "hover:bg-[#F8FAFC]"
              }`}
            >
              <p className="text-[14px] font-semibold text-[#17212B]">
                {rule.name}
                {!rule.active && <span className="ml-2 text-[12px] text-[#64748B]">비활성</span>}
              </p>
              <p className="text-[12px] text-[#64748B] mt-0.5">
                {rule.clause} ·{" "}
                {checkedDate(rule.source?.checkedAt)}
              </p>
            </button>
          ))}
        </Card>
        <Card className="flex-1 min-w-0 p-6">
          {!r ? (
            <EmptyState
              title="등록된 규칙이 없습니다"
              desc={loadError || "분석 규칙을 불러오는 중입니다."}
            />
          ) : (
            <>
              <h3 className="text-[20px] font-bold text-[#17212B] mb-1">
                {r.name}
              </h3>
              <p className="text-[14px] text-[#64748B] mb-5">
                {r.clause} · 마지막 확인:{" "}
                {checkedDate(r.source?.checkedAt)}
              </p>
              <div className="space-y-4">
                <p className="text-[13px] text-[#64748B]">{r.categoryLabel} · {r.id} · {r.version}</p>
                <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
                  <p className="text-[13px] font-semibold text-[#64748B] mb-2">
                    학생용 설명
                  </p>
                  <p className="text-[15px] text-[#334155] leading-6">
                    {r.explanation}
                  </p>
                  <p className="text-[13px] text-[#64748B] mt-2">검사 범위: {r.scope}</p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="p-4 rounded-lg bg-[#FDECEC] border border-[#C62828]/20">
                    <p className="text-[12px] font-semibold text-[#C62828] mb-1">
                      {r.status === "오류 후보" ? "오류 후보 예문" : "확인할 표현"}
                    </p>
                    <p className="text-[16px] font-semibold text-[#17212B]">
                      {r.incorrectExamples?.join(" / ") || "예문 검토 중"}
                    </p>
                  </div>
                  <div className="p-4 rounded-lg bg-[#E9F7EF] border border-[#237A45]/20">
                    <p className="text-[12px] font-semibold text-[#237A45] mb-1">
                      비교할 정상 표현
                    </p>
                    <p className="text-[16px] font-semibold text-[#17212B]">
                      {r.correctExamples?.join(" / ") || "예문 검토 중"}
                    </p>
                  </div>
                </div>
                {r.exceptionExamples?.length > 0 && (
                  <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-[14px] text-[#334155]">
                    <p className="font-semibold mb-1">예외·보호 표현</p>
                    <p>{r.exceptionExamples.join(" / ")}</p>
                    <p className="text-[#64748B] mt-1">고유 어휘와 직접 인용은 문맥을 확인합니다.</p>
                  </div>
                )}
                {r.primaryReference && (
                  <p className="text-[14px] text-[#64748B]">
                    기본 규범집 근거: PDF {r.primaryReference.location.pdfPages.join(", ")}쪽
                  </p>
                )}
                <div className="flex items-center gap-3">
                  <span className="text-[14px] text-[#64748B]">
                    검사 상태:
                  </span>
                  <Badge
                    type="warning"
                    label={r.active ? r.status : "비활성 · 분석에 적용 안 함"}
                  />
                </div>
                {r.source?.url ? (
                  <a
                    href={r.source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-block text-[14px] font-semibold text-[#2563A6] hover:underline"
                  >
                    {r.source.name}에서 출처 확인
                  </a>
                ) : <p className="text-[14px] text-[#64748B]">{r.source?.name}</p>}
              </div>
            </>
          )}
        </Card>
      </div>
      )}
    </div>
  )
}

interface NormProvisionSummary {
  id: string
  title: string
  category: string
  categoryLabel: string
  execution: string
  executionReason: string
  detectorRuleIds: string[]
  pages: number[]
}
interface NormProvisionDetail {
  rule_id: string
  detectorRuleIds: string[]
  exception: { markers: { label: string; page: number }[] }
  passages: { page: number; text: string; start: number; end: number }[]
}

function NormsReferencePanel() {
  const [items, setItems] = useState<NormProvisionSummary[]>([])
  const [indexLoading, setIndexLoading] = useState(true)
  const [selected, setSelected] = useState("")
  const [detail, setDetail] = useState<NormProvisionDetail | null>(null)
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState("")
  const [error, setError] = useState("")
  useEffect(() => {
    let cancelled = false
    api.get<{ provisions: NormProvisionSummary[] }>("/rules/reference").then((data) => {
      if (!cancelled) { setItems(data.provisions); setSelected(data.provisions[0]?.id || "") }
    }).catch((e) => { if (!cancelled) setError(errorMessage(e)) }).finally(() => { if (!cancelled) setIndexLoading(false) })
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    setDetail(null); setError("")
    if (!selected) return
    let cancelled = false
    api.get<NormProvisionDetail>(`/rules/reference/${encodeURIComponent(selected)}`).then((data) => {
      if (!cancelled) setDetail(data)
    }).catch((e) => { if (!cancelled) setError(errorMessage(e)) })
    return () => { cancelled = true }
  }, [selected])
  const filtered = items.filter((item) => (!category || item.category === category) && `${item.title} ${item.id}`.includes(query.trim()))
  useEffect(() => {
    const matching = items.filter((item) => (!category || item.category === category) && `${item.title} ${item.id}`.includes(query.trim()))
    if (!matching.some((item) => item.id === selected)) setSelected(matching[0]?.id || "")
  }, [items, query, category, selected])
  const current = items.find((item) => item.id === selected)
  return (
    <div className="space-y-4">
      <p className="text-[14px] text-[#64748B]">전체 규정·붙임·허용·예외를 원문과 함께 확인합니다. ‘부분 탐지’도 해당 조항 전체를 자동 판정한다는 뜻은 아닙니다. 발음 규정은 글의 맞춤법 오류로 단정하지 않습니다.</p>
      <div className="flex flex-col sm:flex-row gap-3">
        <input className="border border-[#E2E8F0] rounded-lg p-3 flex-1 min-w-0" aria-label="규정명 또는 조항 번호 검색" placeholder="규정명 또는 조항 번호 검색" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select className="border border-[#E2E8F0] rounded-lg p-3" aria-label="규범 분야" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">모든 분야</option><option value="SPELLING">한글 맞춤법</option><option value="PUNCTUATION">문장 부호</option><option value="STANDARD_WORD">표준어 사정</option><option value="PRONUNCIATION">표준 발음</option>
        </select>
      </div>
      <p className="text-[13px] text-[#64748B]">{indexLoading ? "규정 목록을 불러오는 중입니다." : `${filtered.length}개 규정`}</p>
      <div className="flex flex-col lg:flex-row gap-5">
        <Card className="w-full lg:w-72 shrink-0 max-h-[560px] overflow-y-auto">
          {filtered.map((item) => <button key={item.id} aria-pressed={selected === item.id} onClick={() => setSelected(item.id)} className={`w-full text-left px-4 py-3 border-b border-[#F1F5F9] ${selected === item.id ? "bg-[#F0FAF9]" : "hover:bg-[#F8FAFC]"}`}>
            <p className="text-[14px] font-semibold">{item.title}</p><p className="text-[12px] text-[#64748B]">{item.detectorRuleIds.length ? "부분 탐지 · 원문 참조" : "원문 참조 전용"} · PDF {item.pages.join(", ")}쪽</p>
          </button>)}
          {!indexLoading && !filtered.length && <p className="p-4 text-[14px]">일치하는 규정이 없습니다.</p>}
        </Card>
        <Card className="flex-1 min-w-0 p-6 space-y-4">
          <h3 className="text-[20px] font-bold">{current?.title || "규정 원문"}</h3>
          <p className="text-[14px] text-[#64748B]">{current?.detectorRuleIds.length ? `연결된 제한적 검사: ${current.detectorRuleIds.join(", ")}` : "참조 전용 · 자동 오류 판정 없음"}</p>
          {current && <p className="text-[13px] text-[#64748B]">{current.executionReason}</p>}
          {error ? <p role="alert">{error}</p> : !selected && !indexLoading ? <p>검색어나 분야를 바꿔 규정을 선택해 주세요.</p> : !detail ? <p>규정 원문을 불러오는 중입니다.</p> : <>
            <p className="text-[13px] text-[#64748B]">제공 PDF의 추출 원문입니다. 표의 열·띄어쓰기는 추출 시 배열이 달라질 수 있으므로 정상·허용·오류를 표의 순서만으로 판단하지 않습니다. 원자료 발행본은 2017·2018년이며 현행 규범 전체 대조는 미완료입니다.</p>
            {!!detail.exception.markers.length && <p className="text-[13px] text-[#64748B]">붙임·허용·예외 표지 위치: {Array.from(new Set(detail.exception.markers.map((m) => `${m.label}(${m.page}쪽)`))).join(", ")}</p>}
            {detail.passages.map((passage) => <section key={`${passage.page}:${passage.start}:${passage.end}`} className="border-t border-[#E2E8F0] pt-4">
              <h4 className="font-semibold text-[14px] mb-2">PDF {passage.page}쪽</h4>
              <p className="whitespace-pre-wrap break-words text-[14px] leading-7">{passage.text}</p>
            </section>)}
          </>}
        </Card>
      </div>
    </div>
  )
}

// ─── Settings ─────────────────────────────────────────────────────────────────
function SettingsScreen({
  workspace,
  workspaceReady = false,
  workspaceLoadError = "",
  onWorkspaceUpdate,
  onWorkspaceReset,
}: {
  workspace: WorkspaceConfig
  workspaceReady?: boolean
  workspaceLoadError?: string
  onWorkspaceUpdate: (w: WorkspaceConfig) => Promise<void>
  onWorkspaceReset: () => Promise<void>
}) {
  const [section, setSection] = useState("작업 공간")
  const [workspaceDraft, setWorkspaceDraft] = useState<Partial<WorkspaceConfig>>({})
  const editName = workspaceDraft.userName ?? (workspaceReady ? workspace.userName : "")
  const editWsName = workspaceDraft.workspaceName ?? (workspaceReady ? workspace.workspaceName : "")
  const setEditName = (value: string) => setWorkspaceDraft(draft => ({ ...draft, userName: value }))
  const setEditWsName = (value: string) => setWorkspaceDraft(draft => ({ ...draft, workspaceName: value }))
  const retainWorkspaceDraft = (draft: Partial<WorkspaceConfig>, submitted: WorkspaceConfig) => ({
    ...(draft.userName !== undefined && draft.userName !== submitted.userName ? { userName: draft.userName } : {}),
    ...(draft.workspaceName !== undefined && draft.workspaceName !== submitted.workspaceName ? { workspaceName: draft.workspaceName } : {}),
  })
  const [resetInput, setResetInput] = useState("")
  const [showReset, setShowReset] = useState(false)
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [dictionaryStatus, setDictionaryStatus] =
    useState<DictionaryStatusData | null>(null)
  const [actionMessage, setActionMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [restoreFile, setRestoreFile] = useState<File | null>(null)
  const [restoreInput, setRestoreInput] = useState("")
  const [showDeleteRecords, setShowDeleteRecords] = useState(false)
  const restoreRef = useRef<HTMLInputElement>(null)
  const resetOk = resetInput === "초기화"

  useEffect(() => {
    api
      .get<SettingsData>("/settings")
      .then(setSettings)
      .catch((error) => setActionMessage(errorMessage(error)))
    api
      .get<DictionaryStatusData>("/dictionary/status")
      .then(setDictionaryStatus)
      .catch(() =>
        setDictionaryStatus({
          status: "service_unavailable",
          available: false,
        }),
      )
  }, [])

  const saveSettings = async (changes: Partial<SettingsData>) => {
    setBusy(true)
    try {
      const saved = await api.patch<SettingsData>("/settings", changes)
      setSettings(saved)
      window.dispatchEvent(new Event("geulbit-settings-updated"))
      setActionMessage("설정을 저장했습니다.")
    } catch (error) {
      setActionMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const saveWorkspace = async () => {
    if (!workspaceReady || busy) return
    const submitted = { userName: editName, workspaceName: editWsName }
    setBusy(true);setActionMessage("")
    try {
      await onWorkspaceUpdate(submitted)
      setWorkspaceDraft(draft => retainWorkspaceDraft(draft, submitted))
      if (settings) await saveSettings({ autosaveInterval: settings.autosaveInterval })
      else setActionMessage("작업 공간 정보를 저장했습니다.")
    } catch (error) { setActionMessage(errorMessage(error)) }
    finally { setBusy(false) }
  }

  const createBackup = async () => {
    setBusy(true)
    try {
      const backup = await api.post<{ downloadUrl: string }>("/backups", {
        includeUploads: true,
      })
      window.location.assign(backup.downloadUrl)
      setActionMessage("백업 파일을 만들었습니다.")
    } catch (error) {
      setActionMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const restoreBackup = async () => {
    if (!restoreFile || restoreInput !== "복원") return
    const form = new FormData()
    form.append("file", restoreFile)
    form.append("confirmation", restoreInput)
    setBusy(true)
    try {
      await api.post("/backups/restore", form)
      setActionMessage(
        "복원이 완료되었습니다. 프로그램 서버를 다시 시작해 주세요.",
      )
    } catch (error) {
      setActionMessage(errorMessage(error))
    } finally {
      setBusy(false)
      setRestoreFile(null)
      setRestoreInput("")
      if (restoreRef.current) restoreRef.current.value = ""
    }
  }

  const runBackupAction = (index: number) => {
    if (index === 0) void createBackup()
    else if (index === 1) restoreRef.current?.click()
    else window.location.assign("/api/backups/export")
  }

  const deleteRecords = async () => {
    try {
      await api.delete("/records", { confirmation: "분석 기록 전체 삭제" })
      setActionMessage("분석 기록을 모두 삭제했습니다.")
      setShowDeleteRecords(false)
    } catch (error) {
      setActionMessage(errorMessage(error))
    }
  }

  const reset = async () => {
    setBusy(true)
    try {
      await onWorkspaceReset()
      setShowReset(false)
      setResetInput("")
    } catch (error) {
      setActionMessage(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-3 sm:p-8 max-w-[1184px] mx-auto">
      {restoreFile && (
        <ConfirmDialog
          title="백업 파일을 복원할까요?"
          description={`'${restoreFile.name}'의 자료가 현재 작업 공간에 복원됩니다.`}
          confirmLabel="복원 실행"
          requiredText="복원"
          inputValue={restoreInput}
          onInputChange={setRestoreInput}
          busy={busy}
          onConfirm={() => void restoreBackup()}
          onClose={() => {
            if (!busy) {
              setRestoreFile(null)
              setRestoreInput("")
              if (restoreRef.current) restoreRef.current.value = ""
            }
          }}
        />
      )}
      {showDeleteRecords && (
        <ConfirmDialog
          title="분석 기록을 모두 삭제할까요?"
          description="분석 기록과 수정 버전이 삭제됩니다. 등록한 평가 기준과 작품 자료는 유지됩니다."
          confirmLabel="전체 삭제"
          busy={busy}
          onConfirm={() => void deleteRecords()}
          onClose={() => setShowDeleteRecords(false)}
        />
      )}
      {showReset && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-6">
          <div className="bg-white rounded-2xl shadow-[0_12px_32px_rgba(16,42,67,0.18)] w-full max-w-[480px] p-8">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-[#FDECEC] flex items-center justify-center text-[#C62828]">
                <SvgIcon
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                  cls="w-4 h-4"
                />
              </div>
              <h3 className="text-[20px] font-bold text-[#17212B]">
                글빛 작업 공간을 초기화할까요?
              </h3>
            </div>
            <p className="text-[15px] text-[#334155] leading-7 mb-5">
              업로드한 자료, 평가 기준, 인용문 카드, 작성한 글과 분석 기록이
              모두 삭제됩니다.
              <br />
              <span className="font-semibold text-[#C62828]">
                초기화 전에 백업 파일을 만드는 것을 권장합니다.
              </span>
            </p>
            <div className="mb-5">
              <label className="block text-[14px] font-semibold text-[#334155] mb-1.5">
                확인을 위해{" "}
                <span className="text-[#C62828] font-bold">초기화</span>를
                입력해 주세요.
              </label>
              <input
                value={resetInput}
                onChange={(e) => setResetInput(e.target.value)}
                placeholder="초기화"
                className="w-full h-11 px-4 rounded-lg border-2 text-[16px] focus:outline-none transition-colors"
                style={{ borderColor: resetOk ? "#C62828" : "#CBD5E1" }}
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => {
                  setShowReset(false)
                  setResetInput("")
                }}
                className={`flex-1 h-11 text-[15px] ${OUTLINE_BTN}`}
              >
                취소
              </button>
              <button
                onClick={async () => {
                  await createBackup()
                  await reset()
                }}
                disabled={busy || !resetOk}
                className={`h-11 px-4 text-[14px] disabled:opacity-40 ${OUTLINE_BTN}`}
              >
                백업 후 초기화
              </button>
              <button
                onClick={() => void reset()}
                disabled={!resetOk || busy}
                className={`h-11 px-5 rounded-lg text-white text-[14px] font-semibold transition-opacity ${
                  resetOk
                    ? "bg-[#C62828] hover:opacity-90"
                    : "bg-[#C62828]/40 cursor-not-allowed"
                }`}
              >
                작업 공간 초기화
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-6">
        <nav className="w-full lg:w-48 shrink-0 grid grid-cols-2 lg:block gap-1">
          {SETTINGS_SECTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setSection(s)}
              className={`w-full text-left px-4 py-2.5 rounded-lg text-[15px] font-medium transition-colors ${
                section === s
                  ? "bg-[#F0FAF9] text-[#102A43] font-semibold"
                  : "text-[#475569] hover:bg-[#F8FAFC]"
              }`}
            >
              {s}
            </button>
          ))}
        </nav>

        <div className="flex-1 min-w-0 space-y-5">
          {section === "작업 공간" && (
            <>
              <Card className="p-6">
                <h2 className="text-[18px] font-bold text-[#17212B] mb-5">
                  작업 공간
                </h2>
                {!workspaceReady && <p role={workspaceLoadError ? "alert" : "status"} className="mb-4 text-sm leading-7">{workspaceLoadError || "작업 공간 정보를 불러오는 중입니다."}</p>}
                <div className="space-y-5">
                  {[
                    { label: "작업 공간 표시 이름 (Google 계정과 별개)", val: editName, set: setEditName },
                    {
                      label: "작업 공간 이름",
                      val: editWsName,
                      set: setEditWsName,
                    },
                  ].map((f) => (
                    <div key={f.label}>
                      <Label>{f.label}</Label>
                      <input
                        value={f.val}
                        disabled={!workspaceReady || busy}
                        onChange={(e) => f.set(e.target.value)}
                        className="w-full max-w-sm h-12 px-4 rounded-lg border border-[#CBD5E1] text-[16px] focus:outline-none focus:ring-2 focus:ring-[#087F8C]"
                      />
                    </div>
                  ))}
                  <div>
                    <Label>기본 저장 위치</Label>
                    <div className="h-12 px-4 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] text-[15px] text-[#64748B] flex items-center max-w-sm">
                      로컬 저장소 (기본값)
                    </div>
                  </div>
                  <div>
                    <Label>자동 저장 간격</Label>
                    <select
                      value={settings?.autosaveInterval ?? 60}
                      onChange={(event) =>
                        setSettings((current) =>
                          current
                            ? {
                                ...current,
                                autosaveInterval: Number(event.target.value),
                              }
                            : current,
                        )
                      }
                      className="h-12 px-4 rounded-lg border border-[#CBD5E1] text-[16px] text-[#17212B] bg-white focus:outline-none focus:ring-2 focus:ring-[#087F8C] max-w-[200px]"
                    >
                      <option value={60}>1분</option>
                      <option value={180}>3분</option>
                      <option value={300}>5분</option>
                      <option value={600}>10분</option>
                    </select>
                  </div>
                </div>
                <div className="pt-5 mt-5 border-t border-[#E2E8F0]">
                  <PrimaryBtn
                    onClick={() => void saveWorkspace()}
                    disabled={!workspaceReady || busy}
                    className="h-10 px-6 text-[14px]"
                  >
                    변경사항 저장
                  </PrimaryBtn>
                </div>
              </Card>

              <Card className="p-6">
                <h3 className="text-[16px] font-bold text-[#17212B] mb-4">
                  백업 및 복원
                </h3>
                <p className="text-[14px] text-[#64748B] mb-4">전체 DB 백업·복원은 로컬 운영자 CLI로만 수행합니다. 개인 분석 보고서는 글 화면의 PDF 저장을 이용해 주세요.</p>
                <div className="space-y-3">
                  <input
                    ref={restoreRef}
                    type="file"
                    accept=".zip"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) setRestoreFile(file)
                    }}
                  />
                  {BACKUP_ACTIONS.map((item, index) => (
                    <div
                      key={item.label}
                      className="flex items-center justify-between p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0]"
                    >
                      <div>
                        <p className="text-[15px] font-semibold text-[#17212B]">
                          {item.label}
                        </p>
                        <p className="text-[13px] text-[#64748B] mt-0.5">
                          {item.desc}
                        </p>
                      </div>
                      <button
                        onClick={() => runBackupAction(index)}
                        disabled
                        title="전체 DB 백업·복원은 로컬 운영자 CLI에서만 수행할 수 있습니다."
                        className={`h-9 px-4 text-[14px] ml-4 shrink-0 disabled:opacity-40 ${OUTLINE_BTN}`}
                      >
                        {item.btn}
                      </button>
                    </div>
                  ))}
                </div>
              </Card>

              <div className="border border-[#C62828]/30 rounded-xl p-6 bg-white shadow-[0_1px_3px_rgba(16,42,67,0.06)]">
                <h3 className="text-[16px] font-bold text-[#C62828] mb-1">
                  위험 영역
                </h3>
                <p className="text-[13px] text-[#64748B] mb-5">
                  전체 삭제·초기화는 현재 서버에서 제공하지 않습니다. 승인되지 않은 삭제 정책을 적용하지 않습니다.
                </p>
                <div className="space-y-3">
                  {[
                    {
                      title: "분석 기록 전체 삭제",
                      desc: "모든 분석 기록과 수정 버전이 삭제됩니다. 등록된 자료는 유지됩니다.",
                      btn: "전체 삭제",
                      danger: false,
                    },
                    {
                      title: "작업 공간 초기화",
                      desc: "모든 자료, 기준, 분석 기록이 삭제됩니다. 초기화 전에 백업을 권장합니다.",
                      btn: "작업 공간 초기화",
                      danger: true,
                    },
                  ].map((item) => (
                    <div
                      key={item.title}
                      className="flex items-center justify-between p-4 rounded-xl bg-[#FFF8F8] border border-[#C62828]/20"
                    >
                      <div>
                        <p className="text-[15px] font-semibold text-[#17212B]">
                          {item.title}
                        </p>
                        <p className="text-[13px] text-[#64748B] mt-0.5">
                          {item.desc}
                        </p>
                      </div>
                      <button
                        disabled
                        title="현재 서버에서 지원하지 않는 작업입니다."
                        onClick={
                          item.danger
                            ? () => setShowReset(true)
                            : () => setShowDeleteRecords(true)
                        }
                        className={`h-9 px-4 text-[14px] font-semibold shrink-0 ml-4 rounded-lg transition-colors ${
                          item.danger
                            ? "bg-[#C62828] text-white hover:opacity-90"
                            : "border border-[#C62828]/40 text-[#C62828] hover:bg-[#FDECEC]"
                        }`}
                      >
                        {item.btn}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {section === "분석 설정" && (
            <Card className="p-6 space-y-6">
              <h2 className="text-[18px] font-bold text-[#17212B]">
                분석 설정
              </h2>
              <div
                className={`rounded-xl border p-4 ${
                  dictionaryStatus?.available
                    ? "bg-[#E9F7EF] border-[#237A45]/20"
                    : "bg-[#FFF4E5] border-[#B45309]/20"
                }`}
              >
                <p className="text-[15px] font-semibold text-[#334155]">
                  공식 사전 보조 기능:{" "}
                  {dictionaryStatus?.available ? "사용 가능" : "제한됨"}
                </p>
                <p className="text-[13px] text-[#64748B] mt-1">
                  {dictionaryStatus?.notice ??
                    "국립국어원 표준국어대사전으로 기본형과 교정 후보를 보조 검증합니다."}
                </p>
              </div>
              <div>
                <Label>기본 분석 종류</Label>
                <select
                  value="전체 분석"
                  disabled
                  className="h-12 px-4 rounded-lg border border-[#CBD5E1] text-[16px] text-[#17212B] bg-white focus:outline-none focus:ring-2 focus:ring-[#087F8C] min-w-[220px]"
                >
                  <option>전체 분석</option>
                </select>
                <p className="text-sm leading-7 text-[#64748B]">현재 분석은 전체 분석으로 실행합니다. 결과 화면에서 필요한 피드백을 골라 볼 수 있습니다.</p>
              </div>
              <div>
                <Label>주장과 근거 연결 점수 기준</Label>
                <select
                  value={7}
                  disabled
                  className="h-12 px-4 rounded-lg border border-[#CBD5E1] text-[16px] text-[#17212B] bg-white focus:outline-none focus:ring-2 focus:ring-[#087F8C] min-w-[220px]"
                >
                  <option value={7}>7점 이상 (높음)</option>
                </select>
                <p className="text-sm leading-7 text-[#64748B]">연결은 구조적 단서와 출처를 함께 확인하는 고정 기준으로 판단합니다. 이 화면에서 승인 기준을 변경하지 않습니다.</p>
              </div>
              <div>
                <Label>인용문 유사도 기준</Label>
                <select
                  value={settings?.quoteSimilarityThreshold ?? 0.95}
                  onChange={(event) =>
                    void saveSettings({
                      quoteSimilarityThreshold: Number(event.target.value),
                    })
                  }
                  className="h-12 px-4 rounded-lg border border-[#CBD5E1] text-[16px] text-[#17212B] bg-white focus:outline-none focus:ring-2 focus:ring-[#087F8C] min-w-[220px]"
                >
                  <option value={0.95}>95% 이상</option>
                  <option value={0.9}>90% 이상</option>
                  <option value={0.85}>85% 이상</option>
                </select>
              </div>
              <div className="flex items-center justify-between max-w-sm py-4 border-t border-[#E2E8F0]">
                <div>
                  <p className="text-[15px] font-semibold text-[#334155]">
                    맞춤법 제안 검토
                  </p>
                  <p className="text-[13px] text-[#64748B]">
                    일괄 자동 적용은 지원하지 않습니다. 원문과 제안을 비교한 뒤 개별적으로 확인하세요.
                  </p>
                </div>
                <button
                  disabled
                  className="rounded-lg border px-3 py-2 text-sm"
                >
                  개별 확인
                </button>
              </div>
            </Card>
          )}

          {section === "OCR 설정" && (
            <Card className="p-6 space-y-6">
              <h2 className="text-[18px] font-bold text-[#17212B]">OCR 설정</h2>
              <p className="leading-7">스캔 PDF와 이미지는 작품과 근거에 업로드한 뒤 원본과 대조해 검수하세요. 검수창에서 선택 영역을 재인식할 수 있습니다. 인식은 서버의 고정된 한국어·영어 구성으로 실행합니다.</p>
              <div>
                <Label>낮은 신뢰도 기준</Label>
                <input disabled
                  type="number"
                  min={0}
                  max={100}
                  value={settings?.lowOcrConfidenceThreshold ?? 70}
                  onChange={(event) =>
                    setSettings((current) =>
                      current
                        ? {
                            ...current,
                            lowOcrConfidenceThreshold: Number(
                              event.target.value,
                            ),
                          }
                        : current,
                    )
                  }
                  className="h-12 w-32 px-4 rounded-lg border border-[#CBD5E1]"
                />{" "}
                <span className="text-[14px] text-[#64748B]">% 미만</span>
              </div>
              <div>
                <Label>OCR 언어</Label>
                <select disabled
                  value={settings?.ocrLanguage ?? "kor+eng"}
                  onChange={(event) =>
                    setSettings((current) =>
                      current
                        ? { ...current, ocrLanguage: event.target.value }
                        : current,
                    )
                  }
                  className="h-12 px-4 rounded-lg border border-[#CBD5E1] bg-white"
                >
                  <option value="kor+eng">한국어 + 영어</option>
                  <option value="kor">한국어</option>
                  <option value="eng">영어</option>
                </select>
              </div>
              <PrimaryBtn
                onClick={() =>
                  settings &&
                  void saveSettings({
                    lowOcrConfidenceThreshold:
                      settings.lowOcrConfidenceThreshold,
                    ocrLanguage: settings.ocrLanguage,
                  })
                }
                disabled
                className="h-10 px-6 text-[14px]"
              >
                OCR 설정 저장
              </PrimaryBtn>
            </Card>
          )}

          {section === "접근성" && (
            <Card className="p-6 space-y-5">
              <h2 className="text-[18px] font-bold text-[#17212B]">접근성</h2>
              <div>
                <Label>글자 크기</Label>
                <select
                  value={settings?.fontSize ?? "보통"}
                  onChange={(event) =>
                    void saveSettings({ fontSize: event.target.value })
                  }
                  className="h-12 px-4 rounded-lg border border-[#CBD5E1] bg-white"
                >
                  <option>작게</option>
                  <option>보통</option>
                  <option>크게</option>
                </select>
              </div>
              {[
                ["고대비 모드", "highContrast"],
                ["움직임 줄이기", "reduceMotion"],
              ].map(([label, key]) => {
                const active = Boolean(settings?.[(key as keyof SettingsData)])
                return (
                  <div
                    key={key}
                    className="flex items-center justify-between max-w-sm"
                  >
                    <span className="text-[15px] font-semibold text-[#334155]">
                      {label}
                    </span>
                    <button
                      onClick={() =>
                        void saveSettings({
                          [key]: !active,
                        } as Partial<SettingsData>)
                      }
                      aria-pressed={active}
                      className="h-9 px-4 rounded-lg border border-[#CBD5E1] text-[14px]"
                    >
                      {active ? "사용 중" : "사용 안 함"}
                    </button>
                  </div>
                )
              })}
              <p className="text-sm leading-7 text-[#475569]">색상 외 상태 표시 · 항상 사용합니다. 상태는 색상뿐 아니라 글자로도 안내합니다.</p>
            </Card>
          )}

          {section === "데이터 관리" && (
            <Card className="p-6 space-y-4">
              <h2 className="text-[18px] font-bold text-[#17212B]">
                데이터 관리
              </h2>
              <p className="text-[14px] text-[#64748B]">
                자료와 분석 기록은 검증된 로컬 SQLite 저장소에 저장됩니다. DB 백업은 로컬 운영자 CLI에서, 개인 보고서는 글 화면의 PDF 저장에서 처리합니다.
              </p>
              <p className="text-[14px] text-[#64748B]">
                마지막 백업:{" "}
                {settings?.lastBackupAt
                  ? new Date(settings.lastBackupAt).toLocaleString("ko-KR")
                  : "아직 백업하지 않음"}
              </p>
              <div className="flex gap-3">
                <PrimaryBtn
                  onClick={() => void createBackup()}
                  disabled
                  className="h-10 px-5 text-[14px]"
                >
                  백업 만들기
                </PrimaryBtn>
                <button
                  disabled
                  title="현재 서버에서 지원하지 않는 내보내기입니다."
                  onClick={() => window.location.assign("/api/backups/export")}
                  className={`h-10 px-5 text-[14px] ${OUTLINE_BTN}`}
                >
                  JSON 내보내기
                </button>
              </div>
            </Card>
          )}
          {actionMessage && (
            <p role="status" className="text-[14px] text-[#475569]">
              {actionMessage}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── App Root ─────────────────────────────────────────────────────────────────
interface ScreenProps {
  account: AccountSession
  onNav: (screen: Screen) => void
  onOpenAnalysis: (id: string) => void
  activeAnalysisId: string | null
  workspace: WorkspaceConfig
  workspaceReady?: boolean
  workspaceLoadError?: string
  onWorkspaceUpdate: (workspace: WorkspaceConfig) => Promise<void>
  onWorkspaceReset: () => Promise<void>
}

const SCREENS: Partial<Record<Screen, (props: ScreenProps) => React.ReactNode>> = {
  criteria: () => <CriteriaScreen />,
  works: ({ account }) => <WorksScreen account={account} />,
  rules: () => <RulesScreen />,
  settings: ({ workspace, workspaceReady, workspaceLoadError, onWorkspaceUpdate, onWorkspaceReset }) => (
    <SettingsScreen
      workspace={workspace}
      workspaceReady={workspaceReady}
      workspaceLoadError={workspaceLoadError}
      onWorkspaceUpdate={onWorkspaceUpdate}
      onWorkspaceReset={onWorkspaceReset}
    />
  ),
}

const SCREEN_PATHS: Record<Screen, string> = {
  dashboard: "/",
  "new-analysis": "/new-analysis",
  "analysis-results": "/analysis-results",
  history: "/history",
  criteria: "/criteria",
  works: "/works",
  rules: "/rules",
  settings: "/settings",
}

function screenFromPath(pathname: string): Screen {
  const match = (Object.entries(SCREEN_PATHS) as [Screen, string][]).find(
    ([, path]) =>
      path === pathname.replace(/\/$/, "") ||
      (path === "/" && pathname === "/"),
  )
  return match?.[0] ?? "dashboard"
}

function AdminOperations() {
  const [users, setUsers] = useState<{id: string; role: string; status: string}[]>([])
  const [message, setMessage] = useState("")
  const load = async () => { try { setUsers(await api.get("/admin/users")); const state = await api.get<{database: string; retention: string}>("/admin/operations"); setMessage(`${state.database} · ${state.retention}`) } catch (e) { setMessage(errorMessage(e)) } }
  useEffect(() => { void load() }, [])
  return <section style={{padding: 20}}><h2>계정 승인 및 운영</h2><p>{message}</p>{users.map(u => <p key={u.id} style={{overflowWrap: "anywhere"}}>{u.id} · {u.role} · {u.status}{["ACTIVE", "INACTIVE"].map(status => <button className="gb-outline" key={status} onClick={async () => { try { await api.patch(`/admin/users/${u.id}`, {status}); await load() } catch(e) { setMessage(errorMessage(e)) } }}>{status === "ACTIVE" ? "승인" : "비활성화"}</button>)}</p>)}<button className="gb-outline" onClick={async () => {try {await api.patch("/admin/ai",{enabled:false});setMessage("AI 기능을 껐습니다.")} catch(e) {setMessage(errorMessage(e))}}}>AI 기능 끄기</button></section>
}

export default function App() {
  const sessionIdentity = useRef<string | null>(null)
  const [sessionReady, setSessionReady] = useState(false)
  const [entered, setEntered] = useState(false)
  const [account, setAccount] = useState<AccountSession | null>(null)
  const [sessionError, setSessionError] = useState("")
  const [sessionCode, setSessionCode] = useState("")
  const checkSession = useRef<() => void>(() => undefined)
  useEffect(() => {
    let alive = true, serial = 0
    const check = () => {
      const request = ++serial
      api.get<AccountSession>("/auth/session").then(session => {
        if (!alive || request !== serial) return
        if (sessionIdentity.current && sessionIdentity.current !== session.id) {
          resetApiSession(); clearGlbitStorage(); setResetVersion(v => v + 1); setWorkspace(DEFAULT_WORKSPACE); setWorkspaceOwner(null);setWorkspaceLoadError("");setScreen("dashboard"); setActiveAnalysisId(null)
        }
        sessionIdentity.current = session.id; setAccount(session); setSessionReady(true); setEntered(true); setSessionError(""); setSessionCode("")
      }).catch(e => {
        if (!alive || request !== serial) return
        setSessionReady(false); setSessionError(errorMessage(e)); setSessionCode(e instanceof ApiError ? e.code : "NETWORK_ERROR")
      })
    }
    const required = () => { setSessionReady(false); check() }
    const restored = (event: PageTransitionEvent) => { if (event.persisted) required() }
    checkSession.current = check
    check(); window.addEventListener("geulbit-auth-required", required); window.addEventListener("focus", check); window.addEventListener("pageshow", restored)
    return () => { alive = false; window.removeEventListener("geulbit-auth-required", required); window.removeEventListener("focus", check); window.removeEventListener("pageshow", restored) }
  }, [])
  const [screen, setScreen] = useState<Screen>(() =>
    screenFromPath(window.location.pathname),
  )
  const [workspace, setWorkspace] = useState<WorkspaceConfig>(DEFAULT_WORKSPACE)
  const [workspaceOwner, setWorkspaceOwner] = useState<string | null>(null)
  const [workspaceLoadError, setWorkspaceLoadError] = useState("")
  const workspaceReady = sessionReady && !!account && workspaceOwner === account.id
  const [resetVersion, setResetVersion] = useState(0)
  const [activeAnalysisId, setActiveAnalysisId] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("analysis"),
  )
  const navigationEntries = useRef<{ key: string; path: string }[]>([])
  const navigationIndex = useRef(0)
  const undoNavigation=useRef(false)
  const canNavigate=()=>window.dispatchEvent(new Event('geulbit-before-navigation',{cancelable:true}))

  useEffect(() => {
    if (!sessionReady || !account) return
    const owner = account.id
    let alive = true
    setWorkspaceOwner(null);setWorkspaceLoadError("")
    api
      .get<WorkspaceConfig>("/workspace")
      .then(value => { if (alive && sessionIdentity.current === owner) { setWorkspace(value);setWorkspaceOwner(owner) } })
      .catch(error => { if (alive && sessionIdentity.current === owner) setWorkspaceLoadError(errorMessage(error)) })
    return () => { alive = false }
  }, [sessionReady, account?.id])

  useEffect(() => {
    if (!navigationEntries.current.length) {
      const key = crypto.randomUUID()
      navigationEntries.current = [{ key, path: window.location.pathname + window.location.search }]
      window.history.replaceState({ ...window.history.state, geulbitNavigationKey: key }, "")
    }
    const handlePopState = () => {
      const index = navigationEntries.current.findIndex(e => e.key === window.history.state?.geulbitNavigationKey)
      if(undoNavigation.current){undoNavigation.current=false;return}
      if(!canNavigate()){
        if(index>=0 && index!==navigationIndex.current){undoNavigation.current=true;window.history.go(navigationIndex.current-index)}
        else {const entry=navigationEntries.current[navigationIndex.current];if(entry)window.history.replaceState({geulbitNavigationKey:entry.key},'',entry.path)}
        return
      }
      if (index >= 0) navigationIndex.current = index
      else {
        const key = crypto.randomUUID()
        navigationEntries.current = [{ key, path: window.location.pathname + window.location.search }];navigationIndex.current = 0
        window.history.replaceState({ ...window.history.state, geulbitNavigationKey: key }, "")
      }
      setScreen(screenFromPath(window.location.pathname))
      setActiveAnalysisId(
        new URLSearchParams(window.location.search).get("analysis"),
      )
    }
    window.addEventListener("popstate", handlePopState)
    return () => window.removeEventListener("popstate", handlePopState)
  }, [])

  const rememberNavigation = (path: string, replace: boolean) => {
    const key = crypto.randomUUID()
    if (replace) { navigationEntries.current = [{ key, path }];navigationIndex.current = 0 }
    else { navigationEntries.current = navigationEntries.current.slice(0, navigationIndex.current + 1);navigationEntries.current.push({ key, path });navigationIndex.current++ }
    window.history[replace ? "replaceState" : "pushState"]({ geulbitNavigationKey: key }, "", path)
  }
  const back = (): boolean | Promise<boolean> => {
    if(!canNavigate())return false
    if (navigationIndex.current < 1 || window.history.state?.geulbitNavigationKey !== navigationEntries.current[navigationIndex.current]?.key) return false
    return new Promise(resolve => {
      const done = () => { clearTimeout(timer);window.removeEventListener("popstate", done);resolve(true) }
      const timer = window.setTimeout(() => { window.removeEventListener("popstate", done);resolve(false) }, 1000)
      window.addEventListener("popstate", done, { once: true });window.history.back()
    })
  }
  useEscapeLayer("navigation", entered && sessionReady, back)

  const navigate = (target: Screen, replace = false) => {
    if(!canNavigate())return
    setScreen(target)
    const path = SCREEN_PATHS[target]
    if (target !== "analysis-results") setActiveAnalysisId(null)
    rememberNavigation(path, replace)
  }

  const updateWorkspace = async (value: WorkspaceConfig) => {
    const owner = sessionIdentity.current
    if (!workspaceReady || !owner || owner !== account?.id) throw new Error("작업 공간 정보를 불러온 뒤 다시 시도해 주세요.")
    const saved = await api.patch<WorkspaceConfig>("/workspace", value)
    if (sessionIdentity.current !== owner) throw new Error("계정이 변경되어 작업 공간 응답을 적용하지 않았습니다.")
    setWorkspace(saved)
  }

  const resetWorkspace = async () => {
    await api.post("/workspace/reset", { confirmation: "초기화" })
    clearGlbitStorage()
    setWorkspace(DEFAULT_WORKSPACE)
    navigate("dashboard", true)
    setResetVersion((version) => version + 1)
  }

  const openAnalysis = (id: string) => {
    setActiveAnalysisId(id)
    setScreen("analysis-results")
    rememberNavigation(`${SCREEN_PATHS["analysis-results"]}?analysis=${encodeURIComponent(id)}`, false)
  }

  const logout = async () => {
    await api.post("/auth/logout")
    resetApiSession(); clearGlbitStorage(); sessionIdentity.current = null
    setAccount(null); setSessionReady(false); setEntered(false); setResetVersion(v => v + 1)
    setWorkspace(DEFAULT_WORKSPACE);setWorkspaceOwner(null);setWorkspaceLoadError("");setActiveAnalysisId(null); navigate("dashboard", true)
    setSessionCode("LOGGED_OUT"); setSessionError("로그아웃했습니다.")
    return true
  }
  const loginScreen = <main className="gb auth-screen"><section className="auth-card"><h1>글빛</h1><h2>{sessionCode === "LOGGED_OUT" ? "로그아웃 완료" : "로그인 상태 확인"}</h2><p role={sessionError ? "alert" : undefined}>{sessionError || "서버에서 로그인 상태를 확인하고 있습니다…"}</p>{sessionCode && <p className="auth-code">{sessionCode}</p>}{sessionError && <><p>{sessionCode === "NETWORK_ERROR" ? "네트워크 연결을 확인하고 다시 시도해 주세요." : "Google 로그인 후 승인된 계정으로 이용할 수 있습니다. 세션이 만료됐다면 다시 로그인해 주세요."}</p><div className="account-actions"><a className="gb-primary" href="/api/auth/login">Google 로그인</a><button className="gb-outline" onClick={() => checkSession.current()}>상태 다시 확인</button></div></>}</section></main>

  // Writing and analysis routes belong to the current two-theme UI.
  // Keep existing resource/settings implementations inside that same shell.
  const auxiliary = ["criteria", "works", "rules", "settings"].includes(screen)
  const render = auxiliary ? SCREENS[screen] : undefined

  if (!entered || !account) return loginScreen
  return (<>
    {!sessionReady && loginScreen}
    <div hidden={!sessionReady} inert={!sessionReady}>
    <Library
      key={resetVersion}
      active={!auxiliary}
      section={screen}
      activeAnalysisId={activeAnalysisId}
      userName={account.displayName || account.email || ""}
      account={account}
      onLogout={logout}
      onNav={navigate}
      onBack={back}
      onOpenAnalysis={openAnalysis}
    >
      {render ? <>{render({
        account,
        onNav: navigate,
        onOpenAnalysis: openAnalysis,
        activeAnalysisId,
        workspace,
        workspaceReady,
        workspaceLoadError,
        onWorkspaceUpdate: updateWorkspace,
        onWorkspaceReset: resetWorkspace,
      })}
      {screen === "settings" && account.role === "ADMIN" && <AdminOperations />}</> : null}
    </Library>
    </div>
  </>)
}
