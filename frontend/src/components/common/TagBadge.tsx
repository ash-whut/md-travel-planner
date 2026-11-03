import { BedDouble } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { isLodgingTag, UNUSED_PLACE_COLOR } from "@/lib/plan"
import { cn } from "@/lib/utils"

/**
 * A place's letter tag (02 §3): a filled circle (a pill for 2-letter tags) in the colour of
 * the day it first appears; hotels (H1, H2) get a dark pill with a bed icon. Stage 2 reuses
 * it for map markers and makes it clickable.
 */
export function TagBadge({
  tag,
  dayColor = UNUSED_PLACE_COLOR,
}: {
  tag: string
  dayColor?: string
}) {
  const hotel = isLodgingTag(tag)

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex h-6 min-w-6 shrink-0 items-center justify-center gap-0.5 rounded-full px-1.5 text-xs font-semibold text-white",
            hotel && "bg-neutral-900"
          )}
          style={hotel ? undefined : { backgroundColor: dayColor }}
        >
          {hotel && <BedDouble className="size-3.5" aria-hidden />}
          <span className="sr-only">Tag </span>
          {tag}
        </span>
      </TooltipTrigger>
      <TooltipContent>Refer to this as '{tag}' in chat</TooltipContent>
    </Tooltip>
  )
}
