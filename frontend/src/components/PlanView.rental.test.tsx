// Step 51: a vacation rental shows a "Vacation rental" label on its hotel card (Plan) and its
// Book card; a hotel shows none. The Book dialog asks "Book the rental?" for a rental.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { sanJoseProfile, sanJoseV1 } from '@/fixtures'
import type { Booking, Itinerary, LodgingType } from '@/types'
import { BookView } from './BookView'
import { PlanView } from './PlanView'

const LABEL = 'Vacation rental'

// sanJoseV1 with its one lodging (stop D, booking bk-hotel-D) set to the given type.
function withLodging(type: LodgingType, title = type === 'vacation_rental' ? 'Rental Booking' : 'Hotel Booking'): Itinerary {
  return {
    ...sanJoseV1,
    lodging: sanJoseV1.lodging.map((l) => ({ ...l, type })),
    bookings: sanJoseV1.bookings.map((b): Booking => (b.id === 'bk-hotel-D' ? { ...b, title } : b)),
  }
}

function renderPlan(itinerary: Itinerary) {
  return render(<PlanView itinerary={itinerary} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
}

function renderBook(itinerary: Itinerary) {
  return render(<BookView itinerary={itinerary} onTagClick={() => {}} onSetStatus={() => {}} />)
}

// The Plan entry of the lodging item (stop D).
function lodgingEntry(): HTMLElement {
  return screen.getByText('Check in — 2 nights downtown.').closest('li') as HTMLElement
}

// The Book card of the lodging booking.
function lodgingCard(title: string): HTMLElement {
  return screen.getByRole('heading', { level: 3, name: title }).closest('li') as HTMLElement
}

describe('PlanView vacation rental label', () => {
  it('shows "Vacation rental" on the lodging card of a rental', () => {
    renderPlan(withLodging('vacation_rental'))
    expect(within(lodgingEntry()).getByText(LABEL)).toBeTruthy()
    expect(screen.getAllByText(LABEL)).toHaveLength(1) // only on the lodging entry
  })

  it('shows no label for a hotel', () => {
    renderPlan(withLodging('hotel'))
    expect(lodgingEntry()).toBeTruthy()
    expect(screen.queryByText(LABEL)).toBeNull()
  })
})

describe('BookView vacation rental label', () => {
  it('shows "Vacation rental" on the rental booking card only', () => {
    renderBook(withLodging('vacation_rental'))
    expect(within(lodgingCard('Rental Booking')).getByText(LABEL)).toBeTruthy()
    expect(screen.getAllByText(LABEL)).toHaveLength(1)
    const flight = lodgingCard('Flight Booking')
    expect(within(flight).queryByText(LABEL)).toBeNull()
  })

  it('shows no label on a hotel booking card', () => {
    renderBook(withLodging('hotel'))
    expect(lodgingCard('Hotel Booking')).toBeTruthy()
    expect(screen.queryByText(LABEL)).toBeNull()
  })

  it('asks "Book the rental?" for a rental and "Book the hotel?" for a hotel', () => {
    const { unmount } = renderBook(withLodging('vacation_rental'))
    fireEvent.click(within(lodgingCard('Rental Booking')).getByRole('button', { name: /^Book/ }))
    expect(screen.getByRole('dialog', { name: 'Book the rental?' })).toBeTruthy()
    unmount()

    renderBook(withLodging('hotel'))
    fireEvent.click(within(lodgingCard('Hotel Booking')).getByRole('button', { name: /^Book/ }))
    expect(screen.getByRole('dialog', { name: 'Book the hotel?' })).toBeTruthy()
  })
})
