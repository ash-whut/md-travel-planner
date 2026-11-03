import { ChatPanel } from "@/components/chat/ChatPanel"
import { StartupScreen } from "@/components/layout/StartupScreen"
import { PlanPanel } from "@/components/plan/PlanPanel"
import { useTripStore } from "@/store/tripStore"

/**
 * Page layout (02 §1): the plan area on the left, chat on the right half (min 380px).
 * The history sidebar joins the left half in Stage 4.
 */
export function AppShell() {
  const initStatus = useTripStore((s) => s.initStatus)

  if (initStatus !== "ready") return <StartupScreen />

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <PlanPanel className="min-w-0 flex-1" />
      <ChatPanel className="w-1/2 min-w-[380px] shrink-0 border-l" />
    </div>
  )
}
