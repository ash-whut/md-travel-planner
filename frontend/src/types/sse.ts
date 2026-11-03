// SSE event payloads, docs/03-contracts.md §4 (Stage 1 subset). The `itinerary` event's
// payload is an `Itinerary`. `profile` (Stage 3) and `title` (Stage 4) come later.

export interface MessageStartData {
  message_id: string
}

export interface TokenData {
  text: string
}

export interface StatusData {
  label: string
  tool: string | null // null for phases like "Drafting your itinerary…"
  state: "start" | "end" | "error" // Stage 1 only sends "start" (no "end")
}

export interface ErrorData {
  message: string // user-friendly text
  retryable: boolean
}

export interface DoneData {
  message_id: string
}
