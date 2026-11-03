import { formatMiles, formatMoney, formatMoneyRange } from "@/lib/format"
import type { Itinerary, Transit, TransitMode } from "@/types"

// Helpers shared by the plan view (and, from Stage 2, the map): day colours, tag colours and
// the cost / transit labels.

/**
 * Per-day palette (02 §1), used for day-card stripes and tag badges; Stage 2 map markers and
 * polylines reuse it. Tailwind 700 shades, so white badge text stays readable (≥ 4.5:1).
 */
export const DAY_COLORS = [
  "#1d4ed8", // blue
  "#c2410c", // orange
  "#047857", // emerald
  "#7e22ce", // purple
  "#be123c", // rose
  "#0e7490", // cyan
  "#b45309", // amber
] as const

/** Badge colour for a place that no day item refers to. */
export const UNUSED_PLACE_COLOR = "#52525b" // zinc-600

/** Day 1 → the first palette colour; wraps around after 7 days. */
export function dayColor(dayNumber: number): string {
  return DAY_COLORS[(dayNumber - 1) % DAY_COLORS.length]
}

/** "H1", "H2" are hotels; "H" alone is an ordinary place tag. */
export function isLodgingTag(tag: string): boolean {
  return /^H\d+$/.test(tag)
}

/**
 * Tag → colour of the day where the tag first appears (02 §3), scanning days and items in
 * order. Tags that no item uses are missing; callers fall back to `UNUSED_PLACE_COLOR`.
 */
export function tagColors(itinerary: Itinerary): Record<string, string> {
  const colors: Record<string, string> = {}
  for (const day of itinerary.days) {
    for (const item of day.items) {
      const tag = item.place_tag
      if (tag && !(tag in colors)) colors[tag] = dayColor(day.day_number)
    }
  }
  return colors
}

// Costs are LLM guesses in Stage 1 (decisions.md open question), so they are always labelled
// as estimates.

/** Trip total per person: "Est. $230–$340 per person". */
export function formatTripEstimate(low: number, high: number): string {
  return `Est. ${formatMoneyRange(low, high)} per person`
}

/** One item, per person: "Est. $30 per person"; 0 → "Est. free". */
export function formatItemEstimate(amount: number): string {
  return amount === 0 ? "Est. free" : `Est. ${formatMoney(amount)} per person`
}

const TRANSIT_LABELS: Record<TransitMode, string> = {
  walk: "Walk",
  transit: "Transit",
  drive: "Drive",
  rideshare: "Rideshare",
  flight: "Flight",
  train: "Train",
}

/** "Drive · 12 min · 3.4 mi" */
export function formatTransit(transit: Transit): string {
  return `${TRANSIT_LABELS[transit.mode]} · ${transit.duration_min} min · ${formatMiles(transit.distance_mi)}`
}

/** 1 → "1 night", 2 → "2 nights" */
export function formatNights(nights: number): string {
  return `${nights} ${nights === 1 ? "night" : "nights"}`
}

/** 1 → "1 traveler", 3 → "3 travelers" */
export function formatTravelers(travelers: number): string {
  return `${travelers} ${travelers === 1 ? "traveler" : "travelers"}`
}
