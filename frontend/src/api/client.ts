// The backend API as seen by the app (docs/contracts.md §4). Components never call fetch:
// the app talks to an ApiClient, which tests replace with a fake.
import type { SessionDetail } from '@/types'

export interface ApiClient {
  createSession(): Promise<SessionDetail>
  getSession(id: string): Promise<SessionDetail>
}

// A non-2xx response. `message` is the backend's `detail` text when there is one.
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
