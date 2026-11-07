import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, Plus, SendHorizontal } from 'lucide-react'
import { demo } from '@/demoParams'
import type { Itinerary, Message } from '@/types'
import { TagBadge, firstDayByTag } from './TagBadge'

// "[C]" tokens (contracts §2.5) render as tag chips. Step 27 replaces this with lib/tags.ts.
function withTagChips(text: string, firstDay: Map<string, number>, onTagClick: (t: string) => void): ReactNode[] {
  return text.split(/\[([A-Z]{1,2})\]/).map((part, i) =>
    i % 2 === 1 ? (
      <span key={i} className="mx-0.5 inline-block align-middle">
        <TagBadge tag={part} day={firstDay.get(part) ?? 1} size="sm" onClick={() => onTagClick(part)} />
      </span>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  )
}

function versionLabel(version: number) {
  return version === 1 ? 'Plan created · v1' : `Plan updated · v${version}`
}

function demoMessage(role: Message['role'], content: string, id: string): Message {
  return { id, role, content, itinerary_version: null, created_at: new Date().toISOString() }
}

interface Props {
  messages: Message[]
  itinerary: Itinerary | null
  statusLines?: Record<string, string[]> // labels shown just above the message with that id
  onTagClick: (tag: string) => void
}

export function ChatPanel({ messages: savedMessages, itinerary, statusLines = {}, onTagClick }: Props) {
  // v0 canned replies live only here, after the messages from the store (step 14 replaces this).
  const [demoMessages, setMessages] = useState<Message[]>([])
  const [demoStatus, setStatusBefore] = useState<Record<string, string[]>>({})
  const messages = [...savedMessages, ...demoMessages]
  const statusBefore = { ...statusLines, ...demoStatus }
  const [draft, setDraft] = useState('')
  const [picker, setPicker] = useState(demo.picker)
  const bottom = useRef<HTMLDivElement>(null)
  const firstDay = firstDayByTag(itinerary)
  const stops = itinerary?.stops ?? []

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [savedMessages, demoMessages])

  // Shows the user's message; the canned v0 reply only appears in ?demo=1 mode (step 14 sends to the backend).
  function send() {
    const text = draft.trim()
    if (!text) return
    const match = text.match(/\[([A-Z]{1,2})\]|\b([B-HJ-Z])\b/)
    const mentioned = match?.[1] ?? match?.[2]
    const id = Date.now().toString()
    setMessages((m) => [...m, demoMessage('user', text, id)])
    setDraft('')
    if (!demo.enabled) return
    setTimeout(() => {
      setStatusBefore((s) => ({ ...s, [id + 'a']: [mentioned ? `Re-planning ${mentioned} only` : 'Thinking…'] }))
      setMessages((m) => [
        ...m,
        demoMessage(
          'assistant',
          mentioned
            ? `On it — I’ll swap [${mentioned}] and keep every other letter the same. (v0 demo: canned data, no agent connected yet.)`
            : 'Got it! (v0 demo: canned data, no agent connected yet.)',
          id + 'a',
        ),
      ])
    }, 600)
  }

  return (
    <section className="flex h-full min-w-0 flex-col bg-white">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-gray-200 px-5">
        <h2 className="font-semibold">Chat</h2>
        <ol className="flex items-center gap-1.5 text-xs text-gray-500">
          {['Profile', 'Trip details', 'Plan'].map((step, i) => (
            <li key={step} className="flex items-center gap-1.5">
              {i > 0 && <span className="h-px w-4 bg-gray-300" />}
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">
                <Check size={12} /> {step}
              </span>
            </li>
          ))}
        </ol>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {messages.map((m) => {
          const mine = m.role === 'user'
          return (
            <Fragment key={m.id}>
              {(statusBefore[m.id] ?? []).map((label, i) => (
                <p key={i} className="flex items-center gap-1.5 pl-1 text-xs text-gray-400">
                  <Check size={12} className="text-emerald-500" /> {label}
                </p>
              ))}
              {m.itinerary_version !== null && (
                <div className="flex items-center gap-3 py-1 text-[11px] font-medium text-accent">
                  <span className="h-px flex-1 bg-indigo-100" /> {versionLabel(m.itinerary_version)}{' '}
                  <span className="h-px flex-1 bg-indigo-100" />
                </div>
              )}
              <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
                <p
                  className={`max-w-[80%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                    mine ? 'rounded-br-md bg-accent text-white' : 'rounded-bl-md bg-gray-100 text-gray-800'
                  }`}
                >
                  {withTagChips(m.content, firstDay, onTagClick)}
                </p>
              </div>
            </Fragment>
          )
        })}
        <div ref={bottom} />
      </div>

      <div className="relative shrink-0 border-t border-gray-200 p-3">
        {picker && (
          <div className="absolute bottom-full left-3 mb-2 w-64 rounded-xl border border-gray-200 bg-white p-2 shadow-lg">
            <p className="px-1 pb-1.5 text-xs font-medium text-gray-500">Refer to a stop</p>
            <div className="grid max-h-56 grid-cols-1 overflow-y-auto">
              {stops.map((s) => (
                <button
                  key={s.tag}
                  type="button"
                  onClick={() => {
                    setDraft((d) => `${d}${d && !d.endsWith(' ') ? ' ' : ''}[${s.tag}] `)
                    setPicker(false)
                  }}
                  className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-left text-sm hover:bg-gray-50"
                >
                  <TagBadge tag={s.tag} day={firstDay.get(s.tag) ?? 1} size="sm" /> <span className="truncate">{s.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex items-center gap-2 rounded-xl border border-gray-300 px-2 py-1.5 focus-within:border-accent focus-within:ring-2 focus-within:ring-indigo-100">
          <button
            type="button"
            onClick={() => setPicker((p) => !p)}
            title="Refer to a stop by its letter"
            className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100"
          >
            <Plus size={18} />
          </button>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="Edit by letter — e.g. “replace H with something outdoors”"
            className="min-w-0 flex-1 bg-transparent py-1 text-sm outline-none placeholder:text-gray-400"
          />
          <button
            type="button"
            onClick={send}
            disabled={!draft.trim()}
            className="rounded-lg bg-accent p-1.5 text-white disabled:opacity-40"
          >
            <SendHorizontal size={18} />
          </button>
        </div>
      </div>
    </section>
  )
}
