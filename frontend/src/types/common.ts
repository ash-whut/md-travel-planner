// Shared conventions from docs/03-contracts.md (top of file).

/** Calendar date, "YYYY-MM-DD". */
export type IsoDate = string

/** Timestamp, ISO-8601 UTC, e.g. "2026-11-01T18:04:05Z". */
export type IsoDateTime = string

/** Local time of day, "HH:MM" 24h (the UI shows it as 12h; see lib/format.ts). */
export type TimeHHMM = string

export interface Money {
  amount: number
  currency: "USD"
}

export interface Link {
  label: string
  url: string
}
