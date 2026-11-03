import { Loader2 } from "lucide-react"

/** The current phase of a stream, e.g. "Drafting your itinerary…" (02 §6; not saved). */
export function StatusLine({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </p>
  )
}
