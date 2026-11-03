import { ChatHeader } from "@/components/chat/ChatHeader"
import { ChatInput } from "@/components/chat/ChatInput"
import { MessageList } from "@/components/chat/MessageList"
import { cn } from "@/lib/utils"

/** Right half of the page (02 §1–2): title, transcript and message box. */
export function ChatPanel({ className }: { className?: string }) {
  return (
    <section aria-label="Chat" className={cn("flex flex-col", className)}>
      <ChatHeader />
      <MessageList />
      <ChatInput />
    </section>
  )
}
