import type {
  IsoDate,
  IsoDateTime,
  Link,
  Money,
  TimeHHMM,
} from "@/types/common"

// Itinerary, docs/03-contracts.md §2.2. Every field marked null there is nullable here.
// In Stage 1 coordinates, place ids, ratings, prices, weather and transit are null.

export type PlaceCategory =
  | "food"
  | "sight"
  | "nature"
  | "nightlife"
  | "shopping"
  | "museum"
  | "activity"
  | "transport_hub"
  | "other"
export type CostCategory =
  "lodging" | "food" | "activities" | "local_transport" | "other"
export type ItemKind = "activity" | "meal" | "transit" | "lodging" | "free_time"
export type TransitMode =
  "walk" | "transit" | "drive" | "rideshare" | "flight" | "train"
export type ChecklistCategory =
  | "flights"
  | "lodging"
  | "activities"
  | "local_transport"
  | "documents"
  | "packing"
export type WeatherSource = "forecast" | "climate" | "unavailable"
export type PriceSource = "serpapi_google_hotels" | "none"
export type ChecklistStatus = "todo" | "done"

export interface City {
  name: string
  region: string
  country: string
  lat: number | null // null until Stage 2
  lng: number | null
}

export interface CostBreakdown {
  category: CostCategory
  low: number
  high: number
}

/** Per person; flights excluded. */
export interface CostEstimate {
  currency: "USD"
  low: number
  high: number
  breakdown: CostBreakdown[]
}

export interface Place {
  tag: string // A..Z, AA, AB… ; stable across versions
  name: string
  address: string | null
  lat: number | null // null until found (Stage 2+)
  lng: number | null
  place_id: string | null
  category: PlaceCategory
  rating: number | null
  maps_url: string
}

export interface LodgingAlternative {
  name: string
  total_price: Money
  rating: number | null
  link: string
}

export interface Lodging {
  tag: string // H1, H2
  name: string
  city: string
  address: string | null
  lat: number | null
  lng: number | null
  place_id: string | null
  check_in: IsoDate
  check_out: IsoDate
  nights: number
  rating: number | null
  price_per_night: Money | null // null when price_source is "none"
  total_price: Money | null // whole stay, whole room
  price_as_of: IsoDateTime | null
  price_source: PriceSource
  alternatives: LodgingAlternative[]
  links: Link[]
}

/** high_f/low_f are null only when source is "unavailable". */
export interface Weather {
  high_f: number | null
  low_f: number | null
  condition: string | null
  precip_chance: number | null
  source: WeatherSource
}

export interface Transit {
  mode: TransitMode
  duration_min: number
  distance_mi: number
}

export interface Item {
  id: string
  kind: ItemKind
  title: string
  description: string
  start_time: TimeHHMM
  end_time: TimeHHMM
  place_tag: string | null // place tag ("A"), lodging tag ("H1"), or null
  est_cost: Money | null // per person
  booking_required: boolean
  checklist_item_id: string | null
  transit_from_previous: Transit | null // null for the first item and until Stage 3
  tips: string | null
}

export interface Day {
  day_number: number
  date: IsoDate
  title: string
  city: string
  lodging_tag: string | null // null on the departure day or with no hotel
  weather: Weather | null // null until Stage 3
  items: Item[]
}

export interface ChecklistItem {
  id: string
  category: ChecklistCategory
  title: string
  details: string | null
  date: IsoDate | null
  recommended_option: string | null
  links: Link[]
  bookable_by_us: boolean
  status: ChecklistStatus
}

export interface Itinerary {
  id: string
  version: number
  title: string
  summary: string
  start_date: IsoDate
  end_date: IsoDate
  travelers: number
  cities: City[] // 1–2
  cost_estimate: CostEstimate | null
  weather_summary: string | null // null until Stage 3
  assumptions: string[]
  places: Place[]
  lodging: Lodging[] // 0–2
  days: Day[] // 1–7
  checklist: ChecklistItem[]
  created_at: IsoDateTime
}
