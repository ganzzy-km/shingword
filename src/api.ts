export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    fields?: Record<string, unknown>
  }
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers:
      init?.body instanceof FormData
        ? init.headers
        : { "Content-Type": "application/json", ...init?.headers },
  })
  const contentType = response.headers.get("content-type") || ""
  const body = contentType.includes("application/json")
    ? await response.json()
    : null
  if (!response.ok) throw new ApiError(response.status, body || {})
  return body?.data as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "DELETE",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다."
}
