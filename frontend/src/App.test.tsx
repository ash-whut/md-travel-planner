import { StrictMode } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from './api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseV2 } from './fixtures'
import { SESSION_KEY, useTripStore } from './store/useTripStore'
import type { SessionDetail } from './types'
import App from './App'

// A backend session that already holds the San Jose trip.
const sanJoseSession: SessionDetail = {
  id: 's-1',
  title: sanJoseV2.title,
  status: 'planned',
  trip_profile: sanJoseProfile,
  messages: sanJoseMessages,
  itinerary: sanJoseV2,
  created_at: '2027-03-01T00:00:00Z',
  updated_at: '2027-03-01T00:00:00Z',
}

const fakeApi: ApiClient = {
  createSession: async () => sanJoseSession,
  getSession: async () => sanJoseSession,
  sendMessage: async () => {},
  generate: async () => {},
  patchBooking: async () => { throw new Error('patchBooking is not used here') },
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('App', () => {
  it('renders the Plan tab and the Chat header', () => {
    render(<App api={fakeApi} />)
    expect(screen.getByRole('heading', { name: 'Plan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Chat' })).toBeTruthy()
  })

  it('shows the Plan, Map and Book tab buttons', () => {
    render(<App api={fakeApi} />)
    for (const label of ['Plan', 'Map', 'Book']) {
      expect(screen.getByRole('button', { name: label })).toBeTruthy()
    }
  })

  it('renders the Map tab through the mocked react-leaflet', async () => {
    render(<App api={fakeApi} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV2.title }) // Map unlocks once the plan loads
    fireEvent.click(screen.getByRole('button', { name: 'Map' }))
    expect(screen.getByRole('heading', { name: 'Map' })).toBeTruthy()
    expect(await screen.findByTestId('map')).toBeTruthy()
  })
})

describe('App session start (fake ApiClient)', () => {
  const greeting = 'Hey! Where do you want to go?'
  const newSession: SessionDetail = {
    id: 's-new',
    title: 'New trip',
    status: 'intake',
    trip_profile: sanJoseProfile,
    messages: [{ id: 'g1', role: 'assistant', content: greeting, itinerary_version: null, created_at: '' }],
    itinerary: null,
    created_at: '',
    updated_at: '',
  }

  function spyApi(getSession: ApiClient['getSession'] = async () => sanJoseSession) {
    return { createSession: vi.fn(async () => newSession), getSession: vi.fn(getSession), sendMessage: vi.fn(async () => {}), generate: vi.fn(async () => {}), patchBooking: vi.fn() }
  }

  it('creates a session when none is stored, stores its id and shows the backend greeting', async () => {
    const api = spyApi()
    render(<App api={api} />)
    expect(await screen.findByText(greeting)).toBeTruthy()
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(api.getSession).not.toHaveBeenCalled()
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-new')
    // A fresh session has no plan yet: the plan pane shows a placeholder.
    expect(screen.getByText('Your trip plan will appear here')).toBeTruthy()
  })

  it('creates only one session under StrictMode', async () => {
    const api = spyApi()
    render(
      <StrictMode>
        <App api={api} />
      </StrictMode>,
    )
    expect(await screen.findByText(greeting)).toBeTruthy()
    expect(api.createSession).toHaveBeenCalledTimes(1)
  })

  it('reuses a stored session id and shows that trip', async () => {
    localStorage.setItem(SESSION_KEY, 's-1')
    const api = spyApi()
    render(<App api={api} />)
    expect(await screen.findByText(sanJoseMessages[0].content)).toBeTruthy()
    expect(api.getSession).toHaveBeenCalledWith('s-1')
    expect(api.createSession).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV2.title })).toBeTruthy()
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-1')
  })

  it('recovers from a stale stored id (404) by creating a new session', async () => {
    localStorage.setItem(SESSION_KEY, 'stale')
    const api = spyApi(async () => {
      throw new ApiError(404, 'Session not found')
    })
    render(<App api={api} />)
    expect(await screen.findByText(greeting)).toBeTruthy()
    expect(api.getSession).toHaveBeenCalledWith('stale')
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(SESSION_KEY)).toBe('s-new')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows an alert when the backend cannot be reached', async () => {
    const api = {
      createSession: vi.fn(async (): Promise<SessionDetail> => {
        throw new TypeError('Failed to fetch')
      }),
      getSession: vi.fn(async () => sanJoseSession),
      sendMessage: vi.fn(async () => {}),
      generate: vi.fn(async () => {}),
      patchBooking: vi.fn(),
    }
    render(<App api={api} />)
    expect((await screen.findByRole('alert')).textContent).toMatch(/Failed to fetch/)
  })

  it('keeps the Map and Book tabs locked when there is no plan yet', async () => {
    render(<App api={spyApi()} />)
    await screen.findByText(greeting)
    for (const name of ['Map', 'Book']) {
      const tab = screen.getByRole('button', { name })
      expect(tab.getAttribute('aria-disabled')).toBe('true')
      expect(tab.getAttribute('title')).toBe('Generate a plan to unlock')
      fireEvent.click(tab)
      expect(screen.getByRole('heading', { name: 'Plan' })).toBeTruthy()
    }
    expect(screen.queryByTestId('map')).toBeNull()
    expect(screen.getByText('Your trip plan will appear here')).toBeTruthy()
  })
})
