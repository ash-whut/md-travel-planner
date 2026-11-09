// Step 14: sending a chat message through the store (optimistic user message, streamed reply,
// errors and Retry). The ApiClient is a fake; no network.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from '@/api/client'
import { sanJoseProfile } from '@/fixtures'
import type { SessionDetail, SseEvent } from '@/types'
import { useTripStore } from './useTripStore'

const session: SessionDetail = {
  id: 's-1',
  title: 'New trip',
  status: 'intake',
  trip_profile: sanJoseProfile,
  messages: [{ id: 'g', role: 'assistant', content: 'Hi! Where to?', itinerary_version: null, created_at: '' }],
  itinerary: null,
  created_at: '',
  updated_at: '',
}

type SendImpl = ApiClient['sendMessage']

// A sendMessage that plays the given events and then resolves (the stream ends).
function streamOf(...events: SseEvent[]): SendImpl {
  return async (_id, _content, onEvent) => {
    for (const e of events) onEvent(e)
  }
}

const reply = (id: string, ...tokens: string[]): SseEvent[] => [
  { event: 'message_start', data: { message_id: id } },
  ...tokens.map((text): SseEvent => ({ event: 'token', data: { text } })),
  { event: 'done', data: { message_id: id } },
]

function fakeApi(send: SendImpl = streamOf(...reply('a1', 'Hel', 'lo'))) {
  return {
    createSession: vi.fn(async () => session),
    getSession: vi.fn(async () => session),
    sendMessage: vi.fn(send),
    generate: vi.fn(),
    patchBooking: vi.fn(),
  }
}

const state = () => useTripStore.getState()

beforeEach(() => {
  localStorage.clear()
  state().reset()
  state().loadSession(session)
})

describe('sendMessage', () => {
  it('adds the user message, streams the reply into an assistant message and stops streaming', async () => {
    const api = fakeApi()
    await state().sendMessage(api, '  San Jose please  ')
    expect(api.sendMessage).toHaveBeenCalledTimes(1)
    const [id, content, , signal] = api.sendMessage.mock.calls[0]
    expect(id).toBe('s-1')
    expect(content).toBe('San Jose please')
    expect(signal).toBeInstanceOf(AbortSignal)
    const msgs = state().messages
    expect(msgs).toHaveLength(3)
    expect(msgs[1]).toMatchObject({ role: 'user', content: 'San Jose please' })
    expect(msgs[2]).toMatchObject({ id: 'a1', role: 'assistant', content: 'Hello' })
    expect(state().streaming).toBe(false)
    expect(state().error).toBeNull()
  })

  it('shows the user message and is streaming before the reply arrives', async () => {
    let finish!: () => void
    const api = fakeApi(
      (_id, _c, onEvent) =>
        new Promise<void>((resolve) => {
          finish = () => {
            reply('a1', 'Ok').forEach(onEvent)
            resolve()
          }
        }),
    )
    const pending = state().sendMessage(api, 'Austin')
    expect(state().messages.at(-1)).toMatchObject({ role: 'user', content: 'Austin' })
    expect(state().streaming).toBe(true)
    finish()
    await pending
    expect(state().streaming).toBe(false)
    expect(state().messages.at(-1)).toMatchObject({ role: 'assistant', content: 'Ok' })
  })

  it('ignores empty text, a missing session and a second send while streaming', async () => {
    const api = fakeApi()
    await state().sendMessage(api, '   ')
    expect(api.sendMessage).not.toHaveBeenCalled()

    state().reset()
    await state().sendMessage(api, 'hello')
    expect(api.sendMessage).not.toHaveBeenCalled()
    expect(state().messages).toEqual([])

    state().loadSession(session)
    let finish!: () => void
    const slow = fakeApi(() => new Promise<void>((resolve) => (finish = resolve)))
    const first = state().sendMessage(slow, 'one')
    await state().sendMessage(slow, 'two')
    expect(slow.sendMessage).toHaveBeenCalledTimes(1)
    expect(state().messages.filter((m) => m.role === 'user').map((m) => m.content)).toEqual(['one'])
    finish()
    await first
  })

  it('an error event stops streaming, keeps the partial text and stores the error', async () => {
    const api = fakeApi(
      streamOf(
        { event: 'message_start', data: { message_id: 'a1' } },
        { event: 'token', data: { text: 'Half' } },
        { event: 'error', data: { message: 'The model is busy', retryable: true } },
      ),
    )
    await state().sendMessage(api, 'Plan it')
    expect(state().streaming).toBe(false)
    expect(state().error).toEqual({ message: 'The model is busy', retryable: true })
    expect(state().messages.at(-1)).toMatchObject({ id: 'a1', content: 'Half' })
  })

  it('a stream that ends without done is a retryable "cut off" error', async () => {
    const api = fakeApi(
      streamOf({ event: 'message_start', data: { message_id: 'a1' } }, { event: 'token', data: { text: 'Par' } }),
    )
    await state().sendMessage(api, 'Plan it')
    expect(state().streaming).toBe(false)
    expect(state().streamingMessageId).toBeNull()
    expect(state().error?.retryable).toBe(true)
    expect(state().error?.message).toMatch(/cut off/i)
  })

  it('drops an empty assistant reply on error or cut-off, so Retry leaves only one', async () => {
    const start: SseEvent = { event: 'message_start', data: { message_id: 'a1' } }
    await state().sendMessage(fakeApi(streamOf(start, { event: 'error', data: { message: 'Busy', retryable: true } })), 'Plan it')
    expect(state().messages.some((m) => m.id === 'a1')).toBe(false)

    await state().sendMessage(fakeApi(streamOf(start)), 'Plan it', { retry: true })
    expect(state().error?.message).toMatch(/cut off/i)
    expect(state().messages.some((m) => m.id === 'a1')).toBe(false)

    await state().retry(fakeApi())
    expect(state().messages.filter((m) => m.role === 'assistant').map((m) => m.content)).toEqual(['Hi! Where to?', 'Hello'])
  })

  it('a 4xx ApiError is not retryable', async () => {
    const api = fakeApi(async () => {
      throw new ApiError(404, 'Session not found')
    })
    await state().sendMessage(api, 'hello')
    expect(state().streaming).toBe(false)
    expect(state().error?.message).toMatch(/Session not found/)
    expect(state().error?.retryable).toBe(false)
  })

  it('a 5xx ApiError or a network failure is retryable', async () => {
    await state().sendMessage(
      fakeApi(async () => {
        throw new ApiError(503, 'Unavailable')
      }),
      'hello',
    )
    expect(state().error).toMatchObject({ retryable: true })
    expect(state().error?.message).toMatch(/Unavailable/)

    state().loadSession(session)
    await state().sendMessage(
      fakeApi(async () => {
        throw new TypeError('Failed to fetch')
      }),
      'hello',
    )
    expect(state().error).toMatchObject({ retryable: true })
    expect(state().streaming).toBe(false)
  })
})

describe('retry', () => {
  it('resends the last message without adding the user message twice, and clears the error', async () => {
    let calls = 0
    const api = fakeApi(async (_id, _c, onEvent) => {
      calls += 1
      if (calls === 1) throw new TypeError('Failed to fetch')
      reply('a1', 'Done').forEach(onEvent)
    })
    await state().sendMessage(api, 'Plan San Jose')
    expect(state().error).not.toBeNull()

    await state().retry(api)
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
    expect(api.sendMessage.mock.calls[1][1]).toBe('Plan San Jose')
    expect(state().error).toBeNull()
    const users = state().messages.filter((m) => m.role === 'user')
    expect(users.map((m) => m.content)).toEqual(['Plan San Jose'])
    expect(state().messages.at(-1)).toMatchObject({ role: 'assistant', content: 'Done' })
  })

  it('retries loading the session when nothing has been sent yet', async () => {
    state().reset()
    const api = fakeApi()
    await state().retry(api)
    expect(api.sendMessage).not.toHaveBeenCalled()
    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(state().session?.id).toBe('s-1')
  })
})
