import type { IsoDate } from "@/types/common"

// TripProfile, docs/03-contracts.md §2.1. Every field is always present: unknown scalars
// are null and lists are []. The chat fills it from Stage 3; in Stage 1 it stays empty.

export type BudgetLevel = "budget" | "mid" | "splurge"
export type Pace = "relaxed" | "balanced" | "packed"
export type Transport = "car" | "transit" | "walk" | "mixed"
export type RequiredSlot =
  "destination" | "dates" | "origin" | "travelers" | "interests"

export interface TripProfile {
  cities: string[] // 0–2 entries
  vibe: string | null
  start_date: IsoDate | null
  end_date: IsoDate | null
  duration_days: number | null // 1–7
  rough_timing: string | null
  origin: string | null
  travelers: number | null // adults, 1–6
  budget_level: BudgetLevel // never null: the server defaults it to "budget"
  interests: string[]
  pace: Pace | null
  transport: Transport | null
  must_see: string[]
  avoid: string[]
  dietary: string | null
  hotel_area: string | null
  notes: string | null
  missing_required: RequiredSlot[] // computed server-side; [] until Stage 3
}
