// The shared San Jose fixtures must match docs/contracts.md §2 (field names) and §3 (tag rules).
import { describe, expect, it } from 'vitest'
import type { Itinerary } from '@/types'
import { sanJoseMessages, sanJoseProfile, sanJoseV1, sanJoseV2 } from './index'

const keys = (o: object) => Object.keys(o).sort()

const ITINERARY_KEYS = [
  'id', 'version', 'title', 'summary', 'start_date', 'end_date', 'travelers', 'cities', 'cost_estimate',
  'weather_summary', 'assumptions', 'stops', 'lodging', 'days', 'bookings', 'created_at',
].sort()
const STOP_KEYS = ['tag', 'name', 'kind', 'address', 'lat', 'lng', 'place_id', 'rating', 'map_url'].sort()
const DAY_KEYS = ['day_number', 'date', 'title', 'city', 'weather', 'items'].sort()
const ITEM_KEYS = [
  'id', 'kind', 'stop_tag', 'description', 'start_time', 'duration_min', 'nights', 'est_cost', 'cost_source',
  'booking_required', 'booking_id', 'why', 'source', 'transit_from_previous', 'updated_in_version',
].sort()
const BOOKING_KEYS = ['id', 'kind', 'tags', 'title', 'details', 'estimate', 'price_as_of', 'links', 'status'].sort()
const LODGING_KEYS = [
  'stop_tag', 'check_in', 'check_out', 'nights', 'price_per_night', 'total_price', 'price_source',
  'price_as_of', 'links',
].sort()
const PROFILE_KEYS = [
  'cities', 'vibe', 'start_date', 'end_date', 'duration_days', 'rough_timing', 'origin', 'travelers',
  'budget_level', 'interests', 'dietary', 'pace', 'transport', 'notes', 'missing_required',
].sort()
const MESSAGE_KEYS = ['id', 'role', 'content', 'itinerary_version', 'created_at'].sort()

const items = (it: Itinerary) => it.days.flatMap((d) => d.items)

// Tags in the order the itinerary first uses them (days in order, items by start_time).
function walkOrder(it: Itinerary): string[] {
  const seen: string[] = []
  for (const d of it.days) {
    const sorted = [...d.items].sort((a, b) => a.start_time.localeCompare(b.start_time))
    for (const i of sorted) if (i.stop_tag && !seen.includes(i.stop_tag)) seen.push(i.stop_tag)
  }
  return seen
}

describe.each([
  ['v1', sanJoseV1],
  ['v2', sanJoseV2],
])('itinerary fixture %s', (_name, itin) => {
  it('uses exactly the contract field names', () => {
    expect(keys(itin)).toEqual(ITINERARY_KEYS)
    for (const s of itin.stops) expect(keys(s)).toEqual(STOP_KEYS)
    for (const d of itin.days) expect(keys(d)).toEqual(DAY_KEYS)
    for (const i of items(itin)) expect(keys(i)).toEqual(ITEM_KEYS)
    for (const b of itin.bookings) expect(keys(b)).toEqual(BOOKING_KEYS)
    for (const l of itin.lodging) expect(keys(l)).toEqual(LODGING_KEYS)
  })

  it('has unique stop tags, item ids and booking ids', () => {
    const tags = itin.stops.map((s) => s.tag)
    expect(new Set(tags).size).toBe(tags.length)
    const ids = items(itin).map((i) => i.id)
    expect(new Set(ids).size).toBe(ids.length)
    const bookingIds = itin.bookings.map((b) => b.id)
    expect(new Set(bookingIds).size).toBe(bookingIds.length)
  })

  it('only references stops and bookings that exist, and uses every stop', () => {
    const tags = new Set(itin.stops.map((s) => s.tag))
    const bookingIds = new Set(itin.bookings.map((b) => b.id))
    for (const i of items(itin)) {
      if (i.stop_tag !== null) expect(tags).toContain(i.stop_tag)
      if (i.booking_id !== null) expect(bookingIds).toContain(i.booking_id)
    }
    for (const b of itin.bookings) for (const t of b.tags) expect(tags).toContain(t)
    for (const l of itin.lodging) expect(tags).toContain(l.stop_tag)
    const used = new Set(items(itin).map((i) => i.stop_tag))
    for (const t of tags) expect(used).toContain(t)
  })

  it('has well-formed dates, times and day numbers', () => {
    expect(itin.start_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(itin.end_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    itin.days.forEach((d, idx) => {
      expect(d.day_number).toBe(idx + 1)
      expect(d.date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    })
    for (const i of items(itin)) expect(i.start_time).toMatch(/^([01]\d|2[0-3]):[0-5]\d$/)
  })

  it('has 4 bookings', () => {
    expect(itin.bookings).toHaveLength(4)
  })
})

describe('tag rules (contracts §3)', () => {
  it('v1 assigns A..K in walk order and reuses C for the return flight', () => {
    expect(sanJoseV1.version).toBe(1)
    expect(walkOrder(sanJoseV1)).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K'])
    expect(sanJoseV1.stops.find((s) => s.tag === 'F')?.name).toBe('Baconhouse')
    expect(items(sanJoseV1).filter((i) => i.stop_tag === 'C').length).toBeGreaterThanOrEqual(2)
    for (const i of items(sanJoseV1)) expect(i.updated_in_version).toBeNull()
  })

  it('v2 retires F, gives its replacement the next letter L and keeps the other tags', () => {
    expect(sanJoseV2.version).toBe(2)
    expect(sanJoseV2.stops.map((s) => s.tag).sort()).toEqual(['A', 'B', 'C', 'D', 'E', 'G', 'H', 'I', 'J', 'K', 'L'])
    expect(items(sanJoseV2).some((i) => i.stop_tag === 'F')).toBe(false)
    expect(sanJoseV2.stops.find((s) => s.tag === 'L')?.name).toBe('Good Karma Kitchen')
    expect(sanJoseV2.stops.some((s) => s.name === 'Baconhouse')).toBe(false)
    for (const s of sanJoseV2.stops) {
      if (s.tag === 'L') continue
      expect(sanJoseV1.stops.find((old) => old.tag === s.tag)?.name).toBe(s.name)
    }
  })

  it('v2 marks only the replaced item as updated_in_version 2, in F\'s old slot', () => {
    const updated = items(sanJoseV2).filter((i) => i.updated_in_version !== null)
    expect(updated).toHaveLength(1)
    expect(updated[0].stop_tag).toBe('L')
    expect(updated[0].updated_in_version).toBe(2)
    const fDay = sanJoseV1.days.find((d) => d.items.some((i) => i.stop_tag === 'F'))!
    const fItem = fDay.items.find((i) => i.stop_tag === 'F')!
    const lDay = sanJoseV2.days.find((d) => d.items.some((i) => i.stop_tag === 'L'))!
    expect(lDay.day_number).toBe(fDay.day_number)
    expect(updated[0].start_time).toBe(fItem.start_time)
  })
})

describe('profile and messages fixtures', () => {
  it('profile uses exactly the contract field names', () => {
    expect(keys(sanJoseProfile)).toEqual(PROFILE_KEYS)
    expect(sanJoseProfile.cities.length).toBeLessThanOrEqual(2)
  })

  it('messages use the contract field names and unique ids', () => {
    for (const m of sanJoseMessages) {
      expect(keys(m)).toEqual(MESSAGE_KEYS)
      expect(['user', 'assistant']).toContain(m.role)
    }
    const ids = sanJoseMessages.map((m) => m.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('every [X] token in chat refers to a tag used in some version', () => {
    const known = new Set([...sanJoseV1.stops, ...sanJoseV2.stops].map((s) => s.tag))
    for (const m of sanJoseMessages) {
      for (const match of m.content.matchAll(/\[([A-Z]{1,2})\]/g)) expect(known).toContain(match[1])
    }
  })

  it('the versioned messages point at v1 then v2', () => {
    const versions = sanJoseMessages.map((m) => m.itinerary_version).filter((v) => v !== null)
    expect(versions).toEqual([1, 2])
  })
})
