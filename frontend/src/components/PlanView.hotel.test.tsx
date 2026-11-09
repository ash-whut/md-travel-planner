// Step 41: hotel per night + nights + "as of", "check link" for null cost, "Why this?" source,
// map links in a new tab, and travel legs (a flight leg has a null duration).
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { sanJoseProfile, sanJoseV2 } from '@/fixtures'
import type { Itinerary, ItineraryItem, Lodging, Stop } from '@/types'
import { PlanView } from './PlanView'

const local = (y: number, mo: number, d: number, h: number, mi: number) => new Date(y, mo, d, h, mi).toISOString()
const AS_OF = local(2026, 10, 1, 18, 4) // "Nov 1, 6:04 PM" in local time

function stop(tag: string, name: string, kind: Stop['kind'], mapUrl: string | null = null): Stop {
  return { tag, name, kind, address: null, lat: 37.3, lng: -121.9, place_id: null, rating: null, map_url: mapUrl }
}

function item(over: Partial<ItineraryItem> & Pick<ItineraryItem, 'id' | 'kind'>): ItineraryItem {
  return {
    stop_tag: null,
    description: 'Something',
    start_time: '09:00',
    duration_min: 60,
    nights: null,
    est_cost: null,
    cost_source: null,
    booking_required: false,
    booking_id: null,
    why: null,
    source: null,
    transit_from_previous: null,
    updated_in_version: null,
    ...over,
  }
}

const lodging = (over: Partial<Lodging> = {}): Lodging => ({
  stop_tag: 'C',
  check_in: '2027-03-05',
  check_out: '2027-03-07',
  nights: 2,
  price_per_night: { amount: 120, currency: 'USD' },
  total_price: { amount: 240, currency: 'USD' },
  price_source: 'serpapi_google_hotels',
  price_as_of: AS_OF,
  links: [],
  ...over,
})

const STOPS = [
  stop('A', 'DFW Airport', 'airport'),
  stop('B', 'SJC Airport', 'airport'),
  stop('C', 'Hotel Clara', 'lodging', 'https://www.google.com/maps/search/?api=1&query=Hotel+Clara'),
  stop('D', 'Tech Museum', 'museum'),
]

const flight = item({
  id: 'i1', kind: 'flight', stop_tag: 'B', description: 'Fly DFW → SJC', duration_min: 240,
  est_cost: { amount: 300, currency: 'USD' },
})
const hotel = (over: Partial<ItineraryItem> = {}) =>
  item({
    id: 'i2', kind: 'lodging', stop_tag: 'C', description: 'Check in', start_time: '15:00', nights: 2,
    est_cost: { amount: 120, currency: 'USD' }, cost_source: 'tool',
    transit_from_previous: { mode: 'flight', duration_min: null, distance_mi: null, estimated: true },
    ...over,
  })
const museum = item({
  id: 'i3', kind: 'activity', stop_tag: 'D', description: 'Hands-on exhibits', start_time: '17:00', duration_min: 90,
  est_cost: null, why: 'Fits your interest in tech', source: 'Geoapify',
  transit_from_previous: { mode: 'rideshare', duration_min: 12, distance_mi: 4.1, estimated: true },
})

function plan(items: ItineraryItem[], lodgings: Lodging[] = [lodging()]): Itinerary {
  return {
    ...sanJoseV2,
    version: 1,
    stops: STOPS,
    lodging: lodgings,
    days: [{ ...sanJoseV2.days[0], weather: null, items }],
  }
}

function renderPlan(itinerary: Itinerary) {
  return render(<PlanView itinerary={itinerary} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
}

// The <li> of the entry whose description is `text`.
const entry = (text: string) => screen.getByText(text).closest('li') as HTMLElement

describe('PlanView cost text', () => {
  it('shows "Est: check link" when est_cost is null', () => {
    renderPlan(plan([museum]))
    expect(within(entry('Hands-on exhibits')).getByText(/Est: check link/)).toBeTruthy()
    expect(entry('Hands-on exhibits').textContent).toContain('Est: check link | 1.5 hr')
  })

  it('shows a normal price with its duration', () => {
    renderPlan(plan([flight]))
    expect(entry('Fly DFW → SJC').textContent).toContain('Est: $300 | 4 hr')
  })
})

describe('PlanView hotel', () => {
  it('shows the price per night, the nights and the "as of" time', () => {
    renderPlan(plan([hotel()]))
    const li = entry('Check in')
    expect(li.textContent).toContain('Est: $120/night | 2 nights')
    expect(within(li).getByText('as of Nov 1, 6:04 PM')).toBeTruthy()
  })

  it('shows "check link" and no "as of" when the hotel has no price', () => {
    renderPlan(plan([hotel({ est_cost: null })], [lodging({ price_per_night: null, total_price: null })]))
    const li = entry('Check in')
    expect(li.textContent).toContain('Est: check link | 2 nights')
    expect(li.textContent).not.toMatch(/as of/)
  })

  it('shows no "as of" when the lodging entry has no price time', () => {
    renderPlan(plan([hotel()], [lodging({ price_as_of: null, price_source: 'ai_estimate' })]))
    const li = entry('Check in')
    expect(li.textContent).toContain('Est: $120/night | 2 nights')
    expect(li.textContent).not.toMatch(/as of/)
  })

  it('uses the singular for one night', () => {
    renderPlan(plan([hotel({ nights: 1 })], [lodging({ nights: 1 })]))
    expect(entry('Check in').textContent).toContain('Est: $120/night | 1 night')
  })
})

describe('PlanView "Why this?"', () => {
  it('expands the reason and the source', () => {
    renderPlan(plan([museum]))
    const li = entry('Hands-on exhibits')
    expect(within(li).queryByText('Source: Geoapify')).toBeNull()
    fireEvent.click(within(li).getByRole('button', { name: /Why this\?/ }))
    expect(within(li).getByText('Fits your interest in tech')).toBeTruthy()
    expect(within(li).getByText('Source: Geoapify')).toBeTruthy()
  })

  it('appears when only a source is set', () => {
    renderPlan(plan([hotel({ source: 'SerpApi Google Hotels · as of Nov 1, 6:04 PM UTC' })]))
    const li = entry('Check in')
    fireEvent.click(within(li).getByRole('button', { name: /Why this\?/ }))
    expect(within(li).getByText('Source: SerpApi Google Hotels · as of Nov 1, 6:04 PM UTC')).toBeTruthy()
  })

  it('is hidden when the item has neither why nor source', () => {
    renderPlan(plan([flight]))
    expect(within(entry('Fly DFW → SJC')).queryByRole('button', { name: /Why this\?/ })).toBeNull()
  })
})

describe('PlanView map links', () => {
  it('opens the stop in Google Maps in a new tab', () => {
    renderPlan(plan([hotel()]))
    const link = screen.getByRole('link', { name: 'Open Hotel Clara in Google Maps' })
    expect(link.getAttribute('href')).toBe('https://www.google.com/maps/search/?api=1&query=Hotel+Clara')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
  })

  it('has no map link when the stop has no map_url', () => {
    renderPlan(plan([museum]))
    expect(screen.queryByRole('link', { name: /in Google Maps/ })).toBeNull()
  })
})

describe('PlanView travel legs', () => {
  it('renders a flight leg with a null duration without crashing', () => {
    renderPlan(plan([flight, hotel()]))
    const legs = screen.getAllByTestId('transit-leg')
    expect(legs).toHaveLength(1)
    expect(legs[0].textContent).toBe('↓ flight')
    expect(legs[0].textContent).not.toMatch(/null|NaN/)
  })

  it('shows an estimated leg with "~" and an estimate tooltip', () => {
    renderPlan(plan([flight, hotel(), museum]))
    const legs = screen.getAllByTestId('transit-leg')
    expect(legs).toHaveLength(2)
    expect(legs[1].textContent).toBe('↓ ~12 min rideshare · 4.1 mi')
    expect(legs[1].getAttribute('title')).toMatch(/Estimated/)
  })

  it('has no estimate tooltip when the leg is not estimated', () => {
    const walk = { ...museum, transit_from_previous: { mode: 'walk' as const, duration_min: 8, distance_mi: 0.4, estimated: false } }
    renderPlan(plan([hotel(), walk]))
    const legs = screen.getAllByTestId('transit-leg')
    const walkLeg = legs.find((l) => l.textContent?.includes('walk'))
    expect(walkLeg?.textContent).toBe('↓ 8 min walk · 0.4 mi')
    expect(walkLeg?.getAttribute('title')).toBeNull()
  })

  it('shows no leg on the first item', () => {
    renderPlan(plan([flight]))
    expect(screen.queryByTestId('transit-leg')).toBeNull()
  })
})
