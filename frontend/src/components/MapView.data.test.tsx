import { createElement, type ReactNode } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sanJoseV2 } from '@/fixtures'
import { dayColor } from '@/lib/tags'
import type { Itinerary } from '@/types'
import { MapView } from './MapView'

// A react-leaflet mock that records what MapView draws: pins, day lines, attribution and map calls.
const drawn = vi.hoisted(() => ({
  markers: [] as { position: [number, number]; html: string }[],
  polylines: [] as { positions: [number, number][]; color: string; dashArray?: string }[],
  attribution: '',
  fitBounds: [] as unknown[],
  flyTo: [] as unknown[],
}))

vi.mock('react-leaflet', () => {
  const fakeMap = {
    getContainer: () => document.createElement('div'),
    invalidateSize: () => {},
    flyTo: (...args: unknown[]) => drawn.flyTo.push(args),
    fitBounds: (...args: unknown[]) => drawn.fitBounds.push(args),
    setView: () => {},
  }
  return {
    MapContainer: ({ children }: { children?: ReactNode }) => createElement('div', { 'data-testid': 'map' }, children),
    TileLayer: ({ attribution }: { attribution: string }) => {
      drawn.attribution = attribution
      return null
    },
    Marker: ({ position, icon, children }: { position: [number, number]; icon: { options: { html: string } }; children?: ReactNode }) => {
      drawn.markers.push({ position, html: String(icon.options.html) })
      return createElement('div', { 'data-testid': 'pin' }, children)
    },
    Popup: ({ children }: { children?: ReactNode }) => children ?? null,
    Polyline: ({ positions, pathOptions }: { positions: [number, number][]; pathOptions: { color: string; dashArray?: string } }) => {
      drawn.polylines.push({ positions, color: pathOptions.color, dashArray: pathOptions.dashArray })
      return null
    },
    useMap: () => fakeMap,
  }
})

function resetDrawn() {
  drawn.markers.length = 0
  drawn.polylines.length = 0
  drawn.fitBounds.length = 0
  drawn.flyTo.length = 0
  drawn.attribution = ''
}

beforeEach(resetDrawn)

function pinTexts(): string[] {
  return screen.getAllByTestId('pin').map((p) => p.querySelector('b')?.textContent ?? '')
}

function stopsPanel(): HTMLElement {
  return screen.getByText('Stops').parentElement as HTMLElement
}

function renderMap(itinerary: Itinerary = sanJoseV2, selectedTag: string | null = null) {
  return render(<MapView itinerary={itinerary} selectedTag={selectedTag} onTagClick={() => {}} />)
}

describe('MapView from the itinerary', () => {
  it('draws one pin per stop with coordinates, none for off-map stops', () => {
    renderMap()
    expect(pinTexts()).toEqual([
      'C · San Jose Airport',
      'D · San Jose Marriott',
      'E · San Pedro Square',
      'L · Good Karma Kitchen',
      'G · The Tech Interactive',
      'H · Winchester Mystery House',
      'I · Santana Row',
      'J · Japantown',
      'K · Guadalupe River Park',
    ])
    expect(screen.getAllByTestId('pin')[0].textContent).toContain('Day 1 · 1:30 PM')
  })

  it('shows only the chosen day: pins, the Stops list, and its one dashed line', () => {
    renderMap()
    fireEvent.click(screen.getByRole('button', { name: 'Day 3' }))
    expect(pinTexts()).toEqual(['J · Japantown', 'K · Guadalupe River Park', 'C · San Jose Airport'])
    expect(screen.getAllByTestId('pin')[2].textContent).toContain('Day 3 · 2:40 PM')
    const rows = within(stopsPanel()).getAllByRole('listitem').map((li) => li.textContent)
    expect(rows).toEqual(['JJapantown', 'KGuadalupe River Park', 'CSan Jose Airport'])

    resetDrawn()
    fireEvent.click(screen.getByRole('button', { name: 'Day 2' }))
    expect(drawn.polylines).toHaveLength(1)
    expect(drawn.polylines[0].color).toBe(dayColor(2))
    expect(drawn.polylines[0].dashArray).toBeTruthy()
    expect(drawn.polylines[0].positions).toHaveLength(4)
  })

  it('draws a dashed line per day in that day colour for All days', () => {
    renderMap()
    const last = drawn.polylines.slice(-3)
    expect(last.map((p) => p.color)).toEqual([dayColor(1), dayColor(2), dayColor(3)])
    expect(last.map((p) => p.positions.length)).toEqual([3, 4, 3])
  })

  it('colours each pin by the day its tag first appears', () => {
    renderMap()
    const byTag = (tag: string) => drawn.markers.find((m) => m.html.includes(`>${tag}</div>`))
    expect(byTag('C')?.html).toContain(dayColor(1)) // day 1 and day 3: day 1 wins
    expect(byTag('L')?.html).toContain(dayColor(2))
    expect(byTag('K')?.html).toContain(dayColor(3))
  })

  it('shows the OpenStreetMap attribution', () => {
    renderMap()
    expect(drawn.attribution).toMatch(/OpenStreetMap/)
  })

  it('lists every off-map stop, including a repeated one only once', () => {
    const it2 = structuredClone(sanJoseV2)
    const c = it2.stops.find((s) => s.tag === 'C')!
    c.lat = null
    c.lng = null
    renderMap(it2)
    expect(within(stopsPanel()).getByText('Off map: A, B, C')).toBeTruthy()
    expect(pinTexts().some((t) => t.startsWith('C ·'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Day 3' }))
    expect(within(stopsPanel()).getByText('Off map: C')).toBeTruthy()
  })

  it('shows an empty Stops list and no pins when no stop on the day has coordinates', () => {
    const it2 = structuredClone(sanJoseV2)
    for (const s of it2.stops) if (['C', 'D', 'E'].includes(s.tag)) Object.assign(s, { lat: null, lng: null })
    renderMap(it2)
    fireEvent.click(screen.getByRole('button', { name: 'Day 1' }))
    expect(screen.queryAllByTestId('pin')).toHaveLength(0)
    expect(within(stopsPanel()).queryAllByRole('listitem')).toHaveLength(0)
    expect(within(stopsPanel()).getByText('Off map: A, B, C, D, E')).toBeTruthy()
  })

  it('fits the map to the shown pins, and flies to the selected one', () => {
    renderMap()
    expect(drawn.fitBounds.at(-1)).toEqual([
      [
        [37.3184, -121.9511],
        [37.3639, -121.888],
      ],
      expect.anything(),
    ])
    expect(drawn.flyTo).toHaveLength(0)

    resetDrawn()
    renderMap(sanJoseV2, 'H')
    expect(drawn.flyTo.at(-1)).toEqual([[37.3184, -121.9511], 15, expect.anything()])
  })

  it('shows the day and time on the selected Stops row only', () => {
    renderMap(sanJoseV2, 'G')
    const row = within(stopsPanel()).getByRole('button', { name: /The Tech Interactive/ })
    expect(row.textContent).toContain('Day 2 · 1:00 PM')
    expect(within(stopsPanel()).getByRole('button', { name: /Japantown/ }).textContent).not.toContain('Day')
  })
})
