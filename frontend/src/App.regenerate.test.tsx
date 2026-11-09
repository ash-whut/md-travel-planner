// Step 26 end to end in the UI: Regenerate swaps v1 for skeletons, then v2 replaces v1; a failed
// run keeps the old plan; Regenerate is disabled while a chat reply streams.
// App + store + PlanView + ChatPanel with a fake ApiClient (no network).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseProfile, sanJoseV1, sanJoseV2 } from './fixtures'
import { SESSION_KEY, useTripStore } from './store/useTripStore'
import type { SessionDetail, SseEvent } from './types'
import App from './App'

const plannedSession: SessionDetail = {
  id: 's-1',
  title: sanJoseV1.title,
  status: 'planned',
  trip_profile: sanJoseProfile,
  messages: [
    { id: 'm1', role: 'assistant', content: 'Here is your plan.', itinerary_version: 1, created_at: '' },
  ],
  itinerary: sanJoseV1,
  created_at: '',
  updated_at: '',
}

const start = (id: string): SseEvent => ({ event: 'message_start', data: { message_id: id } })
const drafting: SseEvent = { event: 'status', data: { label: 'Drafting your plan…', state: 'start' } }
const done = (id: string): SseEvent => ({ event: 'done', data: { message_id: id } })

function makeApi(overrides: Partial<ApiClient> = {}) {
  return {
    createSession: vi.fn(async () => plannedSession),
    getSession: vi.fn(async () => plannedSession),
    sendMessage: vi.fn<ApiClient['sendMessage']>(async () => {}),
    generate: vi.fn<ApiClient['generate']>(async () => {}),
    patchBooking: vi.fn(),
    ...overrides,
  }
}

/** A stream the test drives by hand: push events, then finish. */
function manualStream() {
  const ctl: { push: (e: SseEvent) => void; finish: () => void } = { push: () => {}, finish: () => {} }
  const run = (onEvent: (e: SseEvent) => void) =>
    new Promise<void>((resolve) => {
      ctl.push = onEvent
      ctl.finish = resolve
    })
  return { ctl, run }
}

const regenerateButton = () => screen.getByRole('button', { name: /Regenerate/ }) as HTMLButtonElement
const badge = () => screen.getByText(/^v\d+ ·/)

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem(SESSION_KEY, 's-1')
  useTripStore.getState().reset()
})

describe('Regenerate', () => {
  it('calls the API, shows skeletons in place of v1, then v2 replaces v1 with a marker in chat', async () => {
    const { ctl, run } = manualStream()
    const generate = vi.fn<ApiClient['generate']>((_id, onEvent) => run(onEvent))
    const api = makeApi({ generate })
    render(<App api={api} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
    expect(badge().textContent).toMatch(/^v1 · created /)
    expect(screen.getAllByTestId('version-marker').map((m) => m.textContent?.trim())).toEqual(['Plan created · v1'])

    fireEvent.click(regenerateButton())
    expect(generate).toHaveBeenCalledTimes(1)
    expect(generate.mock.calls[0][0]).toBe('s-1')
    expect(api.sendMessage).not.toHaveBeenCalled()

    // The old plan is swapped for skeletons right away.
    expect((await screen.findAllByTestId('skeleton-day')).length).toBeGreaterThan(0)
    expect(screen.queryByRole('heading', { level: 1, name: sanJoseV1.title })).toBeNull()

    ctl.push(start('a2'))
    ctl.push(drafting)
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Drafting your plan…'))

    ctl.push({ event: 'itinerary', data: sanJoseV2 })
    ctl.push({ event: 'token', data: { text: 'Here is a fresh version.' } })
    ctl.push(done('a2'))
    ctl.finish()

    await waitFor(() => expect(badge().textContent).toMatch(/^v2 · updated /))
    expect(screen.queryAllByTestId('skeleton-day')).toHaveLength(0)
    expect(screen.getByText('Good Karma Kitchen')).toBeTruthy()
    expect(screen.queryByText('Baconhouse')).toBeNull()
    expect(screen.getAllByText('Updated in v2')).toHaveLength(1)
    expect(screen.getAllByTestId('version-marker').map((m) => m.textContent?.trim())).toEqual([
      'Plan created · v1',
      'Plan updated · v2',
    ])
    expect(regenerateButton().disabled).toBe(false)
  })

  it('a failed run shows the error and the old plan comes back', async () => {
    const generate = vi.fn<ApiClient['generate']>(async (_id, onEvent) => {
      ;[
        start('a2'),
        drafting,
        { event: 'status', data: { label: 'Drafting your plan…', state: 'error' } } as SseEvent,
        { event: 'error', data: { message: 'Could not make the plan', retryable: true } } as SseEvent,
      ].forEach(onEvent)
    })
    render(<App api={makeApi({ generate })} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })

    fireEvent.click(regenerateButton())
    expect((await screen.findByRole('alert')).textContent).toMatch(/Could not make the plan/)
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
    expect(badge().textContent).toMatch(/^v1 ·/)
    expect(screen.queryAllByTestId('skeleton-day')).toHaveLength(0)
    expect(useTripStore.getState().itinerary?.version).toBe(1)
    expect(screen.getAllByTestId('version-marker')).toHaveLength(1)
  })

  it('is disabled while a chat reply streams', async () => {
    const { ctl, run } = manualStream()
    const sendMessage = vi.fn<ApiClient['sendMessage']>((_id, _c, onEvent) => run(onEvent))
    const api = makeApi({ sendMessage })
    render(<App api={api} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })

    const input = screen.getByRole('textbox', { name: 'Message' })
    fireEvent.change(input, { target: { value: 'what is [C]?' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(regenerateButton().disabled).toBe(true))
    fireEvent.click(regenerateButton())
    expect(api.generate).not.toHaveBeenCalled()

    ctl.push(start('a2'))
    ctl.push(done('a2'))
    ctl.finish()
    await waitFor(() => expect(regenerateButton().disabled).toBe(false))
  })

  it('a chat edit keeps the plan on screen (no skeleton) and then shows v2', async () => {
    const { ctl, run } = manualStream()
    const sendMessage = vi.fn<ApiClient['sendMessage']>((_id, _c, onEvent) => run(onEvent))
    render(<App api={makeApi({ sendMessage })} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })

    const input = screen.getByRole('textbox', { name: 'Message' })
    fireEvent.change(input, { target: { value: 'replace [F] with something vegan' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(sendMessage).toHaveBeenCalled())
    ctl.push(start('a2'))
    ctl.push({ event: 'status', data: { label: 'Updating your plan…', state: 'start' } })
    await waitFor(() => expect(useTripStore.getState().generating).toBe(true))
    expect(screen.queryAllByTestId('skeleton-day')).toHaveLength(0)
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()

    ctl.push({ event: 'itinerary', data: sanJoseV2 })
    ctl.push(done('a2'))
    ctl.finish()
    await waitFor(() => expect(badge().textContent).toMatch(/^v2 · updated /))
    expect(screen.getAllByTestId('version-marker')).toHaveLength(2)
  })
})
