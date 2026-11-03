import { CalendarDays, Users, Wallet } from "lucide-react"
import { DayCard } from "@/components/plan/DayCard"
import { LodgingCard } from "@/components/plan/LodgingCard"
import { formatDateRange } from "@/lib/format"
import { formatTravelers, formatTripEstimate, tagColors } from "@/lib/plan"
import type { Itinerary, Lodging, Place } from "@/types"

/**
 * The Plan tab with an itinerary (02 §4.1, Stage 1 subset): header, hotel cards, then one
 * card per day. The version badge, weather chips and "as of" prices arrive in Stage 3.
 */
export function PlanView({ itinerary }: { itinerary: Itinerary }) {
  const colors = tagColors(itinerary)
  const placesByTag: Record<string, Place> = Object.fromEntries(
    itinerary.places.map((place) => [place.tag, place])
  )
  const lodgingByTag: Record<string, Lodging> = Object.fromEntries(
    itinerary.lodging.map((lodging) => [lodging.tag, lodging])
  )

  return (
    <article className="space-y-6">
      <PlanHeader itinerary={itinerary} />

      {itinerary.lodging.length > 0 && (
        <section aria-labelledby="plan-lodging-heading" className="space-y-3">
          <h3 id="plan-lodging-heading" className="font-semibold">
            Where you'll stay
          </h3>
          {itinerary.lodging.map((lodging) => (
            <LodgingCard key={lodging.tag} lodging={lodging} />
          ))}
        </section>
      )}

      <ol aria-label="Days" className="space-y-4">
        {itinerary.days.map((day) => (
          <DayCard
            key={day.day_number}
            day={day}
            lodging={
              day.lodging_tag ? lodgingByTag[day.lodging_tag] : undefined
            }
            placesByTag={placesByTag}
            tagColors={colors}
          />
        ))}
      </ol>

      {/* Item costs are LLM guesses in Stage 1 (05 S1.15 note). */}
      <p className="text-xs text-muted-foreground">
        All costs are rough estimates.
      </p>
    </article>
  )
}

/** Title, dates, travelers, summary, cost estimate and the collapsible assumptions. */
function PlanHeader({ itinerary }: { itinerary: Itinerary }) {
  const { cost_estimate, weather_summary, assumptions } = itinerary

  return (
    <header className="space-y-3">
      <h2 className="text-xl font-semibold">{itinerary.title}</h2>
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <CalendarDays className="size-4" aria-hidden />
          {formatDateRange(itinerary.start_date, itinerary.end_date)}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Users className="size-4" aria-hidden />
          {formatTravelers(itinerary.travelers)}
        </span>
        {cost_estimate && (
          <span className="inline-flex items-center gap-1.5">
            <Wallet className="size-4" aria-hidden />
            {formatTripEstimate(cost_estimate.low, cost_estimate.high)}
            <span>(rough estimate, excludes flights)</span>
          </span>
        )}
      </p>
      <p>{itinerary.summary}</p>
      {weather_summary && (
        <p className="text-sm text-muted-foreground">{weather_summary}</p>
      )}
      {assumptions.length > 0 && (
        <details className="rounded-lg bg-muted px-3 py-2 text-sm">
          <summary className="cursor-pointer font-medium">
            Assumptions ({assumptions.length})
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
            {assumptions.map((assumption, index) => (
              <li key={index}>{assumption}</li>
            ))}
          </ul>
        </details>
      )}
    </header>
  )
}
