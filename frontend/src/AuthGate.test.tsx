// Accounts (decisions D32): login screen, register, profile dialog, logout.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthClient } from './api/auth'
import { getToken, setToken } from './api/auth'
import { ApiError, type ApiClient } from './api/client'
import { useHistoryStore } from './store/useHistoryStore'
import { useTripStore } from './store/useTripStore'
import type { SessionDetail, User, UserProfile } from './types'
import AuthGate from './AuthGate'

const emptyProfile: UserProfile = {
  home_city: null,
  budget_level: null,
  dietary: null,
  pace: null,
  transport: null,
  travel_mode: null,
  interests: [],
}
const sean: User = { id: 'u-1', username: 'sean', profile: emptyProfile }

function fakeAuth(): AuthClient & { [K in keyof AuthClient]: ReturnType<typeof vi.fn> } {
  return {
    register: vi.fn(async () => ({ token: 't-new', user: sean })),
    login: vi.fn(async ({ password }) => {
      if (password !== 'ducks123') throw new ApiError(401, 'Wrong username or password')
      return { token: 't-1', user: sean }
    }),
    logout: vi.fn(async () => {}),
    me: vi.fn(async () => sean),
    updateProfile: vi.fn(async (profile: UserProfile) => ({ ...sean, profile })),
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

function logIn(password = 'ducks123') {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'Sean' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Log in' }))
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useHistoryStore.getState().reset()
})

describe('AuthGate', () => {
  it('shows the login screen without a token, then the app after logging in', async () => {
    const auth = fakeAuth()
    render(<AuthGate auth={auth} api={fakeApi()} />)
    logIn()
    expect(await screen.findByText('Hi, where do you want to go?')).toBeTruthy()
    expect(auth.login).toHaveBeenCalledWith({ username: 'sean', password: 'ducks123' })
    expect(getToken()).toBe('t-1')
  })

  it('shows the error for a wrong password and stays on the login screen', async () => {
    render(<AuthGate auth={fakeAuth()} api={fakeApi()} />)
    logIn('nope')
    expect((await screen.findByRole('alert')).textContent).toContain('Wrong username or password')
    expect(getToken()).toBeNull()
  })

  it('can create an account instead', async () => {
    const auth = fakeAuth()
    render(<AuthGate auth={auth} api={fakeApi()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'aadi' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret12' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Hi, where do you want to go?')).toBeTruthy()
    expect(auth.register).toHaveBeenCalledWith({ username: 'aadi', password: 'secret12' })
  })

  it('a stored token skips the login screen; a rejected one shows it', async () => {
    setToken('t-1')
    const { unmount } = render(<AuthGate auth={fakeAuth()} api={fakeApi()} />)
    expect(await screen.findByText('Hi, where do you want to go?')).toBeTruthy()
    unmount()
    useTripStore.getState().reset()

    const auth = fakeAuth()
    auth.me.mockRejectedValue(new ApiError(401, 'Please log in again'))
    render(<AuthGate auth={auth} api={fakeApi()} />)
    expect(await screen.findByRole('button', { name: 'Log in' })).toBeTruthy()
    expect(getToken()).toBeNull()
  })

  it('edits the profile and logs out', async () => {
    setToken('t-1')
    const auth = fakeAuth()
    const onLoggedOut = vi.fn()
    render(<AuthGate auth={auth} api={fakeApi()} onLoggedOut={onLoggedOut} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Your profile' }))

    fireEvent.change(screen.getByLabelText('Home city / airport'), { target: { value: 'College Station' } })
    fireEvent.change(screen.getByLabelText('Budget'), { target: { value: 'budget' } })
    fireEvent.change(screen.getByLabelText('Dietary needs'), { target: { value: 'vegan' } })
    fireEvent.change(screen.getByLabelText('Interests'), { target: { value: 'food, , museums' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(auth.updateProfile).toHaveBeenCalledWith({
      ...emptyProfile,
      home_city: 'College Station',
      budget_level: 'budget',
      dietary: 'vegan',
      interests: ['food', 'museums'],
    })

    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    await waitFor(() => expect(onLoggedOut).toHaveBeenCalled())
    expect(auth.logout).toHaveBeenCalled()
    expect(getToken()).toBeNull()
  })
})
