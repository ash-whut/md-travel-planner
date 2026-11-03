import { useState } from 'react'
import { ArrowRight, CheckCircle2, ExternalLink, ShieldCheck } from 'lucide-react'
import { trip } from '@/fixtures'
import { demo } from '@/demoParams'
import type { BookingItem } from '@/types'
import { TagBadge } from './TagBadge'

interface Props {
  onTagClick: (tag: string) => void
}

export function BookView({ onTagClick }: Props) {
  const [confirming, setConfirming] = useState<BookingItem | null>(
    trip.bookings.find((b) => b.id === demo.confirm) ?? null,
  )
  const done = trip.bookings.filter((b) => b.done).length

  return (
    <div className="relative h-full overflow-y-auto px-6 py-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-600">
          <b className="text-gray-900">{done} of {trip.bookings.length}</b> booked
        </p>
        <p className="flex items-center gap-1 text-xs text-gray-500">
          <ShieldCheck size={14} className="text-emerald-600" /> Nothing is booked without your approval
        </p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200">
        <div className="h-full bg-emerald-500" style={{ width: `${(done / trip.bookings.length) * 100}%` }} />
      </div>

      <ul className="mt-4 space-y-3">
        {trip.bookings.map((b) => (
          <li key={b.id} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5">
              {b.tags.map((t, i) => (
                <span key={t} className="flex items-center gap-1.5">
                  {i > 0 && <ArrowRight size={14} className="text-gray-400" />}
                  <TagBadge tag={t} onClick={() => onTagClick(t)} />
                </span>
              ))}
              <h3 className="ml-1.5 font-semibold">{b.title}</h3>
            </div>
            <p className="mt-2 text-sm font-medium text-gray-700">Est: {b.estimate}</p>
            <p className="text-xs text-gray-500">{b.detail}</p>
            <div className="mt-3">
              {b.done ? (
                <span className="inline-flex items-center gap-1.5 text-sm font-medium text-emerald-700">
                  <CheckCircle2 size={16} /> Booked
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirming(b)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
                >
                  Book <ExternalLink size={14} />
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {confirming && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-gray-900/30 p-6">
          <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
            <h3 className="font-semibold">Book {confirming.title.replace(/ Booking$/, '').toLowerCase()}?</h3>
            <p className="mt-2 text-sm text-gray-600">{confirming.detail}</p>
            <p className="mt-1 text-sm font-medium">Est: {confirming.estimate}</p>
            <p className="mt-3 text-xs text-gray-500">
              You’ll finish booking on <b>{confirming.provider}</b>. We pre-fill the search; you confirm and pay there.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" onClick={() => setConfirming(null)} className="rounded-lg px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100">
                Cancel
              </button>
              <button
                type="button"
                onClick={() => setConfirming(null)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white"
              >
                Continue to {confirming.provider} <ExternalLink size={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
