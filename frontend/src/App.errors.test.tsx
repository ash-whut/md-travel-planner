// Step 46 end to end in the UI (D36): the "Backend not reachable" banner and its Try again,
// Retry, a failed plan keeping the old plan (with the Plan pane toast), Generate waiting for a
// destination, booking buttons that wait, aria labels on icon buttons and loading states.
// App + stores with a fake ApiClient (no network).
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, NetworkError, type ApiClient } from './api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseV1 } from './fixtures'
import { useHistoryStore } from './store/useHistoryStore'
import { useTripStore } from './store/useTripStore'
import type { Booking, SessionDetail, SessionSummary, SseEvent, TripProfile } from './types'
import App from './App'
import { HistoryRail } from './components/HistoryRail'

const greeting = { id: 'g', role: 'assistant' as const, content: 'Where to?', itinerary_version: null, created_at: '' }

const emptySession: SessionDetail = {
  id: 's-1',
  title: 'New trip',
  status: 'intake',
  trip_profile: sanJoseProfile,
  messages: [greeting],
  itinerary: null,
  created_at: '',
  updated_at: '',
}
const plannedSession: SessionDetail = {
  ...emptySession,
  title: sanJoseV1.title,
  status: 'planned',
  messages: sanJoseMessages,
  itinerary: sanJoseV1,
}

const networkDown = () => new NetworkError('Failed to fetch')
const start = (id: string): SseEvent => ({ event: 'message_start', data: { message_id: id } })
const token = (text: string): SseEvent => ({ event: 'token', data: { text } })
const done = (id: string): SseEvent => ({ event: 'done', data: { message_id: id } })
const editing: SseEvent = { event: 'status', data: { label: 'Updating your plan…', state: 'start' } }
const failed: SseEvent = {
  event: 'error',
  data: { message: "Sorry, I couldn't make the plan this time.", retryable: true },
}

function makeApi(session: SessionDetail, overrides: Partial<ApiClient> = {}) {
  return {
    createSession: vi.fn(async () => structuredClone(session)),
    getSession: vi.fn(async () => structuredClone(session)),
    listSessions: vi.fn<ApiClient['listSessions']>(async () => []),
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

const banner = () => screen.queryByText(/Backend not reachable/)

async function send(text: string) {
  const input = screen.getByRole('textbox', { name: 'Message' })
  fireEvent.change(input, { target: { value: text } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

function bookTab(): HTMLElement {
  return screen.getAllByRole('button', { name: 'Book' }).find((b) => b.hasAttribute('aria-disabled'))!
}

function card(title: string): HTMLElement {
  return screen.getByRole('heading', { level: 3, name: title }).closest('li') as HTMLElement
}

async function openBookTab() {
  await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
  fireEvent.click(bookTab())
  await screen.findByRole('heading', { level: 2, name: 'Book' })
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useHistoryStore.getState().reset()
})

describe('Backend not reachable banner', () => {
  it('shows when the backend gives no response, and Try again reconnects', async () => {
    let up = false
    const api = makeApi(emptySession, {
      listSessions: vi.fn(async () => (up ? [] : Promise.reject(networkDown()))),
    })
    render(<App api={api} />)

    expect(await screen.findByText(/Backend not reachable/)).toBeTruthy()
    expect(banner()!.closest('[role="status"]')).not.toBeNull()
    expect(screen.queryByText('Where to?')).toBeNull()

    up = true
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByText('Where to?')).toBeTruthy()
    await waitFor(() => expect(banner()).toBeNull())
    expect(api.createSession).toHaveBeenCalledTimes(1)
  })

  it('stays while the backend is still down', async () => {
    const api = makeApi(emptySession, { listSessions: vi.fn(async () => Promise.reject(networkDown())) })
    render(<App api={api} />)
    await screen.findByText(/Backend not reachable/)

    fireEvent.click(screen.getByRole('button', { name: /Try again/ }))
    await waitFor(() => expect(vi.mocked(api.listSessions).mock.calls.length).toBeGreaterThan(1))
    expect(banner()).not.toBeNull()
  })

  it('does not show for an HTTP error status (the server answered)', async () => {
    const api = makeApi(emptySession, {
      listSessions: vi.fn(async () => Promise.reject(new ApiError(500, 'Server error'))),
    })
    render(<App api={api} />)
    expect((await screen.findByRole('alert')).textContent).toMatch(/Couldn't load your trip/)
    expect(banner()).toBeNull()
  })

  it('shows when a message gets no response, keeps the plan, and goes once a reply streams', async () => {
    let calls = 0
    const api = makeApi(plannedSession, {
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        calls += 1
        if (calls === 1) throw networkDown()
        onEvent(start('a2'))
        onEvent(token('Back online'))
        onEvent(done('a2'))
      }),
    })
    render(<App api={api} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
    await send('hello')

    expect(await screen.findByText(/Backend not reachable/)).toBeTruthy()
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText('Back online')).toBeTruthy()
    expect(banner()).toBeNull()
  })
})

describe('Retry and a failed plan', () => {
  it('a failed chat edit keeps the old plan, shows the toast, and Retry resends the text once', async () => {
    let calls = 0
    const api = makeApi(plannedSession, {
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        calls += 1
        onEvent(start(`a${calls}`))
        if (calls === 1) {
          onEvent(editing)
          onEvent(failed)
          return
        }
        onEvent(token('Fine now'))
        onEvent(done(`a${calls}`))
      }),
    })
    render(<App api={api} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
    await send('make it cheaper')

    const toast = await screen.findByTestId('plan-error')
    expect(toast.getAttribute('role')).toBe('status')
    expect(toast.textContent).toMatch(/previous plan is unchanged/)
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
    expect(screen.getAllByTitle(/^Refer to this as "/).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText('Fine now')).toBeTruthy()
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.sendMessage).mock.calls[1][1]).toBe('make it cheaper')
    expect(screen.getAllByText('make it cheaper')).toHaveLength(1)
    expect(screen.queryByTestId('plan-error')).toBeNull()
  })

  it('the toast can be dismissed', async () => {
    const api = makeApi(plannedSession, {
      generate: vi.fn(async (_id, onEvent) => {
        onEvent(start('a1'))
        onEvent({ event: 'status', data: { label: 'Drafting your plan…', state: 'start' } })
        onEvent(failed)
      }),
    })
    useTripStore.getState().loadSession(structuredClone(plannedSession))
    render(<App api={api} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
    void useTripStore.getState().generatePlan(api)

    const toast = await screen.findByTestId('plan-error')
    fireEvent.click(within(toast).getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByTestId('plan-error')).toBeNull()
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
  })

  it('a partial reply that failed stays next to the error, then goes when Retry starts', async () => {
    let calls = 0
    const api = makeApi(emptySession, {
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        calls += 1
        onEvent(start(`a${calls}`))
        if (calls === 1) {
          onEvent(token('Half a reply'))
          onEvent({ event: 'error', data: { message: 'Sorry, something went wrong', retryable: true } })
          return
        }
        onEvent(token('Whole reply'))
        onEvent(done(`a${calls}`))
      }),
    })
    render(<App api={api} />)
    await screen.findByText('Where to?')
    await send('hi')

    expect(await screen.findByText('Half a reply')).toBeTruthy()
    expect((await screen.findByRole('alert')).textContent).toMatch(/something went wrong/)

    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText('Whole reply')).toBeTruthy()
    expect(screen.queryByText('Half a reply')).toBeNull()
  })

  it('a cut-off partial reply goes when Retry starts, leaving one reply', async () => {
    let calls = 0
    const api = makeApi(emptySession, {
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        calls += 1
        onEvent(start(`a${calls}`))
        if (calls === 1) {
          onEvent(token('Half a reply')) // the stream ends here: no done, no error
          return
        }
        onEvent(token('Whole reply'))
        onEvent(done(`a${calls}`))
      }),
    })
    render(<App api={api} />)
    await screen.findByText('Where to?')
    await send('hi')

    expect((await screen.findByRole('alert')).textContent).toMatch(/cut off/)
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText('Whole reply')).toBeTruthy()
    expect(screen.queryByText('Half a reply')).toBeNull()
    expect(screen.getAllByText('hi')).toHaveLength(1)
  })

  it('typing the same text again after an error works like Retry (one user bubble)', async () => {
    let calls = 0
    const api = makeApi(emptySession, {
      sendMessage: vi.fn(async (_id, _c, onEvent) => {
        calls += 1
        onEvent(start(`a${calls}`))
        if (calls === 1) {
          onEvent({ event: 'error', data: { message: 'Sorry, something went wrong', retryable: true } })
          return
        }
        onEvent(token('Whole reply'))
        onEvent(done(`a${calls}`))
      }),
    })
    render(<App api={api} />)
    await screen.findByText('Where to?')
    await send('plan austin')
    await screen.findByRole('alert')

    await send('plan austin')
    expect(await screen.findByText('Whole reply')).toBeTruthy()
    expect(screen.getAllByText('plan austin')).toHaveLength(1)
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
  })
})

describe('Generate needs a destination', () => {
  const noWhere = {
    ...sanJoseProfile,
    cities: [],
    vibe: null,
  } as TripProfile

  it('is disabled with a hint until the profile has a city or a vibe', async () => {
    const api = makeApi({ ...emptySession, trip_profile: noWhere })
    render(<App api={api} />)
    await screen.findByText('Where to?')

    const generate = screen.getByRole('button', { name: /Generate/ }) as HTMLButtonElement
    expect(generate.disabled).toBe(true)
    const hint = screen.getByText(/where you'd like to go first/)
    expect(generate.getAttribute('aria-describedby')).toBe(hint.id)
    fireEvent.click(generate)
    expect(api.generate).not.toHaveBeenCalled()
  })

  it('a vibe alone is enough', async () => {
    const api = makeApi({ ...emptySession, trip_profile: { ...noWhere, vibe: 'beach weekend' } })
    render(<App api={api} />)
    await screen.findByText('Where to?')

    expect((screen.getByRole('button', { name: /Generate/ }) as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByText(/where you'd like to go first/)).toBeNull()
  })

  it('a city is enough', async () => {
    const api = makeApi(emptySession)
    render(<App api={api} />)
    await screen.findByText('Where to?')

    const generate = screen.getByRole('button', { name: /Generate/ }) as HTMLButtonElement
    expect(generate.disabled).toBe(false)
    fireEvent.click(generate)
    await waitFor(() => expect(api.generate).toHaveBeenCalledTimes(1))
  })
})

describe('Book buttons wait', () => {
  const hotel = sanJoseV1.bookings.find((b) => b.kind === 'lodging')!
  const firstTodo = (b: Booking) => b.status === 'todo' && b.id !== hotel.id
  const other = sanJoseV1.bookings.find(firstTodo)!

  it('Mark booked is disabled while a plan is being made', async () => {
    const stream = deferred<void>()
    const api = makeApi(plannedSession, {
      sendMessage: vi.fn((_id, _c, onEvent) => {
        onEvent(start('a1'))
        onEvent(editing)
        return stream.promise
      }),
    })
    render(<App api={api} />)
    await openBookTab()
    await send('cheaper hotel')

    await waitFor(() => {
      const button = within(card(hotel.title)).getByRole('button', { name: 'Mark booked' }) as HTMLButtonElement
      expect(button.disabled).toBe(true)
    })
    fireEvent.click(within(card(hotel.title)).getByRole('button', { name: 'Mark booked' }))
    expect(api.patchBooking).not.toHaveBeenCalled()

    stream.resolve()
    await waitFor(() =>
      expect((within(card(hotel.title)).getByRole('button', { name: 'Mark booked' }) as HTMLButtonElement).disabled).toBe(false),
    )
  })

  it('a card waits while its own save runs (Undo too); other cards do not', async () => {
    const save = deferred<Booking>()
    const api = makeApi(plannedSession, { patchBooking: vi.fn(() => save.promise) })
    render(<App api={api} />)
    await openBookTab()

    fireEvent.click(within(card(hotel.title)).getByRole('button', { name: 'Mark booked' }))
    const undo = (await within(card(hotel.title)).findByRole('button', { name: 'Undo' })) as HTMLButtonElement
    expect(undo.disabled).toBe(true)
    fireEvent.click(undo)
    expect(api.patchBooking).toHaveBeenCalledTimes(1)
    expect((within(card(other.title)).getByRole('button', { name: 'Mark booked' }) as HTMLButtonElement).disabled).toBe(false)

    save.resolve({ ...hotel, status: 'booked' })
    await waitFor(() => expect((within(card(hotel.title)).getByRole('button', { name: 'Undo' }) as HTMLButtonElement).disabled).toBe(false))
  })

  it('the booking error clears on a tab change', async () => {
    const api = makeApi(plannedSession, {
      patchBooking: vi.fn(async () => Promise.reject(new ApiError(500, 'Server error'))),
    })
    render(<App api={api} />)
    await openBookTab()

    fireEvent.click(within(card(hotel.title)).getByRole('button', { name: 'Mark booked' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Couldn't save the booking/)

    fireEvent.click(screen.getByRole('button', { name: 'Back to plan' }))
    await screen.findByRole('heading', { level: 2, name: 'Plan' })
    fireEvent.click(bookTab())
    await screen.findByRole('heading', { level: 2, name: 'Book' })
    expect(screen.queryByText(/Couldn't save the booking/)).toBeNull()
  })
})

describe('aria labels and loading states', () => {
  it('icon buttons have aria labels', async () => {
    render(<App api={makeApi(plannedSession)} />)
    await openBookTab()

    expect(screen.getByRole('button', { name: 'Send' }).getAttribute('aria-label')).toBe('Send')
    expect(screen.getByRole('button', { name: 'Back to plan' }).getAttribute('aria-label')).toBe('Back to plan')
    expect(screen.getByRole('button', { name: 'New trip' }).getAttribute('aria-label')).toBe('New trip')

    const expand = screen.getByRole('button', { name: 'Expand history' })
    expect(expand.getAttribute('aria-label')).toBe('Expand history')
    fireEvent.click(expand)
    expect(screen.getByRole('button', { name: 'Collapse history' }).getAttribute('aria-label')).toBe('Collapse history')
  })

  it('shows "Loading your trip…" until the trip is loaded', async () => {
    const create = deferred<SessionDetail>()
    const api = makeApi(emptySession, { createSession: vi.fn(() => create.promise) })
    render(<App api={api} />)

    expect(await screen.findByText(/Loading your trip…/)).toBeTruthy()
    create.resolve(structuredClone(emptySession))
    expect(await screen.findByText('Where to?')).toBeTruthy()
    expect(screen.queryByText(/Loading your trip…/)).toBeNull()
  })

  it('shows "Loading trips…" in the open, empty rail until the list arrives', async () => {
    // Once a trip is open the rail already lists it, so the text shows while the list is empty:
    // here the trip itself failed to load, and the list is still on its way.
    const list = deferred<SessionSummary[]>()
    let calls = 0
    const api = makeApi(emptySession, {
      // The first call picks the trip to open; the second fills the rail.
      listSessions: vi.fn(async () => {
        calls += 1
        return calls === 1 ? [] : list.promise
      }),
      createSession: vi.fn(async () => Promise.reject(new ApiError(500, 'Server error'))),
    })
    render(<App api={api} />)
    fireEvent.click(screen.getByRole('button', { name: 'Expand history' }))

    expect(await screen.findByText(/Loading trips…/)).toBeTruthy()
    list.resolve([{ id: 's-9', title: 'Austin weekend', status: 'intake', updated_at: '2026-11-27T10:00:00Z' }])
    expect(await screen.findByText('Austin weekend')).toBeTruthy()
    expect(screen.queryByText(/Loading trips…/)).toBeNull()
  })
})

describe('HistoryRail loading and busy rows', () => {
  const sessions: SessionSummary[] = [
    { id: 's-1', title: 'San Jose · Mar 5–7', status: 'planned', updated_at: '2026-11-27T10:00:00Z' },
    { id: 's-2', title: 'Austin · Apr 10–12', status: 'planned', updated_at: '2026-11-20T10:00:00Z' },
  ]
  const props = {
    onToggle: vi.fn(),
    activeId: null,
    error: null,
    onNew: vi.fn(),
    onOpen: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onRetry: vi.fn(),
  }

  it('"Loading trips…" shows only in the open rail with no trips yet', () => {
    const { rerender } = render(<HistoryRail {...props} open sessions={[]} loading />)
    expect(screen.getByText(/Loading trips…/)).toBeTruthy()

    rerender(<HistoryRail {...props} open={false} sessions={[]} loading />)
    expect(screen.queryByText(/Loading trips…/)).toBeNull()

    rerender(<HistoryRail {...props} open sessions={sessions} loading />)
    expect(screen.queryByText(/Loading trips…/)).toBeNull()

    rerender(<HistoryRail {...props} open sessions={[]} loading={false} />)
    expect(screen.queryByText(/Loading trips…/)).toBeNull()
  })

  it('a trip being renamed or deleted is marked busy', () => {
    render(<HistoryRail {...props} open sessions={sessions} busyId="s-2" />)
    const row = (title: string) => screen.getByTitle(title).closest('[aria-busy]') as HTMLElement
    expect(row('Austin · Apr 10–12').getAttribute('aria-busy')).toBe('true')
    expect(row('San Jose · Mar 5–7').getAttribute('aria-busy')).toBe('false')
  })
})
