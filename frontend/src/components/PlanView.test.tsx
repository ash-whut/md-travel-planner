import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sanJoseProfile, sanJoseV1, sanJoseV2 } from '@/fixtures'
import { PlanView } from './PlanView'

function shownTags(): string[] {
  const badges = screen.getAllByTitle(/^Refer to this as "/)
  return [...new Set(badges.map((b) => b.textContent ?? ''))].sort()
}

describe('PlanView', () => {
  it('renders v2 letters A–E and G–L, without the retired F', () => {
    render(<PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
    expect(shownTags()).toEqual(['A', 'B', 'C', 'D', 'E', 'G', 'H', 'I', 'J', 'K', 'L'])
    expect(screen.queryByText('Baconhouse')).toBeNull()
    expect(screen.getByText('Good Karma Kitchen')).toBeTruthy()
  })

  it('shows "Updated in v2" once, on the replaced item', () => {
    render(<PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
    const labels = screen.getAllByText('Updated in v2')
    expect(labels).toHaveLength(1)
    expect(labels[0].closest('li')?.textContent).toContain('Good Karma Kitchen')
  })

  it('renders v1 letters A–K with no "Updated" label', () => {
    render(<PlanView itinerary={sanJoseV1} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
    expect(shownTags()).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K'])
    expect(screen.queryByText(/Updated in v/)).toBeNull()
  })

  it('renders the title, one section per day and the version badge', () => {
    render(<PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={() => {}} />)
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV2.title })).toBeTruthy()
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(sanJoseV2.days.length)
    expect(screen.getByText(/^v2 ·/)).toBeTruthy()
  })

  it('calls onTagClick with the letter when a tag is clicked', () => {
    const onTagClick = vi.fn()
    render(<PlanView itinerary={sanJoseV2} profile={sanJoseProfile} selectedTag={null} onTagClick={onTagClick} />)
    fireEvent.click(screen.getByRole('button', { name: 'L' }))
    expect(onTagClick).toHaveBeenCalledWith('L')
  })
})
