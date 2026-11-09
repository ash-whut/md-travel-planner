import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from '@/api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseStatusLines, sanJoseV1, sanJoseV2 } from '@/fixtures'
import type { SessionDetail, TripProfile } from '@/types'
import { SESSION_KEY, reduceEvent, useTripStore, type TripState } from './useTripStore'

const fresh: SessionDetail = {
  id: 's-new',
  title: 'New trip',
  status: 'intake',
  trip_profile: sanJoseProfile,
  messages: [{ id: 'g', role: 'assistant', content: 'Hi! Where to?', itinerary_version: null, created_at: '' }],
  itinerary: null,
  created_at: '',
  updated_at: '',
}

const stored: SessionDetail = { ...fresh, id: 's-old', title: 'San Jose', status: 'planned', itinerary: sanJoseV1 }

// A fake ApiClient whose calls can be inspected.
function fakeApi(overrides: Partial<ApiClient> = {}) {
  return {
    createSession: vi.fn(async () => fresh),
    getSession: vi.fn(async (id: string) => ({ ...stored, id })),
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

describe('useTripStore (smoke)', () => {
  it('creates a session when none is stored and remembers its id', async () => {
    const calls: string[] = []
    await useTripStore.getState().startSession({
      createSession: async () => (calls.push('create'), fresh),
      getSession: async (id) => (calls.push(`get ${id}`), fresh),
      sendMessage: async () => {},
      generate: async () => {},
      patchBooking: async () => { throw new Error('patchBooking is not used here') },
    })
    expect(calls).toEqual(['create'])
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-new')
    expect(useTripStore.getState().messages[0].content).toBe('Hi! Where to?')
  })

  it('builds the assistant message from message_start + tokens', () => {
    const { applyEvent } = useTripStore.getState()
    applyEvent({ event: 'message_start', data: { message_id: 'a1' } })
    applyEvent({ event: 'token', data: { text: 'Hel' } })
    applyEvent({ event: 'token', data: { text: 'lo' } })
    expect(useTripStore.getState().streaming).toBe(true)
    applyEvent({ event: 'done', data: { message_id: 'a1' } })
    const state = useTripStore.getState()
    expect(state.streaming).toBe(false)
    expect(state.messages.at(-1)?.content).toBe('Hello')
  })
})

describe('store actions', () => {
  it('loadSession copies the SessionDetail into the store and clears stream state', () => {
    const store = useTripStore.getState()
    store.applyEvent({ event: 'message_start', data: { message_id: 'x' } })
    store.applyEvent({ event: 'error', data: { message: 'boom', retryable: true } })
    store.loadSession(stored)
    const s = useTripStore.getState()
    expect(s.session).toEqual({ id: 's-old', title: 'San Jose', status: 'planned' })
    expect(s.messages).toEqual(stored.messages)
    expect(s.profile).toEqual(sanJoseProfile)
    expect(s.itinerary).toEqual(sanJoseV1)
    expect(s.streaming).toBe(false)
    expect(s.streamingMessageId).toBeNull()
    expect(s.error).toBeNull()
    expect(s.statusLines).toEqual({})
  })

  it('loadDemo loads the full San Jose v2 trip', () => {
    useTripStore.getState().loadDemo()
    const s = useTripStore.getState()
    expect(s.itinerary).toEqual(sanJoseV2)
    expect(s.messages).toEqual(sanJoseMessages)
    expect(s.profile).toEqual(sanJoseProfile)
    expect(s.statusLines).toEqual(sanJoseStatusLines)
    expect(s.session?.status).toBe('planned')
  })

  it('reset returns to the empty state', () => {
    useTripStore.getState().loadDemo()
    useTripStore.getState().reset()
    const s = useTripStore.getState()
    expect(s.session).toBeNull()
    expect(s.messages).toEqual([])
    expect(s.itinerary).toBeNull()
    expect(s.profile).toBeNull()
  })
})

describe('startSession', () => {
  it('reuses a stored id without creating a new session', async () => {
    localStorage.setItem(SESSION_KEY, 's-old')
    const api = fakeApi()
    await useTripStore.getState().startSession(api)
    expect(api.getSession).toHaveBeenCalledWith('s-old')
    expect(api.createSession).not.toHaveBeenCalled()
    expect(useTripStore.getState().session?.id).toBe('s-old')
    expect(useTripStore.getState().itinerary).toEqual(sanJoseV1)
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-old')
  })

  it('creates a new session when the stored id is stale (404) and stores the new id', async () => {
    localStorage.setItem(SESSION_KEY, 'gone')
    const api = fakeApi({
      getSession: vi.fn(async () => {
        throw new ApiError(404, 'Session not found')
      }),
    })
    await useTripStore.getState().startSession(api)
    expect(api.getSession).toHaveBeenCalledWith('gone')
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-new')
    expect(useTripStore.getState().session?.id).toBe('s-new')
    expect(useTripStore.getState().error).toBeNull()
  })

  it('does not create a new session on a non-404 error; it shows an error instead', async () => {
    localStorage.setItem(SESSION_KEY, 's-old')
    const api = fakeApi({
      getSession: vi.fn(async () => {
        throw new ApiError(500, 'Server exploded')
      }),
    })
    await useTripStore.getState().startSession(api)
    expect(api.createSession).not.toHaveBeenCalled()
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-old')
    const s = useTripStore.getState()
    expect(s.session).toBeNull()
    expect(s.error?.message).toMatch(/Server exploded/)
  })

  it('sets an error when the backend is unreachable', async () => {
    const api = fakeApi({
      createSession: vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    })
    await useTripStore.getState().startSession(api)
    expect(useTripStore.getState().error).not.toBeNull()
    expect(localStorage.getItem(SESSION_KEY)).toBeNull()
  })
})

describe('reduceEvent (contracts §5)', () => {
  // A state with a loaded session and one user message.
  function base(): TripState {
    useTripStore.getState().loadSession({
      ...fresh,
      messages: [
        ...fresh.messages,
        { id: 'u1', role: 'user', content: 'San Jose', itinerary_version: null, created_at: '' },
      ],
    })
    return useTripStore.getState()
  }

  // Apply events one by one to a plain state object (no store involved).
  function run(state: TripState, ...events: Parameters<typeof reduceEvent>[1][]): TripState {
    return events.reduce((s, e) => ({ ...s, ...reduceEvent(s, e) }), state)
  }

  it('message_start appends an empty assistant message and starts streaming', () => {
    const s = run(base(), { event: 'message_start', data: { message_id: 'a1' } })
    expect(s.messages).toHaveLength(3)
    expect(s.messages[2]).toMatchObject({ id: 'a1', role: 'assistant', content: '', itinerary_version: null })
    expect(s.streaming).toBe(true)
    expect(s.streamingMessageId).toBe('a1')
  })

  it('message_start clears a previous error', () => {
    const s = run(
      base(),
      { event: 'error', data: { message: 'Oops', retryable: true } },
      { event: 'message_start', data: { message_id: 'a1' } },
    )
    expect(s.error).toBeNull()
  })

  it('token appends text to the streaming message only', () => {
    const before = base()
    const s = run(
      before,
      { event: 'message_start', data: { message_id: 'a1' } },
      { event: 'token', data: { text: 'Sure, ' } },
      { event: 'token', data: { text: 'San Jose [A]!' } },
    )
    expect(s.messages[2].content).toBe('Sure, San Jose [A]!')
    expect(s.messages.slice(0, 2)).toEqual(before.messages)
  })

  it('status adds a line above the streaming message, once per label', () => {
    const label = 'Checking weather for San Jose · Mar 5–7'
    const s = run(
      base(),
      { event: 'message_start', data: { message_id: 'a1' } },
      { event: 'status', data: { label, state: 'start' } },
      { event: 'status', data: { label, state: 'end' } },
      { event: 'status', data: { label: 'Finding hotels', state: 'start' } },
    )
    expect(s.statusLines).toEqual({
      a1: [
        { label, state: 'end' },
        { label: 'Finding hotels', state: 'start' },
      ],
    })
  })

  it('profile replaces the trip profile', () => {
    const profile: TripProfile = { ...sanJoseProfile, cities: ['Austin'] }
    const s = run(base(), { event: 'profile', data: profile })
    expect(s.profile).toEqual(profile)
  })

  it('title renames the session and keeps its id and status', () => {
    const s = run(base(), { event: 'title', data: { title: 'San Jose · Mar 5–7' } })
    expect(s.session).toEqual({ id: 's-new', title: 'San Jose · Mar 5–7', status: 'intake' })
  })

  it('itinerary sets the plan and marks the streaming message with its version', () => {
    const s = run(
      base(),
      { event: 'message_start', data: { message_id: 'a1' } },
      { event: 'itinerary', data: sanJoseV2 },
    )
    expect(s.itinerary).toEqual(sanJoseV2)
    expect(s.messages[2].itinerary_version).toBe(sanJoseV2.version)
    expect(s.messages[0].itinerary_version).toBeNull()
    expect(s.session?.status).toBe('planned')
  })

  it('error stops streaming, keeps the partial text and stores the error', () => {
    const s = run(
      base(),
      { event: 'message_start', data: { message_id: 'a1' } },
      { event: 'token', data: { text: 'Half' } },
      { event: 'error', data: { message: 'The model is busy', retryable: true } },
    )
    expect(s.streaming).toBe(false)
    expect(s.streamingMessageId).toBeNull()
    expect(s.error).toEqual({ message: 'The model is busy', retryable: true })
    expect(s.messages[2].content).toBe('Half')
  })

  it('done stops streaming and keeps the finished message', () => {
    const s = run(
      base(),
      { event: 'message_start', data: { message_id: 'a1' } },
      { event: 'token', data: { text: 'All set.' } },
      { event: 'done', data: { message_id: 'a1' } },
    )
    expect(s.streaming).toBe(false)
    expect(s.streamingMessageId).toBeNull()
    expect(s.error).toBeNull()
    expect(s.messages.at(-1)).toMatchObject({ id: 'a1', content: 'All set.' })
  })

  it('tokens after done do not change any message', () => {
    const done = run(
      base(),
      { event: 'message_start', data: { message_id: 'a1' } },
      { event: 'token', data: { text: 'Hi' } },
      { event: 'done', data: { message_id: 'a1' } },
    )
    const s = run(done, { event: 'token', data: { text: ' stray' } })
    expect(s.messages).toEqual(done.messages)
  })

  it('is pure: the input state is not mutated', () => {
    const state = run(base(), { event: 'message_start', data: { message_id: 'a1' } })
    const snapshot = structuredClone({ messages: state.messages, statusLines: state.statusLines, session: state.session })
    reduceEvent(state, { event: 'token', data: { text: 'x' } })
    reduceEvent(state, { event: 'status', data: { label: 'L', state: 'start' } })
    reduceEvent(state, { event: 'title', data: { title: 'T' } })
    reduceEvent(state, { event: 'itinerary', data: sanJoseV1 })
    expect({ messages: state.messages, statusLines: state.statusLines, session: state.session }).toEqual(snapshot)
  })

  it('applyEvent runs the reducer on the store', () => {
    base()
    useTripStore.getState().applyEvent({ event: 'title', data: { title: 'Renamed' } })
    expect(useTripStore.getState().session?.title).toBe('Renamed')
  })
})
