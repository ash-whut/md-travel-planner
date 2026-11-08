// Step 24 end to end in the UI: empty plan → Generate → skeleton → day cards; tab locking; reload.
// App + store + PlanView with a fake ApiClient (no network).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseProfile, sanJoseV1, sanJoseV2 } from './fixtures'
import { SESSION_KEY, useTripStore } from './store/useTripStore'
import type { SessionDetail, SseEvent } from './types'
import App from './App'

const emptySession: SessionDetail = {
  id: 's-1',
  title: 'New trip',
  status: 'intake',
  trip_profile: sanJoseProfile,
  messages: [{ id: 'g', role: 'assistant', content: 'Where to?', itinerary_version: null, created_at: '' }],
  itinerary: null,
  created_at: '',
  updated_at: '',
}

const plannedSession: SessionDetail = { ...emptySession, status: 'planned', itinerary: sanJoseV1 }

const start = (id: string): SseEvent => ({ event: 'message_start', data: { message_id: id } })
const drafting: SseEvent = { event: 'status', data: { label: 'Drafting your plan…', state: 'start' } }
const done = (id: string): SseEvent => ({ event: 'done', data: { message_id: id } })

function makeApi(session: SessionDetail, overrides: Partial<ApiClient> = {}) {
  return {
    createSession: vi.fn(async () => session),
    getSession: vi.fn(async () => session),
    sendMessage: vi.fn<ApiClient['sendMessage']>(async () => {}),
    generate: vi.fn<ApiClient['generate']>(async () => {}),
    ...overrides,
  }
}

function tagsShown(): string[] {
  return [...new Set(screen.getAllByTitle(/^Refer to this as "/).map((b) => b.textContent ?? ''))].sort()
}

const tab = (name: string) => screen.getByRole('button', { name })

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('Generate from the empty Plan tab', () => {
  it('calls the API, shows skeletons with the status line, then day cards with letters', async () => {
    let push!: (e: SseEvent) => void
    let finish!: () => void
    const generate = vi.fn<ApiClient['generate']>(
      (_id, onEvent) =>
        new Promise<void>((resolve) => {
          push = onEvent
          finish = resolve
        }),
    )
    const api = makeApi(emptySession, { generate })
    render(<App api={api} />)
    await screen.findByText('Where to?')
    expect(screen.getByText('Your trip plan will appear here')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /Generate/ }))
    expect(generate).toHaveBeenCalledTimes(1)
    expect(generate.mock.calls[0][0]).toBe('s-1')
    // The skeleton shows before any event arrives.
    expect((await screen.findAllByTestId('skeleton-day')).length).toBeGreaterThan(0)

    push(start('a1'))
    push(drafting)
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Drafting your plan…'))

    push({ event: 'itinerary', data: sanJoseV1 })
    push({ event: 'token', data: { text: 'Here is your plan.' } })
    push(done('a1'))
    finish()

    expect(await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
    expect(tagsShown()).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K'])
    expect(screen.queryAllByTestId('skeleton-day')).toHaveLength(0)
    expect(tab('Map').getAttribute('aria-disabled')).not.toBe('true')
    expect(tab('Book').getAttribute('aria-disabled')).not.toBe('true')
  })

  it('a failed generation removes the skeleton, shows an error, and Retry generates again', async () => {
    let calls = 0
    const generate = vi.fn<ApiClient['generate']>(async (_id, onEvent) => {
      calls += 1
      if (calls === 1) {
        ;[start('a0'), drafting, { event: 'error', data: { message: 'Could not make the plan', retryable: true } } as SseEvent].forEach(onEvent)
        return
      }
      ;[start('a1'), drafting, { event: 'itinerary', data: sanJoseV1 } as SseEvent, done('a1')].forEach(onEvent)
    })
    const api = makeApi(emptySession, { generate })
    render(<App api={api} />)
    await screen.findByText('Where to?')
    fireEvent.click(screen.getByRole('button', { name: /Generate/ }))

    expect((await screen.findByRole('alert')).textContent).toMatch(/Could not make the plan/)
    expect(screen.queryAllByTestId('skeleton-day')).toHaveLength(0)
    expect(screen.getByRole('button', { name: /Generate/ })).toBeTruthy()
    expect(tab('Map').getAttribute('aria-disabled')).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
    expect(generate).toHaveBeenCalledTimes(2)
    expect(api.sendMessage).not.toHaveBeenCalled()
  })

  it('disables Generate while a chat reply is streaming', async () => {
    let finish!: () => void
    const sendMessage = vi.fn<ApiClient['sendMessage']>(
      (_id, _c, onEvent) =>
        new Promise<void>((resolve) => {
          onEvent(start('a1'))
          finish = () => {
            onEvent(done('a1'))
            resolve()
          }
        }),
    )
    const api = makeApi(emptySession, { sendMessage })
    render(<App api={api} />)
    await screen.findByText('Where to?')
    const input = screen.getByPlaceholderText(/Edit by letter/)
    fireEvent.change(input, { target: { value: 'San Jose' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    const button = screen.getByRole('button', { name: /Generate/ }) as HTMLButtonElement
    await waitFor(() => expect(button.disabled).toBe(true))
    fireEvent.click(button)
    expect(api.generate).not.toHaveBeenCalled()
    finish()
    await waitFor(() => expect(button.disabled).toBe(false))
  })

  it('"make the plan" in chat shows the skeleton and then the plan', async () => {
    let push!: (e: SseEvent) => void
    let finish!: () => void
    const sendMessage = vi.fn<ApiClient['sendMessage']>(
      (_id, _c, onEvent) =>
        new Promise<void>((resolve) => {
          push = onEvent
          finish = resolve
        }),
    )
    render(<App api={makeApi(emptySession, { sendMessage })} />)
    await screen.findByText('Where to?')
    const input = screen.getByPlaceholderText(/Edit by letter/)
    fireEvent.change(input, { target: { value: 'just make the plan' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalled())

    push(start('a1'))
    push(drafting)
    expect((await screen.findAllByTestId('skeleton-day')).length).toBeGreaterThan(0)
    push({ event: 'itinerary', data: sanJoseV1 })
    push(done('a1'))
    finish()
    expect(await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
  })
})

describe('Map and Book tabs', () => {
  it('are disabled with a tooltip and ignore clicks before a plan exists', async () => {
    render(<App api={makeApi(emptySession)} />)
    await screen.findByText('Where to?')
    for (const name of ['Map', 'Book']) {
      expect(tab(name).getAttribute('aria-disabled')).toBe('true')
      expect(tab(name).getAttribute('title')).toBe('Generate a plan to unlock')
      fireEvent.click(tab(name))
      expect(screen.getByRole('heading', { level: 2, name: 'Plan' })).toBeTruthy()
      expect(screen.queryByTestId('map')).toBeNull()
    }
  })

  it('an itinerary event during a stream switches back to the Plan tab', async () => {
    let push!: (e: SseEvent) => void
    let finish!: () => void
    const sendMessage = vi.fn<ApiClient['sendMessage']>(
      (_id, _c, onEvent) =>
        new Promise<void>((resolve) => {
          push = onEvent
          finish = resolve
        }),
    )
    localStorage.setItem(SESSION_KEY, 's-1')
    render(<App api={makeApi(plannedSession, { sendMessage })} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
    fireEvent.click(tab('Map'))
    expect(await screen.findByTestId('map')).toBeTruthy()

    const input = screen.getByPlaceholderText(/Edit by letter/)
    fireEvent.change(input, { target: { value: 'replace [F] with something vegan' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalled())
    push(start('a2'))
    push({ event: 'itinerary', data: sanJoseV2 })
    push(done('a2'))
    finish()

    expect(await screen.findByRole('heading', { level: 1, name: sanJoseV2.title })).toBeTruthy()
    expect(screen.queryByTestId('map')).toBeNull()
    expect(screen.getByRole('heading', { level: 2, name: 'Plan' })).toBeTruthy()
  })
})

describe('Reload', () => {
  it('shows the saved plan from the stored session without generating', async () => {
    localStorage.setItem(SESSION_KEY, 's-1')
    const api = makeApi(plannedSession)
    render(<App api={api} />)
    expect(await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
    expect(api.getSession).toHaveBeenCalledWith('s-1')
    expect(api.generate).not.toHaveBeenCalled()
    expect(screen.queryByText('Your trip plan will appear here')).toBeNull()
    expect(tab('Map').getAttribute('aria-disabled')).not.toBe('true')
  })
})
