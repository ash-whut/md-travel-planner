import { useEffect } from "react"
import { AppShell } from "@/components/layout/AppShell"
import { useTripStore } from "@/store/tripStore"

function App() {
  const init = useTripStore((s) => s.init)

  // Every page load starts a new trip (02 §5). init() ignores the second call that
  // React StrictMode makes in development.
  useEffect(() => {
    void init()
  }, [init])

  return <AppShell />
}

export default App
