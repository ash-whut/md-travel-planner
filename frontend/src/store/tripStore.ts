import { create } from "zustand"
import { api, ApiError, type StreamHandlers } from "@/api"
import type { ErrorData, Itinerary, Message, SessionDetail } from "@/types"

// The current trip (Stage 1): session, chat messages, streaming state and itinerary.
// One store for now; 02 §9 splits it into sessions/chat/plan stores when the history
// sidebar arrives (Stage 4). Components read it with selectors, e.g.
// `const messages = useTripStore((s) => s.messages)`.

export type StreamKind = "chat" | "generate"

/** The session fields that aren't kept separately below. */
export type SessionInfo = Omit<SessionDetail, "messages" | "itinerary">

/** A chat or generate stream that ended in `error`. `retry()` repeats it. */
export interface StreamError extends ErrorData {
  kind: StreamKind
}

interface TripState {
  /** Startup: every page load creates a new trip (02 §5). */
  initStatus: "idle" | "loading" | "ready" | "error"
  initError: string | null // friendly text when initStatus is "error"

  session: SessionInfo | null
  messages: Message[] // saved messages, oldest first
  /**
   * The user's chat message that the server hasn't saved yet: it is sending, or its stream
   * failed. A turn is saved only on `done` (03 §4), so after an error this is what Retry
   * re-sends. Shown after `messages`.
   */
  pendingUserMessage: Message | null
  itinerary: Itinerary | null // latest version

  streaming: StreamKind | null // a stream is open; at most one at a time
  streamingText: string // assistant text arriving in the open stream ("" when none)
  statusLabel: string | null // e.g. "Drafting your itinerary…"; cleared on itinerary/error/done
  error: StreamError | null // the last stream's error, until the next stream starts

  /** POST /sessions. Safe to call twice (React StrictMode runs effects twice in dev). */
  init: () => Promise<void>
  /** Send a chat message. Ignored while a stream is open or before init. */
  sendMessage: (content: string) => Promise<void>
  /** Generate (or regenerate) the itinerary. Ignored while a stream is open or before init. */
  generate: () => Promise<void>
  /** Repeat the stream that failed: re-send the same chat message, or generate again. */
  retry: () => Promise<void>
}

const INIT_ERROR_MESSAGE = "Couldn't start a new trip. Please try again."
const PLAN_SAVED_MESSAGE =
  "Your plan was saved, but the connection dropped before the reply finished."

// The open stream's controller. Only events from this stream may change the store, so a
// late event from an older stream is ignored.
let currentStream: AbortController | null = null

// Ids for messages the server hasn't saved (and so hasn't given an id) yet.
let localIdCounter = 0

function newMessage(
  id: string,
  role: Message["role"],
  content: string,
  itineraryVersion: number | null = null
): Message {
  return {
    id,
    role,
    content,
    itinerary_version: itineraryVersion,
    created_at: new Date().toISOString(),
  }
}

export const useTripStore = create<TripState>()((set, get) => {
  /**
   * Opens a stream and applies its events to the store. `open` calls the api; it resolves
   * when the stream ends and never rejects (see ApiClient).
   */
  async function runStream(
    kind: StreamKind,
    open: (handlers: StreamHandlers, signal: AbortSignal) => Promise<void>
  ) {
    currentStream?.abort()
    const controller = new AbortController()
    currentStream = controller
    const isCurrent = () => currentStream === controller
    let messageId: string | null = null // from this stream's `message_start` event
    let itineraryVersion: number | null = null // set by this stream's `itinerary` event

    set({ streaming: kind, streamingText: "", statusLabel: null, error: null })

    const handlers: StreamHandlers = {
      onMessageStart: ({ message_id }) => {
        messageId = message_id
      },
      onToken: ({ text }) => {
        if (!isCurrent()) return
        set((s) => ({ streamingText: s.streamingText + text }))
      },
      onStatus: ({ label }) => {
        if (!isCurrent()) return
        set({ statusLabel: label })
      },
      onItinerary: (itinerary) => {
        if (!isCurrent()) return
        itineraryVersion = itinerary.version
        set((s) => ({
          itinerary,
          statusLabel: null,
          session: s.session && { ...s.session, status: "planned" },
        }))
      },
      onDone: ({ message_id }) => {
        if (!isCurrent()) return
        // The turn is saved now: the user's message (chat) and the assistant reply.
        // After generate, the reply is the fixed summary for the new version (03 §4).
        set((s) => ({
          messages: [
            ...s.messages,
            ...(s.pendingUserMessage ? [s.pendingUserMessage] : []),
            newMessage(
              message_id,
              "assistant",
              s.streamingText,
              itineraryVersion
            ),
          ],
          pendingUserMessage: null,
          streaming: null,
          streamingText: "",
          statusLabel: null,
        }))
      },
      onError: ({ message, retryable }) => {
        if (!isCurrent()) return
        if (itineraryVersion !== null) {
          // Generate dropped after `itinerary`: the server already saved the version and
          // its summary message (03 §4), so show the summary and don't offer Retry, which
          // would create yet another version.
          set((s) => ({
            messages:
              messageId && s.streamingText
                ? [
                    ...s.messages,
                    newMessage(
                      messageId,
                      "assistant",
                      s.streamingText,
                      itineraryVersion
                    ),
                  ]
                : s.messages,
            streaming: null,
            streamingText: "",
            statusLabel: null,
            error: { kind, message: PLAN_SAVED_MESSAGE, retryable: false },
          }))
          return
        }
        // Nothing from the turn was saved: drop partial reply text, but keep the user's
        // message (pendingUserMessage) for Retry and keep the itinerary already shown.
        set({
          streaming: null,
          streamingText: "",
          statusLabel: null,
          error: { kind, message, retryable },
        })
      },
    }

    await open(handlers, controller.signal)
    if (isCurrent()) currentStream = null
  }

  function streamChat(sessionId: string, content: string) {
    return runStream("chat", (handlers, signal) =>
      api.sendMessage(sessionId, content, handlers, signal)
    )
  }

  return {
    initStatus: "idle",
    initError: null,
    session: null,
    messages: [],
    pendingUserMessage: null,
    itinerary: null,
    streaming: null,
    streamingText: "",
    statusLabel: null,
    error: null,

    init: async () => {
      const { initStatus } = get()
      if (initStatus === "loading" || initStatus === "ready") return
      set({ initStatus: "loading", initError: null })
      try {
        const { messages, itinerary, ...session } = await api.createSession()
        set({ initStatus: "ready", session, messages, itinerary })
      } catch (err) {
        console.error(err)
        set({
          initStatus: "error",
          // A 404 here means a wrong API address, not a missing trip.
          initError:
            err instanceof ApiError && err.status !== 404
              ? err.message
              : INIT_ERROR_MESSAGE,
        })
      }
    },

    sendMessage: async (content) => {
      const { session, streaming } = get()
      const text = content.trim()
      if (!session || streaming || !text) return
      // Replaces any earlier message that failed to send: the server never saved it.
      localIdCounter += 1
      set({
        pendingUserMessage: newMessage(`local-${localIdCounter}`, "user", text),
      })
      await streamChat(session.id, text)
    },

    generate: async () => {
      const { session, streaming } = get()
      if (!session || streaming) return
      // A chat message that failed to send isn't in the server's history, so the plan
      // won't use it; stop showing it.
      set({ pendingUserMessage: null })
      await runStream("generate", (handlers, signal) =>
        api.generate(session.id, handlers, signal)
      )
    },

    retry: async () => {
      const { session, streaming, error, pendingUserMessage } = get()
      if (!session || streaming || !error?.retryable) return
      if (error.kind === "generate") {
        await get().generate()
      } else if (pendingUserMessage) {
        await streamChat(session.id, pendingUserMessage.content)
      }
    },
  }
})
