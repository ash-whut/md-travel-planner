import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { sanJoseMessages, sanJoseStatusLines, sanJoseV2 } from '@/fixtures'
import { ChatPanel } from './ChatPanel'
import { TagBadge } from './TagBadge'

function renderChat() {
  render(
    <ChatPanel messages={sanJoseMessages} itinerary={sanJoseV2} statusLines={sanJoseStatusLines} onTagClick={() => {}} />,
  )
}

describe('ChatPanel', () => {
  it('renders [X] tokens as tag chips, not raw text', () => {
    renderChat()
    expect(screen.getAllByRole('button', { name: 'L' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: 'F' }).length).toBeGreaterThan(0)
    expect(screen.queryByText(/\[L\]/)).toBeNull()
  })

  it('shows a version divider for each message that created a version', () => {
    renderChat()
    expect(screen.getByText('Plan created · v1')).toBeTruthy()
    expect(screen.getByText('Plan updated · v2')).toBeTruthy()
  })

  it('shows the demo status lines', () => {
    renderChat()
    expect(screen.getByText(/Searching vegan restaurants near downtown/)).toBeTruthy()
  })
})

describe('TagBadge', () => {
  it('is a plain span without onClick and a button with it', () => {
    const { rerender } = render(<TagBadge tag="C" day={1} />)
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByText('C').tagName).toBe('SPAN')
    rerender(<TagBadge tag="C" day={1} onClick={() => {}} />)
    expect(screen.getByRole('button', { name: 'C' })).toBeTruthy()
  })
})
