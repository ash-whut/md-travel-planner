import { trip } from '@/fixtures'

export const DAY_COLORS = ['#2563eb', '#d97706', '#059669', '#9333ea']

// A tag takes the color of the day it first appears on (docs/04-ui-spec.md §3).
const firstDay = new Map<string, number>()
for (const day of trip.days) {
  for (const item of day.items) {
    if (!firstDay.has(item.tag)) firstDay.set(item.tag, day.dayNumber)
  }
}

export function tagColor(tag: string) {
  return DAY_COLORS[((firstDay.get(tag) ?? 1) - 1) % DAY_COLORS.length]
}

interface Props {
  tag: string
  size?: 'sm' | 'md'
  onClick?: () => void
}

export function TagBadge({ tag, size = 'md', onClick }: Props) {
  const dim = size === 'sm' ? 'h-5 min-w-5 text-[11px]' : 'h-7 min-w-7 text-sm'
  return (
    <button
      type="button"
      onClick={onClick}
      title={`Refer to this as "${tag}" in chat`}
      className={`${dim} inline-flex shrink-0 items-center justify-center rounded-full px-1 font-semibold text-white shadow-sm ring-2 ring-white transition hover:scale-110`}
      style={{ backgroundColor: tagColor(tag) }}
    >
      {tag}
    </button>
  )
}
