import { cn } from "@/lib/utils"
import { useTripStore } from "@/store/tripStore"

/**
 * Right half of the page.
 * PLACEHOLDER: S1.13 builds the real panel (markdown bubbles, streaming text, status line,
 * error + Retry, input) and S1.14 adds the ChatHeader with "Generate plan". For now it
 * only lists the saved messages as plain text, so the greeting is visible.
 */
export function ChatPanel({ className }: { className?: string }) {
  const title = useTripStore((s) => s.session?.title)
  const messages = useTripStore((s) => s.messages)

  return (
    <section className={cn("flex flex-col", className)}>
      <header className="border-b px-6 py-3 font-medium">{title}</header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-6">
        {messages.map((message) => (
          <p key={message.id} className="whitespace-pre-wrap">
            {message.content}
          </p>
        ))}
      </div>
    </section>
  )
}
