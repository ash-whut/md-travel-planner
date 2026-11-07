// Display helpers for the trip profile (contracts §2.1): the chat-header stepper and the
// plan-header chips. The server computes `missing_required`, so "known" here means "not in
// missing_required"; that keeps the date rules (exact dates or length + rough timing) in one place.
import type { RequiredField, TripProfile } from '@/types'
import { formatDateRange, formatShortDate } from './format'

export type StepId = 'profile' | 'trip' | 'plan'

export interface StepState {
  id: StepId
  label: string
  done: boolean
}

export interface ProfileChip {
  field: RequiredField | 'dietary'
  label: string
  missing: boolean // a required detail not given yet: shown muted
}

function isKnown(profile: TripProfile, fields: RequiredField[]): boolean {
  return fields.every((f) => !profile.missing_required.includes(f))
}

/** Profile — Trip details — Plan. With no profile loaded yet, nothing is done. */
export function stepperState(profile: TripProfile | null, hasPlan: boolean): StepState[] {
  return [
    { id: 'profile', label: 'Profile', done: profile !== null && isKnown(profile, ['origin', 'travelers', 'interests']) },
    { id: 'trip', label: 'Trip details', done: profile !== null && isKnown(profile, ['destination', 'dates']) },
    { id: 'plan', label: 'Plan', done: hasPlan },
  ]
}

function travelersLabel(n: number): string {
  return `${n} ${n === 1 ? 'traveler' : 'travelers'}`
}

function daysLabel(n: number): string {
  return `${n} ${n === 1 ? 'day' : 'days'}`
}

function destinationLabel(p: TripProfile): string | null {
  if (p.cities.length) return p.cities.join(' + ')
  return p.vibe
}

// "Mar 5–7", or "Mar 5 · 3 days", or "first weekend of March · 3 days".
function datesLabel(p: TripProfile): string | null {
  if (p.start_date && p.end_date) return formatDateRange(p.start_date, p.end_date)
  const length = p.duration_days ? ` · ${daysLabel(p.duration_days)}` : ''
  if (p.start_date) return `${formatShortDate(p.start_date)}${length}`
  if (p.rough_timing) return `${p.rough_timing}${length}`
  return null
}

// Icon, muted placeholder and value text for each required detail.
const REQUIRED: Record<RequiredField, { icon: string; placeholder: string; value: (p: TripProfile) => string | null }> = {
  destination: { icon: '📍', placeholder: 'Destination', value: destinationLabel },
  origin: { icon: '🏠', placeholder: 'Starting from', value: (p) => p.origin },
  dates: { icon: '📅', placeholder: 'Dates', value: datesLabel },
  travelers: { icon: '👤', placeholder: 'Travelers', value: (p) => (p.travelers ? travelersLabel(p.travelers) : null) },
  interests: { icon: '🎯', placeholder: 'Interests', value: (p) => (p.interests.length ? p.interests.join(', ') : null) },
}

function requiredChip(profile: TripProfile, field: RequiredField): ProfileChip | null {
  const { icon, placeholder, value } = REQUIRED[field]
  const missing = profile.missing_required.includes(field)
  const text = missing ? placeholder : value(profile)
  return text ? { field, label: `${icon} ${text}`, missing } : null
}

function dietaryChip(profile: TripProfile): ProfileChip | null {
  if (!profile.dietary) return null
  const dietary = `${profile.dietary.charAt(0).toUpperCase()}${profile.dietary.slice(1)}`
  return { field: 'dietary', label: `🌱 ${dietary}`, missing: false }
}

/** Header chips in the v0 order: known details ("📍 San Jose, CA") plus muted placeholders for missing ones. */
export function profileChips(profile: TripProfile): ProfileChip[] {
  const chips = [
    requiredChip(profile, 'destination'),
    requiredChip(profile, 'origin'),
    requiredChip(profile, 'dates'),
    requiredChip(profile, 'travelers'),
    dietaryChip(profile), // optional, shown only when known
    requiredChip(profile, 'interests'),
  ]
  return chips.filter((chip): chip is ProfileChip => chip !== null)
}
