import type { IsoDate, TimeHHMM } from "@/types"

// Display formatting (02-ui-spec): dates "Sat, Mar 6", 12h times "11:00 AM", °F, miles,
// US dollars. Plain functions so every component formats the same way.

/**
 * "2027-03-06" → a local Date at midnight. (`new Date("2027-03-06")` would be UTC midnight,
 * which shows as the previous day in US time zones.) Malformed input gives an Invalid Date.
 */
export function parseIsoDate(date: IsoDate): Date {
  const [year, month, day] = date.split("-").map(Number)
  return new Date(year, month - 1, day)
}

const weekdayMonthDay = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
})
const monthDay = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
})
const monthDayYear = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
})

const isValidDate = (date: Date) => !Number.isNaN(date.getTime())

/**
 * "2027-03-06" → "Sat, Mar 6". Unparseable input is returned as is. Out-of-range days
 * ("2027-02-30") roll over like `Date` does; the backend validates dates, so this won't occur.
 */
export function formatDate(date: IsoDate): string {
  const parsed = parseIsoDate(date)
  return isValidDate(parsed) ? weekdayMonthDay.format(parsed) : date
}

/** "Mar 6–8", "Mar 30 – Apr 2", "Dec 30, 2026 – Jan 2, 2027"; one day → "Mar 6". */
export function formatDateRange(start: IsoDate, end: IsoDate): string {
  const from = parseIsoDate(start)
  const to = parseIsoDate(end)
  if (!isValidDate(from) || !isValidDate(to)) return `${start} – ${end}`
  if (from.getFullYear() !== to.getFullYear()) {
    return `${monthDayYear.format(from)} – ${monthDayYear.format(to)}`
  }
  if (from.getMonth() !== to.getMonth()) {
    return `${monthDay.format(from)} – ${monthDay.format(to)}`
  }
  if (from.getDate() === to.getDate()) return monthDay.format(from)
  return `${monthDay.format(from)}–${to.getDate()}`
}

/** "13:05" → "1:05 PM", "00:30" → "12:30 AM". Anything not "HH:MM" is returned as is. */
export function formatTime(time: TimeHHMM): string {
  const match = /^(\d{1,2}):(\d{2})$/.exec(time)
  if (!match) return time
  const hours = Number(match[1])
  const period = hours < 12 ? "AM" : "PM"
  const hours12 = hours % 12 === 0 ? 12 : hours % 12
  return `${hours12}:${match[2]} ${period}`
}

/** "11:00", "12:30" → "11:00 AM – 12:30 PM" */
export function formatTimeRange(start: TimeHHMM, end: TimeHHMM): string {
  return `${formatTime(start)} – ${formatTime(end)}`
}

/** 25 → "$25", 25.5 → "$25.50", 1234 → "$1,234". Contract money is always USD. */
export function formatMoney(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
  }).format(amount)
}

/** 280, 390 → "$280–$390"; equal values → "$120". */
export function formatMoneyRange(
  low: number,
  high: number,
  currency = "USD"
): string {
  if (low === high) return formatMoney(low, currency)
  return `${formatMoney(low, currency)}–${formatMoney(high, currency)}`
}

/** 72.4 → "72°" (weather chip); with `unit` → "72 °F". Temperatures are always °F. */
export function formatTemp(fahrenheit: number, unit = false): string {
  const rounded = Math.round(fahrenheit)
  return unit ? `${rounded} °F` : `${rounded}°`
}

/** 3.42 → "3.4 mi", 12 → "12 mi". Distances are always miles. */
export function formatMiles(miles: number): string {
  const value = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
  }).format(miles)
  return `${value} mi`
}
