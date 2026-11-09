import { useCallback, useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import type { ApiClient } from './api/client'
import { httpClient } from './api/http'
import { HistoryRail } from './components/HistoryRail'
import { PlanView } from './components/PlanView'
import { MapView } from './components/MapView'
import { BookView } from './components/BookView'
import { ChatPanel } from './components/ChatPanel'
import { demo } from './demoParams'
import { hasMapStops } from './lib/map'
import { useTripStore } from './store/useTripStore'

type Tab = 'plan' | 'map' | 'book'

const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: 'Plan' },
  { id: 'map', label: 'Map' },
  { id: 'book', label: 'Book' },
]

interface Props {
  api?: ApiClient // tests pass a fake
}

export default function App({ api = httpClient }: Props) {
  const messages = useTripStore((s) => s.messages)
  const profile = useTripStore((s) => s.profile)
  const itinerary = useTripStore((s) => s.itinerary)
  const statusLines = useTripStore((s) => s.statusLines)
  const streaming = useTripStore((s) => s.streaming)
  const streamingMessageId = useTripStore((s) => s.streamingMessageId)
  const generating = useTripStore((s) => s.generating)
  const planStatus = useTripStore((s) => s.planStatus)
  // A Generate/Regenerate run (not a chat edit) swaps an existing plan for skeletons.
  const regenerating = useTripStore((s) => s.generating && s.lastRequest?.kind === 'generate')
  const error = useTripStore((s) => s.error)
  const selectedTag = useTripStore((s) => s.selectedTag)
  const flashKey = useTripStore((s) => s.tagFlashKey)
  const started = useRef(false)

  // Load the fixture trip (?demo=1) or open a backend session, once. The ref survives
  // StrictMode's double effect run, so a new session is never created twice.
  useEffect(() => {
    if (started.current) return
    started.current = true
    const store = useTripStore.getState()
    if (demo.enabled) store.loadDemo()
    else void store.startSession(api)
  }, [api])

  const [historyOpen, setHistoryOpen] = useState(demo.history)
  const [tab, setTab] = useState<Tab>(TABS.some((t) => t.id === demo.tab) ? (demo.tab as Tab) : 'plan')
  const [split, setSplit] = useState(56) // plan pane width, % of the main area
  const main = useRef<HTMLDivElement>(null)

  // A new plan version from the stream (not from loading a session) brings the Plan tab forward.
  // A store subscription (not an effect on `itinerary`) sees each change with its `streaming`
  // flag, so it reacts to the `itinerary` event only and a session load keeps the current tab.
  useEffect(
    () =>
      useTripStore.subscribe((state, prev) => {
        if (state.itinerary !== prev.itinerary && state.streaming) setTab('plan')
      }),
    [],
  )

  // Book unlocks with a plan; Map only once a stop has coordinates (docs/spec.md F5).
  function lockReason(id: Tab): string | null {
    if (id === 'plan') return null
    if (!itinerary) return 'Generate a plan to unlock'
    if (id === 'map' && !hasMapStops(itinerary)) return 'No stops with coordinates yet'
    return null
  }
  const activeTab: Tab = lockReason(tab) ? 'plan' : tab

  // Clicking a tag anywhere: from chat/book jump to the plan entry; on the map, focus the pin.
  const onTagClick = useCallback(
    (tag: string) => {
      useTripStore.getState().selectTag(tag)
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

  const title = TABS.find((t) => t.id === activeTab)!.label

  return (
    <div className="flex h-full">
      <HistoryRail open={historyOpen} onToggle={() => setHistoryOpen((o) => !o)} />

      <div ref={main} className="flex min-w-0 flex-1">
        <section className="flex min-w-0 bg-gray-50" style={{ width: `${split}%` }}>
          {/* Vertical tabs down the pane's edge, as in the sketch */}
          <nav className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-gray-200 bg-white pt-14">
            {TABS.map((t) => {
              const reason = lockReason(t.id)
              const locked = reason !== null
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => !locked && setTab(t.id)}
                  aria-disabled={locked}
                  title={reason ?? undefined}
                  className={`flex w-full justify-center py-5 text-xs font-semibold tracking-wider uppercase ${
                    activeTab === t.id
                      ? 'border-l-2 border-accent bg-accent-soft text-accent'
                      : locked
                        ? 'cursor-not-allowed border-l-2 border-transparent text-gray-300'
                        : 'border-l-2 border-transparent text-gray-500 hover:bg-gray-50'
                  }`}
                >
                  <span className="inline-block rotate-180 [writing-mode:vertical-rl]">{t.label}</span>
                </button>
              )
            })}
          </nav>

          <div className="flex min-w-0 flex-1 flex-col">
            <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-5">
              <h2 className="font-semibold">{title}</h2>
              {activeTab !== 'plan' && (
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
            <div className="min-h-0 flex-1" key={activeTab === 'plan' ? flashKey : activeTab}>
              {activeTab === 'plan' && (
                <PlanView
                  itinerary={itinerary}
                  profile={profile}
                  selectedTag={selectedTag}
                  onTagClick={onTagClick}
                  generating={generating}
                  regenerating={regenerating}
                  planStatus={planStatus}
                  canGenerate={!streaming}
                  onGenerate={() => void useTripStore.getState().generatePlan(api)}
                />
              )}
              {itinerary && activeTab === 'map' && (
                <MapView itinerary={itinerary} selectedTag={selectedTag} onTagClick={onTagClick} />
              )}
              {itinerary && activeTab === 'book' && <BookView itinerary={itinerary} onTagClick={onTagClick} />}
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

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <ChatPanel
              messages={messages}
              itinerary={itinerary}
              statusLines={statusLines}
              streaming={streaming}
              streamingMessageId={streamingMessageId}
              error={error}
              onSend={(text) => void useTripStore.getState().sendMessage(api, text)}
              onRetry={() => void useTripStore.getState().retry(api)}
              onStop={() => useTripStore.getState().stop()}
              onTagClick={onTagClick}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
