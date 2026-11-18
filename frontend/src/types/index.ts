// Mirrors docs/contracts.md §2 (schemas) and §5 (SSE events). Keep in sync with
// backend/app/schemas/. JSON stays snake_case; dates are "YYYY-MM-DD", times "HH:MM" (24h),
// timestamps ISO-8601 UTC strings.

// ---- Shared ----

export interface Money {
  amount: number
  currency: string // "USD"
}

export interface Link {
  label: string
  url: string
}

// ---- §2.1 TripProfile ----

export type BudgetLevel = 'budget' | 'mid' | 'splurge'
export type Pace = 'relaxed' | 'balanced' | 'packed'
export type Transport = 'car' | 'transit' | 'rideshare' | 'mixed'
export type RequiredField = 'destination' | 'dates' | 'origin' | 'travelers' | 'interests'

export interface TripProfile {
  cities: string[] // 0–2 entries
  vibe: string | null
  start_date: string | null
  end_date: string | null
  duration_days: number | null // 1–7
  rough_timing: string | null
  origin: string | null
  travelers: number | null // adults, 1–6
  budget_level: BudgetLevel | null
  interests: string[]
  dietary: string | null
  pace: Pace | null
  transport: Transport | null
  notes: string | null
  missing_required: RequiredField[]
}

// ---- §2.2 Itinerary ----

export interface City {
  name: string
  region: string | null
  country: string | null
  lat: number | null // null until geocoded
  lng: number | null
}

export interface CostEstimate {
  low: number
  high: number
  currency: string
  source: string // "ai_estimate"
}

export type StopKind =
  | 'home'
  | 'airport'
  | 'lodging'
  | 'food'
  | 'sight'
  | 'museum'
  | 'nature'
  | 'nightlife'
  | 'shopping'
  | 'activity'
  | 'other'

export interface Stop {
  tag: string // A..Z, AA, AB… assigned by code
  name: string
  kind: StopKind
  address: string | null
  lat: number | null // null = shown as "off map"
  lng: number | null
  place_id: string | null
  rating: number | null
  map_url: string | null
}

export type PriceSource = 'ai_estimate' | 'serpapi_google_hotels' | 'none'

export interface Lodging {
  stop_tag: string
  check_in: string
  check_out: string
  nights: number
  price_per_night: Money | null
  total_price: Money | null
  price_source: PriceSource
  price_as_of: string | null
  links: Link[]
}

export interface DayWeather {
  high_f: number
  low_f: number
  condition: string
  icon: string
  source: 'forecast' | 'climate'
}

export type ItemKind = 'transit' | 'flight' | 'lodging' | 'meal' | 'activity' | 'free_time'
export type TransitMode = 'walk' | 'transit' | 'drive' | 'rideshare' | 'flight'

export interface TransitLeg {
  mode: TransitMode
  duration_min: number | null
  distance_mi: number | null
  estimated: boolean
}

export interface ItineraryItem {
  id: string
  kind: ItemKind
  stop_tag: string | null // null for untagged items (e.g. free time)
  description: string
  start_time: string // "HH:MM"
  duration_min: number | null
  nights: number | null // lodging items only
  est_cost: Money | null // per person; null = "check link"
  cost_source: 'ai_estimate' | 'tool' | null
  booking_required: boolean
  booking_id: string | null
  why: string | null
  source: string | null
  transit_from_previous: TransitLeg | null // null for the first item
  updated_in_version: number | null
}

export interface Day {
  day_number: number
  date: string
  title: string
  city: string
  weather: DayWeather | null // null until the weather step
  items: ItineraryItem[]
}

export type BookingKind = 'flight' | 'lodging' | 'activity'
export type BookingStatus = 'todo' | 'booked'

export interface Booking {
  id: string
  kind: BookingKind
  tags: string[] // shown as B → C
  title: string
  details: string
  estimate: Money | null // null = "check link"
  price_as_of: string | null
  links: Link[]
  status: BookingStatus
}

export interface Itinerary {
  id: string
  version: number
  title: string
  summary: string
  start_date: string
  end_date: string
  travelers: number
  cities: City[]
  cost_estimate: CostEstimate | null
  weather_summary: string | null
  assumptions: string[]
  stops: Stop[]
  lodging: Lodging[]
  days: Day[]
  bookings: Booking[]
  created_at: string
}

// ---- §2.6 Session DTOs ----

export type SessionStatus = 'intake' | 'planned'
export type MessageRole = 'user' | 'assistant'

export interface Message {
  id: string
  role: MessageRole
  content: string // markdown; [C] tokens render as tag chips
  itinerary_version: number | null
  created_at: string
}

export interface SessionSummary {
  id: string
  title: string
  status: SessionStatus
  updated_at: string
}

export interface SessionDetail {
  id: string
  title: string
  status: SessionStatus
  trip_profile: TripProfile
  messages: Message[]
  itinerary: Itinerary | null
  created_at: string
  updated_at: string
}

// ---- §4 request bodies ----

export interface SendMessageBody {
  content: string // 1–4000 chars
}

export interface RenameSessionBody {
  title: string // 1–80 chars
}

export interface UpdateBookingBody {
  status: BookingStatus
}

// ---- §5 SSE events ----

export type StatusState = 'start' | 'end' | 'error'

export type SseEvent =
  | { event: 'message_start'; data: { message_id: string } }
  | { event: 'token'; data: { text: string } }
  | { event: 'status'; data: { label: string; state: StatusState } }
  | { event: 'profile'; data: TripProfile }
  | { event: 'title'; data: { title: string } }
  | { event: 'itinerary'; data: Itinerary }
  | { event: 'error'; data: { message: string; retryable: boolean } }
  | { event: 'done'; data: { message_id: string } }

export type SseEventName = SseEvent['event']
