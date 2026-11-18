// The history rail's list of trips (docs/spec.md F7). The open trip itself lives in
// useTripStore; this store only keeps the list in step with it.
import { create } from 'zustand'
import type { ApiClient } from '@/api/client'
import type { SessionSummary } from '@/types'
import { useTripStore, type SessionInfo } from './useTripStore'

interface HistoryData {
  sessions: SessionSummary[] // most recently updated first
  error: string | null // the last failed load / rename / delete, shown in the rail
}

interface HistoryActions {
  loadSessions: (api: ApiClient) => Promise<void>
  renameSession: (api: ApiClient, id: string, title: string) => Promise<void>
  deleteSession: (api: ApiClient, id: string) => Promise<void>
  syncTrip: (session: SessionInfo, opts?: { bump?: boolean }) => void
  reset: () => void
}

export type HistoryState = HistoryData & HistoryActions

const initialData: HistoryData = { sessions: [], error: null }

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : 'Something went wrong'
}

export const useHistoryStore = create<HistoryState>()((set, get) => ({
  ...initialData,

  loadSessions: async (api) => {
    try {
      set({ sessions: await api.listSessions(), error: null })
    } catch (err) {
      set({ error: `Couldn't load your trips: ${errorText(err)}` })
    }
  },

  // Saves first, then shows the new title (a rename is quick, and a failure keeps the old one).
  renameSession: async (api, id, title) => {
    try {
      const summary = await api.renameSession(id, title)
      set((state) => ({
        error: null,
        sessions: state.sessions.map((s) => (s.id === id ? { ...s, title: summary.title } : s)),
      }))
      const trip = useTripStore.getState()
      if (trip.session?.id === id) {
        useTripStore.setState({ session: { ...trip.session, title: summary.title } })
      }
    } catch (err) {
      set({ error: `Couldn't rename the trip: ${errorText(err)}` })
    }
  },

  // Deleting the open trip switches to the next one down the list (or the one above, if it was
  // last), and to a new trip when none are left (spec F7).
  deleteSession: async (api, id) => {
    try {
      await api.deleteSession(id)
    } catch (err) {
      set({ error: `Couldn't delete the trip: ${errorText(err)}` })
      return
    }
    const { sessions } = get()
    const index = sessions.findIndex((s) => s.id === id)
    const remaining = sessions.filter((s) => s.id !== id)
    set({ sessions: remaining, error: null })

    const trip = useTripStore.getState()
    if (trip.session?.id !== id) return
    const next = remaining[Math.min(Math.max(index, 0), remaining.length - 1)]
    if (next) await trip.openTrip(api, next.id)
    else await trip.newTrip(api)
  },

  // Keeps the list in step with the open trip: adds it if it's new, copies its title and status
  // (e.g. from a `title` event), and with `bump` moves it to the top (a chat turn just updated it
  // on the server, as the backend's updated_at order does).
  syncTrip: (session, opts = {}) =>
    set((state) => {
      const existing = state.sessions.find((s) => s.id === session.id)
      const updated: SessionSummary = {
        id: session.id,
        title: session.title,
        status: session.status,
        updated_at: existing && !opts.bump ? existing.updated_at : new Date().toISOString(),
      }
      if (existing && !opts.bump) {
        return { sessions: state.sessions.map((s) => (s.id === session.id ? updated : s)) }
      }
      return { sessions: [updated, ...state.sessions.filter((s) => s.id !== session.id)] }
    }),

  reset: () => set(initialData),
}))
