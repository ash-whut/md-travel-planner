import { useCallback, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { HistoryRail } from './components/HistoryRail'
import { PlanView } from './components/PlanView'
import { MapView } from './components/MapView'
import { BookView } from './components/BookView'
import { ChatPanel } from './components/ChatPanel'
import { demo } from './demoParams'

type Tab = 'plan' | 'map' | 'book'

const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: 'Plan' },
  { id: 'map', label: 'Map' },
  { id: 'book', label: 'Book' },
]

export default function App() {
  const [historyOpen, setHistoryOpen] = useState(demo.history)
  const [tab, setTab] = useState<Tab>(TABS.some((t) => t.id === demo.tab) ? (demo.tab as Tab) : 'plan')
  const [split, setSplit] = useState(56) // plan pane width, % of the main area
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [flashKey, setFlashKey] = useState(0)
  const main = useRef<HTMLDivElement>(null)

  // Clicking a tag anywhere: from chat/book jump to the plan entry; on the map, focus the pin.
  const onTagClick = useCallback(
    (tag: string) => {
      setSelectedTag(tag)
      setFlashKey((k) => k + 1)
      if (tab === 'book') setTab('plan')
    },
    [tab],
  )

  function startDrag(e: React.MouseEvent) {
    e.preventDefault()
    const rect = main.current!.getBoundingClientRect()
    const move = (ev: MouseEvent) => {
      const pct = ((ev.clientX - rect.left) / rect.width) * 100
      setSplit(Math.min(72, Math.max(34, pct)))
    }
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  const title = TABS.find((t) => t.id === tab)!.label

  return (
    <div className="flex h-full">
      <HistoryRail open={historyOpen} onToggle={() => setHistoryOpen((o) => !o)} />

      <div ref={main} className="flex min-w-0 flex-1">
        <section className="flex min-w-0 bg-gray-50" style={{ width: `${split}%` }}>
          {/* Vertical tabs down the pane's edge, as in the sketch */}
          <nav className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-gray-200 bg-white pt-14">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`flex w-full justify-center py-5 text-xs font-semibold tracking-wider uppercase ${
                  tab === t.id
                    ? 'border-l-2 border-accent bg-accent-soft text-accent'
                    : 'border-l-2 border-transparent text-gray-500 hover:bg-gray-50'
                }`}
              >
                <span className="inline-block rotate-180 [writing-mode:vertical-rl]">{t.label}</span>
              </button>
            ))}
          </nav>

          <div className="flex min-w-0 flex-1 flex-col">
            <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-5">
              <h2 className="font-semibold">{title}</h2>
              {tab !== 'plan' && (
                <button
                  type="button"
                  onClick={() => setTab('plan')}
                  title="Back to plan"
                  className="rounded-lg border border-gray-300 p-1 text-gray-600 hover:bg-gray-100"
                >
                  <X size={16} />
                </button>
              )}
            </header>
            <div className="min-h-0 flex-1" key={tab === 'plan' ? flashKey : tab}>
              {tab === 'plan' && <PlanView selectedTag={selectedTag} onTagClick={onTagClick} />}
              {tab === 'map' && <MapView selectedTag={selectedTag} onTagClick={onTagClick} />}
              {tab === 'book' && <BookView onTagClick={onTagClick} />}
            </div>
          </div>
        </section>

        <div
          onMouseDown={startDrag}
          title="Drag to resize"
          className="group relative w-1.5 shrink-0 cursor-col-resize bg-gray-200 hover:bg-accent"
        >
          <span className="absolute top-1/2 left-1/2 flex h-8 w-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-gray-300 bg-white text-[10px] text-gray-400 shadow-sm group-hover:border-accent group-hover:text-accent">
            ↔
          </span>
        </div>

        <div className="min-w-0 flex-1">
          <ChatPanel onTagClick={onTagClick} />
        </div>
      </div>
    </div>
  )
}
