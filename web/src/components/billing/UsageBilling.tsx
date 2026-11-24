"use client";

import { useId, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Bell,
  CheckCheck,
  Coins,
  Cpu,
  Download,
  Loader2,
  Network,
  Receipt,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
import type { UsageRange, UsageReport } from "@/lib/types";
import { agentShortName } from "@/lib/agents";
import { useThemeColors } from "@/lib/theme-colors";
import { cn } from "@/lib/cn";
import { api } from "@/data/api";
import {
  Badge,
  Button,
  Card,
  DemoBadge,
  SectionHeader,
} from "@/components/ui/primitives";
import { Switch } from "@/components/ui/Switch";
import { useToast } from "@/components/ui/toast";
import { AgentGlyph } from "@/components/agent/AgentCard";

const nf = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const PROVIDER_NAME = {
  openai: "OpenAI",
  gemini: "Gemini",
  gn7t: "GN7T",
} as const;

function Bar({
  value,
  tone = "var(--accent)",
}: {
  value: number;
  tone?: string;
}) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[color-mix(in_oklab,var(--fg-3)_18%,transparent)]">
      <div
        className="h-full rounded-full"
        style={{ width: `${Math.max(2, value * 100)}%`, background: tone }}
      />
    </div>
  );
}

export function UsageBilling({
  initial,
  demo,
}: {
  initial: UsageReport;
  demo: boolean;
}) {
  const toast = useToast();
  const c = useThemeColors();
  const gid = useId().replace(/:/g, "");
  const [report, setReport] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [alerts, setAlerts] = useState({
    credits80: true,
    memberCap: false,
    agentCap: true,
    weekly: true,
  });

  const changeRange = async (r: UsageRange) => {
    if (r === report.range) return;
    setLoading(true);
    try {
      setReport(await api.usage.report(r));
    } finally {
      setLoading(false);
    }
  };

  const p = report.plan;
  const used = p ? p.creditsTotal - p.creditsRemaining : 0;
  const maxAgentCredits = Math.max(1, ...report.byAgent.map((a) => a.credits));
  const maxMember = Math.max(1, ...report.byMember.map((m) => m.credits));
  const totalCost = report.byModel.reduce((s, m) => s + m.costUsd, 0);

  return (
    <div className="space-y-6">
      {/* Filter row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[22px] font-semibold tracking-tight">
              Usage & billing
            </h2>
            {demo ? <DemoBadge /> : null}
          </div>
          <p className="mt-1 text-[14px] text-fg-2">
            Every model and tool call is metered to the exact model used,
            including fallbacks.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {loading ? (
            <Loader2
              className="size-4 animate-spin text-fg-3"
              aria-label="Loading"
            />
          ) : null}
          <div
            className="flex rounded-[10px] border border-line bg-card-2 p-0.5"
            role="radiogroup"
            aria-label="Date range"
          >
            {(["7d", "30d", "90d"] as const).map((r) => (
              <button
                key={r}
                type="button"
                role="radio"
                aria-checked={report.range === r}
                onClick={() => changeRange(r)}
                className={cn(
                  "h-8 rounded-[8px] px-3 font-mono text-[12.5px]",
                  report.range === r
                    ? "bg-card text-fg shadow-[var(--shadow)]"
                    : "text-fg-3 hover:text-fg-2",
                )}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div
        className={cn(
          "grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px] [&>*]:min-w-0",
          loading && "opacity-60 transition-opacity",
        )}
      >
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              {
                icon: Zap,
                label: "AI requests",
                value: compact.format(report.totals.requests),
              },
              {
                icon: Cpu,
                label: "Tokens",
                value: compact.format(report.totals.tokens),
              },
              {
                icon: Coins,
                label: "Credits used",
                value: nf.format(report.totals.credits),
              },
              {
                icon: CheckCheck,
                label: "Tasks completed",
                value: nf.format(report.totals.tasks),
              },
            ].map(({ icon: Icon, label, value }) => (
              <Card key={label} className="p-4">
                <div className="flex items-center gap-1.5 text-[12px] text-fg-2">
                  <Icon className="size-3.5 text-fg-3" /> {label}
                </div>
                <div className="mt-2 font-mono text-[24px] font-medium tabular-nums">
                  {value}
                </div>
                <div className="text-[11.5px] text-fg-3">
                  last {report.range}
                </div>
              </Card>
            ))}
          </div>

          <Card className="p-5">
            <SectionHeader
              title="Tokens per day"
              subtitle={`All agents · last ${report.range}`}
            />
            <div
              className="mt-4 h-[240px]"
              role="img"
              aria-label={`Area chart of tokens per day over the last ${report.range}`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={report.daily}
                  margin={{ top: 6, right: 6, left: 0, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id={`u-${gid}`} x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="0%"
                        stopColor={c.accent}
                        stopOpacity={0.3}
                      />
                      <stop
                        offset="100%"
                        stopColor={c.accent}
                        stopOpacity={0}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke={c.grid} />
                  <XAxis
                    dataKey="day"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: c.fg3, fontSize: 11 }}
                    minTickGap={28}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: c.fg3, fontSize: 11 }}
                    tickFormatter={(v: number) => compact.format(v)}
                    width={44}
                  />
                  <Tooltip
                    cursor={{ stroke: c.fg3, strokeDasharray: "3 3" }}
                    content={({ active, payload, label }) =>
                      active && payload?.length ? (
                        <div className="rounded-[10px] border border-line bg-card px-3 py-2 text-[12px] shadow-[var(--shadow)]">
                          <div className="text-fg-3">{label}</div>
                          <div className="mt-0.5 font-mono text-fg">
                            {nf.format(Number(payload[0].value))} tokens
                          </div>
                          <div className="font-mono text-fg-2">
                            {nf.format(
                              Number(
                                (payload[0].payload as { credits: number })
                                  .credits,
                              ),
                            )}{" "}
                            credits
                          </div>
                        </div>
                      ) : null
                    }
                  />
                  <Area
                    type="monotone"
                    dataKey="tokens"
                    stroke={c.accent}
                    strokeWidth={2}
                    fill={`url(#u-${gid})`}
                    activeDot={{
                      r: 4,
                      stroke: c.card,
                      strokeWidth: 2,
                      fill: c.accent,
                    }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="p-5 pb-3">
              <SectionHeader
                title="By agent"
                subtitle="Credits include model and tool usage"
              />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-[13px]">
                <thead>
                  <tr className="border-y border-line bg-card-2 text-left text-[11px] font-semibold uppercase tracking-wider text-fg-3">
                    <th className="px-5 py-2.5">Agent</th>
                    <th className="px-3 py-2.5 text-right">Requests</th>
                    <th className="px-3 py-2.5 text-right">Tokens</th>
                    <th className="w-[28%] px-3 py-2.5">Credits</th>
                    <th className="px-5 py-2.5 text-right">Success</th>
                  </tr>
                </thead>
                <tbody>
                  {report.byAgent.map((a) => (
                    <tr
                      key={a.agent}
                      className="border-b border-line last:border-0"
                    >
                      <td className="px-5 py-3">
                        <span className="flex items-center gap-2.5">
                          {a.agent === "orchestrator" ? (
                            <span
                              className="grid size-[26px] place-items-center rounded-[8px] border border-line bg-card-2 text-fg-2"
                              aria-hidden
                            >
                              <Network className="size-3.5" />
                            </span>
                          ) : (
                            <AgentGlyph agent={a.agent} size={26} />
                          )}
                          {agentShortName(a.agent)}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-fg-2">
                        {nf.format(a.requests)}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-fg-2">
                        {compact.format(a.tokens)}
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          <Bar value={a.credits / maxAgentCredits} />
                          <span className="w-12 shrink-0 text-right font-mono text-fg">
                            {nf.format(a.credits)}
                          </span>
                        </div>
                      </td>
                      <td
                        className={cn(
                          "px-5 py-3 text-right font-mono",
                          a.successRate < 0.93 ? "text-warn" : "text-fg-2",
                        )}
                      >
                        {Math.round(a.successRate * 100)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <div className="p-5 pb-3">
              <SectionHeader
                title="By model"
                subtitle={
                  <>
                    Provider cost estimate {usd.format(totalCost)} · self-hosted
                    models show $0
                  </>
                }
              />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-[13px]">
                <thead>
                  <tr className="border-y border-line bg-card-2 text-left text-[11px] font-semibold uppercase tracking-wider text-fg-3">
                    <th className="px-5 py-2.5">Model</th>
                    <th className="px-3 py-2.5">Task type</th>
                    <th className="px-3 py-2.5 text-right">Requests</th>
                    <th className="px-3 py-2.5 text-right">Tokens in / out</th>
                    <th className="px-5 py-2.5 text-right">Est. cost</th>
                  </tr>
                </thead>
                <tbody>
                  {report.byModel.map((m) => (
                    <tr
                      key={m.model}
                      className="border-b border-line last:border-0"
                    >
                      <td className="px-5 py-3">
                        <div className="font-mono text-[12.5px] text-fg">
                          {m.model}
                        </div>
                        <div className="text-[11.5px] text-fg-3">
                          {PROVIDER_NAME[m.provider]}
                        </div>
                      </td>
                      <td className="px-3 py-3 capitalize text-fg-2">
                        {m.capability.replace("_", " ")}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-fg-2">
                        {nf.format(m.requests)}
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-fg-2">
                        {compact.format(m.tokensIn)} /{" "}
                        {compact.format(m.tokensOut)}
                      </td>
                      <td className="px-5 py-3 text-right font-mono text-fg">
                        {usd.format(m.costUsd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          {!p ? null : (
            <Card className="relative overflow-hidden p-5">
              <div
                aria-hidden
                className="pointer-events-none absolute -right-16 -top-16 size-48 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent-2)_22%,transparent),transparent)]"
              />
              <div className="relative">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-[13px] font-medium">
                    <Sparkles className="size-4 text-accent-2" /> {p.name} plan
                  </span>
                  <Badge tone="ok">Active</Badge>
                </div>
                <div className="mt-4 font-mono text-[30px] font-medium tabular-nums">
                  {nf.format(p.creditsRemaining)}
                </div>
                <div className="text-[12.5px] text-fg-2">
                  credits remaining of {nf.format(p.creditsTotal)}
                </div>
                <div className="mt-3">
                  <Bar
                    value={used / p.creditsTotal}
                    tone="linear-gradient(90deg,var(--accent),var(--accent-2))"
                  />
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-2 text-[12px]">
                  <div className="rounded-[10px] border border-line bg-card-2 px-3 py-2">
                    <dt className="text-fg-3">Renews</dt>
                    <dd className="mt-0.5 text-[13px]">{p.renewsOn}</dd>
                  </div>
                  <div className="rounded-[10px] border border-line bg-card-2 px-3 py-2">
                    <dt className="text-fg-3">Seats</dt>
                    <dd className="mt-0.5 font-mono text-[13px]">
                      {p.seatsUsed}/{p.seats}
                    </dd>
                  </div>
                </dl>
                <div className="mt-4 flex gap-2">
                  <Button
                    variant="primary"
                    className="flex-1"
                    onClick={() =>
                      toast({
                        tone: "info",
                        title: "Demo mode",
                        description:
                          "Plan changes connect to the billing provider in Phase 6.",
                      })
                    }
                  >
                    Manage plan
                  </Button>
                  <Button
                    onClick={() =>
                      toast({
                        tone: "info",
                        title: "Demo mode",
                        description:
                          "Credit top-ups connect to the billing provider in Phase 6.",
                      })
                    }
                  >
                    Buy credits
                  </Button>
                </div>
              </div>
            </Card>
          )}

          <Card className="p-5">
            <h3 className="flex items-center gap-1.5 text-[15px] font-semibold">
              <Users className="size-4 text-fg-3" /> By member
            </h3>
            <ul className="mt-3 space-y-3">
              {report.byMember.map((m) => (
                <li key={m.name}>
                  <div className="flex items-center justify-between text-[13px]">
                    <span>
                      {m.name}{" "}
                      <span className="text-[11.5px] capitalize text-fg-3">
                        · {m.role}
                      </span>
                    </span>
                    <span className="font-mono text-fg-2">
                      {nf.format(m.credits)}
                    </span>
                  </div>
                  <div className="mt-1.5">
                    <Bar value={m.credits / maxMember} tone="var(--accent-2)" />
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          {demo ? (
            <>
              <Card className="p-5">
                <h3 className="flex items-center gap-1.5 text-[15px] font-semibold">
                  <Bell className="size-4 text-fg-3" /> Limits & alerts
                </h3>
                <ul className="mt-3 space-y-3">
                  {[
                    {
                      k: "credits80" as const,
                      t: "Alert at 80% of credits",
                      d: "Email owners and admins",
                    },
                    {
                      k: "agentCap" as const,
                      t: "Per-agent monthly cap",
                      d: "Engineer capped at 2,500 credits",
                    },
                    {
                      k: "memberCap" as const,
                      t: "Per-member hard limit",
                      d: "Block new tasks above 1,000 credits",
                    },
                    {
                      k: "weekly" as const,
                      t: "Weekly usage digest",
                      d: "Mondays 08:30",
                    },
                  ].map((x) => (
                    <li
                      key={x.k}
                      className="flex items-start justify-between gap-3"
                    >
                      <div>
                        <p className="text-[13px]">{x.t}</p>
                        <p className="text-[11.5px] text-fg-3">{x.d}</p>
                      </div>
                      <Switch
                        checked={alerts[x.k]}
                        onCheckedChange={(v) =>
                          setAlerts((a) => ({ ...a, [x.k]: v }))
                        }
                        label={x.t}
                      />
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-[11.5px] text-fg-3">
                  Limits are enforced by the Usage & Billing engine before each
                  step, not just in the UI.
                </p>
              </Card>

              <Card className="p-5">
                <h3 className="flex items-center gap-1.5 text-[15px] font-semibold">
                  <Receipt className="size-4 text-fg-3" /> Invoices
                </h3>
                <ul className="mt-3 divide-y divide-[var(--border)]">
                  {!report.invoices?.length && (
                    <li className="py-2.5 text-[13px] text-fg-3">
                      No invoices yet.
                    </li>
                  )}
                  {(report.invoices ?? []).map((inv) => (
                    <li
                      key={inv.id}
                      className="flex items-center justify-between gap-3 py-2.5 text-[13px]"
                    >
                      <div>
                        <p>{inv.period}</p>
                        <p className="font-mono text-[11.5px] text-fg-3">
                          {inv.id}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono">
                          {usd.format(inv.amountUsd)}
                        </span>
                        <Badge tone={inv.status === "paid" ? "ok" : "warn"}>
                          {inv.status === "paid" ? "Paid" : "Open"}
                        </Badge>
                        <button
                          type="button"
                          aria-label={`Download ${inv.id}`}
                          className="grid size-7 place-items-center rounded-md text-fg-3 hover:bg-card-2 hover:text-fg"
                          onClick={() =>
                            toast({
                              tone: "info",
                              title: "Demo mode",
                              description:
                                "Invoices come from the billing provider in Phase 6.",
                            })
                          }
                        >
                          <Download className="size-3.5" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
