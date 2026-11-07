// The backend API as seen by the app (docs/contracts.md §4). Components never call fetch:
// the app talks to an ApiClient, which tests replace with a fake.
import type { SessionDetail, SseEvent } from '@/types'

export interface ApiClient {
  createSession(): Promise<SessionDetail>
  getSession(id: string): Promise<SessionDetail>
  // Streams the reply to a user message (contracts §5). Calls onEvent for each SSE event and
  // resolves when the stream ends or `signal` aborts it. Rejects (ApiError for a non-2xx
  // status, e.g. 404) if the stream cannot be opened or breaks.
  sendMessage(
    sessionId: string,
    content: string,
    onEvent: (event: SseEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>
}

// A non-2xx response. `message` is the backend's `detail` text when there is one.
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
