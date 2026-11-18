// Edge cases for the format helpers (step 7), beyond the examples in format.test.ts.
import { afterEach, describe, expect, it } from 'vitest'
import {
  formatCostRange,
  formatDate,
  formatDateRange,
  formatDuration,
  formatMiles,
  formatMoney,
  formatNights,
  formatShortDate,
  formatTemp,
  formatTime,
} from './format'

describe('formatTime edge cases', () => {
  it('handles midnight, noon and the hour before each', () => {
    expect(formatTime('00:00')).toBe('12:00 AM')
    expect(formatTime('11:59')).toBe('11:59 AM')
    expect(formatTime('12:00')).toBe('12:00 PM')
    expect(formatTime('12:30')).toBe('12:30 PM')
    expect(formatTime('23:59')).toBe('11:59 PM')
  })

  it('keeps leading-zero minutes and drops the leading-zero hour', () => {
    expect(formatTime('07:05')).toBe('7:05 AM')
    expect(formatTime('18:04')).toBe('6:04 PM')
  })
})

describe('dates are timezone independent', () => {
  const originalTz = process.env.TZ
  afterEach(() => {
    process.env.TZ = originalTz
  })

  for (const tz of ['Pacific/Honolulu', 'UTC', 'Asia/Tokyo', 'America/Chicago']) {
    it(`gives the same day in ${tz}`, () => {
      process.env.TZ = tz
      expect(formatDate('2027-03-05')).toBe('Fri, Mar 5')
      expect(formatDate('2027-01-01')).toBe('Fri, Jan 1')
      expect(formatDate('2026-12-31')).toBe('Thu, Dec 31')
      expect(formatShortDate('2027-03-01')).toBe('Mar 1')
      expect(formatDateRange('2027-03-05', '2027-03-07')).toBe('Mar 5–7')
    })
  }

  it('handles a leap day and no zero-padding', () => {
    expect(formatDate('2028-02-29')).toBe('Tue, Feb 29')
    expect(formatShortDate('2027-11-09')).toBe('Nov 9')
  })

  it('formats a range across a year boundary', () => {
    expect(formatDateRange('2026-12-30', '2027-01-02')).toBe('Dec 30 – Jan 2')
  })

  it('uses an en dash in the same-month range', () => {
    expect(formatDateRange('2027-03-05', '2027-03-07')).toContain('–')
  })
})

describe('money edge cases', () => {
  it('formats zero and rounds to whole dollars', () => {
    expect(formatMoney({ amount: 0, currency: 'USD' })).toBe('$0')
    expect(formatMoney({ amount: 120.4, currency: 'USD' })).toBe('$120')
  })

  it('formats a range with thousands separators', () => {
    expect(formatCostRange({ low: 950, high: 1250, currency: 'USD', source: 'ai_estimate' })).toBe(
      '$950 – $1,250',
    )
  })
})

describe('duration, nights, temperature and miles edge cases', () => {
  it('formats durations at the hour boundary and the flight example', () => {
    expect(formatDuration(59)).toBe('59 min')
    expect(formatDuration(60)).toBe('1 hr')
    expect(formatDuration(360)).toBe('6 hr') // spec: "Est: $300 | 6 hr"
    expect(formatDuration(0)).toBe('0 min')
  })

  it('uses the singular only for one night', () => {
    expect(formatNights(1)).toBe('1 night')
    expect(formatNights(3)).toBe('3 nights')
    expect(formatNights(0)).toBe('0 nights')
  })

  it('rounds temperatures to whole °F, including below zero', () => {
    expect(formatTemp(47.4)).toBe('47 °F')
    expect(formatTemp(-3)).toBe('-3 °F')
  })

  it('rounds miles to one decimal', () => {
    expect(formatMiles(0.25)).toBe('0.3 mi')
    expect(formatMiles(12)).toBe('12 mi')
    expect(formatMiles(4.1)).toBe('4.1 mi')
  })
})
