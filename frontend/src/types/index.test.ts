// Step 7: the contract examples from docs/contracts.md §2/§4/§5 must type-check against
// src/types. The real check is `tsc --noEmit` in `npm run build`; the runtime asserts are light.
import { describe, expect, expectTypeOf, it } from 'vitest'
import type {
  Booking,
  Itinerary,
  ItineraryItem,
  Message,
  RenameSessionBody,
  SendMessageBody,
  SessionDetail,
  SessionSummary,
  SseEvent,
  SseEventName,
  Stop,
  TripProfile,
  UpdateBookingBody,
} from './index'

// §2.1 example
const profile = {
  cities: ['San Jose, CA'],
  vibe: null,
  start_date: '2027-03-05',
  end_date: '2027-03-07',
  duration_days: 3,
  rough_timing: null,
  origin: 'College Station, TX',
  travelers: 1,
  budget_level: 'budget',
  interests: ['tech', 'food', 'gardens'],
  dietary: 'vegan',
  pace: 'balanced',
  transport: null,
  notes: null,
  missing_required: [],
} satisfies TripProfile

// §2.2 example (one of each)
const stop = {
  tag: 'C',
  name: 'San Jose Airport',
  kind: 'airport',
  address: '1701 Airport Blvd, San Jose, CA',
  lat: 37.3639,
  lng: -121.9289,
  place_id: 'geoapify:51a3',
  rating: null,
  map_url: 'https://www.google.com/maps/search/?api=1&query=x',
} satisfies Stop

const item = {
  id: 'd1-i2',
  kind: 'flight',
  stop_tag: 'B',
  description: 'Board your flight to San Jose.',
  start_time: '09:15',
  duration_min: 360,
  nights: null,
  est_cost: { amount: 300, currency: 'USD' },
  cost_source: 'ai_estimate',
  booking_required: true,
  booking_id: 'bk-flight',
  why: 'Lowest fare with one stop that lands before 2 PM.',
  source: 'AI suggestion',
  transit_from_previous: { mode: 'rideshare', duration_min: 12, distance_mi: 4.1, estimated: true },
  updated_in_version: null,
} satisfies ItineraryItem

const booking = {
  id: 'bk-flight',
  kind: 'flight',
  tags: ['B', 'C'],
  title: 'Flight Booking',
  details: 'IAH → SJC round trip · Mar 5 – Mar 7',
  estimate: null,
  price_as_of: null,
  links: [{ label: 'Google Flights', url: 'https://example.com' }],
  status: 'todo',
} satisfies Booking

const itinerary = {
  id: 'uuid',
  version: 2,
  title: 'San Jose — Tech, Tacos & Gardens',
  summary: 'One short paragraph.',
  start_date: '2027-03-05',
  end_date: '2027-03-07',
  travelers: 1,
  cities: [{ name: 'San Jose', region: 'CA', country: 'USA', lat: null, lng: null }],
  cost_estimate: { low: 780, high: 910, currency: 'USD', source: 'ai_estimate' },
  weather_summary: null,
  assumptions: ['Budget level assumed (none given)'],
  stops: [stop],
  lodging: [
    {
      stop_tag: 'D',
      check_in: '2027-03-05',
      check_out: '2027-03-07',
      nights: 2,
      price_per_night: { amount: 120, currency: 'USD' },
      total_price: null,
      price_source: 'serpapi_google_hotels',
      price_as_of: '2026-11-01T18:04:05Z',
      links: [{ label: 'Google Hotels', url: 'https://example.com' }],
    },
  ],
  days: [
    {
      day_number: 1,
      date: '2027-03-05',
      title: 'Travel day',
      city: 'San Jose',
      weather: { high_f: 66, low_f: 48, condition: 'sunny', icon: '☀️', source: 'forecast' },
      items: [item],
    },
  ],
  bookings: [booking],
  created_at: '2026-11-01T18:04:05Z',
} satisfies Itinerary

// §2.6
const message = {
  id: 'uuid',
  role: 'assistant',
  content: 'Replace [F]?',
  itinerary_version: null,
  created_at: '2026-11-01T18:04:05Z',
} satisfies Message

const summary = {
  id: 'uuid',
  title: 'San Jose · Mar 5–7',
  status: 'planned',
  updated_at: '2026-11-01T18:04:05Z',
} satisfies SessionSummary

const detail = {
  id: 'uuid',
  title: 'New trip',
  status: 'intake',
  trip_profile: profile,
  messages: [message],
  itinerary: null,
  created_at: '2026-11-01T18:04:05Z',
  updated_at: '2026-11-01T18:04:05Z',
} satisfies SessionDetail

// §4 request bodies
const bodies = [
  { content: 'hi' } satisfies SendMessageBody,
  { title: 'My trip' } satisfies RenameSessionBody,
  { status: 'booked' } satisfies UpdateBookingBody,
]

// §5 — one of every event
const events: SseEvent[] = [
  { event: 'message_start', data: { message_id: 'm1' } },
  { event: 'token', data: { text: 'partial' } },
  { event: 'status', data: { label: 'Checking weather for San Jose · Mar 5–7', state: 'start' } },
  { event: 'profile', data: profile },
  { event: 'title', data: { title: 'San Jose · Mar 5–7' } },
  { event: 'itinerary', data: itinerary },
  { event: 'error', data: { message: 'Something went wrong', retryable: true } },
  { event: 'done', data: { message_id: 'm1' } },
]

// Values the contracts do not allow must be rejected by the compiler.
// @ts-expect-error 'luxury' is not a budget level
const badBudget: TripProfile['budget_level'] = 'luxury'
// @ts-expect-error 'cancelled' is not a booking status
const badStatus: UpdateBookingBody = { status: 'cancelled' }
// @ts-expect-error 'hotel' is not a stop kind
const badKind: Stop['kind'] = 'hotel'
// @ts-expect-error 'bike' is not a transit mode
const badMode: NonNullable<ItineraryItem['transit_from_previous']>['mode'] = 'bike'
// @ts-expect-error the token event carries text, not a message id
const badEvent: SseEvent = { event: 'token', data: { message_id: 'm1' } }
// @ts-expect-error unknown SSE event name
const badName: SseEventName = 'progress'

describe('contract types (step 7)', () => {
  it('accept the contract examples', () => {
    expect(detail.trip_profile.cities).toEqual(['San Jose, CA'])
    expect(itinerary.days[0].items[0].stop_tag).toBe('B')
    expect(summary.status).toBe('planned')
    expect(bodies).toHaveLength(3)
    expect([badBudget, badStatus, badKind, badMode, badEvent, badName]).toHaveLength(6)
  })

  it('cover exactly the eight §5 SSE events', () => {
    expectTypeOf<SseEventName>().toEqualTypeOf<
      'message_start' | 'token' | 'status' | 'profile' | 'title' | 'itinerary' | 'error' | 'done'
    >()
    expect(new Set(events.map((e) => e.event)).size).toBe(8)
  })

  it('keep nullable contract fields nullable', () => {
    expectTypeOf<SessionDetail['itinerary']>().toEqualTypeOf<Itinerary | null>()
    expectTypeOf<ItineraryItem['est_cost']>().toEqualTypeOf<{ amount: number; currency: string } | null>()
    expectTypeOf<Stop['lat']>().toEqualTypeOf<number | null>()
    expectTypeOf<Booking['estimate']>().toEqualTypeOf<{ amount: number; currency: string } | null>()
  })
})
