// The v0 San Jose trip as contract-shaped JSON (docs/contracts.md §2). The JSON files in this
// folder are the one shared copy: backend tests load them too (step 18 validates them).
import type { StatusLine } from '../store/useTripStore'
import type { Itinerary, Message, SessionSummary, TripProfile } from '../types'
import v1 from './sanjose-v1.json'
import v2 from './sanjose-v2.json'
import profile from './sanjose-profile.json'
import messages from './sanjose-messages.json'

// TypeScript types JSON imports loosely (plain strings, bare nulls), so they are cast here.
export const sanJoseV1 = v1 as unknown as Itinerary
export const sanJoseV2 = v2 as unknown as Itinerary // [F] Baconhouse replaced by [L], updated in v2
export const sanJoseProfile = profile as unknown as TripProfile
export const sanJoseMessages = messages as unknown as Message[]

// Status lines are not stored messages (they come from SSE `status` events, step 31). For the
// demo they are shown just above the message they led to, keyed by message id.
export const sanJoseStatusLines: Record<string, StatusLine[]> = {
  m8: [
    { label: 'Checked weather for San Jose · Mar 5–7', state: 'end' },
    { label: 'Found 12 hotels under $150/night', state: 'end' },
  ],
  m10: [{ label: 'Searching vegan restaurants near downtown', state: 'end' }],
}

// The history rail in ?demo=1 (no backend): the v0 sketch's three trips. The first is the demo
// trip itself (id 'demo'), so it shows as the open one.
export function demoHistory(now: Date = new Date()): SessionSummary[] {
  const daysAgo = (days: number) => new Date(now.getTime() - days * 86_400_000).toISOString()
  return [
    { id: 'demo', title: 'San Jose · Mar 5–7', status: 'planned', updated_at: now.toISOString() },
    { id: 'demo-austin', title: 'Austin · Apr 10–12', status: 'planned', updated_at: daysAgo(3) },
    { id: 'demo-nola', title: 'New Orleans weekend', status: 'intake', updated_at: daysAgo(26) },
  ]
}
