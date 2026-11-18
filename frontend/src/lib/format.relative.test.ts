// Step 45: formatRelative labels a trip's last update in the history rail.
import { describe, expect, it } from 'vitest'
import { formatRelative } from './format'

// Local times, so the calendar-day rules don't depend on the test machine's timezone.
const now = new Date(2026, 10, 15, 18, 0) // Sun, Nov 15 2026, 6:00 PM
const at = (...args: [number, number, number, number?, number?, number?]) => new Date(...args).toISOString()

describe('formatRelative', () => {
  it.each([
    ['under a minute', at(2026, 10, 15, 17, 59, 30), 'Just now'],
    ['5 minutes', at(2026, 10, 15, 17, 55), '5 min ago'],
    ['59 minutes', at(2026, 10, 15, 17, 1), '59 min ago'],
    ['3 hours', at(2026, 10, 15, 15, 0), '3 hr ago'],
    ['yesterday morning (over 24 h)', at(2026, 10, 14, 9, 0), 'Yesterday'],
    ['3 calendar days', at(2026, 10, 12, 20, 0), '3 days ago'],
    ['6 calendar days', at(2026, 10, 9, 10, 0), '6 days ago'],
    ['a week or more, this year', at(2026, 9, 20, 10, 0), 'Oct 20'],
    ['another year', at(2025, 11, 31, 10, 0), 'Dec 31, 2025'],
  ])('%s → %s', (_label, iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected)
  })

  it('treats a time slightly in the future as just now', () => {
    expect(formatRelative(at(2026, 10, 15, 18, 1), now)).toBe('Just now')
  })

  it('returns unparseable input unchanged', () => {
    expect(formatRelative('not a date', now)).toBe('not a date')
  })
})
