// Step 41: hotel price per night, the "as of" time, null cost → "check link", travel legs.
import { describe, expect, it } from 'vitest'
import { formatAsOf, formatMoney, formatPerNight, formatTransitLeg } from './format'

// Built from local parts, so the expected text holds in any timezone (like format.timestamp.test.ts).
const local = (y: number, mo: number, d: number, h: number, mi: number) => new Date(y, mo, d, h, mi).toISOString()

describe('null cost → "check link"', () => {
  it('formatMoney and formatPerNight both say "check link" for null', () => {
    expect(formatMoney(null)).toBe('check link')
    expect(formatPerNight(null)).toBe('check link')
  })
})

describe('formatPerNight', () => {
  it('adds "/night" to a USD amount, rounded to whole dollars', () => {
    expect(formatPerNight({ amount: 120, currency: 'USD' })).toBe('$120/night')
    expect(formatPerNight({ amount: 89.6, currency: 'USD' })).toBe('$90/night')
    expect(formatPerNight({ amount: 1250, currency: 'USD' })).toBe('$1,250/night')
  })
})

describe('formatAsOf', () => {
  it('shows "as of" plus the local 12h time', () => {
    expect(formatAsOf(local(2026, 10, 1, 18, 4))).toBe('as of Nov 1, 6:04 PM')
    expect(formatAsOf(local(2026, 10, 9, 1, 21))).toBe('as of Nov 9, 1:21 AM')
  })

  it('handles midnight and noon', () => {
    expect(formatAsOf(local(2027, 2, 5, 0, 0))).toBe('as of Mar 5, 12:00 AM')
    expect(formatAsOf(local(2027, 2, 5, 12, 30))).toBe('as of Mar 5, 12:30 PM')
  })
})

describe('formatTransitLeg', () => {
  it('marks an estimated leg with "~" and shows the miles', () => {
    expect(formatTransitLeg({ mode: 'rideshare', duration_min: 12, distance_mi: 4.12, estimated: true })).toBe(
      '~12 min rideshare · 4.1 mi',
    )
  })

  it('has no "~" when the leg is not estimated', () => {
    expect(formatTransitLeg({ mode: 'walk', duration_min: 8, distance_mi: 0.4, estimated: false })).toBe(
      '8 min walk · 0.4 mi',
    )
  })

  it('shows only the mode for a flight with null duration and distance', () => {
    expect(formatTransitLeg({ mode: 'flight', duration_min: null, distance_mi: null, estimated: true })).toBe('flight')
  })

  it('skips the distance when it is null', () => {
    expect(formatTransitLeg({ mode: 'drive', duration_min: 90, distance_mi: null, estimated: true })).toBe(
      '~1.5 hr drive',
    )
  })
})
