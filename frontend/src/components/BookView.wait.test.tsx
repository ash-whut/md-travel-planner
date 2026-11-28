// Step 46 (D36): "Mark booked" / Undo wait while a plan is being made (`locked`) and while that
// card's own save runs (`pending`); the other cards stay usable.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sanJoseV1, sanJoseV2 } from '@/fixtures'
import { BookView } from './BookView'

function card(title: string): HTMLElement {
  return screen.getByRole('heading', { level: 3, name: title }).closest('li') as HTMLElement
}

function button(title: string, name: string): HTMLButtonElement {
  return within(card(title)).getByRole('button', { name }) as HTMLButtonElement
}

const todo = sanJoseV1.bookings.filter((b) => b.status === 'todo')
const booked = sanJoseV2.bookings.find((b) => b.status === 'booked')!

describe('BookView buttons that wait', () => {
  it('are enabled by default', () => {
    render(<BookView itinerary={sanJoseV1} onTagClick={() => {}} onSetStatus={() => {}} />)
    for (const b of todo) expect(button(b.title, 'Mark booked').disabled).toBe(false)
  })

  it('locked: every Mark booked and Undo is disabled with a reason, and clicks do nothing', () => {
    const onSetStatus = vi.fn()
    render(<BookView itinerary={sanJoseV2} onTagClick={() => {}} onSetStatus={onSetStatus} locked />)

    for (const b of sanJoseV2.bookings.filter((x) => x.status === 'todo')) {
      const mark = button(b.title, 'Mark booked')
      expect(mark.disabled).toBe(true)
      expect(mark.getAttribute('title')).toBe('Wait until the plan is updated')
      fireEvent.click(mark)
    }
    const undo = button(booked.title, 'Undo')
    expect(undo.disabled).toBe(true)
    fireEvent.click(undo)
    expect(onSetStatus).not.toHaveBeenCalled()
  })

  it('locked: the Book link button still works', () => {
    render(<BookView itinerary={sanJoseV1} onTagClick={() => {}} onSetStatus={() => {}} locked />)
    expect(button(todo[0].title, 'Book').disabled).toBe(false)
  })

  it('pending: only that card waits and is marked busy', () => {
    const onSetStatus = vi.fn()
    const [saving, other] = todo
    render(<BookView itinerary={sanJoseV1} onTagClick={() => {}} onSetStatus={onSetStatus} pending={[saving.id]} />)

    expect(button(saving.title, 'Mark booked').disabled).toBe(true)
    expect(card(saving.title).getAttribute('aria-busy')).toBe('true')
    expect(button(other.title, 'Mark booked').disabled).toBe(false)
    expect(card(other.title).getAttribute('aria-busy')).toBe('false')

    fireEvent.click(button(saving.title, 'Mark booked'))
    expect(onSetStatus).not.toHaveBeenCalled()
    fireEvent.click(button(other.title, 'Mark booked'))
    expect(onSetStatus).toHaveBeenCalledWith(other.id, 'booked')
  })

  it('pending: a booked card cannot be undone until its save finishes', () => {
    const onSetStatus = vi.fn()
    render(<BookView itinerary={sanJoseV2} onTagClick={() => {}} onSetStatus={onSetStatus} pending={[booked.id]} />)
    fireEvent.click(button(booked.title, 'Undo'))
    expect(onSetStatus).not.toHaveBeenCalled()
  })
})
