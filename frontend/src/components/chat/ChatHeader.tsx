import { GenerateButton } from "@/components/common/GenerateButton"
import { useTripStore } from "@/store/tripStore"

/** Session title (Stage 4 makes it editable) and the Generate plan / Regenerate button. */
export function ChatHeader() {
  const title = useTripStore((s) => s.session?.title)

  return (
    <header className="flex min-h-14 items-center gap-3 border-b px-6 py-3">
      <h1 className="min-w-0 flex-1 truncate font-medium">{title}</h1>
      <GenerateButton size="sm" />
    </header>
  )
}
