import type { IsoDateTime } from "@/types/common"
import type { Itinerary } from "@/types/itinerary"
import type { TripProfile } from "@/types/tripProfile"

// Session DTOs, docs/03-contracts.md §2.3 (Stage 1 subset: SessionSummary arrives in Stage 4).

export type SessionStatus = "intake" | "planned"
export type MessageRole = "user" | "assistant"

export interface Message {
  id: string
  role: MessageRole
  content: string // markdown
  itinerary_version: number | null // set on the assistant message that produced a version
  created_at: IsoDateTime
}

export interface SessionDetail {
  id: string
  title: string
  status: SessionStatus
  trip_profile: TripProfile
  messages: Message[]
  itinerary: Itinerary | null // latest version
  chat_enabled: boolean // false if the session belongs to a different LLM provider
  created_at: IsoDateTime
  updated_at: IsoDateTime
}
