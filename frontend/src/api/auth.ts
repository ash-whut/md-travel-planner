// Accounts (contracts §4, decisions D32): the login token and the auth/profile calls.
// The token lives in localStorage and every backend request sends it as a Bearer header.
import type { AuthBody, AuthResponse, User, UserProfile } from '@/types'
import { ApiError } from './client'

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const TOKEN_KEY = 'md-travel-planner.token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Storage blocked: the login lasts for this page only.
  }
}

// Spread into a request's headers. Empty when logged out, so requests work as before.
export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface AuthClient {
  register(body: AuthBody): Promise<AuthResponse>
  login(body: AuthBody): Promise<AuthResponse>
  logout(): Promise<void>
  me(): Promise<User>
  updateProfile(profile: UserProfile): Promise<User>
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    // FastAPI validation errors (422) send a list; show something readable instead.
    const detail =
      typeof body?.detail === 'string'
        ? body.detail
        : res.status === 422
          ? 'Username needs 3+ letters/digits and password 6+ characters'
          : `Request failed (${res.status})`
    throw new ApiError(res.status, detail)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const httpAuth: AuthClient = {
  register: (body) => call<AuthResponse>('/auth/register', { method: 'POST', body: JSON.stringify(body) }),
  login: (body) => call<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  logout: () => call<void>('/auth/logout', { method: 'POST' }),
  me: () => call<User>('/me'),
  updateProfile: (profile) => call<User>('/me/profile', { method: 'PUT', body: JSON.stringify(profile) }),
}
