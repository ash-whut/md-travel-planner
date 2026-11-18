// Global test setup. Leaflet needs a real browser layout, so tests swap react-leaflet for
// plain placeholders: the map is a <div>, markers/popups just render their children.
import { createElement, type ReactNode } from 'react'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => cleanup())

// jsdom has no layout, so scrolling is a no-op (the chat scrolls to its newest message).
Element.prototype.scrollIntoView = () => {}

// jsdom has no ResizeObserver either (the map watches its container to keep tiles sized).
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.mock('react-leaflet', () => {
  const passthrough = ({ children }: { children?: ReactNode }) => children ?? null
  const fakeMap = {
    getContainer: () => document.createElement('div'),
    invalidateSize: () => {},
    flyTo: () => {},
    fitBounds: () => {},
    setView: () => {},
  }
  return {
    MapContainer: ({ children }: { children?: ReactNode }) =>
      createElement('div', { 'data-testid': 'map' }, children),
    TileLayer: () => null,
    Marker: passthrough,
    Popup: passthrough,
    Polyline: () => null,
    useMap: () => fakeMap,
  }
})
