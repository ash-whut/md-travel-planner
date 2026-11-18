// Step 15: while a reply streams, the Send button becomes Stop; the stopped marker renders.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Message } from '@/types'
import { ChatPanel } from './ChatPanel'

const msg = (id: string, role: Message['role'], content: string): Message => ({
  id,
  role,
  content,
  itinerary_version: null,
  created_at: '',
})

function renderChat(props: { messages?: Message[]; streaming?: boolean; withStop?: boolean } = {}) {
  const onSend = vi.fn()
  const onStop = vi.fn()
  const view = render(
    <ChatPanel
      messages={props.messages ?? []}
      itinerary={null}
      streaming={props.streaming}
      onSend={onSend}
      onStop={props.withStop === false ? undefined : onStop}
      onTagClick={() => {}}
    />,
  )
  const input = screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement
  return { ...view, onSend, onStop, input }
}

describe('ChatPanel Stop button', () => {
  it('shows Stop instead of Send while streaming', () => {
    renderChat({ streaming: true })
    expect(screen.getByRole('button', { name: 'Stop' })).toBeTruthy()
    expect(screen.queryByTitle('Send')).toBeNull()
  })

  it('clicking Stop calls onStop once and sends nothing', () => {
    const { onStop, onSend } = renderChat({ streaming: true })
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(onStop).toHaveBeenCalledTimes(1)
    expect(onSend).not.toHaveBeenCalled()
  })

  it('Stop is enabled while the input is disabled', () => {
    const { input } = renderChat({ streaming: true })
    expect(input.disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Stop' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows Send (no Stop) when not streaming', () => {
    renderChat({ streaming: false })
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
    expect(screen.getByTitle('Send')).toBeTruthy()
  })

  it('after streaming ends the input is enabled and Send is back', () => {
    const view = renderChat({ streaming: true })
    view.rerender(
      <ChatPanel messages={[]} itinerary={null} streaming={false} onSend={view.onSend} onStop={view.onStop} onTagClick={() => {}} />,
    )
    expect(view.input.disabled).toBe(false)
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
    expect(screen.getByTitle('Send')).toBeTruthy()
  })

  it('renders the stopped marker in italics after the partial text', () => {
    renderChat({ messages: [msg('a1', 'assistant', 'Austin is great *(stopped)*')] })
    const marker = screen.getByText('(stopped)')
    expect(marker.tagName).toBe('EM')
    expect(screen.getByText(/Austin is great/)).toBeTruthy()
  })
})
