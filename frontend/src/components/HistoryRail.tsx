import { ChevronsLeft, ChevronsRight, MapPinned, Plus } from 'lucide-react'

const sessions = [
  { title: 'San Jose · Mar 5–7', when: 'Just now', active: true },
  { title: 'Austin · Apr 10–12', when: '3 days ago' },
  { title: 'New Orleans weekend', when: 'Oct 20' },
]

interface Props {
  open: boolean
  onToggle: () => void
}

export function HistoryRail({ open, onToggle }: Props) {
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
        className="mx-2 flex items-center gap-2 rounded-lg bg-accent px-2.5 py-2 text-sm font-medium text-white hover:opacity-90"
        title="New trip"
      >
        <Plus size={18} />
        {open && 'New trip'}
      </button>
      <nav className="mt-4 flex flex-col gap-1 px-2">
        {sessions.map((s) => (
          <button
            key={s.title}
            type="button"
            title={s.title}
            className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm ${
              s.active ? 'bg-accent-soft text-accent' : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <MapPinned size={18} className="shrink-0" />
            {open && (
              <span className="min-w-0">
                <span className="block truncate font-medium">{s.title}</span>
                <span className="block text-xs text-gray-400">{s.when}</span>
              </span>
            )}
          </button>
        ))}
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
