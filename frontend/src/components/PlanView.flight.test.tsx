// Step 49: flight fare display in PlanView and BookView (real fares from SerpApi Google Flights).
// A flight item with cost_source: "tool" shows the grounded fare; without one it shows "check link".
// The BookView flight booking shows the fare when available.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { sanJoseProfile, sanJoseV1 } from '@/fixtures'
import type { Booking, Itinerary, ItineraryItem, Stop } from '@/types'
import { BookView } from './BookView'
import { PlanView } from './PlanView'

function stop(tag: string, name: string, kind: Stop['kind']): Stop {
  return { tag, name, kind, address: null, lat: 37.3, lng: -121.9, place_id: null, rating: null, map_url: null }
}

function flightItem(over: Partial<ItineraryItem> = {}): ItineraryItem {
  return {
    id: 'd1-i1',
    kind: 'flight',
    stop_tag: 'B',
    description: 'Board your flight to San Jose',
    start_time: '06:15',
    duration_min: 210,
    nights: null,
    est_cost: null,
    cost_source: null,
    booking_required: true,
    booking_id: 'bk-flight',
    why: null,
    source: null,
    transit_from_previous: null,
    updated_in_version: null,
    ...over,
  }
}

function itinerary(items: ItineraryItem[], bookings: Booking[] = []): Itinerary {
  return {
    ...sanJoseV1,
    stops: [
      stop('A', 'College Station', 'home'),
      stop('B', 'George Bush Intercontinental Airport', 'airport'),
      stop('C', 'San Jose Mineta International Airport', 'airport'),
    ],
    days: [{ ...sanJoseV1.days[0], items }],
    bookings,
  }
}

const flightBooking = (over: Partial<Booking> = {}): Booking => ({
  id: 'bk-flight',
  kind: 'flight',
  tags: ['B', 'C'],
  title: 'Flight Booking',
  details: 'George Bush Intercontinental Airport → San Jose round trip · Mar 5 – Mar 7',
  estimate: null,
  price_as_of: null,
  links: [{ label: 'Google Flights', url: 'https://www.google.com/travel/flights' }],
  status: 'todo',
  ...over,
})

describe('PlanView flight item — no fare (link-only)', () => {
  it('shows "check link" when est_cost is null', () => {
    const { container } = render(
      <PlanView
        itinerary={itinerary([flightItem()])}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(container.textContent).toContain('Est: check link')
  })

  it('does not show "real fare" badge when no tool fare', () => {
    const { container } = render(
      <PlanView
        itinerary={itinerary([flightItem()])}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(container.textContent).not.toContain('real fare')
  })
})

describe('PlanView flight item — real fare from tool', () => {
  it('shows the grounded fare amount', () => {
    const { container } = render(
      <PlanView
        itinerary={itinerary([flightItem({ est_cost: { amount: 189, currency: 'USD' }, cost_source: 'tool' })])}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(container.textContent).toContain('Est: $189')
  })

  it('shows "real fare" badge when cost_source is tool', () => {
    const { container } = render(
      <PlanView
        itinerary={itinerary([flightItem({ est_cost: { amount: 189, currency: 'USD' }, cost_source: 'tool' })])}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(container.textContent).toContain('real fare')
  })

  it('shows the duration in the length field', () => {
    const { container } = render(
      <PlanView
        itinerary={itinerary([flightItem({ est_cost: { amount: 189, currency: 'USD' }, cost_source: 'tool', duration_min: 210 })])}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(container.textContent).toContain('3.5 hr')
  })

  it('shows the source in "Why this?" when it names the tool', () => {
    const src = 'SerpApi Google Flights · as of Nov 1, 6:04 PM UTC'
    render(
      <PlanView
        itinerary={itinerary([flightItem({ est_cost: { amount: 189, currency: 'USD' }, cost_source: 'tool', source: src, why: 'Best value' })])}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    const li = screen.getByText('Board your flight to San Jose').closest('li') as HTMLElement
    const btn = within(li).getByRole('button', { name: /Why this\?/ })
    fireEvent.click(btn) // wrapped in act, so the toggle re-renders before the assertion
    expect(within(li).getByText(`Source: ${src}`)).toBeTruthy()
  })
})

describe('BookView flight booking — no fare', () => {
  it('shows "check link" in the estimate', () => {
    render(
      <BookView
        itinerary={itinerary([flightItem()], [flightBooking()])}
        onTagClick={() => {}}
        onSetStatus={() => {}}
      />,
    )
    expect(screen.getByText(/Est:/).textContent).toContain('check link')
  })
})

describe('BookView flight booking — real fare', () => {
  it('shows the fare amount in the booking card', () => {
    render(
      <BookView
        itinerary={itinerary(
          [flightItem({ est_cost: { amount: 189, currency: 'USD' }, cost_source: 'tool', duration_min: 210 })],
          [flightBooking({ estimate: { amount: 189, currency: 'USD' } })],
        )}
        onTagClick={() => {}}
        onSetStatus={() => {}}
      />,
    )
    expect(screen.getByText(/Est:/).textContent).toContain('$189')
  })

  it('shows the duration alongside the fare when duration_min is set', () => {
    render(
      <BookView
        itinerary={itinerary(
          [flightItem({ est_cost: { amount: 189, currency: 'USD' }, cost_source: 'tool', duration_min: 210 })],
          [flightBooking({ estimate: { amount: 189, currency: 'USD' } })],
        )}
        onTagClick={() => {}}
        onSetStatus={() => {}}
      />,
    )
    expect(screen.getByText(/Est:/).textContent).toContain('3.5 hr')
  })
})

describe('travel_mode in profile chips', () => {
  it('shows ✈️ Flying chip when travel_mode is flight', () => {
    const profileWithFlight = { ...sanJoseProfile, travel_mode: 'flight' as const }
    render(
      <PlanView
        itinerary={sanJoseV1}
        profile={profileWithFlight}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(screen.getAllByText(/✈️ Flying/).length).toBeGreaterThan(0)
  })

  it('shows 🚗 Driving chip when travel_mode is drive', () => {
    const profileWithDrive = { ...sanJoseProfile, travel_mode: 'drive' as const }
    render(
      <PlanView
        itinerary={sanJoseV1}
        profile={profileWithDrive}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(screen.getAllByText(/🚗 Driving/).length).toBeGreaterThan(0)
  })

  it('shows no travel_mode chip when travel_mode is null', () => {
    const profileNoMode = { ...sanJoseProfile, travel_mode: null }
    render(
      <PlanView
        itinerary={sanJoseV1}
        profile={profileNoMode}
        selectedTag={null}
        onTagClick={() => {}}
      />,
    )
    expect(screen.queryByText(/✈️ Flying/)).toBeNull()
    expect(screen.queryByText(/🚗 Driving/)).toBeNull()
  })
})
