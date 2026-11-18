// Step 45: the history rail — list, open, New trip, inline rename (Enter / Esc) and delete with
// a confirm.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SessionSummary } from '@/types'
import { HistoryRail } from './HistoryRail'

const now = Date.now()
const sessions: SessionSummary[] = [
  { id: 's-1', title: 'San Jose · Mar 5–7', status: 'planned', updated_at: new Date(now).toISOString() },
  { id: 's-2', title: 'Austin · Apr 10–12', status: 'planned', updated_at: new Date(now - 3 * 86_400_000).toISOString() },
]

function renderRail(overrides: Partial<Parameters<typeof HistoryRail>[0]> = {}) {
  const props = {
    open: true,
    onToggle: vi.fn(),
    sessions,
    activeId: 's-1',
    error: null,
    onNew: vi.fn(),
    onOpen: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
  render(<HistoryRail {...props} />)
  return props
}

afterEach(() => vi.restoreAllMocks())

describe('HistoryRail list', () => {
  it('shows each trip with its title and relative date, newest first', () => {
    renderRail()
    // The trip buttons themselves, not their Rename / Delete buttons.
    const items = within(screen.getByRole('navigation', { name: 'Trip history' })).getAllByRole('button', {
      name: /^(?!Rename|Delete)/,
    })
    expect(items.map((b) => b.getAttribute('title'))).toEqual(['San Jose · Mar 5–7', 'Austin · Apr 10–12'])
    expect(screen.getByText('Just now')).toBeTruthy()
    expect(screen.getByText('3 days ago')).toBeTruthy()
  })

  it('marks the open trip', () => {
    renderRail()
    expect(screen.getByTitle('San Jose · Mar 5–7').getAttribute('aria-current')).toBe('true')
    expect(screen.getByTitle('Austin · Apr 10–12').getAttribute('aria-current')).toBeNull()
  })

  it('clicking another trip opens it; clicking the open one does nothing', () => {
    const props = renderRail()
    fireEvent.click(screen.getByTitle('Austin · Apr 10–12'))
    fireEvent.click(screen.getByTitle('San Jose · Mar 5–7'))
    expect(props.onOpen).toHaveBeenCalledTimes(1)
    expect(props.onOpen).toHaveBeenCalledWith('s-2')
  })

  it('New trip calls onNew', () => {
    const props = renderRail()
    fireEvent.click(screen.getByRole('button', { name: /New trip/ }))
    expect(props.onNew).toHaveBeenCalledTimes(1)
  })

  it('shows an error with a Reload button', () => {
    const props = renderRail({ error: "Couldn't load your trips: offline" })
    expect(screen.getByRole('alert').textContent).toContain("Couldn't load your trips: offline")
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
    expect(props.onRetry).toHaveBeenCalledTimes(1)
  })

  it('collapsed, it hides titles and the rename/delete buttons', () => {
    renderRail({ open: false })
    expect(screen.queryByText('San Jose · Mar 5–7')).toBeNull()
    expect(screen.queryByRole('button', { name: /Rename/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /Delete/ })).toBeNull()
  })
})

describe('HistoryRail rename', () => {
  it('the pencil opens a text box with the current title; Enter saves the trimmed title', () => {
    const props = renderRail()
    fireEvent.click(screen.getByRole('button', { name: 'Rename Austin · Apr 10–12' }))
    const input = screen.getByRole('textbox', { name: 'Trip name' }) as HTMLInputElement
    expect(input.value).toBe('Austin · Apr 10–12')
    expect(input.maxLength).toBe(80)

    fireEvent.change(input, { target: { value: '  Spring break  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(props.onRename).toHaveBeenCalledWith('s-2', 'Spring break')
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('Esc cancels without saving', () => {
    const props = renderRail()
    fireEvent.click(screen.getByRole('button', { name: 'Rename Austin · Apr 10–12' }))
    const input = screen.getByRole('textbox', { name: 'Trip name' })
    fireEvent.change(input, { target: { value: 'Something else' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(props.onRename).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.getByTitle('Austin · Apr 10–12')).toBeTruthy()
  })

  it('an empty or unchanged title is not saved', () => {
    const props = renderRail()
    fireEvent.click(screen.getByRole('button', { name: 'Rename Austin · Apr 10–12' }))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '   ' } })
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })

    fireEvent.click(screen.getByRole('button', { name: 'Rename Austin · Apr 10–12' }))
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })

    expect(props.onRename).not.toHaveBeenCalled()
  })

  it('clicking away cancels', () => {
    const props = renderRail()
    fireEvent.click(screen.getByRole('button', { name: 'Rename Austin · Apr 10–12' }))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Spring break' } })
    fireEvent.blur(screen.getByRole('textbox'))
    expect(props.onRename).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).toBeNull()
  })
})

describe('HistoryRail delete', () => {
  it('asks for confirmation and deletes on OK', () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const props = renderRail()
    fireEvent.click(screen.getByRole('button', { name: 'Delete Austin · Apr 10–12' }))
    expect(confirm).toHaveBeenCalledWith('Delete "Austin · Apr 10–12"? This can\'t be undone.')
    expect(props.onDelete).toHaveBeenCalledWith('s-2')
    expect(props.onOpen).not.toHaveBeenCalled() // the delete button doesn't also open the trip
  })

  it('does nothing on Cancel', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const props = renderRail()
    fireEvent.click(screen.getByRole('button', { name: 'Delete Austin · Apr 10–12' }))
    expect(props.onDelete).not.toHaveBeenCalled()
  })
})
