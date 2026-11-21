"use client";

import { Plus, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api } from "@/data/api";
import { LIVE_DATA, refresh, useResource } from "@/lib/live";
import type { StandingApproval, StandingInput } from "@/lib/api/contracts";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { Badge, Button, Card } from "@/components/ui/primitives";
import { Field, inputClass, Modal, shortDate } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

const FACT_LABEL: Record<string, string> = {
  channel: "Channel",
  amount: "Amount",
  currency: "Currency",
  campaign: "Campaign",
  payee: "Payee",
  recipient_domains: "Recipient domains",
  recipient_count: "Number of recipients",
  target_count: "Records affected",
  environment: "Environment",
  repository: "Repository",
};
const OP_LABEL: Record<string, string> = { eq: "is", in: "is one of", lte: "at most", gte: "at least", all_in: "all within" };

function describe(c: { fact: string; op: string; value: unknown }): string {
  const v = Array.isArray(c.value) ? c.value.join(", ") : String(c.value);
  return `${FACT_LABEL[c.fact] ?? c.fact} ${OP_LABEL[c.op] ?? c.op} ${v}`;
}

/** Pre-approve recurring actions within limits (ADR 0006). Enforced by the API: a standing approval
 * applies only while its creator could still approve the action themselves. */
export function StandingApprovals() {
  if (!LIVE_DATA) return <Card className="p-5 text-[13px] text-fg-2">Standing approvals need the live API.</Card>;
  return <StandingList />;
}

function StandingList() {
  const rows = useResource("standing:list", () => api.standing.list());
  const tools = useResource("standing:tools", () => api.standing.tools());
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h3 className="flex items-center gap-1.5 text-[15px] font-semibold">
            <ShieldCheck className="size-4 text-fg-3" /> Standing approvals
          </h3>
          <p className="mt-1 text-[12.5px] text-fg-2">
            Pre-approve a recurring action, such as the weekly report email to your own domain, so scheduled runs don&apos;t wait for you. Each one has conditions, a use limit and an expiry; every use is recorded on the run. Deploys to production and deletions always need a person.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="size-4" /> New
        </Button>
      </div>
      {rows.length === 0 ? <p className="mt-4 text-[13px] text-fg-3">None yet. Every external action waits for a person to approve it.</p> : null}
      <ul className="mt-3 divide-y divide-line">
        {rows.map((s: StandingApproval) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-[13px]">
            <div className="min-w-0">
              <p className="font-medium">
                {s.note} {s.active ? <Badge tone="ok">active</Badge> : <Badge tone="muted">{s.revoked_at ? "revoked" : s.uses >= s.max_uses ? "used up" : "expired"}</Badge>}
              </p>
              <p className="mt-0.5 text-[12px] text-fg-2">
                <span className="font-mono">{s.tool}</span>
                {s.agent ? ` · ${AGENT_IDENTITIES[s.agent as keyof typeof AGENT_IDENTITIES]?.shortName ?? s.agent} only` : " · any agent"}
                {s.conditions.length ? ` · ${s.conditions.map(describe).join(" · ")}` : " · no conditions"}
              </p>
              <p className="text-[11.5px] text-fg-3">
                Used {s.uses} of {s.max_uses} · expires {shortDate(s.expires_at)}
              </p>
            </div>
            {s.active ? (
              <Button
                size="sm"
                onClick={async () => {
                  try {
                    await api.standing.revoke(s.id);
                    refresh("standing:");
                  } catch (e) {
                    toast({ tone: "error", title: "Couldn't revoke", description: e instanceof Error ? e.message : String(e) });
                  }
                }}
              >
                Revoke
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      {creating ? <CreateDialog tools={tools} onClose={() => setCreating(false)} /> : null}
    </Card>
  );
}

function CreateDialog({ tools, onClose }: { tools: Record<string, string[]>; onClose: () => void }) {
  const toast = useToast();
  const names = Object.keys(tools);
  const [tool, setTool] = useState(names.includes("email.send") ? "email.send" : names[0]);
  const [fact, setFact] = useState("");
  const [op, setOp] = useState("in");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [maxUses, setMaxUses] = useState("10");
  const [days, setDays] = useState("30");
  const facts = tools[tool] ?? [];
  const numeric = ["amount", "recipient_count", "target_count"].includes(fact);
  const submit = async () => {
    const conditions: StandingInput["conditions"] = [];
    if (fact && value.trim()) {
      const list = value.split(",").map((s) => s.trim()).filter(Boolean);
      conditions.push({ fact: fact as never, op: op as never, value: op === "in" || op === "all_in" ? list : numeric ? Number(value) : value.trim() });
    }
    try {
      await api.standing.create({ tool, agent: null, conditions, note, max_uses: Number(maxUses), expires_in_days: Number(days) });
      refresh("standing:");
      onClose();
    } catch (e) {
      toast({ tone: "error", title: "Not created", description: e instanceof Error ? e.message : String(e) });
    }
  };
  return (
    <Modal title="New standing approval" description="You can only pre-approve what you could approve yourself. Money needs a maximum amount." onClose={onClose}>
      <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), void submit())}>
        <Field label="Action">
          <select className={inputClass} value={tool} onChange={(e) => (setTool(e.target.value), setFact(""))}>
            {names.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </Field>
        {facts.length ? (
          <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
            <Field label="Only when">
              <select className={inputClass} value={fact} onChange={(e) => (setFact(e.target.value), setOp(["amount", "recipient_count", "target_count"].includes(e.target.value) ? "lte" : e.target.value === "recipient_domains" ? "all_in" : "in"))}>
                <option value="">(no condition)</option>
                {facts.map((f) => (
                  <option key={f} value={f}>
                    {FACT_LABEL[f] ?? f}
                  </option>
                ))}
              </select>
            </Field>
            <select className={`${inputClass} w-32`} value={op} onChange={(e) => setOp(e.target.value)} aria-label="Comparison" disabled={!fact}>
              {(numeric ? ["lte", "gte", "eq"] : ["in", "all_in", "eq"]).map((o) => (
                <option key={o} value={o}>
                  {OP_LABEL[o]}
                </option>
              ))}
            </select>
            <Field label={numeric ? "Number" : "Values (comma-separated)"}>
              <input className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} disabled={!fact} placeholder={fact === "recipient_domains" ? "northwind.com" : ""} />
            </Field>
          </div>
        ) : null}
        <Field label="Why (shown on every use)">
          <input className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} required minLength={3} placeholder="Weekly revenue report to the team" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Maximum uses">
            <input className={inputClass} type="number" min={1} max={1000} value={maxUses} onChange={(e) => setMaxUses(e.target.value)} />
          </Field>
          <Field label="Expires after (days, max 90)">
            <input className={inputClass} type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} />
          </Field>
        </div>
        <div className="flex gap-2">
          <Button variant="primary" type="submit">
            Create
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </div>
      </form>
    </Modal>
  );
}
