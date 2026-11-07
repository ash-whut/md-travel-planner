// Step 15: aborting the AbortSignal ends httpClient.sendMessage cleanly (Stop). fetch is stubbed
// with a stream that never ends on its own; no network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SseEvent } from '@/types'
import type { ApiClient } from './client'

let httpClient: ApiClient
const fetchMock = vi.fn()

// An SSE response that sends `first` and then stays open until the request is aborted.
function openSseResponse(first: string, requestSignal: AbortSignal): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(first))
      requestSignal.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')))
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

beforeEach(async () => {
  vi.stubEnv('VITE_API_BASE_URL', 'http://api.test/api')
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  vi.resetModules()
  httpClient = (await import('./http')).httpClient
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('httpClient.sendMessage abort', () => {
  it('aborting the signal aborts the request and resolves without more events', async () => {
    let requestSignal: AbortSignal | undefined
    fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
      requestSignal = init.signal ?? undefined
      return openSseResponse('event: message_start\ndata: {"message_id":"a1"}\n\nevent: token\ndata: {"text":"Hi"}\n\n', init.signal!)
    })
    const events: SseEvent[] = []
    const controller = new AbortController()
    const pending = httpClient.sendMessage('s1', 'hi', (e) => events.push(e), controller.signal)

    await vi.waitFor(() => expect(events).toHaveLength(2))
    controller.abort()

    await expect(pending).resolves.toBeUndefined()
    expect(requestSignal?.aborted).toBe(true)
    expect(events.map((e) => e.event)).toEqual(['message_start', 'token'])
    expect(fetchMock).toHaveBeenCalledTimes(1) // no automatic re-send after the abort
  })
})
