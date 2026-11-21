"use client";

import { useId } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, CheckCheck, Coins, Cpu, Zap, ListChecks } from "lucide-react";
import { DEMO_REQUESTS_BY_AGENT, DEMO_TOKENS_14D, DEMO_USAGE } from "@/mocks/demo-data";
import { useThemeColors } from "@/lib/theme-colors";
import { DemoBadge, SectionHeader } from "@/components/ui/primitives";

const nf = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

function Stat({ icon: Icon, label, value, sub, meter }: { icon: typeof Zap; label: string; value: string; sub?: string; meter?: number }) {
  return (
    <div className="rounded-[12px] border border-line bg-card-2 p-3.5">
      <div className="flex items-center gap-1.5 text-[12px] text-fg-2">
        <Icon className="size-3.5 text-fg-3" aria-hidden /> {label}
      </div>
      <div className="mt-2 font-mono text-[22px] font-medium tracking-tight tabular-nums text-fg">{value}</div>
      {meter !== undefined ? (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-[color-mix(in_oklab,var(--fg-3)_18%,transparent)]">
          <div className="h-full rounded-full bg-[linear-gradient(90deg,var(--accent),var(--accent-2))]" style={{ width: `${Math.round(meter * 100)}%` }} />
        </div>
      ) : null}
      {sub ? <div className="mt-1.5 text-[11.5px] text-fg-3">{sub}</div> : null}
    </div>
  );
}

function ChartTooltip({ active, payload, label, unit }: { active?: boolean; payload?: { value?: number }[]; label?: string; unit: string }) {
  if (!active || !payload?.length) return null;
  const v = payload[0]?.value ?? 0;
  return (
    <div className="rounded-[10px] border border-line bg-card px-3 py-2 text-[12px] shadow-[var(--shadow)]">
      <div className="text-fg-3">{label}</div>
      <div className="mt-0.5 font-mono text-fg">
        {nf.format(v)} {unit}
      </div>
    </div>
  );
}

export function UsageOverview() {
  const c = useThemeColors();
  const gid = useId().replace(/:/g, "");
  const u = DEMO_USAGE;

  return (
    <section className="af-card p-5" aria-label="Usage overview">
      <SectionHeader title="Usage overview" subtitle="November · resets Dec 1" action={<DemoBadge />} />

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat icon={Zap} label="AI requests" value={compact.format(u.aiRequests)} sub="this month" />
        <Stat icon={Cpu} label="Tokens" value={compact.format(u.tokensThisMonth)} sub={`of ${compact.format(u.monthlyAllowance)} included`} meter={u.tokensThisMonth / u.monthlyAllowance} />
        <Stat icon={Activity} label="Monthly usage" value={`${Math.round((u.tokensThisMonth / u.monthlyAllowance) * 100)}%`} sub="of plan allowance" />
        <Stat icon={Coins} label="Credits left" value={nf.format(u.creditsRemaining)} sub={`of ${nf.format(u.creditsTotal)}`} meter={u.creditsRemaining / u.creditsTotal} />
        <Stat icon={ListChecks} label="Active tasks" value={String(u.activeTasks)} sub="1 awaiting approval" />
        <Stat icon={CheckCheck} label="Completed" value={nf.format(u.completedTasks)} sub="all time" />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="text-[13px] font-medium text-fg">Tokens per day</h3>
            <span className="text-[11.5px] text-fg-3">Last 14 days</span>
          </div>
          <div className="h-[200px]" role="img" aria-label="Area chart of tokens consumed per day over the last 14 days">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={DEMO_TOKENS_14D} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={`tok-${gid}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={c.accent} stopOpacity={0.32} />
                    <stop offset="100%" stopColor={c.accent} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke={c.grid} />
                <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: c.fg3, fontSize: 11 }} interval="preserveStartEnd" minTickGap={24} />
                <YAxis tickLine={false} axisLine={false} tick={{ fill: c.fg3, fontSize: 11 }} tickFormatter={(v: number) => compact.format(v)} width={44} />
                <Tooltip content={<ChartTooltip unit="tokens" />} cursor={{ stroke: c.fg3, strokeDasharray: "3 3" }} />
                <Area type="monotone" dataKey="tokens" stroke={c.accent} strokeWidth={2} fill={`url(#tok-${gid})`} activeDot={{ r: 4, stroke: c.card, strokeWidth: 2, fill: c.accent }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div className="lg:col-span-2">
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="text-[13px] font-medium text-fg">Requests by agent</h3>
            <span className="text-[11.5px] text-fg-3">This month</span>
          </div>
          <div className="h-[200px]" role="img" aria-label="Bar chart of AI requests per agent this month">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={DEMO_REQUESTS_BY_AGENT} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }} barCategoryGap={6}>
                <CartesianGrid horizontal={false} stroke={c.grid} />
                <XAxis type="number" tickLine={false} axisLine={false} tick={{ fill: c.fg3, fontSize: 11 }} tickFormatter={(v: number) => compact.format(v)} />
                <YAxis type="category" dataKey="agent" tickLine={false} axisLine={false} tick={{ fill: c.fg2, fontSize: 11.5 }} width={72} />
                <Tooltip content={<ChartTooltip unit="requests" />} cursor={{ fill: c.grid }} />
                <Bar dataKey="requests" fill={c.accent2} radius={[0, 4, 4, 0]} maxBarSize={14} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </section>
  );
}
