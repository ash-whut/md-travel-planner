// The open trip session: messages, profile, itinerary and the state of the current stream.
// Components read from here; backend data comes in through loadSession / applyEvent.
import { create } from 'zustand'
import { ApiError, type ApiClient } from '@/api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseStatusLines, sanJoseV2 } from '@/fixtures'
import type { Itinerary, Message, SessionDetail, SessionStatus, SseEvent, TripProfile } from '@/types'

// localStorage key holding the id of the session to reopen on the next visit.
export const SESSION_KEY = 'md-travel-planner.sessionId'

export interface SessionInfo {
  id: string
  title: string
  status: SessionStatus
}

export interface StoreError {
  message: string
  retryable: boolean
}

interface TripData {
  session: SessionInfo | null
  messages: Message[]
  profile: TripProfile | null
  itinerary: Itinerary | null
  streaming: boolean
  streamingMessageId: string | null // the assistant message being streamed
  statusLines: Record<string, string[]> // status labels shown just above the message with that id
  error: StoreError | null
}

interface TripActions {
  loadSession: (detail: SessionDetail) => void
  loadDemo: () => void
  startSession: (api: ApiClient) => Promise<void>
  applyEvent: (event: SseEvent) => void
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
  error: null,
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : 'Something went wrong'
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
      const id = state.streamingMessageId
      const lines = id ? (state.statusLines[id] ?? []) : []
      if (!id || lines.includes(event.data.label)) return {}
      return { statusLines: { ...state.statusLines, [id]: [...lines, event.data.label] } }
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
        session: state.session ? { ...state.session, status: 'planned' } : null,
        messages: state.messages.map((m) => (m.id === state.streamingMessageId ? { ...m, itinerary_version: version } : m)),
      }
    }
    case 'error':
      return { streaming: false, streamingMessageId: null, error: event.data }
    case 'done':
      return { streaming: false, streamingMessageId: null }
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

  applyEvent: (event) => set((state) => reduceEvent(state, event)),

  reset: () => set(initialData),
}))
