import { motion, useReducedMotion } from "framer-motion";
import { formatClock } from "../lib/callState";
import type { Offer, Term } from "../lib/events.gen";
import { useCallStore } from "../stores/call";

type Field = "instrument" | "price" | "quantity" | "total" | "deadline" | "payment" | "fees";

const ROWS: { field: Field; label: string; numeric: boolean }[] = [
  { field: "instrument", label: "Investment", numeric: false },
  { field: "price", label: "Price", numeric: true },
  { field: "quantity", label: "Quantity", numeric: true },
  { field: "total", label: "Total", numeric: true },
  { field: "deadline", label: "Deadline", numeric: false },
  { field: "payment", label: "Payment", numeric: false },
  { field: "fees", label: "Fees", numeric: false },
];

function sourceLine(term: Term): string | null {
  if (term.source === "computed") return "price × quantity";
  if (term.t !== null) return `said at ${formatClock(term.t * 1000)}`;
  return null;
}

function lastChange(offer: Offer, field: Field) {
  for (let i = offer.history.length - 1; i >= 0; i--) if (offer.history[i].field === field) return offer.history[i];
  return null;
}

export function OfferCard() {
  const offer = useCallStore((s) => s.offer);
  const reduce = useReducedMotion();
  const rows = offer ? ROWS.filter((r) => offer[r.field] !== null) : [];

  if (!offer || rows.length === 0) return <p className="muted">Terms fill in as the caller states them.</p>;

  return (
    <dl className="offer" aria-live="polite">
      {rows.map(({ field, label, numeric }) => {
        const term = offer[field] as Term;
        const change = lastChange(offer, field);
        const src = sourceLine(term);
        const unsure = term.confidence === "unsure";
        return (
          <motion.div
            key={field}
            className="offer__row"
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2 }}
          >
            <dt>{label}</dt>
            <dd>
              <span className={numeric ? "offer__value--num" : undefined}>
                {term.display}
                {unsure ? "?" : ""}
              </span>
              {change && <span className="offer__was"> (was {change.old.display})</span>}
              {src && <span className="offer__note">{src}</span>}
              {unsure && <span className="offer__note">Not sure we heard this right</span>}
            </dd>
          </motion.div>
        );
      })}
    </dl>
  );
}
