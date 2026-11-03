import { RefreshCw, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { selectCanGenerate, useTripStore } from "@/store/tripStore"

const NEEDS_MESSAGE_HINT = "Tell me about your trip first."
const BUSY_HINT = "Working on it…"
const DEFAULTS_HINT =
  "Anything you haven't told me yet will be filled in with sensible defaults."

/**
 * "Generate plan", or "Regenerate" once a plan exists (02 §2, §4.1). Used in the chat
 * header and the plan empty state. Each click makes a new itinerary version.
 */
export function GenerateButton({ size }: { size?: "sm" | "default" }) {
  const canGenerate = useTripStore(selectCanGenerate)
  const hasUserMessage = useTripStore((s) =>
    s.messages.some((m) => m.role === "user")
  )
  const hasPlan = useTripStore((s) => s.itinerary !== null)
  const isStreaming = useTripStore((s) => s.streaming !== null)
  const generate = useTripStore((s) => s.generate)

  const Icon = hasPlan ? RefreshCw : Sparkles
  const hint = isStreaming
    ? BUSY_HINT
    : hasUserMessage
      ? DEFAULTS_HINT
      : NEEDS_MESSAGE_HINT

  return (
    <Tooltip>
      {/* A disabled button gets no pointer events, so the span shows the tooltip. */}
      <TooltipTrigger asChild>
        <span className="inline-flex shrink-0">
          <Button
            size={size}
            disabled={!canGenerate}
            onClick={() => void generate()}
          >
            <Icon aria-hidden />
            {hasPlan ? "Regenerate" : "Generate plan"}
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  )
}
