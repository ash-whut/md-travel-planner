import { useEffect, useRef, useState, type KeyboardEvent } from "react"
import { SendHorizontal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useTripStore } from "@/store/tripStore"

// POST /sessions/{id}/messages accepts 1–4000 characters (03 §3).
const MAX_LENGTH = 4000

/** Message box: Enter sends, Shift+Enter adds a new line; disabled while a reply streams. */
export function ChatInput() {
  const streaming = useTripStore((s) => s.streaming)
  const sendMessage = useTripStore((s) => s.sendMessage)
  const [text, setText] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const formRef = useRef<HTMLFormElement>(null)

  const disabled = streaming !== null
  const canSend = !disabled && text.trim().length > 0

  // Disabling the box drops focus; give it back once a chat reply has finished, unless the
  // user has focused something else meanwhile. (Not after generate, which the user starts
  // from a button.) Firefox can leave focus on the disabled textarea or Send button, so
  // focus inside this form also counts as "not moved".
  const wasChatStreaming = useRef(false)
  useEffect(() => {
    if (streaming === "chat") wasChatStreaming.current = true
    else if (!streaming && wasChatStreaming.current) {
      wasChatStreaming.current = false
      const active = document.activeElement
      if (
        !active ||
        active === document.body ||
        formRef.current?.contains(active)
      ) {
        textareaRef.current?.focus()
      }
    }
  }, [streaming])

  function send() {
    if (!canSend) return
    void sendMessage(text)
    setText("")
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Ignore Enter while an IME is composing (e.g. picking Japanese characters).
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
  }

  return (
    <form
      ref={formRef}
      className="flex items-end gap-2 border-t px-6 py-4"
      onSubmit={(e) => {
        e.preventDefault()
        send()
      }}
    >
      <Textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        maxLength={MAX_LENGTH}
        rows={1}
        placeholder="Tell me about your trip…"
        aria-label="Message"
        className="max-h-40 min-h-10 resize-none"
      />
      <Button
        type="submit"
        size="icon-lg"
        disabled={!canSend}
        aria-label="Send message"
      >
        <SendHorizontal />
      </Button>
    </form>
  )
}
