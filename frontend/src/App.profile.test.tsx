// Step 17 "Done when": the empty-state chips fill in as `profile` events arrive during a chat
// turn (the chat-header stepper was removed, D22). Fake ApiClient, no network.
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseProfile } from './fixtures'
import { useTripStore } from './store/useTripStore'
import type { SessionDetail, SseEvent, TripProfile } from './types'
import App from './App'

const emptyProfile: TripProfile = {
  cities: [],
  vibe: null,
  start_date: null,
  end_date: null,
  duration_days: null,
  rough_timing: null,
  origin: null,
  travelers: null,
  budget_level: null,
  interests: [],
  dietary: null,
  pace: null,
  transport: null,
  notes: null,
  missing_required: ['destination', 'dates', 'origin', 'travelers', 'interests'],
}

const session: SessionDetail = {
  id: 's-1',
  title: 'New trip',
  status: 'intake',
  trip_profile: emptyProfile,
  messages: [{ id: 'g', role: 'assistant', content: 'Where to?', itinerary_version: null, created_at: '' }],
  itinerary: null,
  created_at: '',
  updated_at: '',
}

function turn(profile: TripProfile): SseEvent[] {
  return [
    { event: 'message_start', data: { message_id: 'a1' } },
    { event: 'profile', data: profile },
    { event: 'token', data: { text: 'Noted!' } },
    { event: 'done', data: { message_id: 'a1' } },
  ]
}

async function send(api: ApiClient, text: string) {
  render(<App api={api} />)
  await screen.findByText('Where to?')
  const input = screen.getByRole('textbox', { name: 'Message' })
  fireEvent.change(input, { target: { value: text } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('App profile progress', () => {
  it('starts with muted chips in the empty Plan state', async () => {
    const api = { createSession: vi.fn(async () => session), getSession: vi.fn(async () => session), sendMessage: vi.fn(), generate: vi.fn() }
    render(<App api={api} />)
    await screen.findByText('Where to?')
    expect(screen.getAllByTitle(/Not given yet/).length).toBe(5)
  })

  it('fills the chips after a profile event', async () => {
    const api = {
      createSession: vi.fn(async () => session),
      getSession: vi.fn(async () => session),
      sendMessage: vi.fn<ApiClient['sendMessage']>(async (_id, _c, onEvent) => turn(sanJoseProfile).forEach(onEvent)),
      generate: vi.fn(),
    }
    await send(api, 'San Jose, first weekend of March, from College Station, solo, tech and food')
    expect(await screen.findByText('📍 San Jose, CA')).toBeTruthy()
    expect(screen.queryByTitle(/Not given yet/)).toBeNull()
  })
})
