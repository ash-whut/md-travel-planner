// Step 27 in the UI: clicking a tag chip in chat selects the tag in the store, and the Plan
// flashes that entry. Fake ApiClient; no network.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseV2 } from './fixtures'
import { useTripStore } from './store/useTripStore'
import type { SessionDetail } from './types'
import App from './App'

const session: SessionDetail = {
  id: 's-1',
  title: sanJoseV2.title,
  status: 'planned',
  trip_profile: sanJoseProfile,
  messages: sanJoseMessages,
  itinerary: sanJoseV2,
  created_at: '',
  updated_at: '',
}

function fakeApi(): ApiClient {
  return {
    createSession: vi.fn(async () => session),
    getSession: vi.fn(async () => session),
    sendMessage: vi.fn(),
    generate: vi.fn(),
    patchBooking: vi.fn(),
  }
}

function chatPanel(): HTMLElement {
  return screen.getByRole('heading', { name: 'Chat' }).closest('section') as HTMLElement
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('selectTag (store)', () => {
  it('sets the selected tag and bumps the flash key on every call, even for the same tag', () => {
    const store = useTripStore.getState()
    expect(store.selectedTag).toBeNull()
    store.selectTag('L')
    expect(useTripStore.getState().selectedTag).toBe('L')
    const key = useTripStore.getState().tagFlashKey
    useTripStore.getState().selectTag('L')
    expect(useTripStore.getState().tagFlashKey).toBe(key + 1)
    useTripStore.getState().reset()
    expect(useTripStore.getState().selectedTag).toBeNull()
  })
})

describe('App tag chips in chat', () => {
  it('a chip click sets the selected tag and flashes that entry in the Plan', async () => {
    render(<App api={fakeApi()} />)
    await within(chatPanel()).findAllByRole('button', { name: 'L' })
    expect(document.querySelector('.flash')).toBeNull()

    const before = useTripStore.getState().tagFlashKey
    fireEvent.click(within(chatPanel()).getAllByRole('button', { name: 'L' })[0])

    expect(useTripStore.getState().selectedTag).toBe('L')
    expect(useTripStore.getState().tagFlashKey).toBe(before + 1)
    const flashed = document.querySelectorAll('.flash')
    expect(flashed).toHaveLength(1)
    expect(flashed[0].textContent).toContain('Good Karma Kitchen')
  })

  it('a chip click from the Map tab focuses the pin and keeps the Map open', async () => {
    render(<App api={fakeApi()} />)
    await within(chatPanel()).findAllByRole('button', { name: 'D' })
    fireEvent.click(screen.getByRole('button', { name: 'Map' }))
    expect(screen.getByRole('heading', { level: 2, name: 'Map' })).toBeTruthy()

    fireEvent.click(within(chatPanel()).getAllByRole('button', { name: 'D' })[0])

    expect(useTripStore.getState().selectedTag).toBe('D')
    expect(screen.getByRole('heading', { level: 2, name: 'Map' })).toBeTruthy()
  })
})
