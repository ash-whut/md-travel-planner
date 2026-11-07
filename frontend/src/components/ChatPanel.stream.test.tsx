// Step 14: ChatPanel sending, streaming state, markdown bubbles and inline errors with Retry.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { StoreError } from '@/store/useTripStore'
import type { Message } from '@/types'
import { ChatPanel } from './ChatPanel'

const msg = (id: string, role: Message['role'], content: string): Message => ({
  id,
  role,
  content,
  itinerary_version: null,
  created_at: '',
})

function renderChat(
  props: { messages?: Message[]; streaming?: boolean; streamingMessageId?: string; error?: StoreError | null } = {},
) {
  const onSend = vi.fn()
  const onRetry = vi.fn()
  const view = render(
    <ChatPanel
      messages={props.messages ?? []}
      itinerary={null}
      streaming={props.streaming}
      streamingMessageId={props.streamingMessageId}
      error={props.error}
      onSend={onSend}
      onRetry={onRetry}
      onTagClick={() => {}}
    />,
  )
  const input = screen.getByPlaceholderText(/Edit by letter/) as HTMLTextAreaElement
  const sendButton = screen.getByTitle('Send') as HTMLButtonElement
  return { ...view, onSend, onRetry, input, sendButton }
}

describe('ChatPanel sending', () => {
  it('Enter sends the trimmed text and clears the input', () => {
    const { input, onSend } = renderChat()
    fireEvent.change(input, { target: { value: '  Plan San Jose  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSend).toHaveBeenCalledWith('Plan San Jose')
    expect(input.value).toBe('')
  })

  it('Shift+Enter does not send', () => {
    const { input, onSend } = renderChat()
    fireEvent.change(input, { target: { value: 'line one' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()
    expect(input.value).toBe('line one')
  })

  it('the Send button sends; empty or blank text is not sent', () => {
    const { input, sendButton, onSend } = renderChat()
    expect(sendButton.disabled).toBe(true)
    fireEvent.change(input, { target: { value: '   ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSend).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: 'Austin' } })
    fireEvent.click(sendButton)
    expect(onSend).toHaveBeenCalledWith('Austin')
  })
})

describe('ChatPanel while streaming', () => {
  it('disables the input and the Send button', () => {
    const { input, sendButton } = renderChat({ streaming: true })
    expect(input.disabled).toBe(true)
    expect(sendButton.disabled).toBe(true)
  })

  it('does not send on Enter while streaming', () => {
    const { input, onSend, rerender } = renderChat()
    fireEvent.change(input, { target: { value: 'hello' } })
    rerender(<ChatPanel messages={[]} itinerary={null} streaming onSend={onSend} onTagClick={() => {}} />)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSend).not.toHaveBeenCalled()
  })

  it('re-enables the input when streaming ends', () => {
    const { input, onSend, rerender } = renderChat({ streaming: true })
    rerender(<ChatPanel messages={[]} itinerary={null} streaming={false} onSend={onSend} onTagClick={() => {}} />)
    expect(input.disabled).toBe(false)
  })

  it('shows a typing placeholder for an empty streaming assistant message', () => {
    renderChat({
      messages: [msg('u1', 'user', 'hi'), msg('a1', 'assistant', '')],
      streaming: true,
      streamingMessageId: 'a1',
    })
    expect(screen.getByLabelText('Assistant is typing')).toBeTruthy()
  })

  it('shows no typing placeholder for an empty assistant message that is not streaming', () => {
    renderChat({ messages: [msg('u1', 'user', 'hi'), msg('a1', 'assistant', '')] })
    expect(screen.queryByLabelText('Assistant is typing')).toBeNull()
  })
})

describe('ChatPanel bubbles', () => {
  it('renders assistant text as markdown', () => {
    renderChat({ messages: [msg('a1', 'assistant', 'Try **tacos** and\n\n- a park\n- a museum')] })
    expect(screen.getByText('tacos').tagName).toBe('STRONG')
    expect(screen.getByText('a park').tagName).toBe('LI')
    expect(screen.getByText('a museum').tagName).toBe('LI')
    expect(screen.queryByText(/\*\*tacos\*\*/)).toBeNull()
  })

  it('shows user text as plain text, not markdown', () => {
    renderChat({ messages: [msg('u1', 'user', 'I want **cheap** food')] })
    expect(screen.getByText(/I want \*\*cheap\*\* food/)).toBeTruthy()
  })

  it('renders [C] in an assistant message as a tag chip that calls onTagClick', () => {
    const onTagClick = vi.fn()
    const { container } = render(
      <ChatPanel messages={[msg('a1', 'assistant', 'Swap [C] for a park?')]} itinerary={null} onTagClick={onTagClick} />,
    )
    const chip = screen.getByRole('button', { name: 'C' })
    expect(container.textContent).not.toContain('[C]')
    expect(container.querySelector('a')).toBeNull()
    fireEvent.click(chip)
    expect(onTagClick).toHaveBeenCalledTimes(1)
    expect(onTagClick).toHaveBeenCalledWith('C')
  })

  // AGENTS.md rule 5: links and images never come from LLM text.
  it('renders an LLM-written link as plain text with no <a>', () => {
    const { container } = renderChat({ messages: [msg('a1', 'assistant', 'See [site](https://x.y) now')] })
    expect(screen.getByText(/site/)).toBeTruthy()
    expect(container.querySelector('a')).toBeNull()
    expect(container.innerHTML).not.toContain('https://x.y')
  })

  it('renders an LLM-written image as its alt text with no <img>', () => {
    const { container } = renderChat({ messages: [msg('a1', 'assistant', 'Look ![pic](https://x.y/p.png) here')] })
    expect(screen.getByText(/pic/)).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
    expect(container.innerHTML).not.toContain('https://x.y/p.png')
  })
})

describe('ChatPanel errors', () => {
  it('shows the error inline with a Retry button that calls onRetry', () => {
    const { onRetry } = renderChat({
      messages: [msg('u1', 'user', 'Plan it')],
      error: { message: 'The model is busy', retryable: true },
    })
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toMatch(/The model is busy/)
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('a non-retryable error has no Retry button', () => {
    renderChat({ error: { message: 'Session not found', retryable: false } })
    expect(screen.getByRole('alert').textContent).toMatch(/Session not found/)
    expect(screen.queryByRole('button', { name: /Retry/ })).toBeNull()
  })

  it('shows no alert without an error', () => {
    renderChat({ messages: [msg('a1', 'assistant', 'Hi')] })
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
