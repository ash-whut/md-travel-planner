// Step 53: on Vercel the frontend and backend share a domain, so VITE_API_BASE_URL is the
// relative "/api". Every client (REST, SSE, auth) must then request "/api/...". No network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthClient } from './auth'
import type { ApiClient } from './client'

const BASE = '/api'
let httpClient: ApiClient
let httpAuth: AuthClient
const fetchMock = vi.fn()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function sseResponse(body: string): Response {
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

beforeEach(async () => {
  vi.stubEnv('VITE_API_BASE_URL', BASE)
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  vi.resetModules()
  httpClient = (await import('./http')).httpClient
  httpAuth = (await import('./auth')).httpAuth
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('clients with a relative /api base URL', () => {
  it('REST calls go to /api/...', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, []))
    await httpClient.listSessions()
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 's 1' }))
    await httpClient.getSession('s 1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/sessions')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/sessions/s%201')
  })

  it('the SSE chat stream posts to /api/sessions/{id}/messages', async () => {
    fetchMock.mockResolvedValue(sseResponse('event: done\ndata: {"message_id":"a1"}\n\n'))
    const events: unknown[] = []
    await httpClient.sendMessage('s1', 'hi', (e) => events.push(e))

    expect(fetchMock.mock.calls[0][0]).toBe('/api/sessions/s1/messages')
    expect(events).toEqual([{ event: 'done', data: { message_id: 'a1' } }])
  })

  it('auth calls go to /api/auth/... and /api/me', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { token: 't', user: { id: 'u1', username: 'amy' } }))
    await httpAuth.login({ username: 'amy', password: 'secret1' })
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 'u1', username: 'amy' }))
    await httpAuth.me()

    expect(fetchMock.mock.calls[0][0]).toBe('/api/auth/login')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/me')
  })

  it('never falls back to localhost when the base URL is relative', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, []))
    await httpClient.listSessions()
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await httpAuth.logout()

    for (const [url] of fetchMock.mock.calls) expect(String(url)).not.toContain('localhost')
  })
})
