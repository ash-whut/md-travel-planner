import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApiClient, ApiError as ApiErrorType } from './client'

// PATCH /sessions/{id}/bookings/{booking_id} (contracts §4, step 43).
const BASE = 'http://api.test/api'
let httpClient: ApiClient
let ApiError: typeof ApiErrorType
const fetchMock = vi.fn()

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(async () => {
  vi.stubEnv('VITE_API_BASE_URL', BASE)
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  vi.resetModules()
  httpClient = (await import('./http')).httpClient
  ApiError = (await import('./client')).ApiError
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('httpClient.patchBooking', () => {
  it('PATCHes the booking URL with a JSON { status } body and returns the updated booking', async () => {
    const updated = { id: 'bk-flight', status: 'booked' }
    fetchMock.mockResolvedValue(jsonResponse(200, updated))

    const result = await httpClient.patchBooking('s-1', 'bk-flight', 'booked')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/sessions/s-1/bookings/bk-flight`)
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(init?.body as string)).toEqual({ status: 'booked' })
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
    expect(result).toEqual(updated)
  })

  it('sends "todo" for an undo', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 'bk-hotel-D', status: 'todo' }))
    await httpClient.patchBooking('s-1', 'bk-hotel-D', 'todo')
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ status: 'todo' })
  })

  it('URL-encodes the session and booking ids', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}))
    await httpClient.patchBooking('a b', 'bk/x y', 'booked')
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE}/sessions/a%20b/bookings/bk%2Fx%20y`)
  })

  it('throws ApiError with the backend detail on 404', async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { detail: 'Booking not found' }))
    const err = await httpClient.patchBooking('s-1', 'bk-nope', 'booked').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiErrorType).status).toBe(404)
    expect((err as ApiErrorType).message).toBe('Booking not found')
  })
})
