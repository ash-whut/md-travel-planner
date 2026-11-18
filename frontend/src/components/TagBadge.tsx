import { dayColor } from '@/lib/tags'

interface Props {
  tag: string
  day: number // the day the tag first appears on; picks the colour
  size?: 'sm' | 'md'
  onClick?: () => void
}

export function TagBadge({ tag, day, size = 'md', onClick }: Props) {
  const dim = size === 'sm' ? 'h-5 min-w-5 text-[11px]' : 'h-7 min-w-7 text-sm'
  const className = `${dim} inline-flex shrink-0 items-center justify-center rounded-full px-1 font-semibold text-white shadow-sm ring-2 ring-white transition hover:scale-110`
  const title = `Refer to this as "${tag}" in chat`
  const style = { backgroundColor: dayColor(day) }

  // Without a click handler the badge is a plain span, so it can sit inside another button.
  if (!onClick) {
    return (
      <span title={title} className={className} style={style}>
        {tag}
      </span>
    )
  }
  return (
    <button type="button" onClick={onClick} title={title} className={className} style={style}>
      {tag}
    </button>
  )
}
