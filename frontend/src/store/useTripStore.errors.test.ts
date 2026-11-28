// Step 46 (D36): the store's error and loading state — backendDown, loading, planError (the old
// plan is kept), the unsaved partial reply of a failed turn, Stop before any text, and booking
// saves that wait while a plan is made or the card's save runs.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, fetchOrNetworkError, isNetworkError, NetworkError, type ApiClient } from '@/api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseV1, sanJoseV2 } from '@/fixtures'
import type { Booking, SessionDetail, SseEvent } from '@/types'
import { useHistoryStore } from './useHistoryStore'
import { useTripStore } from './useTripStore'

const planned: SessionDetail = {
  id: 's-1',
  title: sanJoseV1.title,
  status: 'planned',
  trip_profile: sanJoseProfile,
  messages: sanJoseMessages,
  itinerary: sanJoseV1,
  created_at: '',
  updated_at: '',
}
const empty: SessionDetail = { ...planned, status: 'intake', messages: [], itinerary: null }

const networkDown = () => new NetworkError('Failed to fetch') // what the api layer throws then
const start = (id: string): SseEvent => ({ event: 'message_start', data: { message_id: id } })
const token = (text: string): SseEvent => ({ event: 'token', data: { text } })
const done = (id: string): SseEvent => ({ event: 'done', data: { message_id: id } })
const failed: SseEvent = { event: 'error', data: { message: 'Sorry, something went wrong', retryable: true } }

function fakeApi(overrides: Partial<ApiClient> = {}) {
  return {
    createSession: vi.fn(async () => structuredClone(empty)),
    getSession: vi.fn(async () => structuredClone(planned)),
    listSessions: vi.fn(async () => []),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
    sendMessage: vi.fn<ApiClient['sendMessage']>(async () => {}),
    generate: vi.fn<ApiClient['generate']>(async () => {}),
    patchBooking: vi.fn<ApiClient['patchBooking']>(),
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const state = () => useTripStore.getState()
const contents = () => state().messages.map((m) => m.content)
const booking = (id: string): Booking => state().itinerary!.bookings.find((b) => b.id === id)!

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useHistoryStore.getState().reset()
})

describe('isNetworkError', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is true only for the NetworkError of the api layer (no response at all)', () => {
    expect(isNetworkError(networkDown())).toBe(true)
    expect(isNetworkError(new ApiError(500, 'Server error'))).toBe(false)
    expect(isNetworkError(new TypeError('x is undefined'))).toBe(false) // a bug in our own code
    expect(isNetworkError(new Error('x'))).toBe(false)
    expect(isNetworkError('x')).toBe(false)
  })

  it('fetchOrNetworkError turns only the TypeError of fetch into a NetworkError', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    const err = await fetchOrNetworkError('http://api.test').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(NetworkError)
    expect((err as Error).message).toBe('Failed to fetch')

    const abort = new DOMException('Aborted', 'AbortError')
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(abort)))
    expect(await fetchOrNetworkError('http://api.test').catch((e: unknown) => e)).toBe(abort)
  })

  it('a TypeError thrown while handling stream events does not show the banner', async () => {
    state().loadSession(structuredClone(empty))
    const api = fakeApi({
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        onEvent(start('a1'))
        throw new TypeError('Cannot read properties of undefined')
      }),
    })
    await state().sendMessage(api, 'hi')
    expect(state().backendDown).toBe(false)
    expect(state().error).not.toBeNull()
  })
})

describe('backend not reachable', () => {
  it('starts with the banner off and nothing loading', () => {
    expect(state().backendDown).toBe(false)
    expect(state().loading).toBe(false)
    expect(state().planError).toBeNull()
    expect(state().pendingBookings).toEqual([])
    expect(state().unsavedReplyId).toBeNull()
  })

  it('a start with no response turns backendDown on and offers a retryable error', async () => {
    const api = fakeApi({ listSessions: vi.fn(async () => Promise.reject(networkDown())) })
    await state().startSession(api)
    expect(state().backendDown).toBe(true)
    expect(state().loading).toBe(false)
    expect(state().error?.retryable).toBe(true)
    expect(state().session).toBeNull()
  })

  it('an HTTP error status is not "backend down"', async () => {
    const api = fakeApi({ listSessions: vi.fn(async () => Promise.reject(new ApiError(500, 'Server error'))) })
    await state().startSession(api)
    expect(state().backendDown).toBe(false)
    expect(state().error).not.toBeNull()
  })

  it('retry after the backend is back loads the trip and turns the banner off', async () => {
    let up = false
    const api = fakeApi({
      listSessions: vi.fn(async () => (up ? [] : Promise.reject(networkDown()))),
    })
    await state().startSession(api)
    expect(state().backendDown).toBe(true)

    up = true
    await state().retry(api)
    expect(state().backendDown).toBe(false)
    expect(state().session?.id).toBe('s-1')
    expect(state().error).toBeNull()
  })

  it('openTrip and newTrip with no response turn backendDown on', async () => {
    state().loadSession(structuredClone(planned))
    await state().openTrip(fakeApi({ getSession: vi.fn(async () => Promise.reject(networkDown())) }), 's-2')
    expect(state().backendDown).toBe(true)
    expect(state().loading).toBe(false)
    expect(state().itinerary?.version).toBe(1) // the open trip stays

    state().loadSession(structuredClone(planned))
    await state().newTrip(fakeApi({ createSession: vi.fn(async () => Promise.reject(networkDown())) }))
    expect(state().backendDown).toBe(true)
    expect(state().session?.id).toBe('s-1')
  })

  it('a send that gets no response turns it on; the next stream start turns it off', async () => {
    state().loadSession(structuredClone(empty))
    const api = fakeApi({ sendMessage: vi.fn(async () => Promise.reject(networkDown())) })
    await state().sendMessage(api, 'hi')
    expect(state().backendDown).toBe(true)
    expect(state().error?.retryable).toBe(true)

    state().applyEvent(start('a1'))
    expect(state().backendDown).toBe(false)
  })

  it('history loads update the banner too', async () => {
    await useHistoryStore.getState().loadSessions(fakeApi({ listSessions: vi.fn(async () => Promise.reject(networkDown())) }))
    expect(state().backendDown).toBe(true)
    expect(useHistoryStore.getState().error).not.toBeNull()

    await useHistoryStore.getState().loadSessions(fakeApi())
    expect(state().backendDown).toBe(false)
  })
})

describe('loading', () => {
  it('is on while the trip loads and off once it is loaded', async () => {
    const list = deferred<[]>()
    const api = fakeApi({ listSessions: vi.fn(() => list.promise) })
    const pending = state().startSession(api)
    expect(state().loading).toBe(true)
    list.resolve([])
    await pending
    expect(state().loading).toBe(false)
    expect(state().session).not.toBeNull()
  })

  it('is on while a history click or New trip loads', async () => {
    state().loadSession(structuredClone(planned))
    const get = deferred<SessionDetail>()
    const opening = state().openTrip(fakeApi({ getSession: vi.fn(() => get.promise) }), 's-2')
    expect(state().loading).toBe(true)
    get.resolve(structuredClone(planned))
    await opening
    expect(state().loading).toBe(false)

    const create = deferred<SessionDetail>()
    const creating = state().newTrip(fakeApi({ createSession: vi.fn(() => create.promise) }))
    expect(state().loading).toBe(true)
    create.reject(new ApiError(500, 'nope'))
    await creating
    expect(state().loading).toBe(false)
  })

  it('the history list has its own loading flag', async () => {
    const list = deferred<[]>()
    const pending = useHistoryStore.getState().loadSessions(fakeApi({ listSessions: vi.fn(() => list.promise) }))
    expect(useHistoryStore.getState().loading).toBe(true)
    list.resolve([])
    await pending
    expect(useHistoryStore.getState().loading).toBe(false)
  })
})

describe('a failed plan keeps the old plan', () => {
  it('an error event while regenerating keeps v1 and sets the plan toast', async () => {
    state().loadSession(structuredClone(planned))
    const api = fakeApi({
      generate: vi.fn(async (_id, onEvent) => {
        onEvent(start('a1'))
        onEvent({ event: 'status', data: { label: 'Drafting your plan…', state: 'start' } })
        onEvent({ event: 'status', data: { label: 'Drafting your plan…', state: 'error' } })
        onEvent(failed)
      }),
    })
    await state().generatePlan(api)
    expect(state().itinerary).toEqual(sanJoseV1)
    expect(state().planError).toMatch(/previous plan is unchanged/)
    expect(state().generating).toBe(false)
    expect(state().error?.retryable).toBe(true)
  })

  it('a failed first plan says to retry instead', async () => {
    state().loadSession(structuredClone(empty))
    const api = fakeApi({
      generate: vi.fn(async (_id, onEvent) => {
        onEvent(start('a1'))
        onEvent(failed)
      }),
    })
    await state().generatePlan(api)
    expect(state().itinerary).toBeNull()
    expect(state().planError).toMatch(/Retry/)
  })

  it('a generate that gets no response keeps the old plan and shows the banner and toast', async () => {
    state().loadSession(structuredClone(planned))
    await state().generatePlan(fakeApi({ generate: vi.fn(async () => Promise.reject(networkDown())) }))
    expect(state().itinerary).toEqual(sanJoseV1)
    expect(state().planError).not.toBeNull()
    expect(state().backendDown).toBe(true)
  })

  it('a chat edit that fails after its status started also gets the toast', async () => {
    state().loadSession(structuredClone(planned))
    const api = fakeApi({
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        onEvent(start('a1'))
        onEvent({ event: 'status', data: { label: 'Updating your plan…', state: 'start' } })
        onEvent(failed)
      }),
    })
    await state().sendMessage(api, 'replace [F]')
    expect(state().itinerary).toEqual(sanJoseV1)
    expect(state().planError).not.toBeNull()
  })

  it('a plain chat error gets no plan toast', async () => {
    state().loadSession(structuredClone(planned))
    const api = fakeApi({
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        onEvent(start('a1'))
        onEvent(failed)
      }),
    })
    await state().sendMessage(api, 'hello')
    expect(state().planError).toBeNull()
    expect(state().error).not.toBeNull()
  })

  it('the toast can be dismissed, and goes away when the next request starts', async () => {
    state().loadSession(structuredClone(planned))
    useTripStore.setState({ planError: 'x' })
    state().dismissPlanError()
    expect(state().planError).toBeNull()

    useTripStore.setState({ planError: 'x' })
    const send = deferred<void>()
    const pending = state().sendMessage(fakeApi({ sendMessage: vi.fn(() => send.promise) }), 'hi')
    expect(state().planError).toBeNull()
    send.resolve()
    await pending

    useTripStore.setState({ planError: 'x' })
    state().applyEvent(start('a2'))
    expect(state().planError).toBeNull()
  })
})

describe('the unsaved partial reply of a failed turn', () => {
  const partialThenError = vi.fn<ApiClient['sendMessage']>(async (_id, _c, onEvent) => {
    onEvent(start('a1'))
    onEvent(token('Half a '))
    onEvent(failed)
  })

  it('stays visible next to the error', async () => {
    state().loadSession(structuredClone(empty))
    await state().sendMessage(fakeApi({ sendMessage: partialThenError }), 'hi')
    expect(contents()).toEqual(['hi', 'Half a '])
    expect(state().unsavedReplyId).toBe('a1')
    expect(state().error).not.toBeNull()
  })

  it('is dropped when Retry starts, and the user message is not added again', async () => {
    state().loadSession(structuredClone(empty))
    let calls = 0
    const sendMessage = vi.fn<ApiClient['sendMessage']>(async (id, content, onEvent, signal) => {
      calls += 1
      if (calls === 1) return partialThenError(id, content, onEvent, signal)
      onEvent(start('a2'))
      onEvent(token('Full reply'))
      onEvent(done('a2'))
    })
    const api = fakeApi({ sendMessage })
    await state().sendMessage(api, 'hi')
    await state().retry(api)
    expect(contents()).toEqual(['hi', 'Full reply'])
    expect(state().unsavedReplyId).toBeNull()
    expect(sendMessage.mock.calls[1][1]).toBe('hi')
  })

  it('is dropped when the next message starts', async () => {
    state().loadSession(structuredClone(empty))
    await state().sendMessage(fakeApi({ sendMessage: partialThenError }), 'hi')
    const send = deferred<void>()
    const pending = state().sendMessage(fakeApi({ sendMessage: vi.fn(() => send.promise) }), 'again')
    expect(contents()).toEqual(['hi', 'again'])
    send.resolve()
    await pending
  })

  it('is dropped when Generate starts', async () => {
    state().loadSession(structuredClone(empty))
    await state().sendMessage(fakeApi({ sendMessage: partialThenError }), 'hi')
    const gen = deferred<void>()
    const pending = state().generatePlan(fakeApi({ generate: vi.fn(() => gen.promise) }))
    expect(contents()).toEqual(['hi'])
    expect(state().unsavedReplyId).toBeNull()
    gen.resolve()
    await pending
  })

  it('a cut-off stream (no done or error) is dropped on Retry, leaving one reply', async () => {
    state().loadSession(structuredClone(empty))
    let calls = 0
    const sendMessage = vi.fn<ApiClient['sendMessage']>(async (_id, _c, onEvent) => {
      calls += 1
      onEvent(start(`a${calls}`))
      onEvent(token(calls === 1 ? 'Half a ' : 'Full reply'))
      if (calls > 1) onEvent(done(`a${calls}`))
    })
    const api = fakeApi({ sendMessage })
    await state().sendMessage(api, 'hi')
    expect(state().error?.message).toMatch(/cut off/)
    expect(state().unsavedReplyId).toBe('a1')

    await state().retry(api)
    expect(contents()).toEqual(['hi', 'Full reply'])
  })

  it('a stream that breaks after some text is dropped on Retry, leaving one reply', async () => {
    state().loadSession(structuredClone(empty))
    let calls = 0
    const sendMessage = vi.fn<ApiClient['sendMessage']>(async (_id, _c, onEvent) => {
      calls += 1
      onEvent(start(`a${calls}`))
      if (calls === 1) {
        onEvent(token('Half a '))
        throw new Error('network error')
      }
      onEvent(token('Full reply'))
      onEvent(done(`a${calls}`))
    })
    const api = fakeApi({ sendMessage })
    await state().sendMessage(api, 'hi')
    expect(contents()).toEqual(['hi', 'Half a '])
    expect(state().unsavedReplyId).toBe('a1')

    await state().retry(api)
    expect(contents()).toEqual(['hi', 'Full reply'])
  })

  it('a finished reply is never dropped', async () => {
    state().loadSession(structuredClone(empty))
    const api = fakeApi({
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        onEvent(start('a1'))
        onEvent(token('Saved'))
        onEvent(done('a1'))
      }),
    })
    await state().sendMessage(api, 'hi')
    await state().sendMessage(fakeApi(), 'next')
    expect(contents()).toEqual(['hi', 'Saved', 'next'])
  })
})

describe('typing the same text again', () => {
  it('after an error counts as a retry: no second user bubble', async () => {
    state().loadSession(structuredClone(empty))
    let calls = 0
    const sendMessage = vi.fn<ApiClient['sendMessage']>(async (_id, _c, onEvent) => {
      calls += 1
      onEvent(start(`a${calls}`))
      onEvent(token(calls === 1 ? 'Half a ' : 'Full reply'))
      onEvent(calls === 1 ? failed : done(`a${calls}`))
    })
    const api = fakeApi({ sendMessage })
    await state().sendMessage(api, 'hi')
    await state().sendMessage(api, ' hi ') // typed again (trimmed like any message)
    expect(contents()).toEqual(['hi', 'Full reply'])
  })

  it('after a send that got no response: no second user bubble', async () => {
    state().loadSession(structuredClone(empty))
    let calls = 0
    const sendMessage = vi.fn<ApiClient['sendMessage']>(async (_id, _c, onEvent) => {
      calls += 1
      if (calls === 1) throw networkDown()
      onEvent(start('a2'))
      onEvent(token('Full reply'))
      onEvent(done('a2'))
    })
    const api = fakeApi({ sendMessage })
    await state().sendMessage(api, 'hi')
    await state().sendMessage(api, 'hi')
    expect(contents()).toEqual(['hi', 'Full reply'])
  })

  it('after a stopped reply counts as a retry too (the backend saves it once)', async () => {
    state().loadSession(structuredClone(empty))
    useTripStore.setState({
      messages: [
        { id: 'u1', role: 'user', content: 'hi', itinerary_version: null, created_at: '' },
        { id: 'a1', role: 'assistant', content: 'Half *(stopped)*', itinerary_version: null, created_at: '' },
      ],
    })
    await state().sendMessage(fakeApi(), 'hi')
    expect(contents()).toEqual(['hi', 'Half *(stopped)*'])
  })

  it('after a stopped reply that saved a plan version is a new message', async () => {
    state().loadSession(structuredClone(planned))
    useTripStore.setState({
      messages: [
        { id: 'u1', role: 'user', content: 'replace [F]', itinerary_version: null, created_at: '' },
        { id: 'a1', role: 'assistant', content: '*(stopped)*', itinerary_version: 2, created_at: '' },
      ],
    })
    await state().sendMessage(fakeApi(), 'replace [F]')
    expect(contents()).toEqual(['replace [F]', '*(stopped)*', 'replace [F]'])
  })

  it('after a finished reply is a new message', async () => {
    state().loadSession(structuredClone(empty))
    const api = fakeApi({
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        onEvent(start('a1'))
        onEvent(token('Saved'))
        onEvent(done('a1'))
      }),
    })
    await state().sendMessage(api, 'hi')
    await state().sendMessage(fakeApi(), 'hi')
    expect(contents()).toEqual(['hi', 'Saved', 'hi'])
  })

  it('a different text after an error is added as usual', async () => {
    state().loadSession(structuredClone(empty))
    await state().sendMessage(fakeApi({ sendMessage: vi.fn(async () => Promise.reject(networkDown())) }), 'hi')
    await state().sendMessage(fakeApi(), 'hello')
    expect(contents()).toEqual(['hi', 'hello'])
  })
})

describe('Stop before any text', () => {
  it('drops the empty reply bubble', () => {
    state().loadSession(structuredClone(empty))
    useTripStore.setState({ streaming: true })
    state().applyEvent(start('a1'))
    state().stop()
    expect(state().messages.find((m) => m.id === 'a1')).toBeUndefined()
    expect(state().streaming).toBe(false)
  })

  it('keeps a reply with text, marked as stopped', () => {
    state().loadSession(structuredClone(empty))
    useTripStore.setState({ streaming: true })
    state().applyEvent(start('a1'))
    state().applyEvent(token('Some text '))
    state().stop()
    expect(state().messages.find((m) => m.id === 'a1')?.content).toBe('Some text *(stopped)*')
  })

  it('keeps an empty reply when a plan version was saved in that turn', () => {
    state().loadSession(structuredClone(planned))
    useTripStore.setState({ streaming: true, generating: true })
    state().applyEvent(start('a1'))
    state().applyEvent({ event: 'itinerary', data: sanJoseV2 })
    state().stop()
    const reply = state().messages.find((m) => m.id === 'a1')
    expect(reply?.itinerary_version).toBe(2)
    expect(reply?.content).toContain('*(stopped)*')
  })
})

describe('booking saves', () => {
  beforeEach(() => {
    state().loadSession(structuredClone(planned))
  })

  it('do nothing while a plan is being made', async () => {
    useTripStore.setState({ generating: true })
    const api = fakeApi()
    await state().setBookingStatus(api, 'bk-hotel-D', 'booked')
    expect(api.patchBooking).not.toHaveBeenCalled()
    expect(booking('bk-hotel-D').status).toBe('todo')
  })

  it('mark the card pending while its save runs, on success', async () => {
    const save = deferred<Booking>()
    const api = fakeApi({ patchBooking: vi.fn(() => save.promise) })
    const pending = state().setBookingStatus(api, 'bk-hotel-D', 'booked')
    expect(state().pendingBookings).toEqual(['bk-hotel-D'])
    save.resolve({ ...booking('bk-hotel-D'), status: 'booked' })
    await pending
    expect(state().pendingBookings).toEqual([])
  })

  it('clear the pending mark on failure too, and a no-response failure shows the banner', async () => {
    const save = deferred<Booking>()
    const api = fakeApi({ patchBooking: vi.fn(() => save.promise) })
    const pending = state().setBookingStatus(api, 'bk-hotel-D', 'booked')
    save.reject(networkDown())
    await pending
    expect(state().pendingBookings).toEqual([])
    expect(state().backendDown).toBe(true)
    expect(booking('bk-hotel-D').status).toBe('todo')
    expect(state().bookingError).not.toBeNull()
  })

  it('a booking error clears on a new plan version', async () => {
    const api = fakeApi({ patchBooking: vi.fn(async () => Promise.reject(new ApiError(500, 'nope'))) })
    await state().setBookingStatus(api, 'bk-hotel-D', 'booked')
    expect(state().bookingError).not.toBeNull()

    useTripStore.setState({ streaming: true, generating: true })
    state().applyEvent(start('a1'))
    state().applyEvent({ event: 'itinerary', data: sanJoseV2 })
    expect(state().bookingError).toBeNull()
  })

  it('clearBookingError clears it', () => {
    useTripStore.setState({ bookingError: 'x' })
    state().clearBookingError()
    expect(state().bookingError).toBeNull()
  })
})
