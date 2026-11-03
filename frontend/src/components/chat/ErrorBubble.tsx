import { AlertCircle, RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"

interface ErrorBubbleProps {
  message: string // the server's friendly text
  onRetry?: () => void // omitted when the error isn't retryable
}

/** A stream that failed, with Retry when the server says it may help. */
export function ErrorBubble({ message, onRetry }: ErrorBubbleProps) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm"
    >
      <AlertCircle
        className="mt-0.5 size-4 shrink-0 text-destructive"
        aria-hidden
      />
      <p className="flex-1">{message}</p>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RotateCcw aria-hidden />
          Retry
        </Button>
      )}
    </div>
  )
}
