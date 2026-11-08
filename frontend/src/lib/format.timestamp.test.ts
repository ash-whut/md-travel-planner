// Step 26: formatTimestamp shows a moment in the user's local time (the version badge).
import { describe, expect, it } from 'vitest'
import { formatTimestamp } from './format'

// Built from local parts, so the expected text holds in any timezone.
const local = (y: number, mo: number, d: number, h: number, mi: number) => new Date(y, mo, d, h, mi).toISOString()

describe('formatTimestamp', () => {
  it('formats an afternoon time in 12h', () => {
    expect(formatTimestamp(local(2026, 10, 1, 18, 8))).toBe('Nov 1, 6:08 PM')
  })

  it('handles midnight and noon', () => {
    expect(formatTimestamp(local(2027, 0, 5, 0, 5))).toBe('Jan 5, 12:05 AM')
    expect(formatTimestamp(local(2027, 2, 31, 12, 0))).toBe('Mar 31, 12:00 PM')
  })

  it('returns the input unchanged when it is not a date', () => {
    expect(formatTimestamp('not a date')).toBe('not a date')
  })
})
