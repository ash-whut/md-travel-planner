// The real ApiClient: REST calls to the FastAPI backend. SSE (sendMessage) arrives in step 14.
import type { SessionDetail } from '@/types'
import { ApiError, type ApiClient } from './client'

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init)
  if (!res.ok) {
    // Errors are { "detail": "message" } (contracts §4); fall back to the status code.
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.detail ?? `Request failed (${res.status})`)
  }
  return (await res.json()) as T
}

export const httpClient: ApiClient = {
  createSession: () => request<SessionDetail>('/sessions', { method: 'POST' }),
  getSession: (id) => request<SessionDetail>(`/sessions/${encodeURIComponent(id)}`),
}
