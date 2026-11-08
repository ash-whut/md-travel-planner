// Display formatting used across the UI (contracts conventions: 12h times, US dates, °F,
// miles, USD). Dates are parsed by hand so the user's timezone can never shift the day.
import type { CostEstimate, Money } from '../types/index'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function parseDate(isoDate: string): { year: number; month: number; day: number } {
  const [year, month, day] = isoDate.split('-').map(Number)
  return { year, month, day }
}

/** "09:15" → "9:15 AM", "13:30" → "1:30 PM", "00:05" → "12:05 AM". */
export function formatTime(hhmm: string): string {
  const [hourText, minuteText] = hhmm.split(':')
  const hour = Number(hourText)
  if (Number.isNaN(hour) || minuteText === undefined) return hhmm
  const suffix = hour < 12 ? 'AM' : 'PM'
  const hour12 = hour % 12 === 0 ? 12 : hour % 12
  return `${hour12}:${minuteText} ${suffix}`
}

/** "2027-03-05" → "Fri, Mar 5". */
export function formatDate(isoDate: string): string {
  const { year, month, day } = parseDate(isoDate)
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay()
  return `${WEEKDAYS[weekday]}, ${MONTHS[month - 1]} ${day}`
}

/** "2027-03-05" → "Mar 5". */
export function formatShortDate(isoDate: string): string {
  const { month, day } = parseDate(isoDate)
  return `${MONTHS[month - 1]} ${day}`
}

/** Same month → "Mar 5–7"; across months → "Mar 30 – Apr 2"; same day → "Mar 5". */
export function formatDateRange(startDate: string, endDate: string): string {
  if (startDate === endDate) return formatShortDate(startDate)
  const start = parseDate(startDate)
  const end = parseDate(endDate)
  if (start.year === end.year && start.month === end.month) {
    return `${MONTHS[start.month - 1]} ${start.day}–${end.day}`
  }
  return `${formatShortDate(startDate)} – ${formatShortDate(endDate)}`
}

/** An ISO timestamp → "Nov 1, 6:06 PM" in the user's local time (a moment, not a trip date). */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const hhmm = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${formatTime(hhmm)}`
}

function formatAmount(amount: number, currency: string): string {
  const number = amount.toLocaleString('en-US', { maximumFractionDigits: 0 })
  return currency === 'USD' ? `$${number}` : `${number} ${currency}`
}

/** { amount: 300, currency: "USD" } → "$300"; null → "check link". */
export function formatMoney(money: Money | null): string {
  if (money === null) return 'check link'
  return formatAmount(money.amount, money.currency)
}

/** { low: 780, high: 910, currency: "USD" } → "$780 – $910". */
export function formatCostRange(estimate: CostEstimate): string {
  return `${formatAmount(estimate.low, estimate.currency)} – ${formatAmount(estimate.high, estimate.currency)}`
}

/** 45 → "45 min", 60 → "1 hr", 90 → "1.5 hr"; null → "". */
export function formatDuration(minutes: number | null): string {
  if (minutes === null) return ''
  if (minutes < 60) return `${minutes} min`
  const hours = Math.round((minutes / 60) * 10) / 10
  return `${hours} hr`
}

/** 1 → "1 night", 2 → "2 nights". */
export function formatNights(nights: number): string {
  return `${nights} ${nights === 1 ? 'night' : 'nights'}`
}

/** 66 → "66 °F" (rounded to whole degrees). */
export function formatTemp(fahrenheit: number): string {
  return `${Math.round(fahrenheit)} °F`
}

/** 4.12 → "4.1 mi", 1 → "1 mi". */
export function formatMiles(miles: number): string {
  const rounded = Math.round(miles * 10) / 10
  return `${rounded} mi`
}
