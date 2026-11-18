import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import { demo } from '@/demoParams'
import { formatTime } from '@/lib/format'
import { bounds, offMapStops, polylineForDay, stopsForDay, type DayFilter, type MapStop } from '@/lib/map'
import { dayColor, firstDayByTag } from '@/lib/tags'
import type { Itinerary } from '@/types'
import { TagBadge } from './TagBadge'

const US_CENTER: [number, number] = [39.8, -98.6]

// A TagBadge-style pin: the tag in a day-coloured circle with a short stem.
function pinIcon(tag: string, color: string, active: boolean) {
  const size = active ? 34 : 28
  return L.divIcon({
    className: 'tag-pin',
    iconSize: [size, size + 8],
    iconAnchor: [size / 2, size + 8],
    popupAnchor: [0, -size],
    html: `<div style="display:flex;flex-direction:column;align-items:center">
      <div style="width:${size}px;height:${size}px;border-radius:9999px;background:${color};
        color:white;font-weight:700;font-size:${active ? 15 : 13}px;display:flex;align-items:center;
        justify-content:center;border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.35)">${tag}</div>
      <div style="width:2px;height:8px;background:${color}"></div></div>`,
  })
}

function FitAndFocus({ stops, focus }: { stops: MapStop[]; focus: MapStop | null }) {
  const map = useMap()
  const container = useRef(map.getContainer())

  // Keep tiles correct when the split divider is dragged.
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(container.current)
    return () => ro.disconnect()
  }, [map])

  useEffect(() => {
    const box = bounds(stops)
    if (focus) map.flyTo([focus.lat, focus.lng], 15, { duration: 0.6 })
    else if (box) map.fitBounds(box, {
        paddingTopLeft: [40, 70],
        paddingBottomRight: [240, 40], // leave room for the stops list
      })
  }, [map, stops, focus])
  return null
}

interface Props {
  itinerary: Itinerary
  selectedTag: string | null
  onTagClick: (tag: string) => void
}

export function MapView({ itinerary, selectedTag, onTagClick }: Props) {
  const [day, setDay] = useState<DayFilter>(demo.day ? Number(demo.day) : 'all')
  const firstDay = useMemo(() => firstDayByTag(itinerary), [itinerary])
  const stops = useMemo(() => stopsForDay(itinerary, day), [itinerary, day])
  const offMap = offMapStops(itinerary, day)
  const focus = stops.find((s) => s.tag === selectedTag) ?? null
  const shownDays = itinerary.days.filter((d) => day === 'all' || d.day_number === day)

  const city = itinerary.cities[0]
  const center: [number, number] = city && city.lat !== null && city.lng !== null ? [city.lat, city.lng] : US_CENTER

  return (
    <div className="relative h-full">
      <MapContainer center={center} zoom={12} className="h-full w-full" zoomControl={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {shownDays.map((d) => (
          <Polyline
            key={d.day_number}
            positions={polylineForDay(itinerary, d.day_number)}
            pathOptions={{ color: dayColor(d.day_number), weight: 4, opacity: 0.75, dashArray: '8 8' }}
          />
        ))}
        {stops.map((s) => (
          <Marker
            key={s.tag}
            position={[s.lat, s.lng]}
            icon={pinIcon(s.tag, dayColor(firstDay.get(s.tag) ?? 1), s.tag === selectedTag)}
            eventHandlers={{ click: () => onTagClick(s.tag) }}
          >
            <Popup>
              <b>
                {s.tag} · {s.name}
              </b>
              <br />
              Day {s.day} · {formatTime(s.startTime)}
            </Popup>
          </Marker>
        ))}
        <FitAndFocus stops={stops} focus={focus} />
      </MapContainer>

      <div className="absolute top-3 left-3 z-[1000] flex gap-1.5">
        {(['all', ...itinerary.days.map((d) => d.day_number)] as const).map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDay(d)}
            className={`rounded-full px-3 py-1 text-xs font-medium shadow ${
              day === d ? 'bg-gray-900 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'
            }`}
          >
            {d === 'all' ? 'All days' : `Day ${d}`}
          </button>
        ))}
      </div>

      <div className="absolute top-3 right-3 z-[1000] flex max-h-[calc(100%-1.5rem)] w-52 flex-col overflow-hidden rounded-xl bg-white/95 shadow-lg backdrop-blur">
        <p className="border-b border-gray-100 px-3 py-2 text-xs font-semibold text-gray-500">Stops</p>
        <ul className="flex-1 overflow-y-auto py-1">
          {stops.map((s) => (
            <li key={s.tag}>
              <button
                type="button"
                onClick={() => onTagClick(s.tag)}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-gray-50 ${
                  s.tag === selectedTag ? 'bg-amber-50' : ''
                }`}
              >
                <TagBadge tag={s.tag} day={firstDay.get(s.tag) ?? 1} size="sm" />
                <span className="min-w-0">
                  <span className="block truncate">{s.name}</span>
                  {s.tag === selectedTag && (
                    <span className="block text-[11px] text-gray-500">
                      Day {s.day} · {formatTime(s.startTime)}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {offMap.length > 0 && (
          <div className="border-t border-gray-100 px-3 py-2 text-[11px] text-gray-400">
            Off map: {offMap.join(', ')}
          </div>
        )}
      </div>
    </div>
  )
}
