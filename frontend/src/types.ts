// Loosely mirrors docs/03-contracts.md; trimmed for the v0 mock UI.

export type ItemKind = 'transit' | 'flight' | 'lodging' | 'meal' | 'activity'

export interface PlanItem {
  tag: string
  place: string
  action: string
  kind: ItemKind
  startTime: string // "11:00 AM"
  cost: number | null // USD per person
  duration: string // "2 hr"
  why: string
  source: string
  lat?: number
  lng?: number
  bookable?: boolean
  updatedInVersion?: number
}

export interface Day {
  dayNumber: number
  date: string
  title: string
  weather: { icon: string; high: number; low: number }
  items: PlanItem[]
}

export interface BookingItem {
  id: string
  tags: string[] // ["B", "C"] renders as a B→C range
  title: string
  estimate: string
  detail: string
  provider: string
  done?: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'status' | 'version'
  text: string
}

export interface Trip {
  title: string
  dates: string
  travelers: number
  costRange: string
  weatherSummary: string
  version: number
  assumptions: string[]
  profile: { label: string; missing?: boolean }[]
  days: Day[]
  bookings: BookingItem[]
}
