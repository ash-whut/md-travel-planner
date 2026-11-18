import { useState } from 'react'
import { ChevronsLeft, ChevronsRight, MapPinned, Pencil, Plus, Trash2 } from 'lucide-react'
import { formatRelative } from '@/lib/format'
import type { SessionSummary } from '@/types'

const MAX_TITLE = 80 // contracts §4: a title is 1–80 chars

interface Props {
  open: boolean
  onToggle: () => void
  sessions: SessionSummary[] // most recently updated first
  activeId: string | null // the trip shown in the app
  error: string | null
  onNew: () => void
  onOpen: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onRetry: () => void
}

export function HistoryRail({
  open,
  onToggle,
  sessions,
  activeId,
  error,
  onNew,
  onOpen,
  onRename,
  onDelete,
  onRetry,
}: Props) {
  // The trip whose title is being edited inline, and the text typed so far.
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  function startRename(s: SessionSummary) {
    setEditingId(s.id)
    setDraft(s.title)
  }

  // Enter saves (an empty or unchanged title just closes the box); Esc or clicking away cancels.
  function finishRename(save: boolean) {
    const title = draft.trim()
    const current = sessions.find((s) => s.id === editingId)
    if (save && editingId && title && title !== current?.title) onRename(editingId, title)
    setEditingId(null)
  }

  function confirmDelete(s: SessionSummary) {
    if (window.confirm(`Delete "${s.title}"? This can't be undone.`)) onDelete(s.id)
  }

  return (
    <aside
      className={`${open ? 'w-60' : 'w-14'} flex shrink-0 flex-col border-r border-gray-200 bg-white transition-all`}
    >
      <div className="flex h-14 items-center gap-2 px-3">
        <span className="text-2xl">🦆</span>
        {open && <span className="font-semibold tracking-tight">Mighty Ducks</span>}
      </div>
      <button
        type="button"
        onClick={onNew}
        className="mx-2 flex items-center gap-2 rounded-lg bg-accent px-2.5 py-2 text-sm font-medium text-white hover:opacity-90"
        title="New trip"
      >
        <Plus size={18} />
        {open && 'New trip'}
      </button>

      {open && error && (
        <div role="alert" className="mx-2 mt-3 rounded-lg bg-red-50 px-2.5 py-2 text-xs text-red-700">
          {error}{' '}
          <button type="button" onClick={onRetry} className="font-medium underline">
            Reload
          </button>
        </div>
      )}

      <nav aria-label="Trip history" className="mt-4 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-2">
        {sessions.map((s) => {
          const active = s.id === activeId
          if (open && editingId === s.id) {
            return (
              <div key={s.id} className="flex items-center gap-2 rounded-lg bg-accent-soft px-2.5 py-2">
                <MapPinned size={18} className="shrink-0 text-accent" />
                <input
                  autoFocus
                  aria-label="Trip name"
                  value={draft}
                  maxLength={MAX_TITLE}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') finishRename(true)
                    if (e.key === 'Escape') finishRename(false)
                  }}
                  onBlur={() => finishRename(false)}
                  className="min-w-0 flex-1 rounded border border-accent bg-white px-1.5 py-0.5 text-sm outline-none"
                />
              </div>
            )
          }
          return (
            <div
              key={s.id}
              className={`group flex items-center rounded-lg ${
                active ? 'bg-accent-soft text-accent' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              <button
                type="button"
                title={s.title}
                aria-current={active ? 'true' : undefined}
                onClick={() => !active && onOpen(s.id)}
                className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-left text-sm"
              >
                <MapPinned size={18} className="shrink-0" />
                {open && (
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{s.title}</span>
                    <span className="block text-xs text-gray-400">{formatRelative(s.updated_at)}</span>
                  </span>
                )}
              </button>
              {open && (
                // Shown on hover, or when tabbing into the row with the keyboard.
                <span className="flex shrink-0 pr-1 opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
                  <button
                    type="button"
                    onClick={() => startRename(s)}
                    aria-label={`Rename ${s.title}`}
                    title="Rename"
                    className="rounded p-1 text-gray-400 hover:bg-white hover:text-gray-700"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => confirmDelete(s)}
                    aria-label={`Delete ${s.title}`}
                    title="Delete"
                    className="rounded p-1 text-gray-400 hover:bg-white hover:text-red-600"
                  >
                    <Trash2 size={14} />
                  </button>
                </span>
              )}
            </div>
          )
        })}
      </nav>
      <button
        type="button"
        onClick={onToggle}
        className="mt-auto mb-3 flex items-center justify-center rounded-lg p-2 text-gray-400 hover:bg-gray-100"
        title={open ? 'Collapse' : 'Expand history'}
      >
        {open ? <ChevronsLeft size={18} /> : <ChevronsRight size={18} />}
      </button>
    </aside>
  )
}
