// Step 14: httpClient.sendMessage over SSE. fetch is stubbed with recorded stream bodies; no network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

describe('httpClient.sendMessage', () => {
  it('POSTs the content as JSON to /sessions/{id}/messages', async () => {
    fetchMock.mockResolvedValue(sseResponse('event: done\ndata: {"message_id":"a1"}\n\n'))
    await httpClient.sendMessage('s 1', 'Plan San Jose', () => {})
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/sessions/s%201/messages`)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ content: 'Plan San Jose' })
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
  })

  it('parses contract events in order and ignores other events', async () => {
    const body = [
      'event: message_start\ndata: {"message_id":"a1"}\n\n',
      ': keep-alive\n\n',
      'event: ping\ndata: {}\n\n',
      'event: token\ndata: {"text":"Hel"}\n\n',
      'event: token\ndata: {"text":"lo"}\n\n',
      'event: done\ndata: {"message_id":"a1"}\n\n',
    ].join('')
    fetchMock.mockResolvedValue(sseResponse(body))
    const events: SseEvent[] = []
    await httpClient.sendMessage('s1', 'hi', (e) => events.push(e))
    expect(events).toEqual([
      { event: 'message_start', data: { message_id: 'a1' } },
      { event: 'token', data: { text: 'Hel' } },
      { event: 'token', data: { text: 'lo' } },
      { event: 'done', data: { message_id: 'a1' } },
    ])
  })

  it('rejects with ApiError (status + detail) on a 404 and makes only one request', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Session not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const err = await httpClient.sendMessage('gone', 'hi', () => {}).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiErrorType).status).toBe(404)
    expect((err as ApiErrorType).message).toBe('Session not found')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('rejects when the network fails, without retrying on its own', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(httpClient.sendMessage('s1', 'hi', () => {})).rejects.toThrow('Failed to fetch')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
