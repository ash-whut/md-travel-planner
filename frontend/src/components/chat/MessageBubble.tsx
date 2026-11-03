import { Loader2 } from "lucide-react"
import { Markdown } from "@/components/chat/Markdown"
import { cn } from "@/lib/utils"
import type { MessageRole } from "@/types"

interface MessageBubbleProps {
  role: MessageRole
  content: string
  /** The assistant reply that is still arriving; shows a spinner until the first text. */
  streaming?: boolean
}

/** One chat message: user on the right, assistant on the left (02 §1). */
export function MessageBubble({
  role,
  content,
  streaming,
}: MessageBubbleProps) {
  const isUser = role === "user"

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        aria-busy={streaming || undefined}
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "rounded-br-sm bg-primary break-words whitespace-pre-wrap text-primary-foreground"
            : "rounded-bl-sm bg-muted text-foreground"
        )}
      >
        <span className="sr-only">{isUser ? "You:" : "Assistant:"}</span>
        {isUser ? (
          content
        ) : streaming && !content ? (
          <Loader2
            className="size-4 animate-spin text-muted-foreground"
            aria-label="Assistant is replying"
          />
        ) : (
          <Markdown>{content}</Markdown>
        )}
      </div>
    </div>
  )
}
