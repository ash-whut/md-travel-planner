// Step 46 (D36): Generate waits for somewhere to go, a city or a vibe; nothing else is needed.
import { describe, expect, it } from 'vitest'
import { sanJoseProfile } from '@/fixtures'
import type { TripProfile } from '@/types'
import { hasDestination } from './profile'

const nowhere: TripProfile = { ...sanJoseProfile, cities: [], vibe: null }

describe('hasDestination', () => {
  it('is false with no profile, or no city and no vibe', () => {
    expect(hasDestination(null)).toBe(false)
    expect(hasDestination(nowhere)).toBe(false)
    expect(hasDestination({ ...nowhere, vibe: '' })).toBe(false)
  })

  it('is true with a city or a vibe, even with nothing else known', () => {
    const bare: TripProfile = { ...nowhere, start_date: null, end_date: null, origin: null, travelers: null, interests: [] }
    expect(hasDestination({ ...bare, cities: ['Austin, TX'] })).toBe(true)
    expect(hasDestination({ ...bare, vibe: 'beach weekend' })).toBe(true)
    expect(hasDestination(sanJoseProfile)).toBe(true)
  })
})
