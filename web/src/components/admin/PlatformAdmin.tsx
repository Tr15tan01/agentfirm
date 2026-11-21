"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { Loader2, Pencil, Plus, Power, RotateCcw } from "lucide-react";
import { useState } from "react";
import { api } from "@/data/api";
import { LiveBoundary, LIVE_DATA, refresh, useResource } from "@/lib/live";
import type { AccountRow, AdminPack, AdminPackInput, AdminPlan, AdminPlanInput, AgentAdminRow, ToolRow } from "@/lib/api/contracts";
import { Badge, Button, Card } from "@/components/ui/primitives";
import { Field, inputClass, Modal, money, shortDate } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";
import { Switch } from "@/components/ui/Switch";

/** Super-admin: plans & pricing, workspaces & credits, agents & tools, billing events. Every
 * action is authorised and audit-logged by the API; this screen only presents it. */
export function PlatformAdmin() {
  if (!LIVE_DATA) {
    return <Card className="p-6 text-[13.5px] text-fg-2">Platform administration needs the live API (NEXT_PUBLIC_AGENTFIRM_API=http).</Card>;
  }
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-[22px] font-semibold tracking-tight">Platform</h2>
        <p className="mt-1 text-[13.5px] text-fg-2">Plans and prices, workspaces and credits, agents and tools. Every change is audit-logged.</p>
      </div>
      <Tabs.Root defaultValue="plans">
        <Tabs.List className="flex gap-1 overflow-x-auto border-b border-line" aria-label="Platform sections">
          {[
            ["plans", "Plans & pricing"],
            ["accounts", "Workspaces"],
            ["agents", "Agents & tools"],
            ["events", "Billing events"],
          ].map(([v, l]) => (
            <Tabs.Trigger key={v} value={v} className="-mb-px border-b-2 border-transparent px-3 py-2 text-[13.5px] text-fg-2 data-[state=active]:border-accent data-[state=active]:text-fg">
              {l}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <div className="pt-5">
          <Tabs.Content value="plans">
            <LiveBoundary>
              <PlansTab />
            </LiveBoundary>
          </Tabs.Content>
          <Tabs.Content value="accounts">
            <LiveBoundary>
              <AccountsTab />
            </LiveBoundary>
          </Tabs.Content>
          <Tabs.Content value="agents">
            <LiveBoundary>
              <AgentsTab />
            </LiveBoundary>
          </Tabs.Content>
          <Tabs.Content value="events">
            <LiveBoundary>
              <EventsTab />
            </LiveBoundary>
          </Tabs.Content>
        </div>
      </Tabs.Root>
    </div>
  );
}

function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try {
      await fn();
      if (ok) toast({ tone: "success", title: ok });
      return true;
    } catch (e) {
      toast({ tone: "error", title: "Not saved", description: e instanceof Error ? e.message : String(e) });
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
}

/* ── plans & packs ─────────────────────────────────────────────────────── */

function PlansTab() {
  const plans = useResource("admin:plans", () => api.platform.plans());
  const packs = useResource("admin:packs", () => api.platform.packs());
  const [editPlan, setEditPlan] = useState<AdminPlan | "new" | null>(null);
  const [editPack, setEditPack] = useState<AdminPack | "new" | null>(null);
  return (
    <div className="space-y-5">
      <Card className="p-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-[15px] font-semibold">Plans</h3>
            <p className="text-[12.5px] text-fg-3">A paid plan is for sale once it has a price and a Paddle price ID (pri_…) from your Paddle catalog.</p>
          </div>
          <Button onClick={() => setEditPlan("new")}>
            <Plus className="size-4" /> New plan
          </Button>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="text-[11.5px] uppercase tracking-wide text-fg-3">
              <tr>
                {["Plan", "Price", "Credits / mo", "Seats", "Tasks at once", "Agents", "Paddle price", "Workspaces", ""].map((h) => (
                  <th key={h} className="py-2 pr-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {plans.map((p) => (
                <tr key={p.key}>
                  <td className="py-2.5 pr-3">
                    <span className="font-medium">{p.name}</span> <span className="font-mono text-[11.5px] text-fg-3">{p.key}</span>
                    {!p.is_active ? <Badge tone="muted" className="ml-1">inactive</Badge> : !p.is_public ? <Badge tone="muted" className="ml-1">hidden</Badge> : null}
                  </td>
                  <td className="py-2.5 pr-3">{p.price_cents === 0 ? "Free" : money(p.price_cents, p.currency)}</td>
                  <td className="py-2.5 pr-3 font-mono">{p.monthly_credits.toLocaleString()}</td>
                  <td className="py-2.5 pr-3 font-mono">{p.max_seats}</td>
                  <td className="py-2.5 pr-3 font-mono">{p.max_concurrent_tasks}</td>
                  <td className="py-2.5 pr-3">{p.agents ? p.agents.join(", ") : "All"}</td>
                  <td className="py-2.5 pr-3 font-mono text-[12px]">{p.paddle_price_id ?? "—"}</td>
                  <td className="py-2.5 pr-3 font-mono">{p.organizations}</td>
                  <td className="py-2.5 text-right">
                    <Button size="sm" aria-label={`Edit ${p.name}`} onClick={() => setEditPlan(p)}>
                      <Pencil className="size-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card className="p-5">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-[15px] font-semibold">Credit packs</h3>
            <p className="text-[12.5px] text-fg-3">One-time top-ups; credits never expire.</p>
          </div>
          <Button onClick={() => setEditPack("new")}>
            <Plus className="size-4" /> New pack
          </Button>
        </div>
        {packs.length === 0 ? <p className="mt-3 text-[13px] text-fg-2">No credit packs yet.</p> : null}
        <ul className="mt-3 divide-y divide-line">
          {packs.map((k) => (
            <li key={k.key} className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
              <span>
                <span className="font-medium">{k.name}</span> · {k.credits.toLocaleString()} credits · {money(k.price_cents, k.currency)}{" "}
                <span className="font-mono text-[11.5px] text-fg-3">{k.paddle_price_id ?? "no Paddle price"}</span>
                {!k.is_active ? <Badge tone="muted" className="ml-1">inactive</Badge> : null}
              </span>
              <Button size="sm" aria-label={`Edit ${k.name}`} onClick={() => setEditPack(k)}>
                <Pencil className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      </Card>
      {editPlan ? <PlanDialog plan={editPlan === "new" ? null : editPlan} onClose={() => setEditPlan(null)} /> : null}
      {editPack ? <PackDialog pack={editPack === "new" ? null : editPack} onClose={() => setEditPack(null)} /> : null}
    </div>
  );
}

const num = (v: string) => (v.trim() === "" ? null : Math.round(Number(v)));

function PlanDialog({ plan, onClose }: { plan: AdminPlan | null; onClose: () => void }) {
  const { busy, run } = useAction();
  const [key, setKey] = useState(plan?.key ?? "");
  const [f, setF] = useState({
    name: plan?.name ?? "",
    description: plan?.description ?? "",
    monthly_credits: String(plan?.monthly_credits ?? 1000),
    max_seats: String(plan?.max_seats ?? 5),
    max_concurrent_tasks: String(plan?.max_concurrent_tasks ?? 3),
    price: plan?.price_cents === null || plan?.price_cents === undefined ? "" : String(plan.price_cents / 100),
    currency: plan?.currency ?? "EUR",
    paddle_price_id: plan?.paddle_price_id ?? "",
    agents: plan?.agents?.join(", ") ?? "",
    is_public: plan?.is_public ?? true,
    is_active: plan?.is_active ?? true,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    const body: AdminPlanInput = {
      name: f.name,
      description: f.description,
      monthly_credits: Number(f.monthly_credits),
      max_seats: Number(f.max_seats),
      max_concurrent_tasks: Number(f.max_concurrent_tasks),
      price_cents: f.price.trim() === "" ? null : Math.round(Number(f.price) * 100),
      currency: f.currency.toUpperCase(),
      paddle_price_id: f.paddle_price_id.trim() || null,
      agents: f.agents.trim() ? f.agents.split(",").map((s) => s.trim()).filter(Boolean) : null,
      is_public: f.is_public,
      is_active: f.is_active,
      sort: plan?.sort ?? 10,
    };
    if (await run(() => api.platform.savePlan(key.trim(), body), "Plan saved")) {
      refresh("admin:plans");
      onClose();
    }
  };
  return (
    <Modal title={plan ? `Edit ${plan.name}` : "New plan"} description="Changes apply to every workspace on this plan from now on." onClose={onClose} wide>
      <form className="grid gap-3 md:grid-cols-2" onSubmit={(e) => (e.preventDefault(), void save())}>
        <Field label="Key" hint="lowercase id, can't change later">
          <input className={inputClass} value={key} onChange={(e) => setKey(e.target.value)} disabled={!!plan} required pattern="[a-z0-9_]{2,32}" />
        </Field>
        <Field label="Name">
          <input className={inputClass} value={f.name} onChange={set("name")} required />
        </Field>
        <div className="md:col-span-2">
          <Field label="Description">
            <input className={inputClass} value={f.description} onChange={set("description")} />
          </Field>
        </div>
        <Field label="Credits per month">
          <input className={inputClass} type="number" min={0} value={f.monthly_credits} onChange={set("monthly_credits")} required />
        </Field>
        <Field label="Seats">
          <input className={inputClass} type="number" min={1} value={f.max_seats} onChange={set("max_seats")} required />
        </Field>
        <Field label="Tasks at a time">
          <input className={inputClass} type="number" min={1} value={f.max_concurrent_tasks} onChange={set("max_concurrent_tasks")} required />
        </Field>
        <Field label="Agents" hint="comma-separated keys; empty = all">
          <input className={inputClass} value={f.agents} onChange={set("agents")} placeholder="research, creative" />
        </Field>
        <Field label="Monthly price" hint="empty = not for sale">
          <input className={inputClass} type="number" min={0} step="0.01" value={f.price} onChange={set("price")} />
        </Field>
        <Field label="Currency">
          <input className={inputClass} value={f.currency} onChange={set("currency")} maxLength={3} />
        </Field>
        <div className="md:col-span-2">
          <Field label="Paddle price ID" hint="From Paddle > Catalog > your product's monthly price (pri_…). Must match the price above.">
            <input className={inputClass} value={f.paddle_price_id} onChange={set("paddle_price_id")} placeholder="pri_01h…" />
          </Field>
        </div>
        <div className="flex gap-5 md:col-span-2">
          <Switch checked={f.is_public} onCheckedChange={(v) => setF({ ...f, is_public: v })} label="Shown to customers" />
          <Switch checked={f.is_active} onCheckedChange={(v) => setF({ ...f, is_active: v })} label="Active" />
        </div>
        <div className="flex gap-2 md:col-span-2">
          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null} Save plan
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

function PackDialog({ pack, onClose }: { pack: AdminPack | null; onClose: () => void }) {
  const { busy, run } = useAction();
  const [key, setKey] = useState(pack?.key ?? "");
  const [f, setF] = useState({
    name: pack?.name ?? "",
    credits: String(pack?.credits ?? 1000),
    price: pack?.price_cents === null || pack?.price_cents === undefined ? "" : String(pack.price_cents / 100),
    currency: pack?.currency ?? "EUR",
    paddle_price_id: pack?.paddle_price_id ?? "",
    is_active: pack?.is_active ?? true,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    const body: AdminPackInput = {
      name: f.name,
      credits: Number(f.credits),
      price_cents: num(f.price) === null ? null : Math.round(Number(f.price) * 100),
      currency: f.currency.toUpperCase(),
      paddle_price_id: f.paddle_price_id.trim() || null,
      is_active: f.is_active,
    };
    if (await run(() => api.platform.savePack(key.trim(), body), "Credit pack saved")) {
      refresh("admin:packs");
      onClose();
    }
  };
  return (
    <Modal title={pack ? `Edit ${pack.name}` : "New credit pack"} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), void save())}>
        <Field label="Key">
          <input className={inputClass} value={key} onChange={(e) => setKey(e.target.value)} disabled={!!pack} required pattern="[a-z0-9_]{2,32}" />
        </Field>
        <Field label="Name">
          <input className={inputClass} value={f.name} onChange={set("name")} required />
        </Field>
        <Field label="Credits">
          <input className={inputClass} type="number" min={1} value={f.credits} onChange={set("credits")} required />
        </Field>
        <Field label="Price" hint="empty = not for sale">
          <input className={inputClass} type="number" min={0} step="0.01" value={f.price} onChange={set("price")} />
        </Field>
        <Field label="Paddle price ID (one-time price)">
          <input className={inputClass} value={f.paddle_price_id} onChange={set("paddle_price_id")} placeholder="pri_01h…" />
        </Field>
        <Switch checked={f.is_active} onCheckedChange={(v) => setF({ ...f, is_active: v })} label="Active" />
        <div className="flex gap-2">
          <Button variant="primary" type="submit" disabled={busy}>
            Save pack
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}

/* ── workspaces ────────────────────────────────────────────────────────── */

function AccountsTab() {
  const rows = useResource("admin:accounts", () => api.platform.accounts());
  const plans = useResource("admin:plans", () => api.platform.plans());
  const [grant, setGrant] = useState<AccountRow | null>(null);
  const [assign, setAssign] = useState<AccountRow | null>(null);
  return (
    <Card className="p-5">
      <h3 className="text-[15px] font-semibold">Workspaces</h3>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-[13px]">
          <thead className="text-[11.5px] uppercase tracking-wide text-fg-3">
            <tr>
              {["Workspace", "Plan", "Billing", "Credits left", "Used (30 days)", "Members", "Created", ""].map((h) => (
                <th key={h} className="py-2 pr-3 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="py-2.5 pr-3 font-medium">{r.name}</td>
                <td className="py-2.5 pr-3">
                  {r.plan} {r.status !== "active" ? <Badge tone="warn">{r.status}</Badge> : null}
                </td>
                <td className="py-2.5 pr-3">{r.provider === "paddle" ? "Paddle" : r.provider === "manual" ? "Invoiced" : "—"}</td>
                <td className="py-2.5 pr-3 font-mono">{r.credits_available.toLocaleString()}</td>
                <td className="py-2.5 pr-3 font-mono">{r.credits_used_30d.toLocaleString()}</td>
                <td className="py-2.5 pr-3 font-mono">{r.members}</td>
                <td className="py-2.5 pr-3">{shortDate(r.created_at)}</td>
                <td className="whitespace-nowrap py-2.5 text-right">
                  <Button size="sm" onClick={() => setGrant(r)}>
                    Credits
                  </Button>{" "}
                  <Button size="sm" onClick={() => setAssign(r)} disabled={r.provider === "paddle" && r.status !== "canceled"} title={r.provider === "paddle" ? "Managed in Paddle" : undefined}>
                    Plan
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {grant ? <GrantDialog row={grant} onClose={() => setGrant(null)} /> : null}
      {assign ? <AssignDialog row={assign} plans={plans} onClose={() => setAssign(null)} /> : null}
    </Card>
  );
}

function GrantDialog({ row, onClose }: { row: AccountRow; onClose: () => void }) {
  const { busy, run } = useAction();
  const [credits, setCredits] = useState("500");
  const [note, setNote] = useState("");
  return (
    <Modal title={`Credits for ${row.name}`} description="Adds (or with a negative number removes) purchased credits. Recorded in the workspace's credit history and the audit log." onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api.platform.grantCredits(row.id, Number(credits), note), "Credits updated")) {
            refresh("admin:accounts");
            onClose();
          }
        }}
      >
        <Field label="Credits">
          <input className={inputClass} type="number" value={credits} onChange={(e) => setCredits(e.target.value)} required />
        </Field>
        <Field label="Reason (visible to the workspace)">
          <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} required minLength={3} placeholder="Goodwill after the outage on 12 Nov" />
        </Field>
        <Button variant="primary" type="submit" disabled={busy}>
          Apply
        </Button>
      </form>
    </Modal>
  );
}

function AssignDialog({ row, plans, onClose }: { row: AccountRow; plans: AdminPlan[]; onClose: () => void }) {
  const { busy, run } = useAction();
  const [plan, setPlan] = useState(row.plan);
  const [note, setNote] = useState("");
  return (
    <Modal title={`Plan for ${row.name}`} description="For customers invoiced outside Paddle. Starts a new allowance period now." onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api.platform.setPlan(row.id, plan, note), "Plan assigned")) {
            refresh("admin:accounts");
            onClose();
          }
        }}
      >
        <Field label="Plan">
          <select className={inputClass} value={plan} onChange={(e) => setPlan(e.target.value)}>
            {plans
              .filter((p) => p.is_active)
              .map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Reason">
          <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} required minLength={3} placeholder="Annual contract #1042" />
        </Field>
        <Button variant="primary" type="submit" disabled={busy}>
          Assign plan
        </Button>
      </form>
    </Modal>
  );
}

/* ── agents & tools ────────────────────────────────────────────────────── */

function AgentsTab() {
  const agents = useResource("admin:agents", () => api.platform.agents());
  const tools = useResource("admin:tools", () => api.platform.tools());
  const { busy, run } = useAction();
  const reason = (what: string) => window.prompt(`Reason for ${what} (audit log):`)?.trim();
  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h3 className="text-[15px] font-semibold">Agents</h3>
        <p className="text-[12.5px] text-fg-3">Turning an agent off stops new and queued runs at once. Rollback makes an earlier published version current.</p>
        <ul className="mt-3 divide-y divide-line">
          {agents.map((a: AgentAdminRow) => (
            <li key={a.key} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-[13px]">
              <span>
                <span className="font-medium">{a.name}</span> <span className="font-mono text-[11.5px] text-fg-3">{a.current_version ?? "unpublished"}</span>
                {!a.enabled ? <Badge tone="err" className="ml-1">off</Badge> : null}
              </span>
              <span className="flex items-center gap-2">
                <select
                  className={`${inputClass} h-8 w-28`}
                  aria-label={`Roll back ${a.name}`}
                  value=""
                  disabled={busy || a.versions.length < 2}
                  onChange={async (e) => {
                    const v = e.target.value;
                    const why = v ? reason(`rolling ${a.name} back to ${v}`) : null;
                    if (v && why && (await run(() => api.platform.rollbackAgent(a.key, v, why), `${a.name} is now ${v}`))) refresh("admin:agents");
                  }}
                >
                  <option value="">Roll back…</option>
                  {a.versions
                    .filter((v) => v !== a.current_version)
                    .map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                </select>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={async () => {
                    const why = reason(`${a.enabled ? "turning off" : "turning on"} ${a.name}`);
                    if (why && (await run(() => api.platform.setAgentEnabled(a.key, !a.enabled, why)))) refresh("admin:agents");
                  }}
                >
                  {a.enabled ? <Power className="size-3.5" /> : <RotateCcw className="size-3.5" />} {a.enabled ? "Turn off" : "Turn on"}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card className="p-5">
        <h3 className="text-[15px] font-semibold">Tools</h3>
        <p className="text-[12.5px] text-fg-3">Kill-switch for every workspace, e.g. during a provider incident. Agents report the tool as unavailable; nothing is retried behind your back.</p>
        <ul className="mt-3 divide-y divide-line">
          {tools.map((t: ToolRow) => (
            <li key={t.key} className="flex flex-wrap items-center justify-between gap-3 py-2 text-[13px]">
              <span className="min-w-0">
                <span className="font-mono">{t.key}</span> <Badge tone={t.side_effect === "none" || t.side_effect === "internal" ? "muted" : "warn"}>{t.side_effect}</Badge>
                <span className="block truncate text-[11.5px] text-fg-3">
                  {t.disabled ? `Off: ${t.reason}` : t.description} · used by {t.agents.join(", ") || "no agent"}
                </span>
              </span>
              <Switch
                checked={!t.disabled}
                disabled={busy}
                label={t.disabled ? "Off" : "On"}
                onCheckedChange={async (on) => {
                  const why = reason(`${on ? "turning on" : "turning off"} ${t.key}`);
                  if (why && (await run(() => api.platform.switchTool(t.key, !on, why)))) refresh("admin:tools");
                }}
              />
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function EventsTab() {
  const events = useResource("admin:billing-events", () => api.platform.billingEvents());
  return (
    <Card className="p-5">
      <h3 className="text-[15px] font-semibold">Paddle webhooks</h3>
      <p className="text-[12.5px] text-fg-3">Verified events, stored once. Errors are acknowledged to Paddle (no retry storm) and listed here for follow-up.</p>
      {events.length === 0 ? <p className="mt-3 text-[13px] text-fg-2">No events received yet.</p> : null}
      <ul className="mt-3 divide-y divide-line">
        {events.map((e) => (
          <li key={e.id} className="py-2 text-[13px]">
            <span className="font-mono">{e.type}</span> · {shortDate(e.received_at)}{" "}
            {e.error ? <Badge tone="err">error</Badge> : e.processed_at ? <Badge tone="ok">applied</Badge> : <Badge tone="muted">ignored</Badge>}
            <span className="block truncate font-mono text-[11.5px] text-fg-3">
              {e.id}
              {e.error ? ` · ${e.error}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
