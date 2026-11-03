import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import { trip } from '@/fixtures'
import { demo } from '@/demoParams'
import type { PlanItem } from '@/types'
import { DAY_COLORS, TagBadge, tagColor } from './TagBadge'

type Located = PlanItem & { lat: number; lng: number; day: number }

function pinIcon(tag: string, active: boolean) {
  const size = active ? 34 : 28
  return L.divIcon({
    className: 'tag-pin',
    iconSize: [size, size + 8],
    iconAnchor: [size / 2, size + 8],
    popupAnchor: [0, -size],
    html: `<div style="display:flex;flex-direction:column;align-items:center">
      <div style="width:${size}px;height:${size}px;border-radius:9999px;background:${tagColor(tag)};
        color:white;font-weight:700;font-size:${active ? 15 : 13}px;display:flex;align-items:center;
        justify-content:center;border:3px solid white;box-shadow:0 2px 6px rgba(0,0,0,.35)">${tag}</div>
      <div style="width:2px;height:8px;background:${tagColor(tag)}"></div></div>`,
  })
}

function FitAndFocus({ points, focus }: { points: Located[]; focus: Located | null }) {
  const map = useMap()
  const container = useRef(map.getContainer())

  // Keep tiles correct when the split divider is dragged.
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(container.current)
    return () => ro.disconnect()
  }, [map])

  useEffect(() => {
    if (focus) map.flyTo([focus.lat, focus.lng], 15, { duration: 0.6 })
    else if (points.length) map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng])), {
        paddingTopLeft: [40, 70],
        paddingBottomRight: [240, 40], // leave room for the stops list
      })
  }, [map, points, focus])
  return null
}

interface Props {
  selectedTag: string | null
  onTagClick: (tag: string) => void
}

export function MapView({ selectedTag, onTagClick }: Props) {
  const [day, setDay] = useState<number | 'all'>(demo.day ? Number(demo.day) : 'all')

  const located = useMemo<Located[]>(
    () =>
      trip.days.flatMap((d) =>
        d.items
          .filter((i): i is PlanItem & { lat: number; lng: number } => i.lat !== undefined && i.lng !== undefined)
          .map((i) => ({ ...i, day: d.dayNumber })),
      ),
    [],
  )
  const visible = useMemo(() => located.filter((p) => day === 'all' || p.day === day), [located, day])
  const markers = useMemo(() => {
    const seen = new Map<string, Located>()
    for (const p of visible) if (!seen.has(p.tag)) seen.set(p.tag, p)
    return [...seen.values()]
  }, [visible])
  const focus = markers.find((m) => m.tag === selectedTag) ?? null
  const offMap = trip.days.flatMap((d) => d.items).filter((i) => i.lat === undefined)

  return (
    <div className="relative h-full">
      <MapContainer center={[37.335, -121.9]} zoom={12} className="h-full w-full" zoomControl={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {trip.days
          .filter((d) => day === 'all' || d.dayNumber === day)
          .map((d) => (
            <Polyline
              key={d.dayNumber}
              positions={located.filter((p) => p.day === d.dayNumber).map((p) => [p.lat, p.lng])}
              pathOptions={{ color: DAY_COLORS[d.dayNumber - 1], weight: 4, opacity: 0.75, dashArray: '8 8' }}
            />
          ))}
        {markers.map((m) => (
          <Marker
            key={m.tag}
            position={[m.lat, m.lng]}
            icon={pinIcon(m.tag, m.tag === selectedTag)}
            eventHandlers={{ click: () => onTagClick(m.tag) }}
          >
            <Popup>
              <b>
                {m.tag} · {m.place}
              </b>
              <br />
              Day {m.day} · {m.startTime}
            </Popup>
          </Marker>
        ))}
        <FitAndFocus points={visible} focus={focus} />
      </MapContainer>

      <div className="absolute top-3 left-3 z-[1000] flex gap-1.5">
        {(['all', ...trip.days.map((d) => d.dayNumber)] as const).map((d) => (
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
          {markers.map((m) => (
            <li key={m.tag}>
              <button
                type="button"
                onClick={() => onTagClick(m.tag)}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-gray-50 ${
                  m.tag === selectedTag ? 'bg-amber-50' : ''
                }`}
              >
                <TagBadge tag={m.tag} size="sm" />
                <span className="truncate">{m.place}</span>
              </button>
            </li>
          ))}
        </ul>
        {day === 'all' || day === 1 ? (
          <div className="border-t border-gray-100 px-3 py-2 text-[11px] text-gray-400">
            Off map (Houston): {offMap.map((i) => i.tag).join(', ')}
          </div>
        ) : null}
      </div>
    </div>
  )
}
