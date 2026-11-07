// ?demo=1 loads the San Jose fixture trip into the store without touching the backend.
// demoParams.ts reads the URL when it loads, so the URL is set in vi.hoisted (before imports).
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.hoisted(() => window.history.replaceState(null, '', '/?demo=1'))

import { sanJoseMessages, sanJoseV2 } from './fixtures'
import { useTripStore } from './store/useTripStore'
import App from './App'

function unusedApi() {
  return {
    createSession: vi.fn(async () => {
      throw new Error('createSession must not be called in demo mode')
    }),
    sendMessage: vi.fn(async () => {
      throw new Error('sendMessage must not be called in demo mode')
    }),
    getSession: vi.fn(async () => {
      throw new Error('getSession must not be called in demo mode')
    }),
  }
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('App with ?demo=1', () => {
  it('shows the full v0 San Jose trip without calling the ApiClient', async () => {
    const api = unusedApi()
    render(<App api={api} />)
    expect(await screen.findByRole('heading', { level: 1, name: sanJoseV2.title })).toBeTruthy()
    expect(api.createSession).not.toHaveBeenCalled()
    expect(api.getSession).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0)
    // Plan: the v2 replacement mark; chat: the fixture conversation with dividers and status lines.
    expect(screen.getAllByText('Updated in v2').length).toBeGreaterThan(0)
    expect(screen.getByText(sanJoseMessages[0].content)).toBeTruthy()
    expect(screen.getByText('Plan updated · v2')).toBeTruthy()
    expect(screen.getByText(/Searching vegan restaurants near downtown/)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows the map and the booking cards of the demo trip', async () => {
    render(<App api={unusedApi()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Map' }))
    expect(await screen.findByTestId('map')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Book' }))
    const main = screen.getByRole('heading', { name: 'Book' }).closest('section')!
    for (const b of sanJoseV2.bookings) {
      expect(within(main).getByRole('heading', { name: b.title })).toBeTruthy()
    }
  })
})
