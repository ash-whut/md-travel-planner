// v0-only UI (fixed price timestamp, canned chat reply) must appear only with ?demo=1.
// demoParams is mocked with a mutable object so each test picks demo mode on or off.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { sanJoseProfile, sanJoseV2 } from '@/fixtures'
import { ChatPanel } from './ChatPanel'
import { PlanView } from './PlanView'

const demo = vi.hoisted(() => ({
  enabled: false,
  tab: null as string | null,
  day: null as string | null,
  confirm: null as string | null,
  why: null as string | null,
  picker: false,
  history: false,
}))
vi.mock('@/demoParams', () => ({ demo }))

beforeEach(() => {
  demo.enabled = false
})

function renderPlan() {
  render(<PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
}

describe('PlanView price footer', () => {
  it('is absent in a real (non-demo) session', () => {
    renderPlan()
    expect(screen.queryByText(/prices as of/)).toBeNull()
  })

  it('is shown with ?demo=1', () => {
    demo.enabled = true
    renderPlan()
    expect(screen.getByText(/prices as of Nov 1, 6:04 PM/)).toBeTruthy()
  })
})

describe('ChatPanel send', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  function sendMessage(text: string) {
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} statusLines={{}} onTagClick={() => {}} />)
    const input = screen.getByPlaceholderText(/Edit by letter/)
    fireEvent.change(input, { target: { value: text } })
    fireEvent.keyDown(input, { key: 'Enter' })
    act(() => {
      vi.advanceTimersByTime(2000)
    })
  }

  it('shows the user message but no canned reply or status line outside demo mode', () => {
    sendMessage('replace [H] with a park')
    expect(screen.getByText(/with a park/)).toBeTruthy()
    expect(screen.queryByText(/v0 demo: canned data/)).toBeNull()
    expect(screen.queryByText(/Re-planning|Thinking…/)).toBeNull()
  })

  it('still adds the canned reply with ?demo=1', () => {
    demo.enabled = true
    sendMessage('replace [H] with a park')
    expect(screen.getByText(/v0 demo: canned data/)).toBeTruthy()
  })
})
