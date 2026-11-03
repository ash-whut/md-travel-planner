import { TagBadge } from "@/components/common/TagBadge"
import { ItineraryItem } from "@/components/plan/ItineraryItem"
import { formatDate } from "@/lib/format"
import { dayColor } from "@/lib/plan"
import type { Day, Lodging, Place } from "@/types"

/**
 * One day of the plan (02 §4.1): "Day 1 · Sat, Mar 6 — title", the city, tonight's hotel
 * (none on the departure day) and the ordered items, with the day colour as a left stripe.
 * The weather chip arrives in Stage 3.
 */
export function DayCard({
  day,
  lodging,
  placesByTag,
  tagColors,
}: {
  day: Day
  lodging: Lodging | undefined
  placesByTag: Record<string, Place>
  tagColors: Record<string, string>
}) {
  return (
    <li
      className="space-y-4 rounded-xl border border-l-4 p-4"
      style={{ borderLeftColor: dayColor(day.day_number) }}
    >
      <header className="space-y-1">
        <h3 className="font-semibold">
          Day {day.day_number} · {formatDate(day.date)} — {day.title}
        </h3>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
          <span>{day.city}</span>
          {lodging && (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1.5">
                Night at
                <TagBadge tag={lodging.tag} />
                {lodging.name}
              </span>
            </>
          )}
        </p>
      </header>
      <ol className="space-y-4">
        {day.items.map((item) => (
          <ItineraryItem
            key={item.id}
            item={item}
            place={item.place_tag ? placesByTag[item.place_tag] : undefined}
            tagColor={item.place_tag ? tagColors[item.place_tag] : undefined}
          />
        ))}
      </ol>
    </li>
  )
}
