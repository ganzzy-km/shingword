export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    fields?: Record<string, unknown>
  }
}

export interface AccountSession {
  id: string
  role: "USER" | "ADMIN"
  status: "ACTIVE"
  email?: string | null
  displayName?: string
  pictureUrl?: string
  loginMethod?: string
}

export class ApiError extends Error {
  status: number
  code: string
  fields: Record<string, unknown>

  constructor(status: number, body: ApiErrorBody) {
    super(body.error?.message || "요청을 처리하지 못했습니다.")
    this.status = status
    this.code = body.error?.code || "UNKNOWN_ERROR"
    this.fields = body.error?.fields || {}
  }
}

let csrfToken: string | null = null
let sessionRequest: Promise<string> | null = null
let sessionEpoch = 0

export function resetApiSession() {
  sessionEpoch += 1
  csrfToken = null
  sessionRequest = null
}

function requireAuthentication() {
  resetApiSession()
  window.dispatchEvent(new Event("geulbit-auth-required"))
}

async function csrf(keepInputOnSessionExpiry = false): Promise<string> {
  const epoch = sessionEpoch
  if (csrfToken) return csrfToken
  if (!sessionRequest) sessionRequest = (async () => {
    const response = await fetch("/api/auth/session", { credentials: "same-origin" })
    const body = await response.json()
    if (epoch !== sessionEpoch) throw new Error("계정이 변경되어 요청을 취소했습니다.")
    if (!response.ok) {
      if (response.status === 401) {if(keepInputOnSessionExpiry)resetApiSession();else requireAuthentication()}
      throw new ApiError(response.status, body)
    }
    if (typeof body?.data?.csrfToken !== "string") throw new Error("세션 보안 정보를 확인할 수 없습니다.")
    csrfToken = body.data.csrfToken
    return csrfToken as string
  })().finally(() => { if (epoch === sessionEpoch) sessionRequest = null })
  return sessionRequest
}

async function request<T>(path: string, init?: RequestInit, keepInputOnSessionExpiry = false): Promise<T> {
  const epoch = sessionEpoch
  const mutating = init?.method && !["GET", "HEAD", "OPTIONS"].includes(init.method)
  const token = mutating ? await csrf(keepInputOnSessionExpiry) : null
  if (epoch !== sessionEpoch) throw new Error("계정이 변경되어 요청을 취소했습니다.")
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    headers:
      init?.body instanceof FormData
        ? { ...init.headers, ...(token ? { "X-CSRF-Token": token } : {}) }
        : { "Content-Type": "application/json", ...init?.headers, ...(token ? { "X-CSRF-Token": token } : {}) },
  })
  const contentType = response.headers.get("content-type") || ""
  const body = contentType.includes("application/json")
    ? await response.json()
    : null
  if (epoch !== sessionEpoch) throw new Error("계정이 변경되어 요청을 취소했습니다.")
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/session") {
      if(keepInputOnSessionExpiry)resetApiSession();else requireAuthentication()
    }
    throw new ApiError(response.status, body || {})
  }
  if (path === "/auth/session" && typeof body?.data?.csrfToken === "string") csrfToken = body.data.csrfToken
  if (path === "/auth/logout") csrfToken = null
  return body?.data as T
}

export const api = {
  download: async (path: string) => {
    const epoch = sessionEpoch;
    const response = await fetch(`/api${path}`, {credentials: "same-origin"});
    if (!response.ok) { const body = await response.json().catch(() => ({})); if (response.status === 401 && epoch === sessionEpoch) requireAuthentication(); throw new ApiError(response.status, body); }
    if (!response.headers.get("content-type")?.includes("application/pdf")) throw new Error("PDF 응답을 확인할 수 없습니다.");
    const blob = await response.blob();
    if (epoch !== sessionEpoch) throw new Error("계정이 변경되어 다운로드를 취소했습니다.");
    return blob;
  },
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, keepInputOnSessionExpiry = false) =>
    request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
    },keepInputOnSessionExpiry),
  patch: <T>(path: string, body: unknown, keepInputOnSessionExpiry = false) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) },keepInputOnSessionExpiry),
  delete: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "DELETE",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다."
}
