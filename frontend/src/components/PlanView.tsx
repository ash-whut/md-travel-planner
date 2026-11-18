import { useEffect, useRef, useState } from 'react'
import {
  BedDouble, Car, ChevronDown, Clock, ExternalLink, Info, Landmark, Plane, RefreshCw, Sparkles, Ticket, Utensils,
} from 'lucide-react'
import { demo } from '@/demoParams'
import {
  formatAsOf, formatCostRange, formatDate, formatDuration, formatMoney, formatNights, formatPerNight, formatTime,
  formatTimestamp, formatTransitLeg,
} from '@/lib/format'
import { profileChips } from '@/lib/profile'
import { firstDayByTag } from '@/lib/tags'
import type { DayWeather, ItemKind, Itinerary, ItineraryItem, Lodging, Stop, TripProfile } from '@/types'
import { TagBadge } from './TagBadge'

const KIND_ICON: Record<ItemKind, typeof Car> = {
  transit: Car,
  flight: Plane,
  lodging: BedDouble,
  meal: Utensils,
  activity: Landmark,
  free_time: Clock,
}

function travelersLabel(n: number) {
  return `${n} ${n === 1 ? 'traveler' : 'travelers'}`
}

/** Profile chips (plan header and empty state). Missing required details show muted and dashed. */
export function ProfileChips({ profile }: { profile: TripProfile }) {
  return (
    <>
      {profileChips(profile).map((chip) =>
        chip.missing ? (
          <span
            key={chip.field}
            title="Not given yet — tell me in the chat"
            className="rounded-full border border-dashed border-gray-300 px-2.5 py-1 text-xs text-gray-400"
          >
            {chip.label}
          </span>
        ) : (
          <span key={chip.field} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-700">
            {chip.label}
          </span>
        ),
      )}
    </>
  )
}

interface EmptyPlanProps {
  profile: TripProfile | null
  generating: boolean
  planStatus: string | null
  canGenerate: boolean
  onGenerate: () => void
}

/** The current status line and skeleton day cards, shown while a plan is being made. */
function PlanSkeleton({ planStatus }: { planStatus: string | null }) {
  return (
    <>
      <p role="status" className="mt-5 flex items-center gap-2 font-medium text-accent">
        <Sparkles size={14} className="animate-pulse" /> {planStatus ?? 'Starting…'}
      </p>
      <div className="mt-5 w-full max-w-xl space-y-4" aria-hidden="true">
        {[1, 2].map((n) => (
          <div
            key={n}
            data-testid="skeleton-day"
            className="animate-pulse rounded-xl border border-gray-200 bg-white p-4 text-left shadow-sm"
          >
            <div className="h-3 w-40 rounded bg-gray-200" />
            {[1, 2, 3].map((row) => (
              <div key={row} className="mt-4 flex items-center gap-3">
                <div className="h-6 w-6 shrink-0 rounded-full bg-gray-200" />
                <div className="h-3 flex-1 rounded bg-gray-100" />
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  )
}

/** No plan yet: the profile so far and a Generate button, or skeleton day cards while generating. */
function EmptyPlan({ profile, generating, planStatus, canGenerate, onGenerate }: EmptyPlanProps) {
  return (
    <div className="flex h-full flex-col items-center overflow-y-auto px-6 py-10 text-center text-sm text-gray-500">
      <p>Your trip plan will appear here</p>
      {profile && (
        <div className="mt-3 flex max-w-lg flex-wrap justify-center gap-1.5">
          <ProfileChips profile={profile} />
        </div>
      )}
      {generating ? (
        <PlanSkeleton planStatus={planStatus} />
      ) : (
        <button
          type="button"
          onClick={onGenerate}
          disabled={!canGenerate}
          className="mt-5 inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Sparkles size={14} /> Generate
        </button>
      )}
    </div>
  )
}

interface Props {
  itinerary: Itinerary | null
  profile: TripProfile | null
  selectedTag: string | null
  onTagClick: (tag: string) => void
  generating?: boolean // a plan is being made (shows skeletons when there is no plan yet)
  // The Regenerate button's run is in progress: skeletons replace the current plan. A chat edit
  // keeps the plan on screen instead (its progress shows as chat status lines).
  regenerating?: boolean
  planStatus?: string | null // the current status label while generating
  canGenerate?: boolean // false while a reply is streaming
  onGenerate?: () => void // the empty-state Generate button and the header Regenerate button
}

export function PlanView({
  itinerary, profile, selectedTag, onTagClick,
  generating = false, regenerating = false, planStatus = null, canGenerate = true, onGenerate = () => {},
}: Props) {
  if (itinerary && regenerating) {
    return (
      <div className="flex h-full flex-col items-center overflow-y-auto px-6 py-10 text-center text-sm text-gray-500">
        <p>Making a new version of your plan…</p>
        <PlanSkeleton planStatus={planStatus} />
      </div>
    )
  }
  if (!itinerary) {
    return (
      <EmptyPlan
        profile={profile}
        generating={generating}
        planStatus={planStatus}
        canGenerate={canGenerate}
        onGenerate={onGenerate}
      />
    )
  }
  return (
    <PlanDetails
      itinerary={itinerary}
      profile={profile}
      selectedTag={selectedTag}
      onTagClick={onTagClick}
      canGenerate={canGenerate}
      onGenerate={onGenerate}
    />
  )
}

interface PlanDetailsProps {
  itinerary: Itinerary
  profile: TripProfile | null
  selectedTag: string | null
  onTagClick: (tag: string) => void
  canGenerate: boolean
  onGenerate: () => void
}

function PlanDetails({ itinerary, profile, selectedTag, onTagClick, canGenerate, onGenerate }: PlanDetailsProps) {
  const [showAssumptions, setShowAssumptions] = useState(false)
  const stopsByTag = new Map(itinerary.stops.map((s) => [s.tag, s]))
  const lodgingByTag = new Map(itinerary.lodging.map((l) => [l.stop_tag, l]))
  const firstDay = firstDayByTag(itinerary)
  const costRange = itinerary.cost_estimate ? ` · ${formatCostRange(itinerary.cost_estimate)} per person` : ''
  // The summary chip borrows the first day's icon; the credit shows whenever any weather is shown.
  const summaryIcon = itinerary.days.find((d) => d.weather)?.weather?.icon ?? null
  const hasWeather = itinerary.weather_summary !== null || summaryIcon !== null

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <header className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">{itinerary.title}</h1>
            <p className="mt-0.5 text-sm text-gray-500">
              {formatDate(itinerary.start_date)} – {formatDate(itinerary.end_date)} · {travelersLabel(itinerary.travelers)}
              {costRange}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2">
            <span className="rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent">
              v{itinerary.version} · {itinerary.version === 1 ? 'created' : 'updated'} {formatTimestamp(itinerary.created_at)}
            </span>
            <button
              type="button"
              onClick={onGenerate}
              disabled={!canGenerate}
              title="Make a fresh version of this plan"
              className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={12} /> Regenerate
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {profile && <ProfileChips profile={profile} />}
          {itinerary.weather_summary && (
            <span data-testid="weather-summary" className="rounded-full bg-sky-50 px-2.5 py-1 text-xs text-sky-700">
              {summaryIcon && `${summaryIcon} `}
              {itinerary.weather_summary}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setShowAssumptions((s) => !s)}
          className="mt-3 flex items-center gap-1 text-xs font-medium text-amber-700"
        >
          <Sparkles size={14} /> {itinerary.assumptions.length} assumptions made
          <ChevronDown size={14} className={showAssumptions ? 'rotate-180' : ''} />
        </button>
        {showAssumptions && (
          <ul className="mt-1.5 list-disc pl-5 text-xs text-gray-600">
            {itinerary.assumptions.map((a) => <li key={a}>{a}</li>)}
          </ul>
        )}
      </header>

      {itinerary.days.map((day) => (
        <section key={day.day_number} className="mt-6">
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-gray-800">
              Day {day.day_number} · {formatDate(day.date)}
              <span className="font-normal text-gray-500"> — {day.title}</span>
            </h2>
            {day.weather && <WeatherChip weather={day.weather} />}
          </div>
          <ol className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white shadow-sm">
            {day.items.map((item) => (
              <Entry
                key={item.id}
                item={item}
                stop={item.stop_tag ? stopsByTag.get(item.stop_tag) : undefined}
                lodging={item.stop_tag ? lodgingByTag.get(item.stop_tag) : undefined}
                day={item.stop_tag ? (firstDay.get(item.stop_tag) ?? day.day_number) : day.day_number}
                version={itinerary.version}
                selected={item.stop_tag !== null && selectedTag === item.stop_tag}
                onTagClick={onTagClick}
              />
            ))}
          </ol>
        </section>
      ))}
      {/* Open-Meteo's free tier asks for this attribution. */}
      {hasWeather && (
        <p className="pt-6 text-center text-xs text-gray-400">
          <a href="https://open-meteo.com/" target="_blank" rel="noreferrer" className="hover:underline">
            Weather data by Open-Meteo.com
          </a>
        </p>
      )}
      {/* v0 footer with a fixed timestamp: only the demo trip shows it. */}
      {demo.enabled && (
        <p className="py-6 text-center text-xs text-gray-400">
          Estimates only · prices as of Nov 1, 6:04 PM and may change
        </p>
      )}
    </div>
  )
}

/** A day's weather: "☀️ 66° / 48°", plus "avg" when it is a climate average, not a forecast. */
function WeatherChip({ weather }: { weather: DayWeather }) {
  const climate = weather.source === 'climate'
  return (
    <span
      data-testid="weather-chip"
      title={climate ? `Typical ${weather.condition} weather for these dates (past years)` : `Forecast: ${weather.condition}`}
      className="text-xs text-gray-500"
    >
      {weather.icon} {Math.round(weather.high_f)}° / {Math.round(weather.low_f)}°
      {climate && <span className="ml-1 rounded bg-gray-100 px-1 text-[10px] font-medium text-gray-500">avg</span>}
    </span>
  )
}

interface EntryProps {
  item: ItineraryItem
  stop: Stop | undefined
  lodging: Lodging | undefined // the hotel details when this item is a lodging stop
  day: number
  version: number
  selected: boolean
  onTagClick: (tag: string) => void
}

function Entry({ item, stop, lodging, day, version, selected, onTagClick }: EntryProps) {
  const tag = item.stop_tag
  const [open, setOpen] = useState(tag !== null && demo.why === tag)
  const ref = useRef<HTMLLIElement>(null)
  const Icon = KIND_ICON[item.kind]
  const updated = version > 1 && item.updated_in_version === version
  // A hotel item's est_cost is per night; its "as of" time comes from the lodging entry (tool price).
  const nights = item.kind === 'lodging' ? item.nights : null
  const cost = nights !== null ? formatPerNight(item.est_cost) : formatMoney(item.est_cost)
  const length = nights !== null ? formatNights(nights) : formatDuration(item.duration_min)
  const asOf = nights !== null && item.est_cost && lodging?.price_as_of ? formatAsOf(lodging.price_as_of) : null
  const leg = item.transit_from_previous

  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [selected])

  return (
    <li
      ref={ref}
      className={`relative px-4 py-3 ${updated ? 'bg-amber-50' : ''} ${selected ? 'flash' : ''}`}
    >
      {updated && <span className="absolute inset-y-0 left-0 w-1 rounded-l-xl bg-amber-400" />}
      <div className="flex gap-3">
        <div className="flex w-16 shrink-0 flex-col items-center gap-1 pt-0.5">
          {tag && <TagBadge tag={tag} day={day} onClick={() => onTagClick(tag)} />}
          <span className="text-[11px] text-gray-400">{formatTime(item.start_time)}</span>
        </div>
        <div className="min-w-0 flex-1">
          {leg && (
            <p
              data-testid="transit-leg"
              title={leg.estimated ? 'Estimated travel time from the previous stop' : undefined}
              className="mb-1 text-[11px] text-gray-400"
            >
              ↓ {formatTransitLeg(leg)}
            </p>
          )}
          <p className="leading-snug">
            {stop && (
              <>
                <span className="mr-1 inline-flex items-center gap-1 rounded-md border border-gray-300 px-1.5 py-0.5 text-sm font-medium">
                  <Icon size={13} className="text-gray-500" />
                  {stop.name}
                </span>
                {stop.map_url && (
                  <a
                    href={stop.map_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open ${stop.name} in Google Maps`}
                    title="Open in Google Maps"
                    className="mr-0.5 inline-flex align-middle text-gray-400 hover:text-gray-700"
                  >
                    <ExternalLink size={12} />
                  </a>
                )}
                <span className="text-gray-400">: </span>
              </>
            )}
            <span className="text-sm text-gray-700">{item.description}</span>
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium text-gray-600">
              Est: {cost}{length && ` | ${length}`}
            </span>
            {asOf && <span className="text-gray-400">{asOf}</span>}
            {item.booking_required && (
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-indigo-700">
                <Ticket size={11} /> Needs booking
              </span>
            )}
            {updated && (
              <span className="rounded-full bg-amber-200 px-2 py-0.5 font-medium text-amber-900">
                Updated in v{item.updated_in_version}
              </span>
            )}
            {(item.why || item.source) && (
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="ml-auto inline-flex items-center gap-1 text-gray-400 hover:text-gray-700"
              >
                <Info size={13} /> Why this?
              </button>
            )}
          </div>
          {open && (item.why || item.source) && (
            <div className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
              {item.why && <p className="mb-1">{item.why}</p>}
              {item.source && <p className="text-gray-400">Source: {item.source}</p>}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}
