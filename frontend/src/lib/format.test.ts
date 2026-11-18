import { describe, expect, it } from 'vitest'
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

describe('formatTime', () => {
  it('converts 24h times to 12h', () => {
    expect(formatTime('09:15')).toBe('9:15 AM')
    expect(formatTime('13:30')).toBe('1:30 PM')
    expect(formatTime('12:00')).toBe('12:00 PM')
    expect(formatTime('00:05')).toBe('12:05 AM')
  })
})

describe('dates', () => {
  it('formats a date with the weekday', () => {
    expect(formatDate('2027-03-05')).toBe('Fri, Mar 5')
    expect(formatShortDate('2027-03-05')).toBe('Mar 5')
  })

  it('formats date ranges', () => {
    expect(formatDateRange('2027-03-05', '2027-03-07')).toBe('Mar 5–7')
    expect(formatDateRange('2027-03-30', '2027-04-02')).toBe('Mar 30 – Apr 2')
    expect(formatDateRange('2027-03-05', '2027-03-05')).toBe('Mar 5')
  })
})

describe('money', () => {
  it('formats USD and null', () => {
    expect(formatMoney({ amount: 300, currency: 'USD' })).toBe('$300')
    expect(formatMoney({ amount: 1200, currency: 'USD' })).toBe('$1,200')
    expect(formatMoney(null)).toBe('check link')
  })

  it('formats a cost range', () => {
    expect(formatCostRange({ low: 780, high: 910, currency: 'USD', source: 'ai_estimate' })).toBe(
      '$780 – $910',
    )
  })
})

describe('durations and units', () => {
  it('formats durations', () => {
    expect(formatDuration(90)).toBe('1.5 hr')
    expect(formatDuration(120)).toBe('2 hr')
    expect(formatDuration(45)).toBe('45 min')
    expect(formatDuration(null)).toBe('')
  })

  it('formats nights', () => {
    expect(formatNights(1)).toBe('1 night')
    expect(formatNights(2)).toBe('2 nights')
  })

  it('formats °F and miles', () => {
    expect(formatTemp(66)).toBe('66 °F')
    expect(formatTemp(47.6)).toBe('48 °F')
    expect(formatMiles(4.12)).toBe('4.1 mi')
    expect(formatMiles(1)).toBe('1 mi')
  })
})
