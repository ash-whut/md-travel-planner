import { StatusLine } from "@/components/chat/StatusLine"
import { Skeleton } from "@/components/ui/skeleton"

const DAY_CARDS = 3
const ROWS_PER_CARD = 3

/** Shown while a plan is being generated: the status label and 3 skeleton day cards (02 §4.1). */
export function PlanSkeleton({ statusLabel }: { statusLabel: string | null }) {
  return (
    <div aria-busy="true" className="space-y-4">
      {/* The label is also in the chat log, which announces it; this copy is visual. */}
      <div aria-hidden className="min-h-5">
        {statusLabel && <StatusLine label={statusLabel} />}
      </div>
      {Array.from({ length: DAY_CARDS }, (_, card) => (
        <div key={card} className="space-y-4 rounded-xl border p-4">
          <Skeleton className="h-5 w-2/5" />
          {Array.from({ length: ROWS_PER_CARD }, (_, row) => (
            <div key={row} className="flex items-center gap-3">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="size-6 rounded-full" />
              <Skeleton className="h-4 flex-1" />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
