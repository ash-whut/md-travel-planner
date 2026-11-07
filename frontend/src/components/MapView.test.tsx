import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sanJoseV2 } from '@/fixtures'
import { MapView } from './MapView'

// The "Stops" side panel (react-leaflet is mocked in src/test/setup.ts).
function stopsPanel(): HTMLElement {
  return screen.getByText('Stops').parentElement as HTMLElement
}

function listedTags(): string[] {
  return within(stopsPanel())
    .getAllByRole('listitem')
    .map((li) => within(li).getByTitle(/^Refer to this as "/).textContent ?? '')
}

describe('MapView', () => {
  it('lists every stop with coordinates once, in visit order', () => {
    render(<MapView itinerary={sanJoseV2} selectedTag={null} onTagClick={() => {}} />)
    expect(listedTags()).toEqual(['C', 'D', 'E', 'L', 'G', 'H', 'I', 'J', 'K'])
    expect(within(stopsPanel()).getByText('Good Karma Kitchen')).toBeTruthy()
  })

  it('names the stops without coordinates as off map', () => {
    render(<MapView itinerary={sanJoseV2} selectedTag={null} onTagClick={() => {}} />)
    expect(within(stopsPanel()).getByText('Off map: A, B')).toBeTruthy()
    expect(listedTags()).not.toContain('A')
    expect(listedTags()).not.toContain('B')
  })

  it('filters stops and off-map stops by day', () => {
    render(<MapView itinerary={sanJoseV2} selectedTag={null} onTagClick={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Day 2' }))
    expect(listedTags()).toEqual(['L', 'G', 'H', 'I'])
    expect(within(stopsPanel()).queryByText(/^Off map/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Day 1' }))
    expect(within(stopsPanel()).getByText('Off map: A, B')).toBeTruthy()
  })

  it('calls onTagClick when a listed stop is clicked', () => {
    const onTagClick = vi.fn()
    render(<MapView itinerary={sanJoseV2} selectedTag={null} onTagClick={onTagClick} />)
    fireEvent.click(within(stopsPanel()).getByRole('button', { name: /Good Karma Kitchen/ }))
    expect(onTagClick).toHaveBeenCalledWith('L')
  })
})
