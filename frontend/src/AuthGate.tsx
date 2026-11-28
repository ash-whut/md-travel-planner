// Login in front of the app (decisions D32): with no valid token, show the login screen;
// once logged in, render the app with the account menu and the profile dialog.
import { useEffect, useState } from 'react'
import App from './App'
import { getToken, httpAuth, setToken, type AuthClient } from './api/auth'
import { isNetworkError, type ApiClient } from './api/client'
import { LoginScreen } from './components/LoginScreen'
import { ProfileDialog } from './components/ProfileDialog'
import { demo } from './demoParams'
import { SESSION_KEY } from './store/useTripStore'
import type { AuthResponse, User } from '@/types'

interface Props {
  auth?: AuthClient // tests pass a fake
  api?: ApiClient
  // Called after logout so the stores start clean for the next account.
  onLoggedOut?: () => void
}

export default function AuthGate({ auth = httpAuth, api, onLoggedOut = () => window.location.reload() }: Props) {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(() => getToken() !== null)
  const [profileOpen, setProfileOpen] = useState(false)
  // The token check got no response: the backend is down, so keep the token and offer a retry.
  const [unreachable, setUnreachable] = useState(false)
  const [attempt, setAttempt] = useState(0) // bumped by Try again to re-run the check

  // A stored token: check it is still valid; a rejected one goes back to the login screen.
  useEffect(() => {
    if (!getToken()) return
    auth
      .me()
      .then((me) => {
        setUnreachable(false)
        setUser(me)
      })
      .catch((err: unknown) => {
        if (isNetworkError(err)) setUnreachable(true)
        else setToken(null)
      })
      .finally(() => setChecking(false))
  }, [auth, attempt])

  // ?demo=1 shows the fixture trip for screenshots; it needs no account.
  if (demo.enabled) return <App api={api} />
  if (checking) return null
  if (unreachable && !user) {
    return (
      <div className="flex h-full items-center justify-center bg-gray-50 px-4">
        <div role="status" className="max-w-sm rounded-2xl border border-red-200 bg-white p-6 text-center shadow-sm">
          <p className="font-medium text-red-700">Backend not reachable</p>
          <p className="mt-1 text-sm text-gray-500">Check that the server is running, then try again.</p>
          <button
            type="button"
            onClick={() => {
              setChecking(true)
              setAttempt((n) => n + 1)
            }}
            className="mt-4 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (!user) {
    return (
      <LoginScreen
        onLogin={auth.login}
        onRegister={auth.register}
        onDone={(res: AuthResponse) => {
          setToken(res.token)
          // Don't reopen the previous account's last trip.
          localStorage.removeItem(SESSION_KEY)
          setUser(res.user)
        }}
      />
    )
  }

  async function logout() {
    await auth.logout().catch(() => undefined)
    setToken(null)
    localStorage.removeItem(SESSION_KEY)
    setUser(null)
    onLoggedOut()
  }

  return (
    <>
      <App api={api} account={{ username: user.username, onProfile: () => setProfileOpen(true), onLogout: logout }} />
      {profileOpen && (
        <ProfileDialog
          username={user.username}
          profile={user.profile}
          onSave={async (profile) => setUser(await auth.updateProfile(profile))}
          onClose={() => setProfileOpen(false)}
        />
      )}
    </>
  )
}
