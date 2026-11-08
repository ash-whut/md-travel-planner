// Letter tags (contracts §2.5): day colours, and the "[C]" tokens in chat text.
import type { Itinerary } from '@/types'

export const DAY_COLORS = ['#2563eb', '#d97706', '#059669', '#9333ea']

export function dayColor(day: number) {
  return DAY_COLORS[(day - 1) % DAY_COLORS.length]
}

// A tag takes the color of the day it first appears on (docs/spec.md F4).
export function firstDayByTag(itinerary: Itinerary | null): Map<string, number> {
  const firstDay = new Map<string, number>()
  for (const day of itinerary?.days ?? []) {
    for (const item of day.items) {
      if (item.stop_tag && !firstDay.has(item.stop_tag)) firstDay.set(item.stop_tag, day.day_number)
    }
  }
  return firstDay
}

export type TagSegment = { kind: 'text'; text: string } | { kind: 'tag'; tag: string }

// "[A]"…"[ZZ]", but not when "(" follows: then it is a markdown link like "[A](url)".
const TAG_TOKEN = /\[([A-Z]{1,2})\](?!\()/g

// True for a bare tag name like "C" or "AA".
export function isTag(text: string): boolean {
  return /^[A-Z]{1,2}$/.test(text)
}

// Splits chat text into plain text and tag tokens. "[abc]" and markdown links stay text.
export function parseTagTokens(text: string): TagSegment[] {
  const segments: TagSegment[] = []
  let last = 0
  for (const match of text.matchAll(TAG_TOKEN)) {
    if (match.index > last) segments.push({ kind: 'text', text: text.slice(last, match.index) })
    segments.push({ kind: 'tag', tag: match[1] })
    last = match.index + match[0].length
  }
  if (last < text.length) segments.push({ kind: 'text', text: text.slice(last) })
  return segments
}

// The href markdown gets for a tag token, so the link renderer can turn it into a chip.
const TAG_HREF = '#tag-'

// True for the href tagsToLinks gave the tag token `tag`.
export function isTagHref(href: string | undefined, tag: string): boolean {
  return href === TAG_HREF + tag
}

// Markdown with every tag token turned into a "#tag-C" link.
export function tagsToLinks(text: string): string {
  return parseTagTokens(text)
    .map((s) => (s.kind === 'tag' ? `[${s.tag}](${TAG_HREF}${s.tag})` : s.text))
    .join('')
}

// Puts "[C] " in place of the selection [start, end), with a space before it if needed.
// Returns the new text and where the cursor goes (just after the inserted tag).
export function insertTag(text: string, start: number, end: number, tag: string): { text: string; cursor: number } {
  const before = text.slice(0, start)
  const after = text.slice(end)
  const insert = `${before && !/\s$/.test(before) ? ' ' : ''}[${tag}] `
  return { text: before + insert + after, cursor: before.length + insert.length }
}
