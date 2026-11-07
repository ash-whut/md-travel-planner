// Step 15 end to end in the UI: App + store + ChatPanel. Stop mid-reply aborts the stream,
// re-enables the input and shows the partial reply with "(stopped)". Fake ApiClient; no network.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseProfile } from './fixtures'
import { useTripStore } from './store/useTripStore'
import type { SessionDetail } from './types'
import App from './App'

const session: SessionDetail = {
  id: 's-1',
  title: 'New trip',
  status: 'intake',
  trip_profile: sanJoseProfile,
  messages: [{ id: 'g', role: 'assistant', content: 'Where to?', itinerary_version: null, created_at: '' }],
  itinerary: null,
  created_at: '',
  updated_at: '',
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('App Stop', () => {
  it('Stop mid-reply aborts the stream, re-enables the input and shows the marker', async () => {
    let signal: AbortSignal | undefined
    const send: ApiClient['sendMessage'] = (_id, _c, onEvent, s) =>
      new Promise<void>((resolve) => {
        signal = s
        onEvent({ event: 'message_start', data: { message_id: 'a1' } })
        onEvent({ event: 'token', data: { text: 'San Jose has ' } })
        s?.addEventListener('abort', () => resolve())
      })
    const api = { createSession: vi.fn(async () => session), getSession: vi.fn(async () => session), sendMessage: vi.fn(send) }
    render(<App api={api} />)

    await screen.findByText('Where to?')
    const input = screen.getByPlaceholderText(/Edit by letter/) as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: 'San Jose' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    const stop = await screen.findByRole('button', { name: 'Stop' })
    expect(input.disabled).toBe(true)
    expect(screen.getByText(/San Jose has/)).toBeTruthy()

    fireEvent.click(stop)

    expect(signal?.aborted).toBe(true)
    await waitFor(() => expect(input.disabled).toBe(false))
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
    expect(screen.getByTitle('Send')).toBeTruthy()
    expect(screen.getByText('(stopped)').tagName).toBe('EM')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
