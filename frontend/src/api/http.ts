// The real ApiClient: REST calls to the FastAPI backend, and SSE for the chat stream.
import { EventStreamContentType, fetchEventSource } from '@microsoft/fetch-event-source'
import type { SendMessageBody, SessionDetail, SseEvent, SseEventName } from '@/types'
import { ApiError, type ApiClient } from './client'

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'

const SSE_EVENTS: SseEventName[] = ['message_start', 'token', 'status', 'profile', 'title', 'itinerary', 'error', 'done']

// Errors are { "detail": "message" } (contracts §4); fall back to the status code.
async function toApiError(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => null)
  const detail = typeof body?.detail === 'string' ? body.detail : `Request failed (${res.status})`
  return new ApiError(res.status, detail)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init)
  if (!res.ok) throw await toApiError(res)
  return (await res.json()) as T
}

async function sendMessage(
  sessionId: string,
  content: string,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const body: SendMessageBody = { content }
  await fetchEventSource(`${BASE_URL}/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
    // Without this the library re-sends the POST whenever the tab is hidden and shown again.
    openWhenHidden: true,
    async onopen(res) {
      if (!res.ok) throw await toApiError(res)
      if (!res.headers.get('content-type')?.startsWith(EventStreamContentType)) {
        throw new ApiError(res.status, 'The server did not send a stream')
      }
    },
    onmessage(msg) {
      // Ignore anything that isn't a contract event (e.g. keep-alive lines).
      if (!SSE_EVENTS.includes(msg.event as SseEventName) || !msg.data) return
      onEvent({ event: msg.event, data: JSON.parse(msg.data) } as SseEvent)
    },
    onerror(err) {
      // Rethrowing stops the library's automatic retry; the user retries with the Retry button.
      throw err
    },
  })
}

export const httpClient: ApiClient = {
  createSession: () => request<SessionDetail>('/sessions', { method: 'POST' }),
  getSession: (id) => request<SessionDetail>(`/sessions/${encodeURIComponent(id)}`),
  sendMessage,
}
