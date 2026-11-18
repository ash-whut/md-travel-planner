// Step 17: the plan-header profile chips as rendered (the chat-header stepper was removed, D22).
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { sanJoseProfile, sanJoseV2 } from '@/fixtures'
import type { TripProfile } from '@/types'
import { ChatPanel } from './ChatPanel'
import { PlanView, ProfileChips } from './PlanView'

const intakeProfile: TripProfile = {
  ...sanJoseProfile,
  origin: null,
  travelers: null,
  interests: [],
  dietary: null,
  missing_required: ['origin', 'travelers', 'interests'],
}

describe('chat header', () => {
  it('has no progress stepper (removed by D22)', () => {
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    expect(screen.queryByRole('list', { name: 'Trip progress' })).toBeNull()
    expect(screen.queryByText('Trip details')).toBeNull()
  })
})

describe('ProfileChips', () => {
  it('renders known chips with their values', () => {
    render(<ProfileChips profile={sanJoseProfile} />)
    expect(screen.getByText('📍 San Jose, CA')).toBeTruthy()
    expect(screen.getByText('🏠 College Station, TX')).toBeTruthy()
    expect(screen.getByText('📅 Mar 5–7')).toBeTruthy()
    expect(screen.queryByTitle(/Not given yet/)).toBeNull()
  })

  it('renders missing details muted, with a hint to give them in chat', () => {
    render(<ProfileChips profile={intakeProfile} />)
    const muted = screen.getAllByTitle(/Not given yet/)
    expect(muted).toHaveLength(3)
    for (const el of muted) expect(el.className).toMatch(/dashed/)
    expect(screen.getByText('📍 San Jose, CA').getAttribute('title')).toBeNull()
  })

  it('appear in the plan header', () => {
    render(<PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
    expect(screen.getByText('🏠 College Station, TX')).toBeTruthy()
  })
})
