import { beforeEach, describe, expect, it, vi } from "vitest"
import { api, ApiError, type StreamHandlers } from "@/api"
import { selectCanGenerate, useTripStore } from "@/store/tripStore"
import type { Itinerary, SessionDetail } from "@/types"

// The real ApiError, a mocked `api`. Each test scripts the SSE events a stream delivers.
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>()
  return {
    ...actual,
    api: {
      createSession: vi.fn(),
      getSession: vi.fn(),
      sendMessage: vi.fn(),
      generate: vi.fn(),
    },
  }
})

const GREETING = {
  id: "m-greeting",
  role: "assistant" as const,
  content: "Hi! Where are you headed?",
  itinerary_version: null,
  created_at: "2026-11-02T10:00:00Z",
}

const SESSION: SessionDetail = {
  id: "s-1",
  title: "New trip",
  status: "intake",
  trip_profile: {} as SessionDetail["trip_profile"],
  messages: [GREETING],
  itinerary: null,
  chat_enabled: true,
  created_at: "2026-11-02T10:00:00Z",
  updated_at: "2026-11-02T10:00:00Z",
}

// Only the fields the store reads; the rest of the shape doesn't matter here.
const plan = (version: number) =>
  ({ version, title: `Austin v${version}` }) as Itinerary

const state = () => useTripStore.getState()

async function startSession(itinerary: Itinerary | null = null) {
  vi.mocked(api.createSession).mockResolvedValue({ ...SESSION, itinerary })
  await state().init()
}

beforeEach(() => {
  vi.resetAllMocks()
  useTripStore.setState(useTripStore.getInitialState(), true)
})

describe("init", () => {
  it("creates one session even when called twice (StrictMode)", async () => {
    vi.mocked(api.createSession).mockResolvedValue(SESSION)
    await Promise.all([state().init(), state().init()])

    expect(api.createSession).toHaveBeenCalledTimes(1)
    expect(state().initStatus).toBe("ready")
    expect(state().session?.id).toBe("s-1")
    expect(state().messages).toEqual([GREETING])
    expect(state().itinerary).toBeNull()
  })

  it("shows the friendly error and can be retried", async () => {
    vi.mocked(api.createSession).mockRejectedValueOnce(
      new ApiError(0, "Can't reach the server.", true)
    )
    await state().init()
    expect(state().initStatus).toBe("error")
    expect(state().initError).toBe("Can't reach the server.")

    vi.mocked(api.createSession).mockResolvedValueOnce(SESSION)
    await state().init()
    expect(state().initStatus).toBe("ready")
    expect(state().initError).toBeNull()
  })

  it("shows a generic message for a 404 (wrong API address), not 'trip not found'", async () => {
    vi.mocked(api.createSession).mockRejectedValueOnce(
      new ApiError(404, "This trip wasn't found.", false)
    )
    await state().init()
    expect(state().initError).toBe(
      "Couldn't start a new trip. Please try again."
    )
  })
})

describe("sendMessage", () => {
  it("streams the reply and saves the turn on done", async () => {
    await startSession()
    vi.mocked(api.sendMessage).mockImplementation(async (_id, _c, h) => {
      h.onMessageStart?.({ message_id: "m-2" })
      h.onToken?.({ text: "Austin " })
      expect(state().streaming).toBe("chat")
      expect(state().pendingUserMessage?.content).toBe("3 days in Austin")
      h.onToken?.({ text: "sounds fun!" })
      expect(state().streamingText).toBe("Austin sounds fun!")
      h.onDone?.({ message_id: "m-2" })
    })

    await state().sendMessage("  3 days in Austin  ")

    expect(api.sendMessage).toHaveBeenCalledWith(
      "s-1",
      "3 days in Austin",
      expect.any(Object),
      expect.any(AbortSignal)
    )
    const messages = state().messages
    expect(messages.map((m) => [m.role, m.content])).toEqual([
      ["assistant", GREETING.content],
      ["user", "3 days in Austin"],
      ["assistant", "Austin sounds fun!"],
    ])
    expect(messages[2].id).toBe("m-2")
    expect(state().pendingUserMessage).toBeNull()
    expect(state().streaming).toBeNull()
    expect(state().streamingText).toBe("")
    expect(state().error).toBeNull()
  })

  it("on error keeps the user's message, drops partial text, and Retry resends it", async () => {
    await startSession()
    vi.mocked(api.sendMessage).mockImplementationOnce(async (_id, _c, h) => {
      h.onMessageStart?.({ message_id: "m-2" })
      h.onToken?.({ text: "Partial" })
      h.onError?.({ message: "The AI service is busy.", retryable: true })
    })

    await state().sendMessage("3 days in Austin")

    expect(state().messages).toEqual([GREETING]) // nothing new saved
    expect(state().pendingUserMessage?.content).toBe("3 days in Austin")
    expect(state().streamingText).toBe("")
    expect(state().streaming).toBeNull()
    expect(state().error).toEqual({
      kind: "chat",
      message: "The AI service is busy.",
      retryable: true,
    })

    vi.mocked(api.sendMessage).mockImplementationOnce(async (_id, _c, h) => {
      expect(state().error).toBeNull() // cleared as the retry starts
      h.onMessageStart?.({ message_id: "m-3" })
      h.onToken?.({ text: "Got it!" })
      h.onDone?.({ message_id: "m-3" })
    })
    await state().retry()

    expect(api.sendMessage).toHaveBeenLastCalledWith(
      "s-1",
      "3 days in Austin",
      expect.any(Object),
      expect.any(AbortSignal)
    )
    expect(state().messages.map((m) => m.content)).toEqual([
      GREETING.content,
      "3 days in Austin", // once, not duplicated by the retry
      "Got it!",
    ])
    expect(state().pendingUserMessage).toBeNull()
  })

  it("ignores events from a stream that is no longer current", async () => {
    await startSession()
    let stale: StreamHandlers = {}
    vi.mocked(api.sendMessage).mockImplementationOnce(async (_id, _c, h) => {
      stale = h
      h.onError?.({ message: "Busy.", retryable: true })
    })
    await state().sendMessage("first")

    vi.mocked(api.sendMessage).mockImplementationOnce(async (_id, _c, h) => {
      stale.onToken?.({ text: "late text" })
      stale.onDone?.({ message_id: "m-stale" })
      expect(state().streamingText).toBe("")
      h.onDone?.({ message_id: "m-2" })
    })
    await state().retry()
    stale.onError?.({ message: "late error", retryable: true })

    expect(state().messages.map((m) => m.id)).not.toContain("m-stale")
    expect(state().messages.at(-1)?.id).toBe("m-2")
    expect(state().error).toBeNull()
  })

  it("Retry does nothing after a non-retryable error", async () => {
    await startSession()
    vi.mocked(api.sendMessage).mockImplementationOnce(async (_id, _c, h) => {
      h.onMessageStart?.({ message_id: "m-2" })
      h.onError?.({ message: "No AI model configured.", retryable: false })
    })
    await state().sendMessage("hello")

    await state().retry()
    expect(api.sendMessage).toHaveBeenCalledTimes(1)
    expect(state().error?.retryable).toBe(false)
  })

  it("is ignored while a stream is open", async () => {
    await startSession()
    useTripStore.setState({ streaming: "generate" })
    await state().sendMessage("hello")
    expect(api.sendMessage).not.toHaveBeenCalled()
    expect(state().pendingUserMessage).toBeNull()
  })
})

describe("generate", () => {
  it("shows the status, then the plan and the summary message", async () => {
    await startSession()
    vi.mocked(api.generate).mockImplementation(async (_id, h) => {
      h.onMessageStart?.({ message_id: "m-sum" })
      h.onStatus?.({
        label: "Drafting your itinerary…",
        tool: null,
        state: "start",
      })
      expect(state().statusLabel).toBe("Drafting your itinerary…")
      expect(state().draftingPlan).toBe(true)
      h.onItinerary?.(plan(1))
      expect(state().statusLabel).toBeNull()
      expect(state().draftingPlan).toBe(false) // the plan replaces the skeleton
      expect(state().itinerary?.version).toBe(1)
      h.onToken?.({ text: "Here's your plan." })
      h.onDone?.({ message_id: "m-sum" })
    })

    await state().generate()

    expect(state().session?.status).toBe("planned")
    const last = state().messages.at(-1)
    expect(last).toMatchObject({
      id: "m-sum",
      role: "assistant",
      content: "Here's your plan.",
      itinerary_version: 1,
    })
    expect(state().streaming).toBeNull()
  })

  it("on error keeps the current plan and clears the status", async () => {
    await startSession(plan(1))
    vi.mocked(api.generate).mockImplementation(async (_id, h) => {
      h.onMessageStart?.({ message_id: "m-sum" })
      h.onStatus?.({
        label: "Drafting your itinerary…",
        tool: null,
        state: "start",
      })
      h.onError?.({ message: "Couldn't build a plan.", retryable: true })
    })

    await state().generate()

    expect(state().itinerary).toEqual(plan(1))
    expect(state().draftingPlan).toBe(false)
    expect(state().statusLabel).toBeNull()
    expect(state().streaming).toBeNull()
    expect(state().messages).toEqual([GREETING])
    expect(state().error).toEqual({
      kind: "generate",
      message: "Couldn't build a plan.",
      retryable: true,
    })

    await state().retry()
    expect(api.generate).toHaveBeenCalledTimes(2)
  })

  it("keeps the saved summary and blocks Retry if the stream drops after the itinerary", async () => {
    await startSession(plan(1))
    vi.mocked(api.generate).mockImplementation(async (_id, h) => {
      h.onMessageStart?.({ message_id: "m-sum" })
      h.onItinerary?.(plan(2))
      h.onToken?.({ text: "Here's your plan." })
      h.onError?.({ message: "The connection dropped.", retryable: true })
    })

    await state().generate()

    expect(state().itinerary).toEqual(plan(2))
    expect(state().messages.at(-1)).toMatchObject({
      id: "m-sum",
      role: "assistant",
      content: "Here's your plan.",
      itinerary_version: 2,
    })
    expect(state().streamingText).toBe("")
    expect(state().error).toMatchObject({ kind: "generate", retryable: false })

    await state().retry()
    expect(api.generate).toHaveBeenCalledTimes(1) // no extra version
  })
})

describe("selectCanGenerate", () => {
  const USER_MESSAGE = {
    ...GREETING,
    id: "m-user",
    role: "user" as const,
    content: "Austin, 3 days",
  }

  it("needs a session and a saved user message", async () => {
    expect(selectCanGenerate(state())).toBe(false) // before init

    await startSession()
    expect(selectCanGenerate(state())).toBe(false) // only the greeting

    useTripStore.setState({ messages: [GREETING, USER_MESSAGE] })
    expect(selectCanGenerate(state())).toBe(true)
  })

  it("ignores a pending (failed) user message", async () => {
    await startSession()
    useTripStore.setState({ pendingUserMessage: USER_MESSAGE })
    expect(selectCanGenerate(state())).toBe(false)
  })

  it("is false while any stream is open", async () => {
    await startSession()
    useTripStore.setState({ messages: [GREETING, USER_MESSAGE] })
    for (const kind of ["chat", "generate"] as const) {
      useTripStore.setState({ streaming: kind })
      expect(selectCanGenerate(state())).toBe(false)
    }
  })
})
