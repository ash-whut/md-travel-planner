import { cn } from "@/lib/utils"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

// Map arrives in Stage 2 and Checklist in Stage 3; until then both tabs are disabled.
const COMING_SOON_TABS = [
  { value: "map", label: "Map" },
  { value: "checklist", label: "Checklist" },
]

/** Left side of the page: the Plan / Map / Checklist tabs (02 §2, §7, §11). */
export function PlanPanel({ className }: { className?: string }) {
  return (
    <section className={cn("flex flex-col", className)}>
      <Tabs defaultValue="plan" className="min-h-0 flex-1 gap-0">
        <div className="border-b px-6 py-3">
          <TabsList>
            <TabsTrigger value="plan" className="px-3">
              Plan
            </TabsTrigger>
            {COMING_SOON_TABS.map(({ value, label }) => (
              <Tooltip key={value}>
                {/* A disabled button gets no pointer events, so the span shows the tooltip. */}
                <TooltipTrigger asChild>
                  <span className="inline-flex h-full cursor-not-allowed">
                    <TabsTrigger
                      value={value}
                      disabled
                      aria-disabled="true"
                      className="px-3 disabled:opacity-40"
                    >
                      {label}
                    </TabsTrigger>
                  </span>
                </TooltipTrigger>
                <TooltipContent>Coming soon</TooltipContent>
              </Tooltip>
            ))}
          </TabsList>
        </div>
        <TabsContent value="plan" className="min-h-0 overflow-y-auto p-6">
          {/* PLACEHOLDER: S1.14 (empty state, Generate plan, skeleton) and S1.15 (PlanView) go here. */}
          <p className="text-muted-foreground">
            Your trip plan will appear here.
          </p>
        </TabsContent>
      </Tabs>
    </section>
  )
}
