import { Fragment, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { Check, Loader2, Plus, RotateCcw, SendHorizontal, Square, X } from 'lucide-react'
import { demo } from '@/demoParams'
import { firstDayByTag, insertTag, isTag, isTagHref, parseTagTokens, tagsToLinks } from '@/lib/tags'
import type { StatusLine, StoreError } from '@/store/useTripStore'
import type { Itinerary, Message } from '@/types'
import { TagBadge } from './TagBadge'

const PLACEHOLDER_INTAKE = 'Tell me about your trip…'
const PLACEHOLDER_EDIT = 'Edit by letter — e.g. “replace H with something outdoors”'

interface ChipProps {
  tag: string
  firstDay: Map<string, number>
  onTagClick: (tag: string) => void
}

function TagChip({ tag, firstDay, onTagClick }: ChipProps) {
  return (
    <span className="mx-0.5 inline-block align-middle">
      <TagBadge tag={tag} day={firstDay.get(tag) ?? 1} size="sm" onClick={() => onTagClick(tag)} />
    </span>
  )
}

// User text is plain: "[C]" tokens (contracts §2.5) become chips, the rest stays as typed.
function UserText({ text, firstDay, onTagClick }: { text: string } & Omit<ChipProps, 'tag'>) {
  return parseTagTokens(text).map((s, i) =>
    s.kind === 'tag' ? (
      <TagChip key={i} tag={s.tag} firstDay={firstDay} onTagClick={onTagClick} />
    ) : (
      <Fragment key={i}>{s.text}</Fragment>
    ),
  )
}

// Assistant text is markdown. Tag tokens become "#tag-C" links first, and the link renderer
// turns those into chips. An LLM-written "[A](url)" becomes a chip only when A is a stop of the
// current plan (its url is dropped), so "[US](url)" stays text. Other links are LLM-written, and
// links must come from code or tools (AGENTS.md rule 5), so they show as plain text until step 40.
function AssistantMarkdown({ text, firstDay, onTagClick }: { text: string } & Omit<ChipProps, 'tag'>) {
  return (
    <Markdown
      components={{
        a: ({ children, href }) =>
          typeof children === 'string' &&
          isTag(children) &&
          (isTagHref(href, children) || firstDay.has(children)) ? (
            <TagChip tag={children} firstDay={firstDay} onTagClick={onTagClick} />
          ) : (
            <>{children}</>
          ),
        // No remote images from LLM text (AGENTS.md rule 5): show the alt text only.
        img: ({ alt }) => <>{alt}</>,
      }}
    >
      {tagsToLinks(text)}
    </Markdown>
  )
}

// A status line: a spinner while its step runs, then ✓ (done) or ✕ (failed). A step still
// running after its reply stopped streaming (Stop, cut-off stream) never finished, so it shows ✕.
function StatusLineRow({ line, live }: { line: StatusLine; live: boolean }) {
  const state = line.state === 'start' && !live ? 'error' : line.state
  return (
    <p data-state={state} className="flex items-center gap-1.5 pl-1 text-xs text-gray-400">
      {state === 'start' && <Loader2 size={12} aria-label="In progress" className="animate-spin text-accent" />}
      {state === 'end' && <Check size={12} aria-label="Done" className="text-emerald-500" />}
      {state === 'error' && <X size={12} aria-label="Failed" className="text-red-500" />} {line.label}
    </p>
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
  statusLines?: Record<string, StatusLine[]> // status lines shown just above the message with that id
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
  const [demoStatus, setStatusBefore] = useState<Record<string, StatusLine[]>>({})
  const messages = [...savedMessages, ...demoMessages]
  const statusBefore = { ...statusLines, ...demoStatus }
  const [draft, setDraft] = useState('')
  // ?picker=1 opens the stop picker for screenshots, only together with ?demo=1.
  const [picker, setPicker] = useState(demo.enabled && demo.picker)
  const bottom = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const pendingCursor = useRef<number | null>(null)
  const firstDay = firstDayByTag(itinerary)
  const stops = itinerary?.stops ?? []

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [savedMessages, demoMessages, error])

  // After the picker inserts a tag, put the cursor right after it.
  useEffect(() => {
    const el = input.current
    if (el && pendingCursor.current !== null) {
      el.focus()
      el.setSelectionRange(pendingCursor.current, pendingCursor.current)
      pendingCursor.current = null
    }
  }, [draft])

  // The "+" picker: "[C] " goes in at the cursor (or replaces the selected text).
  function pickStop(tag: string) {
    const el = input.current
    const start = el?.selectionStart ?? draft.length
    const end = el?.selectionEnd ?? draft.length
    const next = insertTag(draft, start, end, tag)
    pendingCursor.current = next.cursor
    setDraft(next.text)
    setPicker(false)
  }

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
      const label = mentioned ? `Re-planning ${mentioned} only` : 'Thinking…'
      setStatusBefore((s) => ({ ...s, [id + 'a']: [{ label, state: 'end' }] }))
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
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {messages.map((m) => {
          const mine = m.role === 'user'
          return (
            <Fragment key={m.id}>
              {(statusBefore[m.id] ?? []).map((line) => (
                <StatusLineRow key={line.label} line={line} live={m.id === streamingMessageId} />
              ))}
              <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
                {mine ? (
                  <p className="max-w-[80%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap text-white">
                    <UserText text={m.content} firstDay={firstDay} onTagClick={onTagClick} />
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
              {/* The version marker closes the message that came with the new plan (step 26). */}
              {m.itinerary_version !== null && (
                <div
                  data-testid="version-marker"
                  className="flex items-center gap-3 py-1 text-[11px] font-medium text-accent"
                >
                  <span className="h-px flex-1 bg-indigo-100" /> {versionLabel(m.itinerary_version)}{' '}
                  <span className="h-px flex-1 bg-indigo-100" />
                </div>
              )}
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
        {picker && stops.length > 0 && (
          <div
            role="menu"
            aria-label="Refer to a stop"
            className="absolute bottom-full left-3 mb-2 w-64 rounded-xl border border-gray-200 bg-white p-2 shadow-lg"
          >
            <p className="px-1 pb-1.5 text-xs font-medium text-gray-500">Refer to a stop</p>
            <div className="grid max-h-56 grid-cols-1 overflow-y-auto">
              {stops.map((s) => (
                <button
                  key={s.tag}
                  type="button"
                  role="menuitem"
                  onClick={() => pickStop(s.tag)}
                  className="flex items-center gap-2 rounded-lg px-1.5 py-1 text-left text-sm hover:bg-gray-50"
                >
                  <TagBadge tag={s.tag} day={firstDay.get(s.tag) ?? 1} size="sm" /> <span className="truncate">{s.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex items-center gap-2 rounded-xl border border-gray-300 px-2 py-1.5 focus-within:border-accent focus-within:ring-2 focus-within:ring-indigo-100">
          {/* The picker lists the plan's stops, so it is off until a plan exists. */}
          <button
            type="button"
            onClick={() => setPicker((p) => !p)}
            disabled={stops.length === 0}
            title={stops.length > 0 ? 'Refer to a stop by its letter' : 'Stops appear here once there is a plan'}
            aria-label="Refer to a stop"
            aria-expanded={picker && stops.length > 0}
            className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-transparent"
          >
            <Plus size={18} />
          </button>
          {/* Enter sends; Shift+Enter adds a newline. Grows up to 5 lines. */}
          <textarea
            ref={input}
            aria-label="Message"
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
            placeholder={itinerary ? PLACEHOLDER_EDIT : PLACEHOLDER_INTAKE}
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
