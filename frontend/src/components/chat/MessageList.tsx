import { useLayoutEffect, useRef } from "react"
import { ErrorBubble } from "@/components/chat/ErrorBubble"
import { MessageBubble } from "@/components/chat/MessageBubble"
import { StatusLine } from "@/components/chat/StatusLine"
import { shouldStickToBottom } from "@/lib/scroll"
import { useTripStore } from "@/store/tripStore"

/**
 * The transcript: saved messages, the message being sent, the reply as it streams in,
 * the status line and the last error. Keeps the newest content in view unless the user
 * has scrolled up to read (02 §6); sending a message always scrolls back down.
 */
export function MessageList() {
  const messages = useTripStore((s) => s.messages)
  const pendingUserMessage = useTripStore((s) => s.pendingUserMessage)
  const streaming = useTripStore((s) => s.streaming)
  const streamingText = useTripStore((s) => s.streamingText)
  const statusLabel = useTripStore((s) => s.statusLabel)
  const error = useTripStore((s) => s.error)
  const retry = useTripStore((s) => s.retry)

  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  const lastScrollTop = useRef(0)

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    stickToBottom.current = shouldStickToBottom(el, lastScrollTop.current)
    lastScrollTop.current = el.scrollTop
  }

  // A new stream (the user sent a message or started generating) jumps to the bottom.
  // Layout effects run in order, so this runs before the scroll below.
  useLayoutEffect(() => {
    if (streaming) stickToBottom.current = true
  }, [streaming])

  // Before paint, whenever the transcript grows.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [
    messages,
    pendingUserMessage,
    streaming,
    streamingText,
    statusLabel,
    error,
  ])

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="min-h-0 flex-1 overflow-y-auto"
    >
      {/* role="log" is a polite live region: new bubbles and the status line are announced. */}
      <div
        role="log"
        aria-label="Chat messages"
        className="flex flex-col gap-3 px-6 py-4"
      >
        {messages.map((m) => (
          <MessageBubble key={m.id} role={m.role} content={m.content} />
        ))}
        {pendingUserMessage && (
          <MessageBubble role="user" content={pendingUserMessage.content} />
        )}
        {statusLabel && <StatusLine label={statusLabel} />}
        {streaming && (streamingText || !statusLabel) && (
          <MessageBubble role="assistant" content={streamingText} streaming />
        )}
        {error && (
          <ErrorBubble
            message={error.message}
            onRetry={error.retryable ? () => void retry() : undefined}
          />
        )}
      </div>
    </div>
  )
}
