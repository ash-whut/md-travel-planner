import { describe, expect, it } from "vitest"
import {
  DAY_COLORS,
  dayColor,
  formatItemEstimate,
  formatNights,
  formatTransit,
  formatTravelers,
  formatTripEstimate,
  isLodgingTag,
  tagColors,
} from "@/lib/plan"
import type { Day, Item, Itinerary } from "@/types"

function item(id: string, place_tag: string | null): Item {
  return {
    id,
    kind: "activity",
    title: id,
    description: "",
    start_time: "10:00",
    end_time: "11:00",
    place_tag,
    est_cost: null,
    booking_required: false,
    checklist_item_id: null,
    transit_from_previous: null,
    tips: null,
  }
}

function day(day_number: number, tags: (string | null)[]): Day {
  return {
    day_number,
    date: `2027-03-0${day_number}`,
    title: `Day ${day_number}`,
    city: "Austin",
    lodging_tag: null,
    weather: null,
    items: tags.map((tag, i) => item(`d${day_number}-i${i}`, tag)),
  }
}

describe("dayColor", () => {
  it("gives each day its palette colour and wraps after the last one", () => {
    expect(dayColor(1)).toBe(DAY_COLORS[0])
    expect(dayColor(2)).toBe(DAY_COLORS[1])
    expect(dayColor(DAY_COLORS.length + 1)).toBe(DAY_COLORS[0])
  })
})

describe("isLodgingTag", () => {
  it("treats H plus digits as a hotel and plain letters as places", () => {
    expect(isLodgingTag("H1")).toBe(true)
    expect(isLodgingTag("H2")).toBe(true)
    expect(isLodgingTag("H")).toBe(false)
    expect(isLodgingTag("A")).toBe(false)
    expect(isLodgingTag("HA")).toBe(false)
  })
})

describe("tagColors", () => {
  it("colours each tag by the day it first appears on", () => {
    const itinerary = {
      days: [day(1, ["A", null, "H1", "B"]), day(2, ["C", "A", "H1"])],
    } as Itinerary
    expect(tagColors(itinerary)).toEqual({
      A: DAY_COLORS[0],
      H1: DAY_COLORS[0],
      B: DAY_COLORS[0],
      C: DAY_COLORS[1],
    })
  })
})

describe("labels", () => {
  it("labels costs as per-person estimates", () => {
    expect(formatTripEstimate(230, 340)).toBe("Est. $230–$340 per person")
    expect(formatItemEstimate(30)).toBe("Est. $30 per person")
    expect(formatItemEstimate(0)).toBe("Est. free")
  })

  it("formats a transit leg", () => {
    expect(
      formatTransit({ mode: "drive", duration_min: 12, distance_mi: 3.42 })
    ).toBe("Drive · 12 min · 3.4 mi")
  })

  it("pluralises nights and travelers", () => {
    expect(formatNights(1)).toBe("1 night")
    expect(formatNights(2)).toBe("2 nights")
    expect(formatTravelers(1)).toBe("1 traveler")
    expect(formatTravelers(3)).toBe("3 travelers")
  })
})
