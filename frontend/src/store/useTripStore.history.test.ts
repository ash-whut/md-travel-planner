// Step 45: starting with no stored trip opens the most recent one; the rail's open / New trip
// actions stop a running stream first.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '@/api/client'
import { sanJoseProfile } from '@/fixtures'
import type { SessionDetail } from '@/types'
import { SESSION_KEY, STOPPED_MARKER, useTripStore } from './useTripStore'

function detail(id: string, content = `Messages of ${id}`): SessionDetail {
  return {
    id,
    title: 'Trip',
    status: 'intake',
    trip_profile: sanJoseProfile,
    messages: [{ id: `m-${id}`, role: 'assistant', content, itinerary_version: null, created_at: '' }],
    itinerary: null,
    created_at: '',
    updated_at: '',
  }
}

function fakeApi(overrides: Partial<ApiClient> = {}) {
  return {
    createSession: vi.fn(async () => detail('s-new')),
    getSession: vi.fn(async (id: string) => detail(id)),
    listSessions: vi.fn(async () => [
      { id: 's-recent', title: 'Recent', status: 'intake' as const, updated_at: '2026-11-15T18:00:00Z' },
      { id: 's-older', title: 'Older', status: 'intake' as const, updated_at: '2026-11-01T18:00:00Z' },
    ]),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
    sendMessage: vi.fn(async () => {}),
    generate: vi.fn(async () => {}),
    patchBooking: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('startSession with history', () => {
  it('opens the most recent trip when no id is stored', async () => {
    const api = fakeApi()
    await useTripStore.getState().startSession(api)
    expect(api.getSession).toHaveBeenCalledWith('s-recent')
    expect(api.createSession).not.toHaveBeenCalled()
    expect(useTripStore.getState().session?.id).toBe('s-recent')
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-recent')
  })

  it('opens the most recent trip when the stored one was deleted (404)', async () => {
    localStorage.setItem(SESSION_KEY, 's-gone')
    const { ApiError } = await import('@/api/client')
    const api = fakeApi({
      getSession: vi.fn(async (id: string) => {
        if (id === 's-gone') throw new ApiError(404, 'Session not found')
        return detail(id)
      }),
    })
    await useTripStore.getState().startSession(api)
    expect(useTripStore.getState().session?.id).toBe('s-recent')
  })

  it('still prefers the stored trip over the most recent one', async () => {
    localStorage.setItem(SESSION_KEY, 's-older')
    const api = fakeApi()
    await useTripStore.getState().startSession(api)
    expect(api.listSessions).not.toHaveBeenCalled()
    expect(useTripStore.getState().session?.id).toBe('s-older')
  })

  it('creates a trip when there are none', async () => {
    const api = fakeApi({ listSessions: vi.fn(async () => []) })
    await useTripStore.getState().startSession(api)
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(useTripStore.getState().session?.id).toBe('s-new')
  })
})

describe('openTrip / newTrip', () => {
  it('openTrip loads the trip and remembers it', async () => {
    useTripStore.getState().loadSession(detail('s-1'))
    await useTripStore.getState().openTrip(fakeApi(), 's-2')
    const state = useTripStore.getState()
    expect(state.session?.id).toBe('s-2')
    expect(state.messages[0].content).toBe('Messages of s-2')
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-2')
  })

  it('openTrip aborts a running stream first, so it cannot spill into the other trip', async () => {
    let signal: AbortSignal | undefined
    const api = fakeApi({
      sendMessage: vi.fn(async (_id, _text, onEvent, s) => {
        signal = s
        onEvent({ event: 'message_start', data: { message_id: 'a1' } })
        onEvent({ event: 'token', data: { text: 'Half a reply' } })
        await new Promise<void>((resolve) => s?.addEventListener('abort', () => resolve()))
      }),
    })
    useTripStore.getState().loadSession(detail('s-1'))
    const sending = useTripStore.getState().sendMessage(api, 'hello')
    expect(useTripStore.getState().streaming).toBe(true)

    await useTripStore.getState().openTrip(api, 's-2')
    await sending

    expect(signal?.aborted).toBe(true)
    const state = useTripStore.getState()
    expect(state.streaming).toBe(false)
    expect(state.session?.id).toBe('s-2')
    expect(state.messages.map((m) => m.content)).toEqual(['Messages of s-2'])
    expect(state.messages.some((m) => m.content.includes(STOPPED_MARKER))).toBe(false)
  })

  it('newTrip creates a session, opens it and remembers it', async () => {
    const api = fakeApi()
    useTripStore.getState().loadSession(detail('s-1'))
    await useTripStore.getState().newTrip(api)
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(useTripStore.getState().session?.id).toBe('s-new')
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-new')
  })

  it('a failed open keeps the current trip and shows an error', async () => {
    const api = fakeApi({ getSession: vi.fn(async () => { throw new Error('offline') }) })
    useTripStore.getState().loadSession(detail('s-1'))
    await useTripStore.getState().openTrip(api, 's-2')
    const state = useTripStore.getState()
    expect(state.session?.id).toBe('s-1')
    expect(state.error?.message).toBe("Couldn't open that trip: offline")
  })
})
