// Auto-scroll rule for the chat transcript (02 §6).

/** Within this many pixels of the bottom counts as "near the bottom". */
export const STICK_THRESHOLD_PX = 80

interface ScrollPosition {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

/**
 * Whether the transcript should keep following new content after a scroll event.
 * Scrolling up unsticks at once (a smooth wheel scroll moves only a few pixels per frame,
 * less than the threshold), unless the view is still at the very bottom: content that
 * shrinks also lowers scrollTop. Otherwise, follow when near the bottom.
 */
export function shouldStickToBottom(
  { scrollTop, scrollHeight, clientHeight }: ScrollPosition,
  lastScrollTop: number
): boolean {
  const distanceFromBottom = scrollHeight - scrollTop - clientHeight
  if (distanceFromBottom <= 1) return true
  if (scrollTop < lastScrollTop) return false
  return distanceFromBottom < STICK_THRESHOLD_PX
}
