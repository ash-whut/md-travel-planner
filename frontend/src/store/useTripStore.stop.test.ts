// Step 15: Stop aborts the open chat stream, re-enables the input and keeps the partial reply
// with the same " *(stopped)*" marker the backend saves. The ApiClient is a fake; no network.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '@/api/client'
import { sanJoseProfile } from '@/fixtures'
import type { SessionDetail, SseEvent } from '@/types'
import { STOPPED_MARKER, useTripStore } from './useTripStore'

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

// A stream that plays `events`, then stays open until its signal aborts (like fetch-event-source,
// which resolves on abort). Exposes the signal and a way to push more events.
function openStream(...events: SseEvent[]) {
  const ctl: { signal: AbortSignal | null; push: (e: SseEvent) => void } = { signal: null, push: () => {} }
  const send: SendImpl = (_id, _content, onEvent, signal) =>
    new Promise<void>((resolve) => {
      ctl.signal = signal ?? null
      ctl.push = onEvent
      events.forEach(onEvent)
      signal?.addEventListener('abort', () => resolve())
    })
  return { ctl, send }
}

function fakeApi(send: SendImpl) {
  return {
    createSession: vi.fn(async () => session),
    getSession: vi.fn(async () => session),
    sendMessage: vi.fn(send),
  }
}

const start = (id: string): SseEvent => ({ event: 'message_start', data: { message_id: id } })
const token = (text: string): SseEvent => ({ event: 'token', data: { text } })
const done = (id: string): SseEvent => ({ event: 'done', data: { message_id: id } })

const state = () => useTripStore.getState()

beforeEach(() => {
  localStorage.clear()
  state().reset()
  state().loadSession(session)
})

describe('stop', () => {
  it('the marker is the contract text', () => {
    expect(STOPPED_MARKER).toBe(' *(stopped)*')
  })

  it('aborts the signal passed to api.sendMessage', async () => {
    const { ctl, send } = openStream(start('a1'), token('Hal'))
    const pending = state().sendMessage(fakeApi(send), 'Austin')
    expect(ctl.signal?.aborted).toBe(false)
    state().stop()
    expect(ctl.signal?.aborted).toBe(true)
    await pending
  })

  it('turns streaming off right away and keeps the partial reply with the marker', async () => {
    const { send } = openStream(start('a1'), token('Austin '), token('is '))
    const pending = state().sendMessage(fakeApi(send), 'Austin')
    expect(state().streaming).toBe(true)
    state().stop()
    expect(state().streaming).toBe(false)
    expect(state().streamingMessageId).toBeNull()
    expect(state().messages.at(-1)).toMatchObject({ id: 'a1', role: 'assistant', content: 'Austin is' + STOPPED_MARKER })
    await pending
    expect(state().streaming).toBe(false)
  })

  it('does not show an error after Stop (not "cut off", no Retry)', async () => {
    const { send } = openStream(start('a1'), token('Part'))
    const pending = state().sendMessage(fakeApi(send), 'Austin')
    state().stop()
    await pending
    expect(state().error).toBeNull()
  })

  it('adds the marker only to the streaming message', async () => {
    const { send } = openStream(start('a1'), token('Part'))
    const pending = state().sendMessage(fakeApi(send), 'Austin')
    state().stop()
    await pending
    const [greeting, user, assistant] = state().messages
    expect(greeting.content).toBe('Hi! Where to?')
    expect(user).toMatchObject({ role: 'user', content: 'Austin' })
    expect(assistant.content).toBe('Part' + STOPPED_MARKER)
    expect(state().messages.filter((m) => m.content.includes('(stopped)'))).toHaveLength(1)
  })

  it('Stop before message_start changes no message and still re-enables sending', async () => {
    const { ctl, send } = openStream()
    const pending = state().sendMessage(fakeApi(send), 'Austin')
    state().stop()
    await pending
    expect(ctl.signal?.aborted).toBe(true)
    expect(state().streaming).toBe(false)
    expect(state().messages.map((m) => m.content)).toEqual(['Hi! Where to?', 'Austin'])
  })

  it('Stop with no open stream is harmless', () => {
    const before = state().messages
    state().stop()
    expect(state().streaming).toBe(false)
    expect(state().messages).toEqual(before)
    expect(state().error).toBeNull()
  })

  it('a finished reply cannot be stopped afterwards (no marker on it)', async () => {
    const { ctl, send } = openStream(start('a1'), token('Done.'), done('a1'))
    const api = fakeApi(send)
    const pending = state().sendMessage(api, 'Austin')
    // The fake stream stays open after `done`; the server would close it. Abort to settle it.
    state().stop()
    await pending
    expect(ctl.signal?.aborted).toBe(true)
    expect(state().messages.at(-1)?.content).toBe('Done.')
  })

  it('a new message can be sent after Stop, and the old stream ending does not cut it off', async () => {
    const first = openStream(start('a1'), token('Half'))
    const p1 = state().sendMessage(fakeApi(first.send), 'first')
    state().stop()

    const second = openStream(start('a2'), token('New '))
    const api2 = fakeApi(second.send)
    const p2 = state().sendMessage(api2, 'second')
    expect(api2.sendMessage).toHaveBeenCalledTimes(1)
    expect(state().streaming).toBe(true)

    await p1 // the old stream settles while the new one is still open
    expect(state().streaming).toBe(true)
    expect(state().streamingMessageId).toBe('a2')
    expect(second.ctl.signal?.aborted).toBe(false)

    second.ctl.push(token('reply'))
    second.ctl.push(done('a2'))
    expect(state().streaming).toBe(false)
    expect(state().messages.at(-1)).toMatchObject({ id: 'a2', content: 'New reply' })
    expect(state().messages.find((m) => m.id === 'a1')?.content).toBe('Half' + STOPPED_MARKER)

    state().stop() // settle the still-open fake stream
    await p2
    expect(state().messages.at(-1)?.content).toBe('New reply')
  })
})
