import {
  EventStreamContentType,
  fetchEventSource,
  type EventSourceMessage,
} from "@microsoft/fetch-event-source"
import { ApiError, type ApiClient, type StreamHandlers } from "@/api/client"
import type { ErrorData, SessionDetail } from "@/types"

// The real ApiClient: fetch for REST, @microsoft/fetch-event-source for the SSE streams
// (native EventSource can't POST). The only place in the app that calls fetch.

const NETWORK_MESSAGE =
  "Can't reach the server. Check that the backend is running, then try again."
const CUT_OFF_MESSAGE =
  "The connection dropped before the reply finished. Please try again."
const SERVER_MESSAGE = "Something went wrong on the server. Please try again."
const UNEXPECTED_MESSAGE =
  "The server sent an unexpected response. Check that the API address is right, then try again."

/** User-facing text for an HTTP error status (the server's `detail` goes to the console). */
function messageForStatus(status: number): ErrorData {
  if (status === 404) {
    return {
      message: "This trip wasn't found. Reload the page to start a new trip.",
      retryable: false,
    }
  }
  if (status === 400) {
    // Only a chat message body can be invalid (03 §3: 400 {detail}, not 422).
    return {
      message:
        "That message couldn't be sent. Messages must be 1 to 4,000 characters.",
      retryable: false,
    }
  }
  return { message: SERVER_MESSAGE, retryable: status >= 500 }
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let detail: string | null = null
  try {
    const body: unknown = await response.json()
    if (body && typeof body === "object" && "detail" in body) {
      detail = String(body.detail)
    }
  } catch {
    // Body isn't JSON; the status alone decides the message.
  }
  console.warn(`API error ${response.status}: ${detail ?? response.statusText}`)
  const { message, retryable } = messageForStatus(response.status)
  return new ApiError(response.status, message, retryable, detail)
}

export function createHttpClient(baseUrl: string): ApiClient {
  const url = (path: string) => `${baseUrl}${path}`
  const sessionPath = (sessionId: string) =>
    `/sessions/${encodeURIComponent(sessionId)}`

  async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response
    try {
      response = await fetch(url(path), init)
    } catch {
      throw new ApiError(0, NETWORK_MESSAGE, true)
    }
    if (!response.ok) throw await errorFromResponse(response)
    try {
      return (await response.json()) as T
    } catch {
      throw new ApiError(response.status, SERVER_MESSAGE, true)
    }
  }

  /**
   * POST `body` and dispatch the SSE events to `handlers`. Resolves once the stream has
   * ended (after `done`/`error`, a failure, or an abort); never rejects.
   */
  async function stream(
    path: string,
    body: object,
    handlers: StreamHandlers,
    signal?: AbortSignal
  ): Promise<void> {
    if (signal?.aborted) return
    // Our own controller, so the stream can also be closed right after `done`/`error`.
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal?.addEventListener("abort", abort)

    let opened = false // got a 2xx event-stream response
    let finished = false // `done` or `error` was delivered; ignore anything after it

    // Ends the stream once, then calls the final handler. A throwing handler is logged:
    // after abort() fetch-event-source would swallow the error silently.
    const finish = (deliver: () => void) => {
      if (finished) return
      finished = true
      controller.abort()
      try {
        deliver()
      } catch (err) {
        console.error(err)
      }
    }
    const fail = (data: ErrorData) => finish(() => handlers.onError?.(data))

    const dispatch = (event: EventSourceMessage) => {
      if (finished) return
      switch (event.event) {
        case "message_start":
          handlers.onMessageStart?.(JSON.parse(event.data))
          break
        case "token":
          handlers.onToken?.(JSON.parse(event.data))
          break
        case "status":
          handlers.onStatus?.(JSON.parse(event.data))
          break
        case "itinerary":
          handlers.onItinerary?.(JSON.parse(event.data))
          break
        case "done": {
          const data = JSON.parse(event.data)
          finish(() => handlers.onDone?.(data))
          break
        }
        case "error":
          fail(JSON.parse(event.data))
          break
        default:
          // Events from later stages (`profile`, `title`) are ignored for now.
          break
      }
    }

    try {
      await fetchEventSource(url(path), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
        // The default closes the stream when the tab is hidden and re-POSTs when it is
        // shown again, which would send the message twice.
        openWhenHidden: true,
        async onopen(response) {
          if (!response.ok) throw await errorFromResponse(response)
          const type = response.headers.get("content-type") ?? ""
          if (!type.startsWith(EventStreamContentType)) {
            // e.g. an HTML page because VITE_API_BASE_URL points at the wrong server
            const detail = `Expected an event stream, got "${type}"`
            console.warn(detail)
            throw new ApiError(
              response.status,
              UNEXPECTED_MESSAGE,
              true,
              detail
            )
          }
          opened = true
        },
        onmessage: dispatch,
        onclose() {
          // The server closed the stream without `done` or `error`.
          fail({ message: CUT_OFF_MESSAGE, retryable: true })
        },
        onerror(err) {
          // Rethrow so fetch-event-source never retries: a retry would re-send the POST.
          throw err
        },
      })
    } catch (err) {
      if (signal?.aborted) return // the caller cancelled; not an error
      if (err instanceof ApiError) {
        fail({ message: err.message, retryable: err.retryable })
      } else {
        console.error(err)
        fail({
          message: opened ? CUT_OFF_MESSAGE : NETWORK_MESSAGE,
          retryable: true,
        })
      }
    } finally {
      signal?.removeEventListener("abort", abort)
    }
  }

  return {
    createSession: () =>
      requestJson<SessionDetail>("/sessions", { method: "POST" }),
    getSession: (sessionId) =>
      requestJson<SessionDetail>(sessionPath(sessionId)),
    sendMessage: (sessionId, content, handlers, signal) =>
      stream(
        `${sessionPath(sessionId)}/messages`,
        { content },
        handlers,
        signal
      ),
    // The body is `{}`; the server ignores it (03 §4, S1.10 note).
    generate: (sessionId, handlers, signal) =>
      stream(`${sessionPath(sessionId)}/generate`, {}, handlers, signal),
  }
}
