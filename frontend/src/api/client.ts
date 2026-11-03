import type {
  DoneData,
  ErrorData,
  Itinerary,
  MessageStartData,
  SessionDetail,
  StatusData,
  TokenData,
} from "@/types"

/**
 * One callback per SSE event (docs/03-contracts.md §4). All are optional.
 * `message_start` comes first; `done` or `error` comes last and ends the stream.
 */
export interface StreamHandlers {
  onMessageStart?: (data: MessageStartData) => void
  onToken?: (data: TokenData) => void
  onStatus?: (data: StatusData) => void
  onItinerary?: (data: Itinerary) => void
  onDone?: (data: DoneData) => void
  /**
   * Server `error` events, and also client-side failures (HTTP error, network down,
   * stream cut off), always with a user-friendly `message`. Not called on abort.
   */
  onError?: (data: ErrorData) => void
}

/**
 * Everything the UI needs from the backend. Components use this through `@/api`
 * and never call `fetch` themselves. Methods are added as their stage needs them.
 *
 * REST methods reject with an `ApiError` (friendly `message`).
 * Stream methods never reject: they resolve once the stream has ended (after `onDone`
 * or `onError`, or when `signal` is aborted) and report every failure through `onError`.
 */
export interface ApiClient {
  /** POST /sessions: a new trip with the greeting message. */
  createSession(): Promise<SessionDetail>
  /** GET /sessions/{id}. */
  getSession(sessionId: string): Promise<SessionDetail>
  /**
   * POST /sessions/{id}/messages (SSE). The turn is saved only on `done`; after an error
   * nothing is saved, so Retry re-sends the same `content`.
   */
  sendMessage(
    sessionId: string,
    content: string,
    handlers: StreamHandlers,
    signal?: AbortSignal
  ): Promise<void>
  /** POST /sessions/{id}/generate (SSE): status → itinerary → one token → done. */
  generate(
    sessionId: string,
    handlers: StreamHandlers,
    signal?: AbortSignal
  ): Promise<void>
}

/** A failed REST call. `message` is safe to show to the user; `detail` is the server's text. */
export class ApiError extends Error {
  readonly status: number // HTTP status, or 0 when the server could not be reached
  readonly retryable: boolean
  readonly detail: string | null

  constructor(
    status: number,
    message: string,
    retryable: boolean,
    detail: string | null = null
  ) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.retryable = retryable
    this.detail = detail
  }
}
