import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseV2 } from './fixtures'
import { useTripStore } from './store/useTripStore'
import type { Itinerary, SessionDetail } from './types'
import App from './App'

// The Map tab rule (step 36): Map unlocks only once a stop has coordinates.
function apiWith(itinerary: Itinerary): ApiClient {
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
    createSession: async () => session,
    getSession: async () => session,
    sendMessage: async () => {},
    generate: async () => {},
    patchBooking: async () => { throw new Error('patchBooking is not used here') },
  }
}

function noCoords(): Itinerary {
  const it = structuredClone(sanJoseV2)
  for (const s of it.stops) Object.assign(s, { lat: null, lng: null })
  return it
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('Map tab enable rule', () => {
  it('locks Map when the plan has no stop with coordinates, but unlocks Book', async () => {
    render(<App api={apiWith(noCoords())} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV2.title })

    const map = screen.getByRole('button', { name: 'Map' })
    expect(map.getAttribute('aria-disabled')).toBe('true')
    expect(map.getAttribute('title')).toBe('No stops with coordinates yet')
    fireEvent.click(map)
    expect(screen.getByRole('heading', { name: 'Plan' })).toBeTruthy()
    expect(screen.queryByTestId('map')).toBeNull()

    const book = screen.getByRole('button', { name: 'Book' })
    expect(book.getAttribute('aria-disabled')).toBe('false')
    expect(book.getAttribute('title')).toBeNull()
  })

  it('unlocks Map once a single stop has coordinates', async () => {
    const it2 = noCoords()
    Object.assign(it2.stops.find((s) => s.tag === 'K')!, { lat: 37.3405, lng: -121.899 })
    render(<App api={apiWith(it2)} />)
    await screen.findByRole('heading', { level: 1, name: sanJoseV2.title })

    const map = screen.getByRole('button', { name: 'Map' })
    expect(map.getAttribute('aria-disabled')).toBe('false')
    expect(map.getAttribute('title')).toBeNull()
    fireEvent.click(map)
    expect(screen.getByRole('heading', { name: 'Map' })).toBeTruthy()
    expect(await screen.findByTestId('map')).toBeTruthy()
  })
})
