// Step 24: httpClient.generate over SSE (POST /sessions/{id}/generate). fetch is stubbed; no network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { sanJoseV1 } from '@/fixtures'
import type { SseEvent } from '@/types'
import type { ApiClient, ApiError as ApiErrorType } from './client'

const BASE = 'http://api.test/api'
let httpClient: ApiClient
let ApiError: typeof ApiErrorType
const fetchMock = vi.fn()

function sseResponse(body: string, status = 200): Response {
  return new Response(body, { status, headers: { 'Content-Type': 'text/event-stream' } })
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

describe('httpClient.generate', () => {
  it('POSTs to /sessions/{id}/generate', async () => {
    fetchMock.mockResolvedValue(sseResponse('event: done\ndata: {"message_id":"a1"}\n\n'))
    await httpClient.generate('s 1', () => {})
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/sessions/s%201/generate`)
    expect(init.method).toBe('POST')
  })

  it('parses status, itinerary and done events in order', async () => {
    const body = [
      'event: message_start\ndata: {"message_id":"a1"}\n\n',
      'event: status\ndata: {"label":"Drafting your plan…","state":"start"}\n\n',
      `event: itinerary\ndata: ${JSON.stringify(sanJoseV1)}\n\n`,
      'event: token\ndata: {"text":"Here is your plan."}\n\n',
      'event: done\ndata: {"message_id":"a1"}\n\n',
    ].join('')
    fetchMock.mockResolvedValue(sseResponse(body))
    const events: SseEvent[] = []
    await httpClient.generate('s1', (e) => events.push(e))
    expect(events.map((e) => e.event)).toEqual(['message_start', 'status', 'itinerary', 'token', 'done'])
    expect(events[1]).toEqual({ event: 'status', data: { label: 'Drafting your plan…', state: 'start' } })
    expect(events[2].data).toEqual(sanJoseV1)
  })

  it('rejects with ApiError on a 404 and makes only one request', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Session not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const err = await httpClient.generate('gone', () => {}).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiErrorType).status).toBe(404)
    expect((err as ApiErrorType).message).toBe('Session not found')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
