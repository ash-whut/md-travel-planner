import { MapPinned } from "lucide-react"
import { GenerateButton } from "@/components/common/GenerateButton"

/** The Plan tab before any itinerary exists (02 §4.1; no TripProfileCard until Stage 3). */
export function PlanEmptyState() {
  return (
    <div className="flex flex-col items-center gap-4 py-16 text-center">
      <MapPinned className="size-10 text-muted-foreground" aria-hidden />
      <p className="text-muted-foreground">Your trip plan will appear here.</p>
      <GenerateButton />
    </div>
  )
}
