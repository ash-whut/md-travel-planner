// The backend API as seen by the app (docs/contracts.md §4). Components never call fetch:
// the app talks to an ApiClient, which tests replace with a fake.
import type { Booking, BookingStatus, SessionDetail, SessionSummary, SseEvent } from '@/types'

export interface ApiClient {
  createSession(): Promise<SessionDetail>
  getSession(id: string): Promise<SessionDetail>
  // The history list: every session, most recently updated first.
  listSessions(): Promise<SessionSummary[]>
  // The user's own title (1–80 chars); the backend stops auto-titling that session.
  renameSession(id: string, title: string): Promise<SessionSummary>
  // Deletes the session with its messages and plans.
  deleteSession(id: string): Promise<void>
  // Streams the reply to a user message (contracts §5). Calls onEvent for each SSE event and
  // resolves when the stream ends or `signal` aborts it. Rejects (ApiError for a non-2xx
  // status, e.g. 404) if the stream cannot be opened or breaks.
  sendMessage(
    sessionId: string,
    content: string,
    onEvent: (event: SseEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>
  // Makes (or remakes) the plan: POST /generate, streamed the same way as sendMessage.
  generate(sessionId: string, onEvent: (event: SseEvent) => void, signal?: AbortSignal): Promise<void>
  // PATCH /sessions/{id}/bookings/{booking_id}: saves a booking's status, returns the updated booking.
  patchBooking(sessionId: string, bookingId: string, status: BookingStatus): Promise<Booking>
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

// The backend could not be reached at all (no HTTP response). Only thrown around the fetch call
// itself (see fetchOrNetworkError), so a TypeError from a bug in our own code isn't taken for it.
export class NetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NetworkError'
  }
}

// fetch, but "no response at all" (fetch's TypeError, e.g. "Failed to fetch") becomes a
// NetworkError. Other rejections (e.g. an abort by Stop) pass through unchanged.
export async function fetchOrNetworkError(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch (err) {
    throw err instanceof TypeError ? new NetworkError(err.message) : err
  }
}

// True when the backend could not be reached at all; a reply with an error status is an ApiError.
export function isNetworkError(err: unknown): boolean {
  return err instanceof NetworkError
}
