import { describe, expect, it } from 'vitest'
import { sanJoseV1 } from '@/fixtures'
import { hasBookings } from './map'

// The Book tab rule (docs/spec.md F6): Book unlocks once the plan has bookings.
describe('hasBookings', () => {
  it('is false without a plan', () => {
    expect(hasBookings(null)).toBe(false)
  })

  it('is false for a plan with no bookings', () => {
    expect(hasBookings({ ...sanJoseV1, bookings: [] })).toBe(false)
  })

  it('is true once the plan has a booking, booked or not', () => {
    expect(hasBookings(sanJoseV1)).toBe(true)
    const allBooked = { ...sanJoseV1, bookings: sanJoseV1.bookings.map((b) => ({ ...b, status: 'booked' as const })) }
    expect(hasBookings(allBooked)).toBe(true)
  })
})
