import { useState, type FormEvent } from 'react'
import { LogIn, UserPlus } from 'lucide-react'
import { isNetworkError } from '@/api/client'
import type { AuthBody, AuthResponse } from '@/types'

interface Props {
  onLogin: (body: AuthBody) => Promise<AuthResponse>
  onRegister: (body: AuthBody) => Promise<AuthResponse>
  onDone: (res: AuthResponse) => void
}

export function LoginScreen({ onLogin, onRegister, onDone }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const registering = mode === 'register'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = { username: username.trim().toLowerCase(), password }
      onDone(await (registering ? onRegister(body) : onLogin(body)))
    } catch (err) {
      if (isNetworkError(err)) setError('Backend not reachable. Check that the server is running.')
      else setError(err instanceof Error ? err.message : 'Something went wrong')
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-gray-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2">
          <span className="text-3xl">🦆</span>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Mighty Ducks Trip Planner</h1>
            <p className="text-xs text-gray-500">
              {registering ? 'Create an account to save your trips and preferences' : 'Log in to see your trips'}
            </p>
          </div>
        </div>

        <label className="mt-5 block text-sm font-medium text-gray-700">
          Username
          <input
            autoFocus
            required
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-indigo-100"
          />
        </label>
        <label className="mt-3 block text-sm font-medium text-gray-700">
          Password
          <input
            required
            type="password"
            autoComplete={registering ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-indigo-100"
          />
        </label>

        {error && (
          <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {registering ? <UserPlus size={16} /> : <LogIn size={16} />}
          {registering ? 'Create account' : 'Log in'}
        </button>
        <p className="mt-4 text-center text-xs text-gray-500">
          {registering ? 'Already have an account?' : 'New here?'}{' '}
          <button
            type="button"
            onClick={() => {
              setMode(registering ? 'login' : 'register')
              setError(null)
            }}
            className="font-medium text-accent hover:underline"
          >
            {registering ? 'Log in' : 'Create an account'}
          </button>
        </p>
      </form>
    </div>
  )
}
