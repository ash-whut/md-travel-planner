import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import Markdown from 'react-markdown'
import { Check, Circle, Plus, RotateCcw, SendHorizontal, Square } from 'lucide-react'
import { demo } from '@/demoParams'
import { stepperState } from '@/lib/profile'
import type { StoreError } from '@/store/useTripStore'
import type { Itinerary, Message, TripProfile } from '@/types'
import { TagBadge, firstDayByTag } from './TagBadge'

const TAG_TOKEN = /\[([A-Z]{1,2})\]/g
const TAG_HREF = '#tag-'

function tagChip(tag: string, key: number | string, firstDay: Map<string, number>, onTagClick: (t: string) => void) {
  return (
    <span key={key} className="mx-0.5 inline-block align-middle">
      <TagBadge tag={tag} day={firstDay.get(tag) ?? 1} size="sm" onClick={() => onTagClick(tag)} />
    </span>
  )
}

// "[C]" tokens (contracts §2.5) render as tag chips. Step 27 replaces this with lib/tags.ts.
function withTagChips(text: string, firstDay: Map<string, number>, onTagClick: (t: string) => void): ReactNode[] {
  return text
    .split(/\[([A-Z]{1,2})\]/)
    .map((part, i) => (i % 2 === 1 ? tagChip(part, i, firstDay, onTagClick) : <Fragment key={i}>{part}</Fragment>))
}

// Assistant text is markdown. "[C]" becomes a link to "#tag-C" first, and the link renderer
// turns those links into tag chips. Other links are LLM-written, and links must come from code
// or tools (AGENTS.md rule 5), so they show as plain text until step 40.
function AssistantMarkdown(props: { text: string; firstDay: Map<string, number>; onTagClick: (t: string) => void }) {
  const { text, firstDay, onTagClick } = props
  return (
    <Markdown
      components={{
        a: ({ href, children }) =>
          href?.startsWith(TAG_HREF) ? tagChip(href.slice(TAG_HREF.length), href, firstDay, onTagClick) : <>{children}</>,
        // No remote images from LLM text (AGENTS.md rule 5): show the alt text only.
        img: ({ alt }) => <>{alt}</>,
      }}
    >
      {text.replace(TAG_TOKEN, `[$1](${TAG_HREF}$1)`)}
    </Markdown>
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
  profile?: TripProfile | null // drives the header stepper (with whether a plan exists)
  statusLines?: Record<string, string[]> // labels shown just above the message with that id
  streaming?: boolean // a reply is streaming: the input is disabled
  streamingMessageId?: string | null // the assistant message being streamed (shows "…" until text arrives)
  error?: StoreError | null // shown inline after the last message
  onSend?: (text: string) => void
  onRetry?: () => void
  onStop?: () => void // shown as a Stop button while streaming
  onTagClick: (tag: string) => void
}

export function ChatPanel({
  messages: savedMessages,
  itinerary,
  profile = null,
  statusLines = {},
  streaming = false,
  streamingMessageId = null,
  error = null,
  onSend,
  onRetry,
  onStop,
  onTagClick,
}: Props) {
  // ?demo=1 has no backend session: canned replies live only here, after the store's messages.
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
  }, [savedMessages, demoMessages, error])

  // Sends to the backend through onSend; ?demo=1 answers locally with a canned v0 reply.
  function send() {
    const text = draft.trim()
    if (!text || streaming) return
    setDraft('')
    if (!demo.enabled) {
      onSend?.(text)
      return
    }
    const match = text.match(/\[([A-Z]{1,2})\]|\b([B-HJ-Z])\b/)
    const mentioned = match?.[1] ?? match?.[2]
    const id = Date.now().toString()
    setMessages((m) => [...m, demoMessage('user', text, id)])
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
        <ol aria-label="Trip progress" className="flex items-center gap-1.5 text-xs text-gray-500">
          {stepperState(profile, itinerary !== null).map((step, i) => (
            <li key={step.id} className="flex items-center gap-1.5">
              {i > 0 && <span className="h-px w-4 bg-gray-300" />}
              {step.done ? (
                <span
                  aria-label={`${step.label} done`}
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700"
                >
                  <Check size={12} /> {step.label}
                </span>
              ) : (
                <span
                  aria-label={`${step.label} to do`}
                  className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-gray-400"
                >
                  <Circle size={12} /> {step.label}
                </span>
              )}
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
                {mine ? (
                  <p className="max-w-[80%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap text-white">
                    {withTagChips(m.content, firstDay, onTagClick)}
                  </p>
                ) : (
                  <div className="max-w-[80%] space-y-2 rounded-2xl rounded-bl-md bg-gray-100 px-3.5 py-2 text-sm leading-relaxed text-gray-800 [&_a]:underline [&_ol]:list-decimal [&_ol]:pl-5 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-5">
                    {!m.content && m.id === streamingMessageId ? (
                      <span className="text-gray-400" aria-label="Assistant is typing">
                        …
                      </span>
                    ) : (
                      <AssistantMarkdown text={m.content} firstDay={firstDay} onTagClick={onTagClick} />
                    )}
                  </div>
                )}
              </div>
            </Fragment>
          )
        })}
        {error && (
          <div
            role="alert"
            className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2 text-sm text-red-700"
          >
            <span>{error.message}</span>
            {error.retryable && onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-red-300 bg-white px-2 py-1 text-xs font-medium hover:bg-red-100"
              >
                <RotateCcw size={12} /> Retry
              </button>
            )}
          </div>
        )}
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
          {/* Enter sends; Shift+Enter adds a newline. Grows up to 5 lines. */}
          <textarea
            value={draft}
            rows={Math.min(5, draft.split('\n').length)}
            disabled={streaming}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
            placeholder="Edit by letter — e.g. “replace H with something outdoors”"
            className="min-w-0 flex-1 resize-none bg-transparent py-1 text-sm outline-none placeholder:text-gray-400 disabled:opacity-60"
          />
          {streaming && onStop ? (
            <button
              type="button"
              onClick={onStop}
              title="Stop"
              aria-label="Stop"
              className="rounded-lg bg-gray-700 p-1.5 text-white hover:bg-gray-800"
            >
              <Square size={18} />
            </button>
          ) : (
            <button
              type="button"
              onClick={send}
              title="Send"
              disabled={streaming || !draft.trim()}
              className="rounded-lg bg-accent p-1.5 text-white disabled:opacity-40"
            >
              <SendHorizontal size={18} />
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
