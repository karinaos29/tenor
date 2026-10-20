import type { ReactNode } from "react";
import { OfferCard } from "./OfferCard";

function RailCard({ title, hint, live, children }: { title: string; hint?: string; live?: boolean; children: ReactNode }) {
  const id = `rail-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section className="card rail__card" aria-labelledby={id}>
      <div className="rail__head">
        <h2 id={id} className="card__title">{title}</h2>
        {hint && <span className="muted rail__hint">{hint}</span>}
      </div>
      {live ? <div aria-live="polite">{children}</div> : children}
    </section>
  );
}

export function RightRail() {
  return (
    <div className="rail">
      <RailCard title="Suggestions" hint="4 at most" live>
        <p className="muted">Tenor&apos;s suggestions appear here when there&apos;s something worth saying or checking.</p>
      </RailCard>
      <RailCard title="The offer">
        <OfferCard />
      </RailCard>
      <RailCard title="Claims vs. data">
        <p className="muted">Claims the caller makes are checked against market data here.</p>
      </RailCard>
      <RailCard title="Pressure tactics">
        <p className="muted">Pressure tactics, like a deadline for today, are flagged here.</p>
      </RailCard>
    </div>
  );
}
