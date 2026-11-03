import {
  BedDouble,
  Coffee,
  ExternalLink,
  Lightbulb,
  MapPin,
  Route,
  Utensils,
  type LucideIcon,
} from "lucide-react"
import { TagBadge } from "@/components/common/TagBadge"
import { formatTimeRange } from "@/lib/format"
import { formatItemEstimate, formatTransit } from "@/lib/plan"
import type { Item, ItemKind, Place } from "@/types"

const KIND_ICONS: Record<ItemKind, LucideIcon> = {
  activity: MapPin,
  meal: Utensils,
  transit: Route,
  lodging: BedDouble,
  free_time: Coffee,
}

/**
 * One stop in a day (02 §4.1): time range · tag badge · kind icon · title, then the
 * description, a Google Maps link, the estimated cost, "Needs booking" and tips. Optional
 * lines are left out when their field is null.
 */
export function ItineraryItem({
  item,
  place,
  tagColor,
}: {
  item: Item
  place: Place | undefined
  tagColor: string | undefined
}) {
  const KindIcon = KIND_ICONS[item.kind]
  const transit = item.transit_from_previous

  return (
    <li className="space-y-2">
      {transit && (
        <p className="flex items-center gap-1.5 pl-1 text-xs text-muted-foreground">
          <Route className="size-3.5" aria-hidden />
          {formatTransit(transit)}
        </p>
      )}
      <div className="flex gap-3">
        <p className="w-36 shrink-0 pt-0.5 text-sm text-muted-foreground tabular-nums">
          {formatTimeRange(item.start_time, item.end_time)}
        </p>
        {/* Keeps titles aligned whether or not the item has a tag. */}
        <div className="flex w-10 shrink-0 justify-center">
          {item.place_tag && (
            <TagBadge tag={item.place_tag} dayColor={tagColor} />
          )}
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <h4 className="flex items-start gap-1.5 font-medium">
            <KindIcon
              className="mt-0.5 size-4 shrink-0 text-muted-foreground"
              aria-hidden
            />
            {item.title}
          </h4>
          {item.description && (
            <p className="text-sm text-muted-foreground">{item.description}</p>
          )}
          <ItemMeta item={item} place={place} />
          {item.tips && (
            <p className="flex items-start gap-1.5 text-sm">
              <Lightbulb
                className="mt-0.5 size-3.5 shrink-0 text-amber-600"
                aria-hidden
              />
              <span>
                <span className="sr-only">Tip: </span>
                {item.tips}
              </span>
            </p>
          )}
        </div>
      </div>
    </li>
  )
}

/** The small line under the description; rendered only if it has something to show. */
function ItemMeta({ item, place }: { item: Item; place: Place | undefined }) {
  if (!place && !item.est_cost && !item.booking_required) return null

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {place && (
        <a
          href={place.maps_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 underline-offset-2 hover:text-foreground hover:underline"
        >
          {place.name}
          <ExternalLink className="size-3" aria-hidden />
          <span className="sr-only">(Google Maps, opens in a new tab)</span>
        </a>
      )}
      {item.est_cost && <span>{formatItemEstimate(item.est_cost.amount)}</span>}
      {item.booking_required && (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-900">
          Needs booking
        </span>
      )}
    </div>
  )
}
