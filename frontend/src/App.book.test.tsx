import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from './api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseV1 } from './fixtures'
import { useTripStore } from './store/useTripStore'
import type { Booking, Itinerary, SessionDetail } from './types'
import App from './App'

// The Book tab rule (step 43, docs/spec.md F6): Book unlocks only once the plan has bookings.
function apiWith(itinerary: Itinerary, patchBooking: ApiClient['patchBooking'] = async () => {
  throw new Error('patchBooking is not used here')
}) {
  const session: SessionDetail = {
    id: 's-1',
    title: itinerary.title,
    status: 'planned',
    trip_profile: sanJoseProfile,
    messages: sanJoseMessages,
    itinerary,
    created_at: '',
    updated_at: '',
  }
  return {
    createSession: vi.fn(async () => session),
    getSession: vi.fn(async () => session),
    sendMessage: vi.fn(async () => {}),
    generate: vi.fn(async () => {}),
    patchBooking: vi.fn(patchBooking),
  }
}

// The vertical tab (cards on the Book tab also have "Book" buttons, without aria-disabled).
function bookTab(): HTMLElement {
  return screen.getAllByRole('button', { name: 'Book' }).find((b) => b.hasAttribute('aria-disabled'))!
}

function hotelCard(): HTMLElement {
  return screen.getByRole('heading', { level: 3, name: 'Hotel Booking' }).closest('li') as HTMLElement
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('Book tab enable rule', () => {
  it('locks Book when the plan has no bookings', async () => {
    render(<App api={apiWith({ ...structuredClone(sanJoseV1), bookings: [] })} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })

    const book = bookTab()
    expect(book.getAttribute('aria-disabled')).toBe('true')
    expect(book.getAttribute('title')).toBe('Nothing to book yet')
    fireEvent.click(book)
    expect(screen.getByRole('heading', { level: 2, name: 'Plan' })).toBeTruthy()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('unlocks Book once the plan has bookings and shows the progress', async () => {
    render(<App api={apiWith(structuredClone(sanJoseV1))} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })

    const book = bookTab()
    expect(book.getAttribute('aria-disabled')).toBe('false')
    expect(book.getAttribute('title')).toBeNull()
    fireEvent.click(book)
    expect(screen.getByRole('heading', { level: 2, name: 'Book' })).toBeTruthy()
    expect(screen.getByText('0 of 4')).toBeTruthy()
  })
})

describe('Book tab Mark booked', () => {
  it('saves through api.patchBooking and updates the progress', async () => {
    const api = apiWith(structuredClone(sanJoseV1), async (_s, id) => ({
      ...(sanJoseV1.bookings.find((b) => b.id === id) as Booking),
      status: 'booked',
    }))
    render(<App api={api} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
    fireEvent.click(bookTab())

    fireEvent.click(within(hotelCard()).getByRole('button', { name: 'Mark booked' }))
    expect(screen.getByText('1 of 4')).toBeTruthy() // optimistic
    expect(api.patchBooking).toHaveBeenCalledWith('s-1', 'bk-hotel-D', 'booked')
    await waitFor(() => expect(within(hotelCard()).getByText('Booked')).toBeTruthy())
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('reverts the card and shows an error when the save fails', async () => {
    const api = apiWith(structuredClone(sanJoseV1), async () => {
      throw new ApiError(500, 'Server down')
    })
    render(<App api={api} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV1.title })
    fireEvent.click(bookTab())

    fireEvent.click(within(hotelCard()).getByRole('button', { name: 'Mark booked' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Server down/)
    expect(screen.getByText('0 of 4')).toBeTruthy()
    expect(within(hotelCard()).getByRole('button', { name: 'Mark booked' })).toBeTruthy()
  })
})
