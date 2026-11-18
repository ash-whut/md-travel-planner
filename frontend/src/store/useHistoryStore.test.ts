// Step 45: the history list — load, rename, delete (switching away from the open trip) and
// keeping the list in step with the open trip.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from '@/api/client'
import { sanJoseProfile } from '@/fixtures'
import type { SessionDetail, SessionSummary } from '@/types'
import { useHistoryStore } from './useHistoryStore'
import { SESSION_KEY, useTripStore } from './useTripStore'

const summaries: SessionSummary[] = [
  { id: 's-1', title: 'San Jose · Mar 5–7', status: 'planned', updated_at: '2026-11-15T18:00:00Z' },
  { id: 's-2', title: 'Austin · Apr 10–12', status: 'planned', updated_at: '2026-11-12T18:00:00Z' },
  { id: 's-3', title: 'New Orleans weekend', status: 'intake', updated_at: '2026-10-20T18:00:00Z' },
]

function detail(id: string, title = 'Trip'): SessionDetail {
  return {
    id,
    title,
    status: 'intake',
    trip_profile: sanJoseProfile,
    messages: [],
    itinerary: null,
    created_at: '',
    updated_at: '',
  }
}

function fakeApi(overrides: Partial<ApiClient> = {}) {
  return {
    createSession: vi.fn(async () => detail('s-new', 'New trip')),
    getSession: vi.fn(async (id: string) => detail(id)),
    listSessions: vi.fn(async () => summaries),
    renameSession: vi.fn(async (id: string, title: string) => ({ ...summaries.find((s) => s.id === id)!, title })),
    deleteSession: vi.fn(async () => {}),
    sendMessage: vi.fn(async () => {}),
    generate: vi.fn(async () => {}),
    patchBooking: vi.fn(),
    ...overrides,
  }
}

const titles = () => useHistoryStore.getState().sessions.map((s) => s.title)
const ids = () => useHistoryStore.getState().sessions.map((s) => s.id)

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useHistoryStore.getState().reset()
})

describe('loadSessions', () => {
  it('stores the list in server order', async () => {
    await useHistoryStore.getState().loadSessions(fakeApi())
    expect(ids()).toEqual(['s-1', 's-2', 's-3'])
    expect(useHistoryStore.getState().error).toBeNull()
  })

  it('keeps the old list and sets an error when loading fails', async () => {
    useHistoryStore.setState({ sessions: [summaries[0]] })
    await useHistoryStore.getState().loadSessions(fakeApi({ listSessions: async () => { throw new Error('offline') } }))
    expect(ids()).toEqual(['s-1'])
    expect(useHistoryStore.getState().error).toBe("Couldn't load your trips: offline")
  })
})

describe('renameSession', () => {
  it('saves through the API and shows the new title', async () => {
    const api = fakeApi()
    useHistoryStore.setState({ sessions: summaries })
    await useHistoryStore.getState().renameSession(api, 's-2', 'Spring break')
    expect(api.renameSession).toHaveBeenCalledWith('s-2', 'Spring break')
    expect(titles()).toEqual(['San Jose · Mar 5–7', 'Spring break', 'New Orleans weekend'])
  })

  it('renaming the open trip also updates the trip store', async () => {
    useTripStore.getState().loadSession(detail('s-1', 'San Jose · Mar 5–7'))
    useHistoryStore.setState({ sessions: summaries })
    await useHistoryStore.getState().renameSession(fakeApi(), 's-1', 'My trip')
    expect(useTripStore.getState().session?.title).toBe('My trip')
  })

  it('keeps the old title and sets an error when the save fails', async () => {
    useHistoryStore.setState({ sessions: summaries })
    const api = fakeApi({ renameSession: async () => { throw new ApiError(404, 'Session not found') } })
    await useHistoryStore.getState().renameSession(api, 's-2', 'Spring break')
    expect(titles()[1]).toBe('Austin · Apr 10–12')
    expect(useHistoryStore.getState().error).toBe("Couldn't rename the trip: Session not found")
  })
})

describe('deleteSession', () => {
  it('removes another trip without touching the open one', async () => {
    const api = fakeApi()
    useTripStore.getState().loadSession(detail('s-1'))
    useHistoryStore.setState({ sessions: summaries })
    await useHistoryStore.getState().deleteSession(api, 's-2')
    expect(api.deleteSession).toHaveBeenCalledWith('s-2')
    expect(ids()).toEqual(['s-1', 's-3'])
    expect(useTripStore.getState().session?.id).toBe('s-1')
    expect(api.getSession).not.toHaveBeenCalled()
  })

  it('deleting the open trip opens the next one down the list', async () => {
    const api = fakeApi()
    useTripStore.getState().loadSession(detail('s-2'))
    useHistoryStore.setState({ sessions: summaries })
    await useHistoryStore.getState().deleteSession(api, 's-2')
    expect(api.getSession).toHaveBeenCalledWith('s-3')
    expect(useTripStore.getState().session?.id).toBe('s-3')
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-3')
  })

  it('deleting the open trip at the bottom opens the one above it', async () => {
    const api = fakeApi()
    useTripStore.getState().loadSession(detail('s-3'))
    useHistoryStore.setState({ sessions: summaries })
    await useHistoryStore.getState().deleteSession(api, 's-3')
    expect(useTripStore.getState().session?.id).toBe('s-2')
  })

  it('deleting the only trip creates a new one', async () => {
    const api = fakeApi()
    useTripStore.getState().loadSession(detail('s-1'))
    useHistoryStore.setState({ sessions: [summaries[0]] })
    await useHistoryStore.getState().deleteSession(api, 's-1')
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(useTripStore.getState().session?.id).toBe('s-new')
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-new')
  })

  it('keeps the trip and sets an error when the delete fails', async () => {
    useTripStore.getState().loadSession(detail('s-1'))
    useHistoryStore.setState({ sessions: summaries })
    const api = fakeApi({ deleteSession: async () => { throw new Error('offline') } })
    await useHistoryStore.getState().deleteSession(api, 's-1')
    expect(ids()).toEqual(['s-1', 's-2', 's-3'])
    expect(useTripStore.getState().session?.id).toBe('s-1')
    expect(useHistoryStore.getState().error).toBe("Couldn't delete the trip: offline")
  })
})

describe('syncTrip', () => {
  it('copies a new title (a `title` event) without reordering', () => {
    useHistoryStore.setState({ sessions: summaries })
    useHistoryStore.getState().syncTrip({ id: 's-2', title: 'Austin · Apr 11–13', status: 'planned' })
    expect(titles()).toEqual(['San Jose · Mar 5–7', 'Austin · Apr 11–13', 'New Orleans weekend'])
    expect(useHistoryStore.getState().sessions[1].updated_at).toBe(summaries[1].updated_at)
  })

  it('adds a trip that is not in the list yet at the top', () => {
    useHistoryStore.setState({ sessions: summaries })
    useHistoryStore.getState().syncTrip({ id: 's-new', title: 'New trip', status: 'intake' })
    expect(ids()).toEqual(['s-new', 's-1', 's-2', 's-3'])
  })

  it('with bump, moves the trip to the top with a fresh updated_at', () => {
    useHistoryStore.setState({ sessions: summaries })
    useHistoryStore.getState().syncTrip({ id: 's-3', title: 'New Orleans weekend', status: 'intake' }, { bump: true })
    expect(ids()).toEqual(['s-3', 's-1', 's-2'])
    expect(useHistoryStore.getState().sessions[0].updated_at > summaries[0].updated_at).toBe(true)
  })
})
