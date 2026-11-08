// Step 24: generatePlan streams like a chat turn; `generating`/`planStatus` drive the plan skeleton.
// The ApiClient is a fake; no network.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from '@/api/client'
import { sanJoseProfile, sanJoseV1 } from '@/fixtures'
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

type GenerateImpl = ApiClient['generate']

// A generate stream that plays `events`, then stays open until push()/abort.
function openStream(...events: SseEvent[]) {
  const ctl: { signal: AbortSignal | null; push: (e: SseEvent) => void; finish: () => void } = {
    signal: null,
    push: () => {},
    finish: () => {},
  }
  const generate: GenerateImpl = (_id, onEvent, signal) =>
    new Promise<void>((resolve) => {
      ctl.signal = signal ?? null
      ctl.push = onEvent
      ctl.finish = resolve
      events.forEach(onEvent)
      signal?.addEventListener('abort', () => resolve())
    })
  return { ctl, generate }
}

function fakeApi(generate: GenerateImpl) {
  return {
    createSession: vi.fn(async () => session),
    getSession: vi.fn(async () => session),
    sendMessage: vi.fn(async () => {}),
    generate: vi.fn(generate),
  }
}

const start = (id: string): SseEvent => ({ event: 'message_start', data: { message_id: id } })
const status = (label: string, s: 'start' | 'end' | 'error' = 'start'): SseEvent => ({
  event: 'status',
  data: { label, state: s },
})
const itinerary: SseEvent = { event: 'itinerary', data: sanJoseV1 }
const done = (id: string): SseEvent => ({ event: 'done', data: { message_id: id } })

const state = () => useTripStore.getState()

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useTripStore.getState().loadSession(session)
})

describe('generatePlan', () => {
  it('sets generating right away and calls api.generate with the session id', () => {
    const { generate } = openStream()
    const api = fakeApi(generate)
    void state().generatePlan(api)
    expect(state().generating).toBe(true)
    expect(state().streaming).toBe(true)
    expect(state().planStatus).toBeNull()
    expect(api.generate).toHaveBeenCalledTimes(1)
    expect(api.generate.mock.calls[0][0]).toBe('s-1')
    state().stop()
  })

  it('shows the status label, then stores the itinerary and clears generating', async () => {
    const { ctl, generate } = openStream(start('a1'), status('Drafting your plan…'))
    const run = state().generatePlan(fakeApi(generate))
    expect(state().planStatus).toBe('Drafting your plan…')
    ctl.push(itinerary)
    expect(state().itinerary).toEqual(sanJoseV1)
    expect(state().generating).toBe(false)
    expect(state().planStatus).toBeNull()
    expect(state().session?.status).toBe('planned')
    ctl.push(done('a1'))
    ctl.finish()
    await run
    expect(state().streaming).toBe(false)
    expect(state().error).toBeNull()
  })

  it('an error event clears generating, keeps no plan and Retry generates again', async () => {
    let calls = 0
    const api = fakeApi(async (_id, onEvent) => {
      calls += 1
      if (calls === 1) {
        onEvent(start('a0'))
        onEvent(status('Drafting your plan…'))
        onEvent({ event: 'error', data: { message: 'Could not make the plan', retryable: true } })
        return
      }
      ;[start('a1'), status('Drafting your plan…'), itinerary, done('a1')].forEach(onEvent)
    })
    await state().generatePlan(api)
    expect(state().generating).toBe(false)
    expect(state().planStatus).toBeNull()
    expect(state().itinerary).toBeNull()
    expect(state().error?.message).toMatch(/Could not make the plan/)
    await state().retry(api)
    expect(api.generate).toHaveBeenCalledTimes(2)
    expect(api.sendMessage).not.toHaveBeenCalled()
    expect(state().itinerary?.version).toBe(1)
  })

  it('a status error event ends generating', () => {
    const { generate } = openStream(start('a1'), status('Drafting your plan…'), status('Drafting your plan…', 'error'))
    void state().generatePlan(fakeApi(generate))
    expect(state().generating).toBe(false)
    expect(state().planStatus).toBeNull()
    state().stop()
  })

  it('a rejected request clears generating and shows a retryable error', async () => {
    await state().generatePlan(fakeApi(async () => Promise.reject(new TypeError('Failed to fetch'))))
    expect(state().generating).toBe(false)
    expect(state().streaming).toBe(false)
    expect(state().error?.retryable).toBe(true)
  })

  it('Stop aborts the generation and clears generating', () => {
    const { ctl, generate } = openStream(start('a1'), status('Drafting your plan…'))
    void state().generatePlan(fakeApi(generate))
    state().stop()
    expect(ctl.signal?.aborted).toBe(true)
    expect(state().generating).toBe(false)
    expect(state().planStatus).toBeNull()
    expect(state().streaming).toBe(false)
  })

  it('does nothing while another reply is streaming', () => {
    const { generate } = openStream()
    const api = fakeApi(generate)
    useTripStore.setState({ streaming: true })
    void state().generatePlan(api)
    expect(api.generate).not.toHaveBeenCalled()
    expect(state().generating).toBe(false)
  })

  it('a chat turn that plans also drives the skeleton through status events', () => {
    const events = [start('a1'), status('Drafting your plan…')]
    const api = {
      ...fakeApi(async () => {}),
      sendMessage: vi.fn<ApiClient['sendMessage']>(
        (_id, _c, onEvent, signal) =>
          new Promise<void>((resolve) => {
            events.forEach(onEvent)
            signal?.addEventListener('abort', () => resolve())
          }),
      ),
    }
    void state().sendMessage(api, 'just make the plan')
    expect(state().generating).toBe(true)
    expect(state().planStatus).toBe('Drafting your plan…')
    state().stop()
  })
})
