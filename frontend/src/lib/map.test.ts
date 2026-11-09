import { describe, expect, it } from 'vitest'
import { sanJoseV2 } from '@/fixtures'
import type { Itinerary } from '@/types'
import { bounds, dayColorForTag, hasMapStops, offMapStops, polylineForDay, stopsForDay } from './map'
import { dayColor } from './tags'

// San Jose v2: A, B have no coordinates; C (the airport) is visited on day 1 and day 3.
//   day 1: A B C D E   day 2: L G H I   day 3: J K C
function copy(): Itinerary {
  return structuredClone(sanJoseV2)
}

function withoutCoords(itinerary: Itinerary, tags: string[]): Itinerary {
  for (const stop of itinerary.stops) {
    if (tags.includes(stop.tag)) {
      stop.lat = null
      stop.lng = null
    }
  }
  return itinerary
}

describe('stopsForDay', () => {
  it('lists each stop with coordinates once, in visit order, for all days', () => {
    expect(stopsForDay(sanJoseV2, 'all').map((s) => s.tag)).toEqual(['C', 'D', 'E', 'L', 'G', 'H', 'I', 'J', 'K'])
  })

  it('keeps only the chosen day', () => {
    expect(stopsForDay(sanJoseV2, 1).map((s) => s.tag)).toEqual(['C', 'D', 'E'])
    expect(stopsForDay(sanJoseV2, 2).map((s) => s.tag)).toEqual(['L', 'G', 'H', 'I'])
    expect(stopsForDay(sanJoseV2, 3).map((s) => s.tag)).toEqual(['J', 'K', 'C'])
  })

  it('keeps the first visit of a repeated stop (day, time, coordinates, name)', () => {
    const c = stopsForDay(sanJoseV2, 'all').find((s) => s.tag === 'C')
    expect(c).toEqual({ tag: 'C', name: 'San Jose Airport', lat: 37.3639, lng: -121.9289, day: 1, startTime: '13:30' })
    // On day 3 alone, the day-3 visit is the one shown.
    const c3 = stopsForDay(sanJoseV2, 3).find((s) => s.tag === 'C')
    expect(c3?.day).toBe(3)
    expect(c3?.startTime).toBe('14:40')
  })

  it('skips untagged items and stops without coordinates', () => {
    const it2 = withoutCoords(copy(), ['G'])
    it2.days[1].items.push({ ...it2.days[1].items[0], stop_tag: null, start_time: '20:00' })
    expect(stopsForDay(it2, 2).map((s) => s.tag)).toEqual(['L', 'H', 'I'])
  })

  it('returns nothing for a day that does not exist or has no mapped stops', () => {
    expect(stopsForDay(sanJoseV2, 9)).toEqual([])
    expect(stopsForDay(withoutCoords(copy(), ['C', 'D', 'E']), 1)).toEqual([])
  })
})

describe('dayColorForTag', () => {
  it('uses the colour of the day the tag first appears on', () => {
    expect(dayColorForTag(sanJoseV2, 'D')).toBe(dayColor(1))
    expect(dayColorForTag(sanJoseV2, 'L')).toBe(dayColor(2))
    expect(dayColorForTag(sanJoseV2, 'J')).toBe(dayColor(3))
    expect(dayColorForTag(sanJoseV2, 'C')).toBe(dayColor(1)) // day 1 and day 3: first wins
  })

  it('falls back to the day 1 colour for a tag that is never visited', () => {
    expect(dayColorForTag(sanJoseV2, 'ZZ')).toBe(dayColor(1))
  })
})

describe('polylineForDay', () => {
  it('connects the day visits with coordinates, in order', () => {
    expect(polylineForDay(sanJoseV2, 1)).toEqual([
      [37.3639, -121.9289],
      [37.3299, -121.8889],
      [37.3364, -121.8945],
    ])
  })

  it('includes a repeated stop at each visit', () => {
    const it2 = copy()
    it2.days[1].items.push({ ...it2.days[1].items[0], stop_tag: 'L', start_time: '21:00' }) // back to L
    const line = polylineForDay(it2, 2)
    expect(line).toHaveLength(5)
    expect(line[0]).toEqual([37.3352, -121.888])
    expect(line[4]).toEqual([37.3352, -121.888])
  })

  it('ends day 3 at the airport even though it was first visited on day 1', () => {
    expect(polylineForDay(sanJoseV2, 3).at(-1)).toEqual([37.3639, -121.9289])
  })

  it('is empty for a missing day', () => {
    expect(polylineForDay(sanJoseV2, 9)).toEqual([])
  })
})

describe('offMapStops', () => {
  it('lists tags without coordinates on the shown days, in visit order', () => {
    expect(offMapStops(sanJoseV2, 'all')).toEqual(['A', 'B'])
    expect(offMapStops(sanJoseV2, 1)).toEqual(['A', 'B'])
    expect(offMapStops(sanJoseV2, 2)).toEqual([])
  })

  it('lists a repeated off-map stop once', () => {
    const it2 = withoutCoords(copy(), ['C'])
    expect(offMapStops(it2, 'all')).toEqual(['A', 'B', 'C'])
    expect(offMapStops(it2, 3)).toEqual(['C'])
  })
})

describe('bounds', () => {
  it('is null when there are no points', () => {
    expect(bounds([])).toBeNull()
  })

  it('is a zero-size box around a single point', () => {
    expect(bounds([{ lat: 1, lng: 2 }])).toEqual([
      [1, 2],
      [1, 2],
    ])
  })

  it('spans the south-west and north-east corners', () => {
    const points = [
      { lat: 37.3, lng: -121.9 },
      { lat: 37.4, lng: -121.95 },
      { lat: 37.35, lng: -121.85 },
    ]
    expect(bounds(points)).toEqual([
      [37.3, -121.95],
      [37.4, -121.85],
    ])
  })

  it('accepts the stops from stopsForDay', () => {
    expect(bounds(stopsForDay(sanJoseV2, 2))).toEqual([
      [37.3184, -121.9511],
      [37.3352, -121.888],
    ])
  })
})

describe('hasMapStops (Map tab rule)', () => {
  it('is false without a plan', () => {
    expect(hasMapStops(null)).toBe(false)
  })

  it('is false when no stop has coordinates', () => {
    const it2 = copy()
    expect(hasMapStops(withoutCoords(it2, it2.stops.map((s) => s.tag)))).toBe(false)
  })

  it('is false when a stop has only one of lat/lng', () => {
    const it2 = copy()
    withoutCoords(it2, it2.stops.map((s) => s.tag))
    it2.stops[2].lat = 37.36
    expect(hasMapStops(it2)).toBe(false)
  })

  it('is true once any stop has coordinates', () => {
    const it2 = copy()
    withoutCoords(it2, it2.stops.filter((s) => s.tag !== 'K').map((s) => s.tag))
    expect(hasMapStops(it2)).toBe(true)
    expect(hasMapStops(sanJoseV2)).toBe(true)
  })
})
