import { useEffect, useRef, useState } from 'react'
import {
  BedDouble, Car, ChevronDown, Info, Landmark, Plane, Sparkles, Ticket, Utensils,
} from 'lucide-react'
import { trip } from '@/fixtures'
import { demo } from '@/demoParams'
import type { ItemKind, PlanItem } from '@/types'
import { TagBadge } from './TagBadge'

const KIND_ICON: Record<ItemKind, typeof Car> = {
  transit: Car,
  flight: Plane,
  lodging: BedDouble,
  meal: Utensils,
  activity: Landmark,
}

interface Props {
  selectedTag: string | null
  onTagClick: (tag: string) => void
}

export function PlanView({ selectedTag, onTagClick }: Props) {
  const [showAssumptions, setShowAssumptions] = useState(false)

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <header className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">{trip.title}</h1>
            <p className="mt-0.5 text-sm text-gray-500">
              {trip.dates} · {trip.travelers} traveler · {trip.costRange} per person
            </p>
          </div>
          <span className="shrink-0 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent">
            v{trip.version} · updated just now
          </span>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {trip.profile.map((p) => (
            <span key={p.label} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-700">
              {p.label}
            </span>
          ))}
          <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs text-sky-700">☀️ {trip.weatherSummary}</span>
        </div>
        <button
          type="button"
          onClick={() => setShowAssumptions((s) => !s)}
          className="mt-3 flex items-center gap-1 text-xs font-medium text-amber-700"
        >
          <Sparkles size={14} /> {trip.assumptions.length} assumptions made
          <ChevronDown size={14} className={showAssumptions ? 'rotate-180' : ''} />
        </button>
        {showAssumptions && (
          <ul className="mt-1.5 list-disc pl-5 text-xs text-gray-600">
            {trip.assumptions.map((a) => <li key={a}>{a}</li>)}
          </ul>
        )}
      </header>

      {trip.days.map((day) => (
        <section key={day.dayNumber} className="mt-6">
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-gray-800">
              Day {day.dayNumber} · {day.date}
              <span className="font-normal text-gray-500"> — {day.title}</span>
            </h2>
            <span className="text-xs text-gray-500">
              {day.weather.icon} {day.weather.high}° / {day.weather.low}°
            </span>
          </div>
          <ol className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white shadow-sm">
            {day.items.map((item, i) => (
              <Entry
                key={`${item.tag}-${i}`}
                item={item}
                selected={selectedTag === item.tag}
                onTagClick={onTagClick}
              />
            ))}
          </ol>
        </section>
      ))}
      <p className="py-6 text-center text-xs text-gray-400">
        Estimates only · prices as of Nov 1, 6:04 PM and may change
      </p>
    </div>
  )
}

function Entry({ item, selected, onTagClick }: { item: PlanItem; selected: boolean; onTagClick: (t: string) => void }) {
  const [open, setOpen] = useState(demo.why === item.tag)
  const ref = useRef<HTMLLIElement>(null)
  const Icon = KIND_ICON[item.kind]
  const updated = item.updatedInVersion === trip.version

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
          <TagBadge tag={item.tag} onClick={() => onTagClick(item.tag)} />
          <span className="text-[11px] text-gray-400">{item.startTime}</span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="leading-snug">
            <span className="mr-1 inline-flex items-center gap-1 rounded-md border border-gray-300 px-1.5 py-0.5 text-sm font-medium">
              <Icon size={13} className="text-gray-500" />
              {item.place}
            </span>
            <span className="text-gray-400">: </span>
            <span className="text-sm text-gray-700">{item.action}</span>
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium text-gray-600">
              Est: {item.cost === null ? '—' : `$${item.cost}`} | {item.duration}
            </span>
            {item.bookable && (
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-indigo-700">
                <Ticket size={11} /> Needs booking
              </span>
            )}
            {updated && (
              <span className="rounded-full bg-amber-200 px-2 py-0.5 font-medium text-amber-900">
                Updated in v{item.updatedInVersion}
              </span>
            )}
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              className="ml-auto inline-flex items-center gap-1 text-gray-400 hover:text-gray-700"
            >
              <Info size={13} /> Why this?
            </button>
          </div>
          {open && (
            <div className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
              <p>{item.why}</p>
              <p className="mt-1 text-gray-400">Source: {item.source}</p>
            </div>
          )}
        </div>
      </div>
    </li>
  )
}
