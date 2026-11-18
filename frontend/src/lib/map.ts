// Map tab helpers (docs/spec.md F5): which stops get a pin, their colours, the day lines and
// the stops that have no coordinates. Plain data in, plain data out, so they test without Leaflet.
import type { Itinerary, Stop } from '@/types'
import { dayColor, firstDayByTag } from './tags'

// 'all' or a day number, as picked by the day chips.
export type DayFilter = number | 'all'

// One visit to a stop that has coordinates.
export interface MapStop {
  tag: string
  name: string
  lat: number
  lng: number
  day: number
  startTime: string
}

type LatLng = [number, number]

function hasCoords(stop: Stop): stop is Stop & { lat: number; lng: number } {
  return stop.lat !== null && stop.lng !== null
}

function shownDays(itinerary: Itinerary, day: DayFilter) {
  return itinerary.days.filter((d) => day === 'all' || d.day_number === day)
}

// Every visit (in day and time order) on the shown days to a stop with coordinates.
// A stop visited twice (e.g. the hotel) appears twice.
function visits(itinerary: Itinerary, day: DayFilter): MapStop[] {
  const stopsByTag = new Map(itinerary.stops.map((s) => [s.tag, s]))
  const result: MapStop[] = []
  for (const d of shownDays(itinerary, day)) {
    for (const item of d.items) {
      const stop = item.stop_tag ? stopsByTag.get(item.stop_tag) : undefined
      if (stop && hasCoords(stop)) {
        result.push({ tag: stop.tag, name: stop.name, lat: stop.lat, lng: stop.lng, day: d.day_number, startTime: item.start_time })
      }
    }
  }
  return result
}

// The stops that get a pin for the chosen day: one per tag, in visit order (first visit kept).
export function stopsForDay(itinerary: Itinerary, day: DayFilter): MapStop[] {
  const seen = new Map<string, MapStop>()
  for (const v of visits(itinerary, day)) if (!seen.has(v.tag)) seen.set(v.tag, v)
  return [...seen.values()]
}

// A tag's pin colour: the colour of the day it first appears on (day 1 if it is not visited).
export function dayColorForTag(itinerary: Itinerary, tag: string): string {
  return dayColor(firstDayByTag(itinerary).get(tag) ?? 1)
}

// The dashed line of one day: the coordinates of its visits in order.
export function polylineForDay(itinerary: Itinerary, dayNumber: number): LatLng[] {
  return visits(itinerary, dayNumber).map((v) => [v.lat, v.lng])
}

// Tags visited on the shown days whose stop has no coordinates, once each, in visit order.
export function offMapStops(itinerary: Itinerary, day: DayFilter): string[] {
  const stopsByTag = new Map(itinerary.stops.map((s) => [s.tag, s]))
  const tags: string[] = []
  for (const d of shownDays(itinerary, day)) {
    for (const item of d.items) {
      const stop = item.stop_tag ? stopsByTag.get(item.stop_tag) : undefined
      if (stop && !hasCoords(stop) && !tags.includes(stop.tag)) tags.push(stop.tag)
    }
  }
  return tags
}

// The south-west and north-east corners around the points, or null when there are none.
export function bounds(points: { lat: number; lng: number }[]): [LatLng, LatLng] | null {
  if (points.length === 0) return null
  const lats = points.map((p) => p.lat)
  const lngs = points.map((p) => p.lng)
  return [
    [Math.min(...lats), Math.min(...lngs)],
    [Math.max(...lats), Math.max(...lngs)],
  ]
}

// The Map tab rule: it unlocks once any stop has coordinates.
export function hasMapStops(itinerary: Itinerary | null): boolean {
  return itinerary?.stops.some(hasCoords) ?? false
}

// The Book tab rule (docs/spec.md F6): it unlocks once the plan has bookings.
export function hasBookings(itinerary: Itinerary | null): boolean {
  return (itinerary?.bookings.length ?? 0) > 0
}
