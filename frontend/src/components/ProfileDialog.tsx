import { useState, type FormEvent } from 'react'
import { X } from 'lucide-react'
import type { BudgetLevel, Pace, TravelMode, Transport, UserProfile } from '@/types'

interface Props {
  username: string
  profile: UserProfile
  onSave: (profile: UserProfile) => Promise<void>
  onClose: () => void
}

const BUDGETS: BudgetLevel[] = ['budget', 'mid', 'splurge']
const PACES: Pace[] = ['relaxed', 'balanced', 'packed']
const TRANSPORTS: Transport[] = ['car', 'transit', 'rideshare', 'mixed']
const TRAVEL_MODES: TravelMode[] = ['flight', 'drive']

const field =
  'mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-normal outline-none focus:border-accent focus:ring-2 focus:ring-indigo-100'

// "Not set" is the empty option; the backend stores it as null.
function Choice<T extends string>(props: {
  label: string
  value: T | null
  options: T[]
  onChange: (value: T | null) => void
}) {
  return (
    <label className="block text-sm font-medium text-gray-700">
      {props.label}
      <select
        value={props.value ?? ''}
        onChange={(e) => props.onChange((e.target.value || null) as T | null)}
        className={field}
      >
        <option value="">Not set</option>
        {props.options.map((o) => (
          <option key={o} value={o}>
            {o[0].toUpperCase() + o.slice(1)}
          </option>
        ))}
      </select>
    </label>
  )
}

export function ProfileDialog({ username, profile, onSave, onClose }: Props) {
  const [draft, setDraft] = useState<UserProfile>(profile)
  const [interests, setInterests] = useState(profile.interests.join(', '))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function set<K extends keyof UserProfile>(key: K, value: UserProfile[K]) {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSave({ ...draft, interests: interests.split(',').map((s) => s.trim()).filter(Boolean) })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-gray-900/30 p-4" onClick={onClose}>
      <form
        role="dialog"
        aria-label="Your profile"
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
      >
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold">Your profile</h2>
            <p className="text-xs text-gray-500">
              @{username} · every new trip starts with these, and the planner updates them when you tell it a
              preference in chat.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-gray-500 hover:bg-gray-100">
            <X size={18} />
          </button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="col-span-2 block text-sm font-medium text-gray-700">
            Home city / airport
            <input
              value={draft.home_city ?? ''}
              placeholder="e.g. College Station, TX"
              onChange={(e) => set('home_city', e.target.value || null)}
              className={field}
            />
          </label>
          <Choice label="Budget" value={draft.budget_level} options={BUDGETS} onChange={(v) => set('budget_level', v)} />
          <Choice label="Pace" value={draft.pace} options={PACES} onChange={(v) => set('pace', v)} />
          <Choice label="Getting around" value={draft.transport} options={TRANSPORTS} onChange={(v) => set('transport', v)} />
          <Choice label="Fly or drive" value={draft.travel_mode} options={TRAVEL_MODES} onChange={(v) => set('travel_mode', v)} />
          <label className="block text-sm font-medium text-gray-700">
            Dietary needs
            <input
              value={draft.dietary ?? ''}
              placeholder="e.g. vegan"
              onChange={(e) => set('dietary', e.target.value || null)}
              className={field}
            />
          </label>
          <label className="col-span-2 block text-sm font-medium text-gray-700">
            Interests
            <input
              value={interests}
              placeholder="food, museums, hiking"
              onChange={(e) => setInterests(e.target.value)}
              className={field}
            />
          </label>
        </div>

        {error && (
          <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            Save profile
          </button>
        </div>
      </form>
    </div>
  )
}
