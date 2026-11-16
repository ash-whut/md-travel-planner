import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, ApiError as ApiErrorType } from './client'

// Step 45: GET /sessions, PATCH /sessions/{id}, DELETE /sessions/{id} (contracts §4).
const BASE = 'http://api.test/api'
let httpClient: ApiClient
let ApiError: typeof ApiErrorType
const fetchMock = vi.fn()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const summary = { id: 's-1', title: 'San Jose · Mar 5–7', status: 'planned', updated_at: '2026-11-15T18:00:00Z' }

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

describe('httpClient.listSessions', () => {
  it('GETs /sessions and returns the summaries in server order', async () => {
    const other = { ...summary, id: 's-2', title: 'Austin' }
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [summary, other]))

    const result = await httpClient.listSessions()

    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/sessions`, undefined)
    expect(result).toEqual([summary, other])
  })
})

describe('httpClient.renameSession', () => {
  it('PATCHes the session with a JSON { title } body and returns the summary', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ...summary, title: 'Spring break' }))

    const result = await httpClient.renameSession('s-1', 'Spring break')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/sessions/s-1`)
    expect(init.method).toBe('PATCH')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body)).toEqual({ title: 'Spring break' })
    expect(result.title).toBe('Spring break')
  })

  it('encodes the id and rejects with ApiError on 404', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(404, { detail: 'Session not found' }))

    const err = await httpClient.renameSession('a b', 'Trip').catch((e: unknown) => e)

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/sessions/a%20b`)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiErrorType).status).toBe(404)
    expect((err as ApiErrorType).message).toBe('Session not found')
  })
})

describe('httpClient.deleteSession', () => {
  it('DELETEs the session and resolves on 204 (no body)', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await expect(httpClient.deleteSession('s-1')).resolves.toBeUndefined()

    expect(fetchMock).toHaveBeenCalledWith(`${BASE}/sessions/s-1`, { method: 'DELETE' })
  })

  it('rejects with ApiError on 404', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(404, { detail: 'Session not found' }))

    const err = await httpClient.deleteSession('nope').catch((e: unknown) => e)

    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiErrorType).status).toBe(404)
  })
})
