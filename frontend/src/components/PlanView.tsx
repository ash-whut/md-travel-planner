import { useEffect, useRef, useState } from 'react'
import {
  BedDouble, Car, ChevronDown, Clock, Info, Landmark, Plane, Sparkles, Ticket, Utensils,
} from 'lucide-react'
import { demo } from '@/demoParams'
import {
  formatCostRange, formatDate, formatDateRange, formatDuration, formatMoney, formatNights, formatTime,
} from '@/lib/format'
import type { ItemKind, Itinerary, ItineraryItem, Stop, TripProfile } from '@/types'
import { TagBadge, firstDayByTag } from './TagBadge'

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

// Header chips for the known profile fields. Step 17 moves this to lib/profile.ts.
function profileChips(profile: TripProfile): string[] {
  const chips: string[] = []
  if (profile.cities.length) chips.push(`📍 ${profile.cities.join(' + ')}`)
  if (profile.origin) chips.push(`🏠 ${profile.origin}`)
  if (profile.start_date && profile.end_date) chips.push(`📅 ${formatDateRange(profile.start_date, profile.end_date)}`)
  if (profile.travelers) chips.push(`👤 ${travelersLabel(profile.travelers)}`)
  if (profile.dietary) chips.push(`🌱 ${profile.dietary.charAt(0).toUpperCase()}${profile.dietary.slice(1)}`)
  if (profile.interests.length) chips.push(`🎯 ${profile.interests.join(', ')}`)
  return chips
}

interface Props {
  itinerary: Itinerary
  profile: TripProfile
  selectedTag: string | null
  onTagClick: (tag: string) => void
}

export function PlanView({ itinerary, profile, selectedTag, onTagClick }: Props) {
  const [showAssumptions, setShowAssumptions] = useState(false)
  const stopsByTag = new Map(itinerary.stops.map((s) => [s.tag, s]))
  const firstDay = firstDayByTag(itinerary)
  const costRange = itinerary.cost_estimate ? ` · ${formatCostRange(itinerary.cost_estimate)} per person` : ''

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
          <span className="shrink-0 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent">
            v{itinerary.version} · updated just now
          </span>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {profileChips(profile).map((label) => (
            <span key={label} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-700">
              {label}
            </span>
          ))}
          {itinerary.weather_summary && (
            <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs text-sky-700">☀️ {itinerary.weather_summary}</span>
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
            {day.weather && (
              <span className="text-xs text-gray-500">
                {day.weather.icon} {Math.round(day.weather.high_f)}° / {Math.round(day.weather.low_f)}°
              </span>
            )}
          </div>
          <ol className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white shadow-sm">
            {day.items.map((item) => (
              <Entry
                key={item.id}
                item={item}
                stop={item.stop_tag ? stopsByTag.get(item.stop_tag) : undefined}
                day={item.stop_tag ? (firstDay.get(item.stop_tag) ?? day.day_number) : day.day_number}
                version={itinerary.version}
                selected={item.stop_tag !== null && selectedTag === item.stop_tag}
                onTagClick={onTagClick}
              />
            ))}
          </ol>
        </section>
      ))}
      {/* v0 footer with a fixed timestamp: only the demo trip shows it. */}
      {demo.enabled && (
        <p className="py-6 text-center text-xs text-gray-400">
          Estimates only · prices as of Nov 1, 6:04 PM and may change
        </p>
      )}
    </div>
  )
}

interface EntryProps {
  item: ItineraryItem
  stop: Stop | undefined
  day: number
  version: number
  selected: boolean
  onTagClick: (tag: string) => void
}

function Entry({ item, stop, day, version, selected, onTagClick }: EntryProps) {
  const tag = item.stop_tag
  const [open, setOpen] = useState(tag !== null && demo.why === tag)
  const ref = useRef<HTMLLIElement>(null)
  const Icon = KIND_ICON[item.kind]
  const updated = version > 1 && item.updated_in_version === version
  const length = item.kind === 'lodging' && item.nights !== null ? formatNights(item.nights) : formatDuration(item.duration_min)

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
          <p className="leading-snug">
            {stop && (
              <>
                <span className="mr-1 inline-flex items-center gap-1 rounded-md border border-gray-300 px-1.5 py-0.5 text-sm font-medium">
                  <Icon size={13} className="text-gray-500" />
                  {stop.name}
                </span>
                <span className="text-gray-400">: </span>
              </>
            )}
            <span className="text-sm text-gray-700">{item.description}</span>
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium text-gray-600">
              Est: {formatMoney(item.est_cost)}{length && ` | ${length}`}
            </span>
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
            {item.why && (
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="ml-auto inline-flex items-center gap-1 text-gray-400 hover:text-gray-700"
              >
                <Info size={13} /> Why this?
              </button>
            )}
          </div>
          {open && item.why && (
            <div className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
              <p>{item.why}</p>
              {item.source && <p className="mt-1 text-gray-400">Source: {item.source}</p>}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}
