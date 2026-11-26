export interface ApiError extends Error {
  status?: number
  payload?: unknown
}

function getConsoleToken(): string {
  const token = window.CONSOLE_TOKEN
  if (!token || token === '__TOKEN__') return ''
  return token
}

export async function apiGet<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { method: 'GET', headers: { Accept: 'application/json' }, signal })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err: ApiError = new Error((data && (data.error || data.detail)) || `HTTP ${res.status}`)
    err.status = res.status
    err.payload = data
    throw err
  }
  return data as T
}

export async function apiPost<T>(url: string, body?: Record<string, unknown>): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'application/json' }
  const token = getConsoleToken()
  if (token) headers['X-Console-Token'] = token
  const res = await fetch(url, { method: 'POST', headers, body: body ? JSON.stringify(body) : '{}' })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err: ApiError = new Error((data && (data.error || data.detail)) || `HTTP ${res.status}`)
    err.status = res.status
    err.payload = data
    throw err
  }
  return data as T
}
