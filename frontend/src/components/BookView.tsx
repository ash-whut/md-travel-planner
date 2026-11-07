import { useState } from 'react'
import { ArrowRight, CheckCircle2, ExternalLink, ShieldCheck } from 'lucide-react'
import { demo } from '@/demoParams'
import { formatDuration, formatMoney } from '@/lib/format'
import type { Booking, Itinerary } from '@/types'
import { TagBadge, firstDayByTag } from './TagBadge'

// "$300 | 6 hr" for a flight, "$240 total ($120/night)" for a hotel, else just the price.
function estimateLabel(booking: Booking, itinerary: Itinerary): string {
  const price = formatMoney(booking.estimate)
  if (booking.estimate === null) return price
  if (booking.kind === 'lodging') {
    const lodging = itinerary.lodging.find((l) => l.stop_tag === booking.tags[0])
    if (lodging?.price_per_night) return `${price} total (${formatMoney(lodging.price_per_night)}/night)`
  }
  if (booking.kind === 'flight') {
    const item = itinerary.days.flatMap((d) => d.items).find((i) => i.booking_id === booking.id)
    if (item?.duration_min) return `${price} | ${formatDuration(item.duration_min)}`
  }
  return price
}

function providerOf(booking: Booking): string {
  return booking.links[0]?.label ?? 'the provider site'
}

// ?confirm=flight opens the dialog for booking "bk-flight" (an exact booking id works too).
function demoBooking(bookings: Booking[]): Booking | null {
  if (!demo.confirm) return null
  return bookings.find((b) => b.id === demo.confirm || b.id === `bk-${demo.confirm}`) ?? null
}

interface Props {
  itinerary: Itinerary
  onTagClick: (tag: string) => void
}

export function BookView({ itinerary, onTagClick }: Props) {
  const bookings = itinerary.bookings
  const [confirming, setConfirming] = useState<Booking | null>(() => demoBooking(bookings))
  const done = bookings.filter((b) => b.status === 'booked').length
  const firstDay = firstDayByTag(itinerary)

  return (
    <div className="relative h-full overflow-y-auto px-6 py-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-600">
          <b className="text-gray-900">{done} of {bookings.length}</b> booked
        </p>
        <p className="flex items-center gap-1 text-xs text-gray-500">
          <ShieldCheck size={14} className="text-emerald-600" /> Nothing is booked without your approval
        </p>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full bg-emerald-500"
          style={{ width: `${bookings.length ? (done / bookings.length) * 100 : 0}%` }}
        />
      </div>

      <ul className="mt-4 space-y-3">
        {bookings.map((b) => (
          <li key={b.id} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-1.5">
              {b.tags.map((t, i) => (
                <span key={t} className="flex items-center gap-1.5">
                  {i > 0 && <ArrowRight size={14} className="text-gray-400" />}
                  <TagBadge tag={t} day={firstDay.get(t) ?? 1} onClick={() => onTagClick(t)} />
                </span>
              ))}
              <h3 className="ml-1.5 font-semibold">{b.title}</h3>
            </div>
            <p className="mt-2 text-sm font-medium text-gray-700">Est: {estimateLabel(b, itinerary)}</p>
            <p className="text-xs text-gray-500">{b.details}</p>
            <div className="mt-3">
              {b.status === 'booked' ? (
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
            <p className="mt-2 text-sm text-gray-600">{confirming.details}</p>
            <p className="mt-1 text-sm font-medium">Est: {estimateLabel(confirming, itinerary)}</p>
            <p className="mt-3 text-xs text-gray-500">
              You’ll finish booking on <b>{providerOf(confirming)}</b>. We pre-fill the search; you confirm and pay there.
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
                Continue to {providerOf(confirming)} <ExternalLink size={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
