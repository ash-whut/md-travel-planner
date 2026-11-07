import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, ApiError as ApiErrorType } from './client'

// http.ts reads VITE_API_BASE_URL when it loads, so it is imported after the env is stubbed.
const BASE = 'http://api.test/api'
let httpClient: ApiClient
let ApiError: typeof ApiErrorType // re-imported with http.ts so instanceof matches
const fetchMock = vi.fn()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(async () => {
  vi.stubEnv('VITE_API_BASE_URL', BASE)
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  vi.resetModules()
  httpClient = (await import('./http')).httpClient
  ApiError = (await import('./client')).ApiError
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('httpClient', () => {
  it('createSession POSTs to /sessions and returns the body', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 's-1', title: 'New trip' }))
    const detail = await httpClient.createSession()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/sessions`)
    expect(init?.method).toBe('POST')
    expect(detail).toMatchObject({ id: 's-1' })
  })

  it('getSession GETs /sessions/{id} with the id URL-encoded', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 'a b' }))
    await httpClient.getSession('a b')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/sessions/a%20b`)
    expect(init?.method ?? 'GET').toBe('GET')
  })

  it('throws ApiError with the status and the backend detail on 404', async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { detail: 'Session not found' }))
    const err = await httpClient.getSession('gone').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiErrorType).status).toBe(404)
    expect((err as ApiErrorType).message).toBe('Session not found')
  })

  it('throws ApiError with a fallback message when a 500 has no JSON body', async () => {
    fetchMock.mockResolvedValue(new Response('Internal Server Error', { status: 500 }))
    const err = await httpClient.createSession().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiErrorType).status).toBe(500)
    expect((err as ApiErrorType).message).toMatch(/500/)
  })
})
