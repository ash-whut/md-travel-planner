import { toast } from "sonner"
import { Button } from "@/components/ui/button"

// Placeholder screen for S1.2; replaced by AppShell in S1.12.
function App() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">
        md-travel-planner
      </h1>
      <p className="text-muted-foreground">Stage 1 skeleton</p>
      <Button onClick={() => toast("Frontend skeleton is running")}>
        Say hello
      </Button>
    </main>
  )
}

export default App
