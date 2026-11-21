import { FileText, FileCode2, Network, BookOpenText, AlertTriangle, type LucideIcon } from "lucide-react";
import { DEMO_ACTIVITY, type ActivityKind } from "@/mocks/demo-data";
import { DemoBadge, SectionHeader } from "@/components/ui/primitives";
import { TimeAgo } from "@/components/ui/time";

const ICON: Record<ActivityKind, { icon: LucideIcon; color: string }> = {
  report: { icon: FileText, color: "var(--ok)" },
  file: { icon: FileCode2, color: "var(--accent)" },
  collab: { icon: Network, color: "var(--accent-2)" },
  research: { icon: BookOpenText, color: "var(--cyan)" },
  failure: { icon: AlertTriangle, color: "var(--err)" },
};

export function RecentActivity() {
  return (
    <section className="af-card flex h-full flex-col p-5" aria-label="Recent activity">
      <SectionHeader title="Recent activity" subtitle="Executions, files and reports" action={<DemoBadge />} />
      <ul className="mt-4 divide-y divide-[var(--border)]">
        {DEMO_ACTIVITY.map((a) => {
          const { icon: Icon, color } = ICON[a.kind];
          return (
            <li key={a.id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
              <span
                className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-[9px] border"
                style={{ color, borderColor: `color-mix(in oklab, ${color} 30%, var(--border))`, background: `color-mix(in oklab, ${color} 8%, transparent)` }}
              >
                <Icon className="size-4" strokeWidth={1.8} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-fg">{a.title}</p>
                <p className="truncate text-[12px] text-fg-3">{a.meta}</p>
              </div>
              <span className="shrink-0 text-[11.5px] text-fg-3">
                <TimeAgo secondsAgo={a.secondsAgo} />
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
