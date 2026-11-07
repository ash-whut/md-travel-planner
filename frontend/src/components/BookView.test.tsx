import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sanJoseV1, sanJoseV2 } from '@/fixtures'
import { BookView } from './BookView'

function cards(): HTMLElement[] {
  return screen.getAllByRole('heading', { level: 3 }).map((h) => h.closest('li') as HTMLElement)
}

describe('BookView', () => {
  it('renders 4 booking cards with their titles', () => {
    render(<BookView itinerary={sanJoseV2} onTagClick={() => {}} />)
    expect(cards()).toHaveLength(4)
    for (const b of sanJoseV2.bookings) expect(screen.getByRole('heading', { name: b.title })).toBeTruthy()
  })

  it('shows the booked count and a Booked label for booked items', () => {
    render(<BookView itinerary={sanJoseV2} onTagClick={() => {}} />)
    const booked = sanJoseV2.bookings.filter((b) => b.status === 'booked').length
    expect(screen.getByText(`${booked} of 4`)).toBeTruthy()
    expect(screen.getAllByText('Booked')).toHaveLength(booked)
    expect(screen.getAllByRole('button', { name: /^Book/ })).toHaveLength(4 - booked)
  })

  it('shows the flight card tags as B → C', () => {
    render(<BookView itinerary={sanJoseV1} onTagClick={() => {}} />)
    const flight = cards().find((c) => c.textContent?.includes('Flight Booking'))!
    const tags = within(flight).getAllByTitle(/^Refer to this as "/).map((b) => b.textContent)
    expect(tags).toEqual(['B', 'C'])
  })

  it('calls onTagClick when a tag on a card is clicked', () => {
    const onTagClick = vi.fn()
    render(<BookView itinerary={sanJoseV2} onTagClick={onTagClick} />)
    fireEvent.click(screen.getByRole('button', { name: 'D' }))
    expect(onTagClick).toHaveBeenCalledWith('D')
  })

  it('opens and cancels the confirm dialog from a Book button', () => {
    render(<BookView itinerary={sanJoseV1} onTagClick={() => {}} />)
    fireEvent.click(screen.getAllByRole('button', { name: /^Book/ })[0])
    expect(screen.getByRole('button', { name: /^Continue to/ })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('button', { name: /^Continue to/ })).toBeNull()
  })
})
