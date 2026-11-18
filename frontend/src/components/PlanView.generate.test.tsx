// Step 24: PlanView empty state, Generate button, skeleton while generating, "Why this?".
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sanJoseProfile, sanJoseV1 } from '@/fixtures'
import { PlanView } from './PlanView'

const noop = () => {}

describe('PlanView without a plan', () => {
  it('shows the empty state and a Generate button that calls onGenerate', () => {
    const onGenerate = vi.fn()
    render(<PlanView itinerary={null} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} onGenerate={onGenerate} />)
    expect(screen.getByText('Your trip plan will appear here')).toBeTruthy()
    expect(screen.queryAllByTestId('skeleton-day')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: /Generate/ }))
    expect(onGenerate).toHaveBeenCalledTimes(1)
  })

  it('disables Generate while a reply is streaming', () => {
    const onGenerate = vi.fn()
    render(
      <PlanView itinerary={null} profile={null} selectedTag={null} onTagClick={noop} canGenerate={false} onGenerate={onGenerate} />,
    )
    const button = screen.getByRole('button', { name: /Generate/ }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(onGenerate).not.toHaveBeenCalled()
  })

  it('shows skeleton day cards and the current status line while generating', () => {
    render(
      <PlanView
        itinerary={null}
        profile={sanJoseProfile}
        selectedTag={null}
        onTagClick={noop}
        generating
        planStatus="Drafting your plan…"
      />,
    )
    expect(screen.getAllByTestId('skeleton-day').length).toBeGreaterThan(0)
    expect(screen.getByRole('status').textContent).toContain('Drafting your plan…')
    expect(screen.queryByRole('button', { name: /Generate/ })).toBeNull()
  })

  it('shows a status line before the first status event arrives', () => {
    render(<PlanView itinerary={null} profile={null} selectedTag={null} onTagClick={noop} generating planStatus={null} />)
    expect(screen.getAllByTestId('skeleton-day').length).toBeGreaterThan(0)
    expect(screen.getByRole('status').textContent?.trim()).not.toBe('')
  })
})

describe('PlanView with a plan', () => {
  it('renders the fixture plan instead of the empty state, without skeletons', () => {
    render(<PlanView itinerary={sanJoseV1} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} generating />)
    expect(screen.getByRole('heading', { level: 1, name: sanJoseV1.title })).toBeTruthy()
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(sanJoseV1.days.length)
    expect(screen.queryByText('Your trip plan will appear here')).toBeNull()
    expect(screen.queryAllByTestId('skeleton-day')).toHaveLength(0)
  })

  it('"Why this?" reveals the item why and its source', () => {
    const item = sanJoseV1.days.flatMap((d) => d.items).find((i) => i.why && i.source)!
    render(<PlanView itinerary={sanJoseV1} profile={sanJoseProfile} selectedTag={null} onTagClick={noop} />)
    expect(screen.queryByText(item.why!)).toBeNull()
    const row = screen.getByText(item.description).closest('li')!
    const whyButton = [...row.querySelectorAll('button')].find((b) => b.textContent?.includes('Why this?'))!
    fireEvent.click(whyButton)
    expect(screen.getByText(item.why!)).toBeTruthy()
    expect(screen.getByText(`Source: ${item.source}`)).toBeTruthy()
    fireEvent.click(whyButton)
    expect(screen.queryByText(item.why!)).toBeNull()
  })
})
