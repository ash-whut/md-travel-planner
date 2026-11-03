import { describe, expect, it } from "vitest"
import {
  formatDate,
  formatDateRange,
  formatMiles,
  formatMoney,
  formatMoneyRange,
  formatTemp,
  formatTime,
  formatTimeRange,
} from "@/lib/format"

describe("dates", () => {
  it("formats a date without shifting it to the previous day", () => {
    expect(formatDate("2027-03-06")).toBe("Sat, Mar 6")
    expect(formatDate("2027-01-01")).toBe("Fri, Jan 1")
  })

  it("formats date ranges", () => {
    expect(formatDateRange("2027-03-06", "2027-03-08")).toBe("Mar 6–8")
    expect(formatDateRange("2027-03-30", "2027-04-02")).toBe("Mar 30 – Apr 2")
    expect(formatDateRange("2026-12-30", "2027-01-02")).toBe(
      "Dec 30, 2026 – Jan 2, 2027"
    )
    expect(formatDateRange("2027-03-06", "2027-03-06")).toBe("Mar 6")
  })

  it("returns malformed dates unchanged instead of throwing", () => {
    expect(formatDate("soon")).toBe("soon")
    expect(formatDateRange("soon", "2027-03-08")).toBe("soon – 2027-03-08")
  })
})

describe("times", () => {
  it("formats 24h times as 12h", () => {
    expect(formatTime("00:30")).toBe("12:30 AM")
    expect(formatTime("09:05")).toBe("9:05 AM")
    expect(formatTime("11:00")).toBe("11:00 AM")
    expect(formatTime("12:00")).toBe("12:00 PM")
    expect(formatTime("13:05")).toBe("1:05 PM")
    expect(formatTime("23:59")).toBe("11:59 PM")
  })

  it("returns unexpected input unchanged", () => {
    expect(formatTime("noon")).toBe("noon")
  })

  it("formats time ranges", () => {
    expect(formatTimeRange("11:00", "12:30")).toBe("11:00 AM – 12:30 PM")
  })
})

describe("money", () => {
  it("drops cents for whole dollars", () => {
    expect(formatMoney(25)).toBe("$25")
    expect(formatMoney(25.5)).toBe("$25.50")
    expect(formatMoney(1234)).toBe("$1,234")
  })

  it("formats ranges", () => {
    expect(formatMoneyRange(280, 390)).toBe("$280–$390")
    expect(formatMoneyRange(120, 120)).toBe("$120")
  })
})

describe("units", () => {
  it("formats °F", () => {
    expect(formatTemp(72.4)).toBe("72°")
    expect(formatTemp(51.6, true)).toBe("52 °F")
  })

  it("formats miles", () => {
    expect(formatMiles(3.42)).toBe("3.4 mi")
    expect(formatMiles(12)).toBe("12 mi")
  })
})
