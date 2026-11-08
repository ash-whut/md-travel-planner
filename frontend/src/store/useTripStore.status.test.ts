// Step 31: `status` events become one StatusLine per label whose state follows the latest event.
import { beforeEach, describe, expect, it } from 'vitest'
import { sanJoseV1 } from '@/fixtures'
import type { SseEvent } from '@/types'
import { reduceEvent, useTripStore, type TripState } from './useTripStore'

const weather = 'Checking weather for San Jose · Mar 5–7'
const status = (label: string, state: 'start' | 'end' | 'error'): SseEvent => ({ event: 'status', data: { label, state } })
const start = (id: string): SseEvent => ({ event: 'message_start', data: { message_id: id } })

function run(state: TripState, ...events: SseEvent[]): TripState {
  return events.reduce((s, e) => ({ ...s, ...reduceEvent(s, e) }), state)
}

const empty = () => useTripStore.getState()

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('status lines (step 31)', () => {
  it('start adds a spinning line; end updates the same line to done', () => {
    let s = run(empty(), start('a1'), status(weather, 'start'))
    expect(s.statusLines.a1).toEqual([{ label: weather, state: 'start' }])
    s = run(s, status(weather, 'end'))
    expect(s.statusLines.a1).toEqual([{ label: weather, state: 'end' }])
  })

  it('error updates the same line to failed', () => {
    const s = run(empty(), start('a1'), status(weather, 'start'), status(weather, 'error'))
    expect(s.statusLines.a1).toEqual([{ label: weather, state: 'error' }])
  })

  it('keeps line order and updates only the matching label', () => {
    const s = run(
      empty(),
      start('a1'),
      status(weather, 'start'),
      status('Drafting your plan…', 'start'),
      status(weather, 'end'),
    )
    expect(s.statusLines.a1).toEqual([
      { label: weather, state: 'end' },
      { label: 'Drafting your plan…', state: 'start' },
    ])
  })

  it('lines belong to the message that was streaming', () => {
    let s = run(empty(), start('a1'), status(weather, 'end'), { event: 'done', data: { message_id: 'a1' } })
    s = run(s, start('a2'), status('Drafting your plan…', 'start'))
    expect(s.statusLines.a1).toEqual([{ label: weather, state: 'end' }])
    expect(s.statusLines.a2).toEqual([{ label: 'Drafting your plan…', state: 'start' }])
  })

  it('a status with no streaming message adds no line', () => {
    const s = run(empty(), status(weather, 'start'))
    expect(s.statusLines).toEqual({})
  })

  it('a failed weather step does not end generation; the plan still arrives', () => {
    const s = run(
      empty(),
      start('a1'),
      status(weather, 'start'),
      status(weather, 'error'),
      status('Drafting your plan…', 'start'),
    )
    expect(s.generating).toBe(true)
    expect(s.planStatus).toBe('Drafting your plan…')
    const after = run(s, { event: 'itinerary', data: sanJoseV1 })
    expect(after.itinerary?.version).toBe(1)
    expect(after.statusLines.a1[0]).toEqual({ label: weather, state: 'error' })
  })

  it('the SSE error event ends generation', () => {
    const s = run(empty(), start('a1'), status('Drafting your plan…', 'start'), status('Drafting your plan…', 'error'), {
      event: 'error',
      data: { message: 'Could not make the plan', retryable: true },
    })
    expect(s.generating).toBe(false)
    expect(s.planStatus).toBeNull()
    expect(s.statusLines.a1).toEqual([{ label: 'Drafting your plan…', state: 'error' }])
  })
})
