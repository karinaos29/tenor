import type { ReactNode } from "react";
import { ClaimsCard } from "./ClaimsCard";
import { OfferCard } from "./OfferCard";
import { TacticsCard } from "./TacticsCard";
import { Suggestions } from "./Suggestions";

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
        <Suggestions />
      </RailCard>
      <RailCard title="The offer">
        <OfferCard />
      </RailCard>
      <RailCard title="Claims vs. data">
        <ClaimsCard />
      </RailCard>
      <RailCard title="Pressure tactics">
        <TacticsCard />
      </RailCard>
    </div>
  );
}
