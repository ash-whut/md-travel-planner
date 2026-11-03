import { AlertCircle, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useTripStore } from "@/store/tripStore"

/** Shown until the new trip exists: a spinner, or the error with a Retry button. */
export function StartupScreen() {
  const initStatus = useTripStore((s) => s.initStatus)
  const initError = useTripStore((s) => s.initError)
  const init = useTripStore((s) => s.init)

  return (
    <main className="flex h-dvh flex-col items-center justify-center gap-4 p-8 text-center">
      {initStatus === "error" ? (
        <>
          <AlertCircle className="size-8 text-destructive" aria-hidden />
          <p role="alert" className="max-w-sm text-muted-foreground">
            {initError}
          </p>
          <Button onClick={() => void init()}>Retry</Button>
        </>
      ) : (
        <>
          <Loader2
            className="size-6 animate-spin text-muted-foreground"
            aria-hidden
          />
          <p className="text-muted-foreground">Starting a new trip…</p>
        </>
      )}
    </main>
  )
}
