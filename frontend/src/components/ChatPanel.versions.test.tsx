// Step 26: chat version markers sit right AFTER the message that came with the new version (D21).
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { sanJoseMessages, sanJoseStatusLines, sanJoseV2 } from '@/fixtures'
import type { Message } from '@/types'
import { ChatPanel } from './ChatPanel'

const isBefore = (a: Node, b: Node) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0

function textOf(id: string): HTMLElement {
  const message = sanJoseMessages.find((m) => m.id === id)!
  // Match on a plain-text prefix that stops before the first tag (tags become chips).
  const prefix = message.content.split('[')[0].slice(0, 20)
  return screen.getByText((_, el) => el?.tagName === 'P' && (el.textContent ?? '').startsWith(prefix))
}

describe('Version markers', () => {
  it('there is one marker per message with itinerary_version, with the right labels in order', () => {
    render(<ChatPanel messages={sanJoseMessages} itinerary={sanJoseV2} onTagClick={() => {}} />)
    const markers = screen.getAllByTestId('version-marker')
    expect(markers).toHaveLength(sanJoseMessages.filter((m) => m.itinerary_version !== null).length)
    expect(markers.map((m) => m.textContent?.trim())).toEqual(['Plan created · v1', 'Plan updated · v2'])
  })

  it('each marker comes after its message and before the next one', () => {
    render(
      <ChatPanel messages={sanJoseMessages} itinerary={sanJoseV2} statusLines={sanJoseStatusLines} onTagClick={() => {}} />,
    )
    const [v1Marker, v2Marker] = screen.getAllByTestId('version-marker')
    const m7 = textOf('m7')
    const m8 = textOf('m8')
    const m9 = textOf('m9')
    const m10 = textOf('m10')

    expect(isBefore(m7, v1Marker)).toBe(true)
    expect(isBefore(m8, v1Marker)).toBe(true)
    expect(isBefore(v1Marker, m9)).toBe(true)
    expect(isBefore(m10, v2Marker)).toBe(true)
    // Status lines stay above their message, so the marker is after them too.
    const statusLine = screen.getByText(/Searching vegan restaurants near downtown/)
    expect(isBefore(statusLine, m10)).toBe(true)
    expect(isBefore(statusLine, v2Marker)).toBe(true)
  })

  it('shows no marker when no message has a version', () => {
    const messages: Message[] = sanJoseMessages.map((m) => ({ ...m, itinerary_version: null }))
    render(<ChatPanel messages={messages} itinerary={null} onTagClick={() => {}} />)
    expect(screen.queryAllByTestId('version-marker')).toHaveLength(0)
    expect(screen.queryByText(/Plan (created|updated)/)).toBeNull()
  })

  it('labels a later version as "Plan updated · vN"', () => {
    const messages: Message[] = [
      { id: 'x', role: 'assistant', content: 'Fresh version.', itinerary_version: 3, created_at: '' },
    ]
    render(<ChatPanel messages={messages} itinerary={null} onTagClick={() => {}} />)
    expect(screen.getByTestId('version-marker').textContent?.trim()).toBe('Plan updated · v3')
  })
})
