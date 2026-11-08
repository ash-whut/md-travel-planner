// Step 17: profile chips, from contracts §2.1 and spec F3 ("📍 San Jose, CA", "🏠
// College Station, TX", "📅 Mar 5–7", …). The server's missing_required decides what is known.
// (The chat-header stepper was removed by D22.)
import { describe, expect, it } from 'vitest'
import { sanJoseProfile } from '@/fixtures'
import type { RequiredField, TripProfile } from '@/types'
import { profileChips } from './profile'

const ALL_REQUIRED: RequiredField[] = ['destination', 'dates', 'origin', 'travelers', 'interests']

function emptyProfile(overrides: Partial<TripProfile> = {}): TripProfile {
  return {
    cities: [],
    vibe: null,
    start_date: null,
    end_date: null,
    duration_days: null,
    rough_timing: null,
    origin: null,
    travelers: null,
    budget_level: null,
    interests: [],
    dietary: null,
    pace: null,
    transport: null,
    notes: null,
    missing_required: [...ALL_REQUIRED],
    ...overrides,
  }
}

function chip(profile: TripProfile, field: string) {
  return profileChips(profile).find((c) => c.field === field)
}

describe('profileChips', () => {
  it('shows the full San Jose profile like the v0 header, in order', () => {
    const chips = profileChips(sanJoseProfile)
    expect(chips.every((c) => !c.missing)).toBe(true)
    expect(chips.slice(0, 3).map((c) => c.label)).toEqual(['📍 San Jose, CA', '🏠 College Station, TX', '📅 Mar 5–7'])
    expect(chips.map((c) => c.label.split(' ')[0])).toEqual(['📍', '🏠', '📅', '👤', '🌱', '🎯'])
    expect(chip(sanJoseProfile, 'travelers')!.label).toMatch(/1 traveler/)
    expect(chip(sanJoseProfile, 'dietary')!.label).toMatch(/vegan/i)
    const interests = chip(sanJoseProfile, 'interests')!.label
    for (const i of ['tech', 'food', 'gardens']) expect(interests).toContain(i)
  })

  it('prefers exact dates over the rough timing', () => {
    expect(chip(sanJoseProfile, 'dates')!.label).not.toMatch(/weekend/)
  })

  it('shows exact dates across months', () => {
    const p = { ...sanJoseProfile, start_date: '2027-03-30', end_date: '2027-04-01' }
    expect(chip(p, 'dates')!.label).toMatch(/Mar 30.*Apr 1/)
  })

  it('shows a start date plus a length when there is no end date', () => {
    const p = { ...sanJoseProfile, end_date: null, rough_timing: null, duration_days: 3 }
    const label = chip(p, 'dates')!.label
    expect(label).toMatch(/^📅 /)
    expect(label).toContain('Mar 5')
    expect(label).toMatch(/3 days/)
  })

  it('shows the rough timing plus a length before exact dates are known', () => {
    const p = { ...sanJoseProfile, start_date: null, end_date: null, rough_timing: 'first weekend of March', duration_days: 3 }
    const label = chip(p, 'dates')!.label
    expect(label).toContain('first weekend of March')
    expect(label).toMatch(/3 days/)
    expect(chip(p, 'dates')!.missing).toBe(false)
  })

  it('shows a vibe as the destination when no city is chosen', () => {
    const p = { ...sanJoseProfile, cities: [], vibe: 'beach, ≤4h drive' }
    const dest = chip(p, 'destination')!
    expect(dest.label).toMatch(/^📍 /)
    expect(dest.label).toContain('beach, ≤4h drive')
    expect(dest.missing).toBe(false)
  })

  it('shows both cities of a two-city trip', () => {
    const p = { ...sanJoseProfile, cities: ['San Jose, CA', 'San Francisco, CA'] }
    const label = chip(p, 'destination')!.label
    expect(label).toContain('San Jose, CA')
    expect(label).toContain('San Francisco, CA')
  })

  it('pluralises travelers', () => {
    expect(chip({ ...sanJoseProfile, travelers: 3 }, 'travelers')!.label).toMatch(/3 travelers/)
  })

  it('shows every missing required detail as a muted placeholder', () => {
    const chips = profileChips(emptyProfile())
    const fields = chips.map((c) => c.field)
    for (const f of ALL_REQUIRED) expect(fields).toContain(f)
    expect(chips.every((c) => c.missing)).toBe(true)
    expect(chip(emptyProfile(), 'destination')!.label).toMatch(/^📍 \S/)
  })

  it('mixes known and muted chips for a partial profile', () => {
    const p = emptyProfile({ cities: ['San Jose, CA'], missing_required: ['dates', 'origin', 'travelers', 'interests'] })
    expect(chip(p, 'destination')).toEqual({ field: 'destination', label: '📍 San Jose, CA', missing: false })
    expect(chip(p, 'dates')!.missing).toBe(true)
    expect(chip(p, 'origin')!.missing).toBe(true)
  })

  it('leaves dietary out when it is not known, and never marks it missing', () => {
    expect(chip(emptyProfile(), 'dietary')).toBeUndefined()
    expect(chip(sanJoseProfile, 'dietary')!.missing).toBe(false)
  })
})
