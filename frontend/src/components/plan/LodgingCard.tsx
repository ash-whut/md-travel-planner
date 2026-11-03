import { ExternalLink } from "lucide-react"
import { TagBadge } from "@/components/common/TagBadge"
import { formatDate, formatMoney } from "@/lib/format"
import { formatNights } from "@/lib/plan"
import type { Lodging } from "@/types"

/**
 * A hotel stay (02 §4.1): H1 badge, name, city, check-in → check-out and nights, the price
 * (or "Price not available yet" — Stage 1 has no hotel prices) and any booking links.
 * The "Prices as of …" line arrives with live prices in Stage 3.
 */
export function LodgingCard({ lodging }: { lodging: Lodging }) {
  const { total_price, price_per_night } = lodging

  return (
    <div className="space-y-2 rounded-xl border p-4">
      <div className="flex items-start gap-2">
        <TagBadge tag={lodging.tag} />
        <div className="min-w-0">
          <h4 className="font-medium">{lodging.name}</h4>
          <p className="text-sm text-muted-foreground">
            {lodging.address ?? lodging.city}
          </p>
        </div>
      </div>
      <p className="text-sm">
        {formatDate(lodging.check_in)} → {formatDate(lodging.check_out)} ·{" "}
        {formatNights(lodging.nights)}
      </p>
      <p className="text-sm">
        {total_price ? (
          <>
            {formatMoney(total_price.amount)} total
            {price_per_night &&
              ` · ${formatMoney(price_per_night.amount)} per night`}
          </>
        ) : (
          <span className="text-muted-foreground">Price not available yet</span>
        )}
      </p>
      {lodging.links.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {lodging.links.map((link) => (
            <li key={`${link.label}-${link.url}`}>
              <a
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 underline underline-offset-2"
              >
                {link.label}
                <ExternalLink className="size-3" aria-hidden />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
