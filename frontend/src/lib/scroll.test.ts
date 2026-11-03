import { describe, expect, it } from "vitest"
import { shouldStickToBottom } from "@/lib/scroll"

// A 1000px transcript in a 400px viewport: the bottom is at scrollTop 600.
const at = (scrollTop: number) => ({
  scrollTop,
  scrollHeight: 1000,
  clientHeight: 400,
})

describe("shouldStickToBottom", () => {
  it("sticks at the bottom", () => {
    expect(shouldStickToBottom(at(600), 500)).toBe(true)
  })

  it("stays stuck at the bottom when shrinking content lowers scrollTop", () => {
    expect(shouldStickToBottom(at(600), 700)).toBe(true)
  })

  it("unsticks on a small upward scroll, even near the bottom", () => {
    expect(shouldStickToBottom(at(590), 600)).toBe(false)
  })

  it("sticks when scrolling down to near the bottom", () => {
    expect(shouldStickToBottom(at(550), 400)).toBe(true)
  })

  it("does not stick when scrolling down but still far from the bottom", () => {
    expect(shouldStickToBottom(at(300), 200)).toBe(false)
  })
})
