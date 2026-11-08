// Step 31: chat status lines from SSE `status` events: spinner while running, then ✓ or ✕.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { StatusLine } from '@/store/useTripStore'
import type { Message } from '@/types'
import { ChatPanel } from './ChatPanel'

const msg = (id: string, role: Message['role'], content: string): Message => ({
  id,
  role,
  content,
  itinerary_version: null,
  created_at: '',
})

const weather = 'Checking weather for San Jose · Mar 5–7'
const messages = [msg('u1', 'user', 'Plan San Jose'), msg('a1', 'assistant', '')]

function renderStatus(lines: StatusLine[], streamingMessageId: string | null) {
  return render(
    <ChatPanel
      messages={messages}
      itinerary={null}
      statusLines={{ a1: lines }}
      streaming={streamingMessageId !== null}
      streamingMessageId={streamingMessageId}
      onTagClick={() => {}}
    />,
  )
}

// The <p> holding a status label, and its data-state.
function line(label: string): HTMLElement {
  const el = screen.getByText(label, { exact: false }).closest('[data-state]')
  if (!el) throw new Error(`no status line for ${label}`)
  return el as HTMLElement
}

describe('ChatPanel status lines', () => {
  it('shows a spinner while a step is running', () => {
    renderStatus([{ label: weather, state: 'start' }], 'a1')
    expect(line(weather).dataset.state).toBe('start')
    expect(screen.getByLabelText('In progress')).toBeTruthy()
    expect(screen.queryByLabelText('Done')).toBeNull()
  })

  it('turns the spinner into a check mark when the step ends', () => {
    const view = renderStatus([{ label: weather, state: 'start' }], 'a1')
    view.rerender(
      <ChatPanel
        messages={messages}
        itinerary={null}
        statusLines={{ a1: [{ label: weather, state: 'end' }] }}
        streaming
        streamingMessageId="a1"
        onTagClick={() => {}}
      />,
    )
    expect(line(weather).dataset.state).toBe('end')
    expect(screen.getByLabelText('Done')).toBeTruthy()
    expect(screen.queryByLabelText('In progress')).toBeNull()
  })

  it('shows a cross when the step fails', () => {
    renderStatus([{ label: weather, state: 'error' }], 'a1')
    expect(line(weather).dataset.state).toBe('error')
    expect(screen.getByLabelText('Failed')).toBeTruthy()
  })

  it('shows each label once, above its message, with its own state', () => {
    renderStatus(
      [
        { label: weather, state: 'end' },
        { label: 'Drafting your plan…', state: 'start' },
      ],
      'a1',
    )
    expect(screen.getAllByText(weather, { exact: false })).toHaveLength(1)
    expect(line(weather).dataset.state).toBe('end')
    expect(line('Drafting your plan…').dataset.state).toBe('start')
  })

  it('a step still spinning after the reply stopped streaming shows as failed', () => {
    renderStatus([{ label: weather, state: 'start' }], null)
    expect(line(weather).dataset.state).toBe('error')
    expect(screen.getByLabelText('Failed')).toBeTruthy()
    expect(screen.queryByLabelText('In progress')).toBeNull()
  })

  it('finished steps keep their check mark after streaming ends', () => {
    renderStatus([{ label: weather, state: 'end' }], null)
    expect(line(weather).dataset.state).toBe('end')
  })
})
