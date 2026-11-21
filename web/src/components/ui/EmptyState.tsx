import type { LucideIcon } from "lucide-react";
import { Card } from "./primitives";

/** Designed placeholder for screens scheduled in later phases. */
export function PlannedScreen({
  icon: Icon,
  title,
  phase,
  description,
  bullets,
}: {
  icon: LucideIcon;
  title: string;
  phase: string;
  description: string;
  bullets: string[];
}) {
  return (
    <Card className="relative mx-auto mt-4 max-w-2xl overflow-hidden p-8 text-center sm:p-12">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-24 mx-auto size-72 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent)_16%,transparent),transparent)]" />
      <div className="relative mx-auto grid size-14 place-items-center rounded-[16px] border border-line bg-card-2">
        <Icon className="size-6 text-accent" strokeWidth={1.6} />
      </div>
      <p className="af-label relative mt-5">{phase}</p>
      <h2 className="relative mt-2 text-[22px] font-semibold tracking-tight">{title}</h2>
      <p className="relative mx-auto mt-2 max-w-md text-[14px] text-fg-2">{description}</p>
      <ul className="relative mx-auto mt-6 grid max-w-md gap-2 text-left">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-2 rounded-[10px] border border-line bg-card-2 px-3 py-2 text-[13px] text-fg-2">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
            {b}
          </li>
        ))}
      </ul>
    </Card>
  );
}
