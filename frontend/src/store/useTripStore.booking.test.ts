import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from '@/api/client'
import { sanJoseMessages, sanJoseProfile, sanJoseV1 } from '@/fixtures'
import type { Booking, SessionDetail } from '@/types'
import { useTripStore } from './useTripStore'

// Step 43: "Mark booked" is optimistic, saved with api.patchBooking, reverted on error.

const session: SessionDetail = {
  id: 's-1',
  title: sanJoseV1.title,
  status: 'planned',
  trip_profile: sanJoseProfile,
  messages: sanJoseMessages,
  itinerary: sanJoseV1,
  created_at: '',
  updated_at: '',
}

function fakeApi(patchBooking: ApiClient['patchBooking']) {
  return {
    createSession: vi.fn(async () => session),
    getSession: vi.fn(async () => session),
    sendMessage: vi.fn(async () => {}),
    generate: vi.fn(async () => {}),
    patchBooking: vi.fn(patchBooking),
  }
}

function booking(id: string): Booking {
  return useTripStore.getState().itinerary!.bookings.find((b) => b.id === id)!
}

// A promise the test resolves or rejects by hand, to look at the state in between.
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  localStorage.clear()
  useTripStore.getState().reset()
  useTripStore.getState().loadSession(structuredClone(session))
})

describe('setBookingStatus', () => {
  it('shows "booked" right away, before the save finishes', async () => {
    const save = deferred<Booking>()
    const api = fakeApi(() => save.promise)
    const pending = useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'booked')

    expect(booking('bk-hotel-D').status).toBe('booked')
    expect(api.patchBooking).toHaveBeenCalledWith('s-1', 'bk-hotel-D', 'booked')

    save.resolve({ ...booking('bk-hotel-D'), status: 'booked' })
    await pending
    expect(booking('bk-hotel-D').status).toBe('booked')
    expect(useTripStore.getState().bookingError).toBeNull()
  })

  it('keeps the local booking after a successful save (only the status changed)', async () => {
    const before = booking('bk-flight')
    const api = fakeApi(async (_s, id) => ({ ...booking(id), status: 'booked', details: 'saved by server' }))
    await useTripStore.getState().setBookingStatus(api, 'bk-flight', 'booked')
    expect(booking('bk-flight')).toEqual({ ...before, status: 'booked' })
  })

  it('Mark booked then Undo: a late reply to the first click does not undo the Undo', async () => {
    const markSave = deferred<Booking>()
    const undoSave = deferred<Booking>()
    const api = fakeApi((_s, _id, status) => (status === 'booked' ? markSave.promise : undoSave.promise))

    const mark = useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'booked')
    const undo = useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'todo')
    expect(booking('bk-hotel-D').status).toBe('todo')

    undoSave.resolve({ ...booking('bk-hotel-D'), status: 'todo' })
    await undo
    markSave.resolve({ ...booking('bk-hotel-D'), status: 'booked' }) // arrives last
    await mark
    expect(booking('bk-hotel-D').status).toBe('todo')
  })

  it('Mark booked then Undo: a failed first save does not revert the Undo', async () => {
    const markSave = deferred<Booking>()
    const api = fakeApi(async (_s, id, status) => {
      if (status === 'booked') return markSave.promise
      return { ...booking(id), status }
    })

    const mark = useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'booked')
    await useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'todo')
    markSave.reject(new ApiError(500, 'Server down'))
    await mark
    expect(booking('bk-hotel-D').status).toBe('todo')
    expect(useTripStore.getState().bookingError).toBeNull()
  })

  it('reverts the status and sets bookingError when the save fails', async () => {
    const save = deferred<Booking>()
    const api = fakeApi(() => save.promise)
    const pending = useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'booked')
    expect(booking('bk-hotel-D').status).toBe('booked')

    save.reject(new ApiError(500, 'Server down'))
    await pending
    expect(booking('bk-hotel-D').status).toBe('todo')
    expect(useTripStore.getState().bookingError).toMatch(/Server down/)
  })

  it('reverts an Undo (booked → todo) when the save fails', async () => {
    const api = fakeApi(async () => ({ ...booking('bk-activity-G'), status: 'booked' }))
    await useTripStore.getState().setBookingStatus(api, 'bk-activity-G', 'booked')

    const failing = fakeApi(async () => {
      throw new ApiError(404, 'Booking not found')
    })
    await useTripStore.getState().setBookingStatus(failing, 'bk-activity-G', 'todo')
    expect(booking('bk-activity-G').status).toBe('booked')
    expect(useTripStore.getState().bookingError).toMatch(/Booking not found/)
  })

  it('leaves the other bookings untouched', async () => {
    const before = structuredClone(useTripStore.getState().itinerary!.bookings)
    const api = fakeApi(async () => {
      throw new Error('offline')
    })
    await useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'booked')
    expect(useTripStore.getState().itinerary!.bookings).toEqual(before)
  })

  it('a later successful save clears the previous error', async () => {
    await useTripStore.getState().setBookingStatus(
      fakeApi(async () => {
        throw new Error('offline')
      }),
      'bk-hotel-D',
      'booked',
    )
    expect(useTripStore.getState().bookingError).not.toBeNull()
    await useTripStore.getState().setBookingStatus(
      fakeApi(async (_s, id) => ({ ...booking(id), status: 'booked' })),
      'bk-hotel-D',
      'booked',
    )
    expect(useTripStore.getState().bookingError).toBeNull()
    expect(booking('bk-hotel-D').status).toBe('booked')
  })

  it('does not call the API for an unknown booking id', async () => {
    const api = fakeApi(async () => booking('bk-hotel-D'))
    await useTripStore.getState().setBookingStatus(api, 'bk-nope', 'booked')
    expect(api.patchBooking).not.toHaveBeenCalled()
  })

  it('in the ?demo=1 trip it changes the status locally without calling the API', async () => {
    useTripStore.getState().loadDemo()
    const api = fakeApi(async () => {
      throw new Error('patchBooking must not be called in demo mode')
    })
    await useTripStore.getState().setBookingStatus(api, 'bk-hotel-D', 'booked')
    expect(api.patchBooking).not.toHaveBeenCalled()
    expect(booking('bk-hotel-D').status).toBe('booked')
    expect(useTripStore.getState().bookingError).toBeNull()
  })
})
