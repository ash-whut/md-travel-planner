// The open trip session: messages, profile, itinerary and the state of the current stream.
// Components read from here; backend data comes in through loadSession / applyEvent.
import { create } from 'zustand'
import { ApiError, type ApiClient } from '@/api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseStatusLines, sanJoseV2 } from '@/fixtures'
import type { Itinerary, Message, SessionDetail, SessionStatus, SseEvent, StatusState, TripProfile } from '@/types'

// localStorage key holding the id of the session to reopen on the next visit.
export const SESSION_KEY = 'md-travel-planner.sessionId'

// Appended to a reply the user stopped; the backend saves the same text (contracts §5).
export const STOPPED_MARKER = ' *(stopped)*'

export interface SessionInfo {
  id: string
  title: string
  status: SessionStatus
}

// One chat status line from SSE `status` events: a spinner while `start`, then ✓ or ✕.
export interface StatusLine {
  label: string
  state: StatusState
}

export interface StoreError {
  message: string
  retryable: boolean
}

// The last stream the user started, so Retry can repeat it.
type LastRequest = { kind: 'message'; text: string } | { kind: 'generate' }

interface TripData {
  session: SessionInfo | null
  messages: Message[]
  profile: TripProfile | null
  itinerary: Itinerary | null
  streaming: boolean
  streamingMessageId: string | null // the assistant message being streamed
  statusLines: Record<string, StatusLine[]> // status lines shown just above the message with that id
  generating: boolean // the backend is making a plan (Generate, or a chat turn that plans)
  planStatus: string | null // the latest status label while generating, shown on the skeleton
  error: StoreError | null
  lastRequest: LastRequest | null // what Retry repeats
  selectedTag: string | null // the stop picked by a tag click (Plan flashes it, Map focuses its pin)
  tagFlashKey: number // bumped on every tag click, so clicking the same tag flashes it again
}

interface TripActions {
  loadSession: (detail: SessionDetail) => void
  loadDemo: () => void
  startSession: (api: ApiClient) => Promise<void>
  sendMessage: (api: ApiClient, content: string, opts?: { retry?: boolean }) => Promise<void>
  generatePlan: (api: ApiClient) => Promise<void>
  retry: (api: ApiClient) => Promise<void>
  stop: () => void
  applyEvent: (event: SseEvent) => void
  selectTag: (tag: string) => void
  reset: () => void
}

export type TripState = TripData & TripActions

const initialData: TripData = {
  session: null,
  messages: [],
  profile: null,
  itinerary: null,
  streaming: false,
  streamingMessageId: null,
  statusLines: {},
  generating: false,
  planStatus: null,
  error: null,
  lastRequest: null,
  selectedTag: null,
  tagFlashKey: 0,
}

// The open SSE stream (chat reply or generation), kept so Stop can abort it.
let activeStream: AbortController | null = null

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : 'Something went wrong'
}

// A 4xx (bad request, unknown session) fails the same way again, so it offers no Retry.
function isRetryable(err: unknown): boolean {
  return !(err instanceof ApiError && err.status >= 400 && err.status < 500)
}

// After an error or a cut-off stream, drop the streamed reply if no text arrived, so no empty
// bubble is left behind (and Retry doesn't add a second one).
function withoutEmptyReply(messages: Message[], id: string | null): Message[] {
  return messages.filter((m) => !(m.id === id && m.content === ''))
}

// Reopen the stored session, or create a new one if none is stored or it no longer exists.
async function openSession(api: ApiClient): Promise<SessionDetail> {
  const storedId = localStorage.getItem(SESSION_KEY)
  if (storedId) {
    try {
      return await api.getSession(storedId)
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err
    }
  }
  return api.createSession()
}

// Pure reducer for one SSE event (contracts §5). Kept outside the store so it is easy to test.
export function reduceEvent(state: TripData, event: SseEvent): Partial<TripData> {
  switch (event.event) {
    case 'message_start': {
      const message: Message = {
        id: event.data.message_id,
        role: 'assistant',
        content: '',
        itinerary_version: null,
        created_at: new Date().toISOString(),
      }
      return { streaming: true, streamingMessageId: message.id, error: null, messages: [...state.messages, message] }
    }
    case 'token':
      return {
        messages: state.messages.map((m) =>
          m.id === state.streamingMessageId ? { ...m, content: m.content + event.data.text } : m,
        ),
      }
    case 'status': {
      // Only plan generation sends `status` (decision D23), so `start` means a plan is being made
      // and its label goes on the skeleton. A status `error` doesn't end generation: a tool such as
      // weather can fail while the plan carries on, and a failed plan always ends with `error`.
      const { label, state: step } = event.data
      const generation: Partial<TripData> = step === 'start' ? { generating: true, planStatus: label } : {}
      const id = state.streamingMessageId
      if (!id) return generation
      // One line per label: a later event for the same label updates its state (spinner → ✓ / ✕).
      const lines = state.statusLines[id] ?? []
      const next = lines.some((l) => l.label === label)
        ? lines.map((l) => (l.label === label ? { label, state: step } : l))
        : [...lines, { label, state: step }]
      return { ...generation, statusLines: { ...state.statusLines, [id]: next } }
    }
    case 'profile':
      return { profile: event.data }
    case 'title':
      return state.session ? { session: { ...state.session, title: event.data.title } } : {}
    case 'itinerary': {
      // The streaming message is the one that produced this version (it gets the divider).
      const version = event.data.version
      return {
        itinerary: event.data,
        generating: false,
        planStatus: null,
        session: state.session ? { ...state.session, status: 'planned' } : null,
        messages: state.messages.map((m) => (m.id === state.streamingMessageId ? { ...m, itinerary_version: version } : m)),
      }
    }
    case 'error':
      return {
        streaming: false,
        streamingMessageId: null,
        generating: false,
        planStatus: null,
        error: event.data,
        messages: withoutEmptyReply(state.messages, state.streamingMessageId),
      }
    case 'done':
      return { streaming: false, streamingMessageId: null, generating: false, planStatus: null }
  }
}

export const useTripStore = create<TripState>()((set, get) => ({
  ...initialData,

  loadSession: (detail) =>
    set({
      ...initialData,
      session: { id: detail.id, title: detail.title, status: detail.status },
      messages: detail.messages,
      profile: detail.trip_profile,
      itinerary: detail.itinerary,
    }),

  // ?demo=1: the v0 San Jose trip, so screenshots stay reproducible without a backend.
  loadDemo: () =>
    set({
      ...initialData,
      session: { id: 'demo', title: sanJoseV2.title, status: 'planned' },
      messages: sanJoseMessages,
      profile: sanJoseProfile,
      itinerary: sanJoseV2,
      statusLines: sanJoseStatusLines,
    }),

  startSession: async (api) => {
    try {
      const detail = await openSession(api)
      localStorage.setItem(SESSION_KEY, detail.id)
      get().loadSession(detail)
    } catch (err) {
      set({ error: { message: `Couldn't load your trip: ${errorText(err)}`, retryable: true } })
    }
  },

  // Shows the user message right away, then streams the assistant reply into the store.
  // A retry resends without adding the user message again.
  sendMessage: async (api, content, opts = {}) => {
    const text = content.trim()
    const { session, streaming } = get()
    if (!text || !session || streaming) return

    if (!opts.retry) {
      const userMessage: Message = {
        id: `local-${Date.now()}`,
        role: 'user',
        content: text,
        itinerary_version: null,
        created_at: new Date().toISOString(),
      }
      set((state) => ({ messages: [...state.messages, userMessage] }))
    }
    set({ streaming: true, error: null, lastRequest: { kind: 'message', text } })
    await runStream(
      (onEvent, signal) => api.sendMessage(session.id, text, onEvent, signal),
      "Couldn't send your message",
    )
  },

  // The Generate button: streams the same events as a chat turn that makes the plan.
  // The skeleton shows right away, before the first status event arrives.
  generatePlan: async (api) => {
    const { session, streaming } = get()
    if (!session || streaming) return
    set({ streaming: true, generating: true, planStatus: null, error: null, lastRequest: { kind: 'generate' } })
    await runStream((onEvent, signal) => api.generate(session.id, onEvent, signal), "Couldn't make the plan")
  },

  // Retry repeats the last message or Generate; with nothing sent yet, it retries loading the session.
  retry: async (api) => {
    const { lastRequest } = get()
    if (lastRequest?.kind === 'message') await get().sendMessage(api, lastRequest.text, { retry: true })
    else if (lastRequest?.kind === 'generate') await get().generatePlan(api)
    else await get().startSession(api)
  },

  // Stop: abort the stream and keep the partial reply, marked like the backend saves it.
  stop: () => {
    activeStream?.abort()
    activeStream = null
    set((state) => ({
      streaming: false,
      streamingMessageId: null,
      generating: false,
      planStatus: null,
      messages: state.messages.map((m) =>
        m.id === state.streamingMessageId ? { ...m, content: m.content.trimEnd() + STOPPED_MARKER } : m,
      ),
    }))
  },

  applyEvent: (event) => set((state) => reduceEvent(state, event)),

  selectTag: (tag) => set((state) => ({ selectedTag: tag, tagFlashKey: state.tagFlashKey + 1 })),

  reset: () => set(initialData),
}))

// Opens one SSE stream, passing each event to the callback; resolves when the stream ends.
type OpenStream = (onEvent: (event: SseEvent) => void, signal: AbortSignal) => Promise<void>

// Runs a chat reply or a generation into the store: applies each event, turns a broken or
// cut-off stream into an inline error, and cleans up unless Stop already did.
// The caller has already set `streaming: true`.
async function runStream(open: OpenStream, failText: string): Promise<void> {
  const { getState: get, setState: set } = useTripStore
  const controller = new AbortController()
  activeStream = controller
  let finished = false // saw `done` or `error`
  try {
    await open((event) => {
      if (event.event === 'done' || event.event === 'error') finished = true
      get().applyEvent(event)
    }, controller.signal)
    if (!finished && !controller.signal.aborted) {
      set((state) => ({
        error: { message: 'The reply was cut off.', retryable: true },
        messages: withoutEmptyReply(state.messages, state.streamingMessageId),
      }))
    }
  } catch (err) {
    set((state) => ({
      error: { message: `${failText}: ${errorText(err)}`, retryable: isRetryable(err) },
      messages: withoutEmptyReply(state.messages, state.streamingMessageId),
    }))
  } finally {
    // After Stop, stop() already reset the state (and a new stream may have started since).
    if (activeStream === controller) {
      activeStream = null
      if (get().streaming || get().generating) {
        set({ streaming: false, streamingMessageId: null, generating: false, planStatus: null })
      }
    }
  }
}
