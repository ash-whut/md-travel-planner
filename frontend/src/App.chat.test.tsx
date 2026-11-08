// Step 14 end to end in the UI: App + store + ChatPanel with a fake ApiClient (no network).
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient } from './api/client'
import { sanJoseProfile } from './fixtures'
import { useTripStore } from './store/useTripStore'
import type { SessionDetail, SseEvent } from './types'
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

const reply: SseEvent[] = [
  { event: 'message_start', data: { message_id: 'a1' } },
  { event: 'token', data: { text: 'San Jose ' } },
  { event: 'token', data: { text: 'sounds **great**!' } },
  { event: 'done', data: { message_id: 'a1' } },
]

function makeApi(send: ApiClient['sendMessage']) {
  return { createSession: vi.fn(async () => session), getSession: vi.fn(async () => session), sendMessage: vi.fn(send), generate: vi.fn() }
}

async function typeAndSend(text: string) {
  await screen.findByText('Where to?')
  const input = screen.getByRole('textbox', { name: 'Message' })
  fireEvent.change(input, { target: { value: text } })
  fireEvent.keyDown(input, { key: 'Enter' })
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
})

describe('App chat', () => {
  it('sends a message and shows the streamed reply as markdown', async () => {
    const api = makeApi(async (_id, _c, onEvent) => reply.forEach(onEvent))
    render(<App api={api} />)
    await typeAndSend('San Jose')
    expect(await screen.findByText('great')).toBeTruthy()
    expect(screen.getByText('San Jose')).toBeTruthy()
    expect(api.sendMessage.mock.calls[0].slice(0, 2)).toEqual(['s-1', 'San Jose'])
    expect((screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement).disabled).toBe(false)
  })

  it('disables the input while the reply streams', async () => {
    let finish!: () => void
    const api = makeApi(
      (_id, _c, onEvent) =>
        new Promise<void>((resolve) => {
          onEvent(reply[0])
          finish = () => {
            reply.slice(1).forEach(onEvent)
            resolve()
          }
        }),
    )
    render(<App api={api} />)
    await typeAndSend('San Jose')
    const input = screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement
    await waitFor(() => expect(input.disabled).toBe(true))
    finish()
    await waitFor(() => expect(input.disabled).toBe(false))
  })

  it('shows an error bubble and Retry resends the same message', async () => {
    let calls = 0
    const api = makeApi(async (_id, _c, onEvent) => {
      calls += 1
      if (calls === 1) {
        onEvent({ event: 'message_start', data: { message_id: 'a0' } })
        onEvent({ event: 'error', data: { message: 'The model is busy', retryable: true } })
        return
      }
      reply.forEach(onEvent)
    })
    render(<App api={api} />)
    await typeAndSend('San Jose')
    expect((await screen.findByRole('alert')).textContent).toMatch(/The model is busy/)
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText('great')).toBeTruthy()
    expect(api.sendMessage).toHaveBeenCalledTimes(2)
    expect(api.sendMessage.mock.calls[1][1]).toBe('San Jose')
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getAllByText('San Jose')).toHaveLength(1)
  })
})
