import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { Suggestion } from "../lib/events.gen";
import { useCallStore } from "../stores/call";

function clock(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toTimeString().slice(0, 8);
}

function SayThis({ s }: { s: Suggestion }) {
  return (
    <div className="sug sug--say">
      <p className="sug__label">Say this</p>
      <p className="sug__say">“{s.text}”</p>
      {s.reason && <p className="sug__reason">{s.reason}</p>}
    </div>
  );
}

function Research({ s }: { s: Suggestion }) {
  const item = useCallStore((st) => st.research[s.id]);
  const ready = s.status === "ready";
  const at = clock(item?.checked_at ?? s.checked_at);
  const source = item?.source ?? s.source;
  return (
    <div className="sug sug--research">
      <p className="sug__rlabel">{ready ? "Research · ready" : "Research · prefetching"}</p>
      <p className="sug__title">{s.title}</p>
      {ready ? <p className="sug__body">{item?.summary || s.text}</p> : <p className="sug__rlabel">Prefetching…</p>}
      {at && <p className="sug__src">Source: {source} · checked <span className="numbers">{at}</span></p>}
    </div>
  );
}

export function Suggestions() {
  const visible = useCallStore((s) => s.suggestions.visible).slice(0, 4);
  const reduce = useReducedMotion();
  if (visible.length === 0) {
    return <p className="muted">Tenor&apos;s suggestions appear here when there&apos;s something worth saying or checking.</p>;
  }
  return (
    <div className="sug__list">
      <AnimatePresence initial={false}>
        {visible.map((s) => (
          <motion.div
            key={s.id}
            layout={reduce ? false : "position"}
            initial={reduce ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18 }}
          >
            {s.kind === "say_this" ? <SayThis s={s} /> : <Research s={s} />}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
