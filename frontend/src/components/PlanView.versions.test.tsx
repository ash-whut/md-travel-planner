// Step 26: the header version badge, the "Updated in vN" highlight, and the Regenerate button.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sanJoseProfile, sanJoseV1, sanJoseV2 } from '@/fixtures'
import type { Itinerary } from '@/types'
import { PlanView } from './PlanView'

const noop = () => {}
// "Nov 1, 6:08 PM" in whatever timezone the test runs in.
const STAMP = /[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} (AM|PM)/

function clone(it: Itinerary): Itinerary {
  return JSON.parse(JSON.stringify(it)) as Itinerary
}

/** v3 from v2: the v2 change stays marked 2 (stale), and one other item changes in v3. */
function makeV3(): { v3: Itinerary; changed: string } {
  const v3 = clone(sanJoseV2)
  v3.version = 3
  v3.created_at = '2026-11-01T18:20:00Z'
  const item = v3.days[2].items.find((i) => i.updated_in_version === null)!
  item.updated_in_version = 3
  return { v3, changed: item.description }
}

function highlightedRows(): HTMLElement[] {
  return screen.getAllByRole('listitem').filter((li) => /Updated in v\d+/.test(li.textContent ?? ''))
}

describe('Version badge', () => {
  it('v1 reads "created" with the version time, not "just now"', () => {
    render(<PlanView itinerary={sanJoseV1} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} />)
    const badge = screen.getByText(/^v1 ·/)
    expect(badge.textContent).toMatch(new RegExp(`^v1 · created ${STAMP.source}$`))
    expect(screen.queryByText(/just now/)).toBeNull()
  })

  it('v2 reads "updated" with the version time', () => {
    render(<PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} />)
    expect(screen.getByText(/^v2 ·/).textContent).toMatch(new RegExp(`^v2 · updated ${STAMP.source}$`))
  })
})

describe('"Updated in vN" highlight', () => {
  it('v2: only the changed item has the label and the highlight bar', () => {
    const { container } = render(
      <PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} />,
    )
    const changed = sanJoseV2.days.flatMap((d) => d.items).filter((i) => i.updated_in_version === 2)
    expect(changed).toHaveLength(1)
    const rows = highlightedRows()
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain(changed[0].description)
    expect(screen.getAllByText('Updated in v2')).toHaveLength(1)
    // The amber bar is drawn only on that row.
    expect(container.querySelectorAll('li .bg-amber-400')).toHaveLength(1)
    expect(rows[0].querySelector('.bg-amber-400')).not.toBeNull()
  })

  it('v1 has no highlight, even if every item says updated_in_version = 1', () => {
    const v1 = clone(sanJoseV1)
    v1.days.forEach((d) => d.items.forEach((i) => (i.updated_in_version = 1)))
    const { container } = render(<PlanView itinerary={v1} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} />)
    expect(screen.queryByText(/Updated in v/)).toBeNull()
    expect(container.querySelectorAll('li .bg-amber-400')).toHaveLength(0)
  })

  it('v3: items changed in an older version are no longer highlighted', () => {
    const { v3, changed } = makeV3()
    render(<PlanView itinerary={v3} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} />)
    expect(screen.queryByText('Updated in v2')).toBeNull()
    const rows = highlightedRows()
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain(changed)
    expect(screen.getByText(/^v3 ·/).textContent).toMatch(/^v3 · updated /)
  })
})

describe('Regenerate button', () => {
  it('is shown once a plan exists and calls onGenerate', () => {
    const onGenerate = vi.fn()
    render(<PlanView itinerary={sanJoseV1} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} onGenerate={onGenerate} />)
    fireEvent.click(screen.getByRole('button', { name: /Regenerate/ }))
    expect(onGenerate).toHaveBeenCalledTimes(1)
  })

  it('is not shown without a plan (the empty state has Generate instead)', () => {
    render(<PlanView itinerary={null} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} />)
    expect(screen.queryByRole('button', { name: /Regenerate/ })).toBeNull()
  })

  it('is disabled while a reply streams', () => {
    const onGenerate = vi.fn()
    render(
      <PlanView
        itinerary={sanJoseV1}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={noop}
        canGenerate={false}
        onGenerate={onGenerate}
      />,
    )
    const button = screen.getByRole('button', { name: /Regenerate/ }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(onGenerate).not.toHaveBeenCalled()
  })

  it('a Regenerate run swaps the plan for skeletons and the status line', () => {
    render(
      <PlanView
        itinerary={sanJoseV1}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={noop}
        generating
        regenerating
        planStatus="Drafting your plan…"
      />,
    )
    expect(screen.getAllByTestId('skeleton-day').length).toBeGreaterThan(0)
    expect(screen.getByRole('status').textContent).toContain('Drafting your plan…')
    expect(screen.queryByRole('heading', { level: 1, name: sanJoseV1.title })).toBeNull()
  })
})
