// Step 46 (D36): with the backend down, the login check keeps the token and offers Try again
// instead of logging out; the login form says the backend isn't reachable.
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthClient } from './api/auth'
import { getToken, setToken } from './api/auth'
import { ApiError, NetworkError, type ApiClient } from './api/client'
import { useHistoryStore } from './store/useHistoryStore'
import { useTripStore } from './store/useTripStore'
import type { SessionDetail, User } from './types'
import AuthGate from './AuthGate'

const sean: User = {
  id: 'u-1',
  username: 'sean',
  profile: { home_city: null, budget_level: null, dietary: null, pace: null, transport: null, travel_mode: null, interests: [] },
}

function fakeAuth(): AuthClient & { [K in keyof AuthClient]: ReturnType<typeof vi.fn> } {
  return {
    register: vi.fn(async () => ({ token: 't-new', user: sean })),
    login: vi.fn(async () => ({ token: 't-1', user: sean })),
    logout: vi.fn(async () => {}),
    me: vi.fn(async () => sean),
    updateProfile: vi.fn(async () => sean),
  }
}

function fakeApi(): ApiClient {
  const trip: SessionDetail = {
    id: 's-1',
    title: 'New trip',
    status: 'intake',
    trip_profile: { cities: [], interests: [], missing_required: [] } as unknown as SessionDetail['trip_profile'],
    messages: [{ id: 'g', role: 'assistant', content: 'Hi, where do you want to go?', itinerary_version: null, created_at: '' }],
    itinerary: null,
    created_at: '',
    updated_at: '',
  }
  return {
    createSession: vi.fn(async () => trip),
    getSession: vi.fn(async () => trip),
    listSessions: vi.fn(async () => []),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
    sendMessage: vi.fn(async () => {}),
    generate: vi.fn(async () => {}),
    patchBooking: vi.fn(),
  }
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useHistoryStore.getState().reset()
})

describe('AuthGate with the backend down', () => {
  it('keeps the token and shows "Backend not reachable" with Try again', async () => {
    setToken('t-1')
    const auth = fakeAuth()
    auth.me.mockRejectedValueOnce(new NetworkError('Failed to fetch'))
    render(<AuthGate auth={auth} api={fakeApi()} />)

    expect(await screen.findByText('Backend not reachable')).toBeTruthy()
    expect(getToken()).toBe('t-1')
    expect(screen.queryByRole('button', { name: 'Log in' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Hi, where do you want to go?')).toBeTruthy()
    expect(auth.me).toHaveBeenCalledTimes(2)
    expect(screen.queryByText('Backend not reachable')).toBeNull()
  })

  it('a rejected token (HTTP 401) still goes back to the login screen', async () => {
    setToken('t-1')
    const auth = fakeAuth()
    auth.me.mockRejectedValue(new ApiError(401, 'Please log in again'))
    render(<AuthGate auth={auth} api={fakeApi()} />)

    expect(await screen.findByRole('button', { name: 'Log in' })).toBeTruthy()
    expect(getToken()).toBeNull()
    expect(screen.queryByText('Backend not reachable')).toBeNull()
  })

  it('logging in with no response says the backend is not reachable', async () => {
    const auth = fakeAuth()
    auth.login.mockRejectedValue(new NetworkError('Failed to fetch'))
    render(<AuthGate auth={auth} api={fakeApi()} />)

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'sean' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'ducks123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    expect((await screen.findByRole('alert')).textContent).toMatch(/Backend not reachable/)
    expect(getToken()).toBeNull()
    expect((screen.getByRole('button', { name: 'Log in' }) as HTMLButtonElement).disabled).toBe(false)
  })
})
