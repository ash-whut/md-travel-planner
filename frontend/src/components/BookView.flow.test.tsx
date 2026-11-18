import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { sanJoseV1, sanJoseV2 } from '@/fixtures'
import type { BookingStatus, Itinerary } from '@/types'
import { BookView } from './BookView'

// Step 43 (docs/spec.md F6): progress count, the approval dialog, Mark booked / Undo, errors.

function withStatuses(base: Itinerary, status: BookingStatus): Itinerary {
  const plan = structuredClone(base)
  for (const b of plan.bookings) b.status = status
  return plan
}

function card(title: string): HTMLElement {
  return screen.getByRole('heading', { level: 3, name: title }).closest('li') as HTMLElement
}

function renderView(itinerary: Itinerary, onSetStatus = vi.fn(), error: string | null = null) {
  render(<BookView itinerary={itinerary} onTagClick={() => {}} onSetStatus={onSetStatus} error={error} />)
  return onSetStatus
}

let openSpy: ReturnType<typeof vi.fn>

beforeEach(() => {
  openSpy = vi.fn()
  vi.stubGlobal('open', openSpy)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BookView progress', () => {
  it('shows "0 of 4 booked" and an empty bar when nothing is booked', () => {
    renderView(sanJoseV1)
    expect(screen.getByText('0 of 4').closest('p')?.textContent).toMatch(/0 of 4\s*booked/)
    const bar = screen.getByRole('progressbar')
    expect(bar.getAttribute('aria-valuenow')).toBe('0')
    expect(bar.getAttribute('aria-valuemax')).toBe('4')
  })

  it('counts booked cards from the itinerary (1 of 4 in v2)', () => {
    renderView(sanJoseV2)
    expect(screen.getByText('1 of 4')).toBeTruthy()
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('1')
  })

  it('shows "4 of 4" when every card is booked, with no Book buttons left', () => {
    renderView(withStatuses(sanJoseV1, 'booked'))
    expect(screen.getByText('4 of 4')).toBeTruthy()
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('4')
    expect(screen.queryByRole('button', { name: /^Book\b/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Mark booked' })).toBeNull()
  })

  it('states that nothing is booked without approval', () => {
    renderView(sanJoseV1)
    expect(screen.getByText(/Nothing is booked without your approval/)).toBeTruthy()
  })
})

describe('BookView cards', () => {
  it('shows "check link" when a booking has no estimate (flights in the MVP)', () => {
    expect(sanJoseV1.bookings.find((b) => b.id === 'bk-flight')!.estimate).toBeNull()
    renderView(sanJoseV1)
    expect(within(card('Flight Booking')).getByText(/Est: check link/)).toBeTruthy()
  })

  it('shows "$300 | 6 hr" for a flight booking with an estimate (real fares, step 49)', () => {
    const plan = structuredClone(sanJoseV1)
    plan.bookings.find((b) => b.id === 'bk-flight')!.estimate = { amount: 300, currency: 'USD' }
    renderView(plan)
    expect(within(card('Flight Booking')).getByText(/Est: \$300 \| 6 hr/)).toBeTruthy()
  })

  it('shows the estimate and the details with the "as of" time for the hotel', () => {
    renderView(sanJoseV1)
    const hotel = card('Hotel Booking')
    expect(within(hotel).getByText(/Est: \$240/)).toBeTruthy()
    expect(within(hotel).getByText(/San Jose Marriott · 2 nights · Mar 5 – Mar 7 · as of /)).toBeTruthy()
  })

  it('does not add an "as of" time when the booking has no price_as_of', () => {
    renderView(sanJoseV1)
    expect(within(card('Flight Booking')).queryByText(/as of/)).toBeNull()
  })
})

describe('BookView approval dialog', () => {
  it('Book opens a dialog; Continue opens the first link in a new tab with noopener/noreferrer', () => {
    const onSetStatus = renderView(sanJoseV1)
    fireEvent.click(within(card('Flight Booking')).getByRole('button', { name: /^Book\b/ }))

    const dialog = screen.getByRole('dialog', { name: 'Book the flight?' })
    expect(openSpy).not.toHaveBeenCalled() // nothing opens before approval
    fireEvent.click(within(dialog).getByRole('button', { name: /^Continue to Google Flights/ }))

    const flight = sanJoseV1.bookings.find((b) => b.id === 'bk-flight')!
    expect(openSpy).toHaveBeenCalledTimes(1)
    const [url, target, features] = openSpy.mock.calls[0]
    expect(url).toBe(flight.links[0].url)
    expect(target).toBe('_blank')
    expect(String(features)).toMatch(/noopener/)
    expect(String(features)).toMatch(/noreferrer/)
    expect(screen.queryByRole('dialog')).toBeNull()
    // Opening the provider does not mark the card booked; the user does that afterwards.
    expect(onSetStatus).not.toHaveBeenCalled()
  })

  it('Cancel closes the dialog without opening anything', () => {
    renderView(sanJoseV1)
    fireEvent.click(within(card('Hotel Booking')).getByRole('button', { name: /^Book\b/ }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(openSpy).not.toHaveBeenCalled()
  })

  it('titles the dialog by kind and offers the other links as safe new-tab anchors', () => {
    renderView(sanJoseV1)
    fireEvent.click(within(card('Hotel Booking')).getByRole('button', { name: /^Book\b/ }))
    const dialog = screen.getByRole('dialog', { name: 'Book the hotel?' })
    expect(within(dialog).getByRole('button', { name: /^Continue to Booking\.com/ })).toBeTruthy()

    const other = within(dialog).getByRole('link', { name: 'Google Hotels' })
    expect(other.getAttribute('href')).toBe('https://www.google.com/travel/hotels?q=San%20Jose%20Marriott%20San%20Jose')
    expect(other.getAttribute('target')).toBe('_blank')
    const rel = other.getAttribute('rel') ?? ''
    expect(rel).toMatch(/noopener/)
    expect(rel).toMatch(/noreferrer/)
  })

  it('names an activity in the dialog title', () => {
    renderView(sanJoseV1)
    fireEvent.click(within(card('Tourist Spot 1 Booking')).getByRole('button', { name: /^Book\b/ }))
    expect(screen.getByRole('dialog', { name: 'Book Tourist Spot 1 Booking?' })).toBeTruthy()
  })
})

describe('BookView Mark booked / Undo', () => {
  it('Mark booked calls onSetStatus with the booking id and "booked"', () => {
    const onSetStatus = renderView(sanJoseV1)
    fireEvent.click(within(card('Hotel Booking')).getByRole('button', { name: 'Mark booked' }))
    expect(onSetStatus).toHaveBeenCalledWith('bk-hotel-D', 'booked')
  })

  it('a booked card shows Booked and Undo, which sets it back to "todo"', () => {
    const onSetStatus = renderView(sanJoseV2)
    const tech = card('Tourist Spot 1 Booking')
    expect(within(tech).getByText('Booked')).toBeTruthy()
    expect(within(tech).queryByRole('button', { name: 'Mark booked' })).toBeNull()
    fireEvent.click(within(tech).getByRole('button', { name: 'Undo' }))
    expect(onSetStatus).toHaveBeenCalledWith('bk-activity-G', 'todo')
  })

  it('shows a save error as an alert', () => {
    renderView(sanJoseV1, vi.fn(), "Couldn't save the booking: Server down")
    expect(screen.getByRole('alert').textContent).toMatch(/Server down/)
  })

  it('shows no alert without an error', () => {
    renderView(sanJoseV1)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
