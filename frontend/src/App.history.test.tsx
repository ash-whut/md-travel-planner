// Step 45: the history rail wired to the stores and a fake backend — the list loads on start,
// a `title` event renames the open trip in the list, opening and deleting switch trips.
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseProfile } from './fixtures'
import { useHistoryStore } from './store/useHistoryStore'
import { SESSION_KEY, useTripStore } from './store/useTripStore'
import type { SessionDetail, SessionSummary, SseEvent } from './types'
import App from './App'

function detail(id: string, title: string, greeting: string): SessionDetail {
  return {
    id,
    title,
    status: 'intake',
    trip_profile: sanJoseProfile,
    messages: [{ id: `g-${id}`, role: 'assistant', content: greeting, itinerary_version: null, created_at: '' }],
    itinerary: null,
    created_at: '',
    updated_at: '',
  }
}

// A tiny in-memory backend: the summaries are the server's list, newest first.
function fakeBackend(summaries: SessionSummary[]) {
  let list = [...summaries]
  const api = {
    createSession: vi.fn(async () => {
      const created = detail('s-new', 'New trip', 'Hi from the new trip')
      list = [{ id: created.id, title: created.title, status: 'intake' as const, updated_at: new Date().toISOString() }, ...list]
      return created
    }),
    getSession: vi.fn(async (id: string) => {
      const s = list.find((x) => x.id === id)!
      return detail(id, s.title, `Hi from ${s.title}`)
    }),
    listSessions: vi.fn(async () => list),
    renameSession: vi.fn(async (id: string, title: string) => {
      list = list.map((s) => (s.id === id ? { ...s, title } : s))
      return list.find((s) => s.id === id)!
    }),
    deleteSession: vi.fn(async (id: string) => {
      list = list.filter((s) => s.id !== id)
    }),
    sendMessage: vi.fn<ApiClient['sendMessage']>(async () => {}),
    generate: vi.fn(async () => {}),
    patchBooking: vi.fn(),
  }
  return api
}

const now = new Date().toISOString()
const twoTrips: SessionSummary[] = [
  { id: 's-1', title: 'San Jose · Mar 5–7', status: 'intake', updated_at: now },
  { id: 's-2', title: 'Austin · Apr 10–12', status: 'intake', updated_at: now },
]

const rail = () => within(screen.getByRole('navigation', { name: 'Trip history' }))
const railTitles = () => rail().getAllByRole('button', { name: /^(?!Rename|Delete)/ }).map((b) => b.getAttribute('title'))

async function openRail() {
  fireEvent.click(screen.getByTitle('Expand history'))
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useHistoryStore.getState().reset()
})

describe('App history', () => {
  it('on start with no stored id, opens the most recent trip and lists all trips', async () => {
    const api = fakeBackend(twoTrips)
    render(<App api={api} />)
    expect(await screen.findByText('Hi from San Jose · Mar 5–7')).toBeTruthy()
    expect(api.createSession).not.toHaveBeenCalled()
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-1')

    await openRail()
    await screen.findByTitle('Austin · Apr 10–12')
    expect(railTitles()).toEqual(['San Jose · Mar 5–7', 'Austin · Apr 10–12'])
  })

  it('clicking a trip opens its chat', async () => {
    const api = fakeBackend(twoTrips)
    render(<App api={api} />)
    await openRail()
    fireEvent.click(await screen.findByTitle('Austin · Apr 10–12'))
    expect(await screen.findByText('Hi from Austin · Apr 10–12')).toBeTruthy()
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-2')
    expect(screen.getByTitle('Austin · Apr 10–12').getAttribute('aria-current')).toBe('true')
  })

  it('a `title` event renames the open trip in the list, and the turn moves it to the top', async () => {
    const api = fakeBackend(twoTrips)
    api.sendMessage.mockImplementation(async (_id, _text, onEvent: (e: SseEvent) => void) => {
      onEvent({ event: 'message_start', data: { message_id: 'a1' } })
      onEvent({ event: 'title', data: { title: 'Austin · Mar 6–8' } })
      onEvent({ event: 'token', data: { text: 'Sounds fun!' } })
      onEvent({ event: 'done', data: { message_id: 'a1' } })
    })
    localStorage.setItem(SESSION_KEY, 's-2')
    render(<App api={api} />)
    await openRail()
    await screen.findByText('Hi from Austin · Apr 10–12')
    await screen.findByTitle('San Jose · Mar 5–7')

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'Austin, Mar 6–8' } })
    await act(async () => fireEvent.keyDown(input, { key: 'Enter' }))

    expect(await screen.findByTitle('Austin · Mar 6–8')).toBeTruthy()
    expect(railTitles()).toEqual(['Austin · Mar 6–8', 'San Jose · Mar 5–7'])
  })

  it('New trip creates a session, opens it and adds it to the top of the list', async () => {
    const api = fakeBackend(twoTrips)
    render(<App api={api} />)
    await screen.findByText('Hi from San Jose · Mar 5–7')
    await openRail()
    fireEvent.click(screen.getByRole('button', { name: /New trip/ }))
    expect(await screen.findByText('Hi from the new trip')).toBeTruthy()
    expect(railTitles()[0]).toBe('New trip')
  })

  it('renaming through the rail saves it and shows the new name', async () => {
    const api = fakeBackend(twoTrips)
    render(<App api={api} />)
    await openRail()
    fireEvent.click(await screen.findByRole('button', { name: 'Rename Austin · Apr 10–12' }))
    const input = screen.getByRole('textbox', { name: 'Trip name' })
    fireEvent.change(input, { target: { value: 'Spring break' } })
    await act(async () => fireEvent.keyDown(input, { key: 'Enter' }))
    expect(api.renameSession).toHaveBeenCalledWith('s-2', 'Spring break')
    expect(await screen.findByTitle('Spring break')).toBeTruthy()
  })

  it('deleting the open trip switches to the next one', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const api = fakeBackend(twoTrips)
    render(<App api={api} />)
    await screen.findByText('Hi from San Jose · Mar 5–7')
    await openRail()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Delete San Jose · Mar 5–7' })))
    expect(api.deleteSession).toHaveBeenCalledWith('s-1')
    expect(await screen.findByText('Hi from Austin · Apr 10–12')).toBeTruthy()
    expect(railTitles()).toEqual(['Austin · Apr 10–12'])
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-2')
  })

  it('the list survives a reload: a fresh start shows the same trips from the backend', async () => {
    const api = fakeBackend(twoTrips)
    const { unmount } = render(<App api={api} />)
    await openRail()
    await screen.findByTitle('Austin · Apr 10–12')
    unmount()
    useTripStore.getState().reset()
    useHistoryStore.getState().reset()

    render(<App api={api} />)
    await openRail()
    await screen.findByTitle('Austin · Apr 10–12')
    expect(railTitles()).toEqual(['San Jose · Mar 5–7', 'Austin · Apr 10–12'])
  })
})
