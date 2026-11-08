// Step 27: tag chips in chat, the "+" stop picker and the input placeholder.
// demoParams is mocked with a mutable object so ?picker=1 can be tested with and without ?demo=1.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sanJoseV2 } from '@/fixtures'
import type { Message } from '@/types'
import { ChatPanel } from './ChatPanel'

const demo = vi.hoisted(() => ({
  enabled: false,
  tab: null as string | null,
  day: null as string | null,
  confirm: null as string | null,
  why: null as string | null,
  picker: false,
  history: false,
}))
vi.mock('@/demoParams', () => ({ demo }))

beforeEach(() => {
  demo.enabled = false
  demo.picker = false
})

function msg(id: string, role: Message['role'], content: string): Message {
  return { id, role, content, itinerary_version: null, created_at: '' }
}

function messageInput(): HTMLTextAreaElement {
  return screen.getByRole('textbox', { name: 'Message' }) as HTMLTextAreaElement
}

function pickerButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: 'Refer to a stop' }) as HTMLButtonElement
}

// Types `value` and puts the cursor (or selection) at [start, end).
function typeWithCursor(value: string, start: number, end = start) {
  const input = messageInput()
  fireEvent.change(input, { target: { value } })
  input.setSelectionRange(start, end)
  return input
}

describe('ChatPanel stop picker', () => {
  it('is disabled until there are stops', () => {
    const { rerender } = render(<ChatPanel messages={[]} itinerary={null} onTagClick={() => {}} />)
    expect(pickerButton().disabled).toBe(true)
    fireEvent.click(pickerButton())
    expect(screen.queryByRole('menu')).toBeNull()

    rerender(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    expect(pickerButton().disabled).toBe(false)
  })

  it('lists every stop of the plan by tag and name', () => {
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(pickerButton())
    const items = within(screen.getByRole('menu')).getAllByRole('menuitem')
    expect(items).toHaveLength(sanJoseV2.stops.length)
    for (const stop of sanJoseV2.stops) {
      expect(items.some((li) => li.textContent?.includes(stop.tag) && li.textContent.includes(stop.name))).toBe(true)
    }
  })

  it('inserts "[C] " at the cursor, closes, and leaves the cursor after the tag', () => {
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    const input = typeWithCursor('replace with a park', 8) // cursor after "replace "
    fireEvent.click(pickerButton())
    fireEvent.click(screen.getByRole('menuitem', { name: /Winchester Mystery House/ }))

    expect(input.value).toBe('replace [H] with a park')
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(input)
    expect(input.selectionStart).toBe(12)
    expect(input.selectionEnd).toBe(12)
  })

  it('adds a space when the cursor is right after a word, and appends to the end', () => {
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    const input = typeWithCursor('swap', 4)
    fireEvent.click(pickerButton())
    fireEvent.click(screen.getByRole('menuitem', { name: /Good Karma Kitchen/ }))
    expect(input.value).toBe('swap [L] ')
  })

  it('replaces the selected text', () => {
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    const input = typeWithCursor('replace XX now', 8, 10)
    fireEvent.click(pickerButton())
    fireEvent.click(screen.getByRole('menuitem', { name: /Japantown/ }))
    expect(input.value).toBe('replace [J]  now')
  })

  it('sends the inserted tag as typed text', () => {
    const onSend = vi.fn()
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onSend={onSend} onTagClick={() => {}} />)
    const input = typeWithCursor('', 0)
    fireEvent.click(pickerButton())
    fireEvent.click(screen.getByRole('menuitem', { name: /Santana Row/ }))
    fireEvent.change(input, { target: { value: input.value + 'is too far' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSend).toHaveBeenCalledWith('[I] is too far')
  })

  it('toggles closed on a second "+" click', () => {
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    fireEvent.click(pickerButton())
    expect(screen.getByRole('menu')).toBeTruthy()
    fireEvent.click(pickerButton())
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('?picker=1 opens it only together with ?demo=1', () => {
    demo.picker = true
    const { unmount } = render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    expect(screen.queryByRole('menu')).toBeNull()
    unmount()

    demo.enabled = true
    render(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    expect(screen.getByRole('menu')).toBeTruthy()
  })
})

describe('ChatPanel placeholder', () => {
  it('asks about the trip before a plan exists and suggests edit-by-letter after', () => {
    const { rerender } = render(<ChatPanel messages={[]} itinerary={null} onTagClick={() => {}} />)
    expect(messageInput().placeholder).toBe('Tell me about your trip…')

    rerender(<ChatPanel messages={[]} itinerary={sanJoseV2} onTagClick={() => {}} />)
    expect(messageInput().placeholder).not.toBe('Tell me about your trip…')
    expect(messageInput().placeholder).toMatch(/letter/i)
  })
})

describe('ChatPanel tag chips', () => {
  it('renders [A], [AA] and adjacent tags in an assistant message as chips', () => {
    render(
      <ChatPanel messages={[msg('a1', 'assistant', 'Try [A][B] or **[AA]**.')]} itinerary={null} onTagClick={() => {}} />,
    )
    for (const t of ['A', 'B', 'AA']) expect(screen.getByRole('button', { name: t })).toBeTruthy()
    expect(screen.queryByText(/\[A\]/)).toBeNull()
  })

  it('renders tags in a user message as chips and keeps [abc] as text', () => {
    render(<ChatPanel messages={[msg('u1', 'user', 'replace [F] and [abc]')]} itinerary={null} onTagClick={() => {}} />)
    expect(screen.getByRole('button', { name: 'F' })).toBeTruthy()
    expect(screen.getByText(/\[abc\]/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'abc' })).toBeNull()
  })

  it('keeps [abc] as text in an assistant message', () => {
    render(<ChatPanel messages={[msg('a1', 'assistant', 'see [abc] and [C]')]} itinerary={null} onTagClick={() => {}} />)
    expect(screen.getByText(/\[abc\]/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'C' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /abc/ })).toBeNull()
  })

  it('shows an LLM-written [A](url) as one chip when A is a stop, with no stray url', () => {
    render(
      <ChatPanel
        messages={[msg('a1', 'assistant', 'Start at [A](https://example.com/home) today.')]}
        itinerary={sanJoseV2}
        onTagClick={() => {}}
      />,
    )
    expect(screen.getAllByRole('button', { name: 'A' })).toHaveLength(1)
    expect(screen.queryByText(/example\.com/)).toBeNull()
    expect(screen.queryByText(/\(/)).toBeNull()
    expect(document.querySelector('a[href^="http"]')).toBeNull()
  })

  it('keeps an LLM-written [US](url) as plain text when US is not a stop', () => {
    render(
      <ChatPanel
        messages={[msg('a1', 'assistant', 'Fly within the [US](https://x.y) and say [OK](https://x.y).')]}
        itinerary={sanJoseV2}
        onTagClick={() => {}}
      />,
    )
    expect(screen.queryByRole('button', { name: 'US' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'OK' })).toBeNull()
    expect(screen.getByText(/US/)).toBeTruthy()
    expect(screen.queryByText(/x\.y/)).toBeNull()
  })

  it('shows a non-tag markdown link as plain text without a link', () => {
    render(
      <ChatPanel messages={[msg('a1', 'assistant', 'Read [the guide](https://x.y) first.')]} itinerary={null} onTagClick={() => {}} />,
    )
    expect(screen.getByText(/the guide/)).toBeTruthy()
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByText(/x\.y/)).toBeNull()
  })

  it('calls onTagClick with the tag of the clicked chip', () => {
    const onTagClick = vi.fn()
    render(
      <ChatPanel messages={[msg('u1', 'user', '[D] or [AA]?')]} itinerary={sanJoseV2} onTagClick={onTagClick} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'AA' }))
    expect(onTagClick).toHaveBeenCalledWith('AA')
    fireEvent.click(screen.getByRole('button', { name: 'D' }))
    expect(onTagClick).toHaveBeenLastCalledWith('D')
  })
})
