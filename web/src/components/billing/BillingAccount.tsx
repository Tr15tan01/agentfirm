"use client";

import { Check, CreditCard, ExternalLink, FileText, Loader2, Sparkles, Users, Zap } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/data/api";
import { refresh, useResource } from "@/lib/live";
import type { BillingAccount as Account, BillingCatalog, InvoiceRow, LedgerRow } from "@/lib/api/contracts";
import { Badge, Button, Card, Progress } from "@/components/ui/primitives";
import { money, shortDate } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

const REASON: Record<string, string> = {
  period_grant: "Plan allowance",
  top_up: "Credit top-up",
  admin_grant: "Added by AgentFirm",
  admin_debit: "Removed by AgentFirm",
  refund: "Refund",
};

/** Paddle pages are external; the fixture checkout and portal are pages of this app. */
function useGo() {
  const router = useRouter();
  return (url: string) => (url.startsWith("/") ? router.push(url) : window.location.assign(url));
}

const STATUS_TONE: Record<string, "ok" | "warn" | "err" | "muted"> = { active: "ok", trialing: "ok", past_due: "warn", paused: "muted", canceled: "err" };

/** Plan, credits, limits, upgrades, top-ups, invoices and the credit ledger (live data only). */
export function BillingAccount() {
  const account = useResource("billing:account", () => api.account.summary());
  const catalog = useResource("billing:catalog", () => api.account.catalog());
  const params = useSearchParams();
  const toast = useToast();

  useEffect(() => {
    if (params.get("paid")) {
      toast({ tone: "success", title: "Payment received", description: "Your plan and credits update as soon as Paddle confirms it." });
      const id = setInterval(() => refresh("billing:"), 2000);
      const stop = setTimeout(() => clearInterval(id), 12000);
      return () => {
        clearInterval(id);
        clearTimeout(stop);
      };
    }
  }, [params, toast]);

  return (
    <div className="space-y-5">
      <AccountSummary a={account} />
      <Plans a={account} catalog={catalog} />
      {account.can_manage ? <History /> : null}
    </div>
  );
}

function AccountSummary({ a }: { a: Account }) {
  const toast = useToast();
  const go = useGo();
  const [busy, setBusy] = useState<string | null>(null);
  const planPct = a.credits_plan_monthly ? a.credits_plan_remaining / a.credits_plan_monthly : 0;
  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    try {
      await fn();
    } catch (e) {
      toast({ tone: "error", title: "Couldn't do that", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[12px] font-medium uppercase tracking-wide text-fg-3">Current plan</p>
          <div className="mt-1 flex items-center gap-2">
            <h2 className="text-[22px] font-semibold tracking-tight">{a.plan.name}</h2>
            <Badge tone={STATUS_TONE[a.status] ?? "muted"}>{a.status.replace("_", " ")}</Badge>
            {a.provider === "manual" ? <Badge tone="muted">Invoiced</Badge> : null}
          </div>
          <p className="mt-1 text-[13px] text-fg-2">
            {a.cancel_at_period_end ? `Ends ${shortDate(a.period_end)}, then the Free plan applies. ` : `Allowance renews ${shortDate(a.period_end)}. `}
            {a.status === "past_due" ? "Paddle couldn't take the last payment; update your payment method to keep this plan." : null}
          </p>
        </div>
        {a.can_manage ? (
          <div className="flex flex-wrap gap-2">
            {a.portal_available ? (
              <Button disabled={!!busy} onClick={() => run("portal", async () => go((await api.account.portal()).url))}>
                {busy === "portal" ? <Loader2 className="size-4 animate-spin" /> : <CreditCard className="size-4" />} Payment & invoices
              </Button>
            ) : null}
            {a.provider === "paddle" && !a.cancel_at_period_end && ["active", "trialing", "past_due"].includes(a.status) ? (
              <Button
                disabled={!!busy}
                onClick={() =>
                  run("cancel", async () => {
                    if (!window.confirm(`Cancel ${a.plan.name}? It stays active until ${shortDate(a.period_end)}, then the Free plan applies. Purchased credits are kept.`)) return;
                    await api.account.cancel();
                    refresh("billing:");
                  })
                }
              >
                Cancel plan
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <div className="rounded-[12px] border border-line p-3.5">
          <div className="flex items-center justify-between text-[12.5px] text-fg-2">
            <span className="inline-flex items-center gap-1.5">
              <Zap className="size-3.5" /> Credits available
            </span>
            <span className="font-mono text-fg">{a.credits_available.toLocaleString()}</span>
          </div>
          <Progress value={Math.max(0, Math.min(1, planPct))} className="mt-2.5" />
          <p className="mt-2 text-[11.5px] text-fg-3">
            {a.credits_plan_remaining.toLocaleString()} of {a.credits_plan_monthly.toLocaleString()} plan credits left · {a.credits_purchased.toLocaleString()} purchased (kept until used). Plan credits are used first.
          </p>
        </div>
        <Meter icon={<Users className="size-3.5" />} label="Seats" used={a.seats_used} max={a.seats_max} />
        <Meter icon={<Sparkles className="size-3.5" />} label="Tasks running" used={a.tasks_active} max={a.tasks_max} />
      </div>
      {a.credits_available <= 0 ? (
        <p className="mt-3 rounded-[10px] border border-[color:var(--warn)]/40 bg-[color:var(--warn)]/10 px-3 py-2 text-[13px]">
          You&apos;re out of credits: new tasks and model calls are paused until the allowance renews or you buy credits.
        </p>
      ) : null}
    </Card>
  );
}

function Meter({ icon, label, used, max }: { icon: React.ReactNode; label: string; used: number; max: number }) {
  return (
    <div className="rounded-[12px] border border-line p-3.5">
      <div className="flex items-center justify-between text-[12.5px] text-fg-2">
        <span className="inline-flex items-center gap-1.5">
          {icon} {label}
        </span>
        <span className="font-mono text-fg">
          {used} / {max}
        </span>
      </div>
      <Progress value={max ? Math.min(1, used / max) : 0} className="mt-2.5" />
      <p className="mt-2 text-[11.5px] text-fg-3">Plan limit, enforced by the server.</p>
    </div>
  );
}

function Plans({ a, catalog }: { a: Account; catalog: BillingCatalog }) {
  const toast = useToast();
  const go = useGo();
  const [busy, setBusy] = useState<string | null>(null);
  const buy = async (input: { plan?: string; credit_pack?: string }) => {
    setBusy(input.plan ?? input.credit_pack ?? "");
    try {
      const r = await api.account.checkout(input);
      if (r.changed) {
        toast({ tone: "success", title: "Plan change requested", description: "Paddle prorates the difference; your allowance updates when it confirms." });
        setTimeout(() => refresh("billing:"), 1500);
      } else if (r.checkout_url) {
        go(r.checkout_url);
      }
    } catch (e) {
      toast({ tone: "error", title: "Checkout unavailable", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[15px] font-semibold">Plans</h3>
        <p className="text-[12px] text-fg-3">
          Payments by Paddle (merchant of record: tax and invoices are handled by Paddle).{catalog.provider_mode === "fixture" ? " Test mode: no real payments." : ""}
        </p>
      </div>
      {!catalog.billing_enabled ? <p className="mt-2 text-[13px] text-fg-2">Paid plans are turned off on this server.</p> : null}
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {catalog.plans.map((p) => {
          const current = p.key === a.plan.key;
          return (
            <div key={p.key} className={`flex flex-col rounded-[12px] border p-4 ${current ? "border-accent" : "border-line"}`}>
              <div className="flex items-center justify-between">
                <span className="text-[15px] font-semibold">{p.name}</span>
                {current ? <Badge tone="accent">Current</Badge> : null}
              </div>
              <p className="mt-1 text-[22px] font-semibold tracking-tight">
                {p.price_cents === 0 ? "Free" : money(p.price_cents, p.currency)}
                {p.price_cents ? <span className="text-[13px] font-normal text-fg-3"> / month</span> : null}
              </p>
              <p className="mt-1 text-[12.5px] text-fg-2">{p.description}</p>
              <ul className="mt-3 space-y-1.5 text-[12.5px]">
                {[
                  `${p.monthly_credits.toLocaleString()} credits / month`,
                  `${p.max_seats} seats`,
                  `${p.max_concurrent_tasks} tasks at a time`,
                  p.agents ? `Agents: ${p.agents.join(", ")}` : "All six agents",
                ].map((f) => (
                  <li key={f} className="flex items-center gap-1.5">
                    <Check className="size-3.5 text-[color:var(--ok)]" /> {f}
                  </li>
                ))}
              </ul>
              <div className="mt-auto pt-4">
                {current || p.key === "free" ? null : !a.can_manage ? (
                  <p className="text-[12px] text-fg-3">Only owners can change the plan.</p>
                ) : p.purchasable ? (
                  <Button variant="primary" className="w-full" disabled={!!busy || a.provider === "manual"} onClick={() => void buy({ plan: p.key })}>
                    {busy === p.key ? <Loader2 className="size-4 animate-spin" /> : null}
                    {a.provider === "paddle" ? `Switch to ${p.name}` : `Upgrade to ${p.name}`}
                  </Button>
                ) : (
                  <p className="text-[12px] text-fg-3">Not available yet.</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {catalog.credit_packs.length ? (
        <div className="mt-5">
          <h4 className="text-[13px] font-semibold">Need more credits now?</h4>
          <div className="mt-2 flex flex-wrap gap-2">
            {catalog.credit_packs.map((k) => (
              <Button key={k.key} disabled={!a.can_manage || !k.purchasable || !!busy} onClick={() => void buy({ credit_pack: k.key })}>
                {busy === k.key ? <Loader2 className="size-4 animate-spin" /> : <Zap className="size-4" />}
                {k.credits.toLocaleString()} credits · {money(k.price_cents, k.currency)}
              </Button>
            ))}
          </div>
          <p className="mt-1.5 text-[11.5px] text-fg-3">Purchased credits never expire and are used after your plan allowance.</p>
        </div>
      ) : null}
    </Card>
  );
}

function History() {
  const invoices = useResource("billing:invoices", () => api.account.invoices());
  const ledger = useResource("billing:ledger", () => api.account.ledger());
  const toast = useToast();
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="p-5">
        <h3 className="text-[15px] font-semibold">Invoices</h3>
        {invoices.length === 0 ? (
          <p className="mt-2 text-[13px] text-fg-2">No invoices yet. They appear here after each Paddle payment.</p>
        ) : (
          <ul className="mt-3 divide-y divide-line">
            {invoices.map((i: InvoiceRow) => (
              <li key={i.id} className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
                <div className="min-w-0">
                  <p className="truncate font-medium">{i.description || i.kind}</p>
                  <p className="text-[11.5px] text-fg-3">
                    {i.number ?? "—"} · {shortDate(i.billed_at)} · {i.status}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono">{money(i.total_cents, i.currency)}</span>
                  <Button
                    size="sm"
                    aria-label="Open invoice PDF"
                    onClick={async () => {
                      try {
                        window.open((await api.account.invoicePdf(i.id)).url, "_blank", "noopener");
                      } catch (e) {
                        toast({ tone: "error", title: "Invoice unavailable", description: e instanceof Error ? e.message : String(e) });
                      }
                    }}
                  >
                    <FileText className="size-3.5" /> PDF <ExternalLink className="size-3" />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="p-5">
        <h3 className="text-[15px] font-semibold">Credit history</h3>
        <p className="mt-0.5 text-[12px] text-fg-3">Every grant and top-up, from an append-only ledger. Usage is itemised above.</p>
        <ul className="mt-3 divide-y divide-line">
          {ledger.slice(0, 12).map((l: LedgerRow) => (
            <li key={l.id} className="flex items-center justify-between gap-3 py-2 text-[13px]">
              <div className="min-w-0">
                <p className="truncate">{REASON[l.reason] ?? l.reason}</p>
                <p className="truncate text-[11.5px] text-fg-3">
                  {shortDate(l.created_at)}
                  {l.note ? ` · ${l.note}` : ""}
                </p>
              </div>
              <span className={`font-mono ${l.delta < 0 ? "text-[color:var(--danger)]" : ""}`}>
                {l.delta > 0 ? "+" : ""}
                {l.delta.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
