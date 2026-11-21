"use client";

import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Database, GitBranch, KeyRound, Loader2, Mail, Plus, Power, Trash2, Webhook, X, type LucideIcon } from "lucide-react";
import { api } from "@/data/api";
import { LiveBoundary, refresh, useResource } from "@/lib/live";
import type { Connection, ConnectionKind } from "@/lib/types";
import { Badge, Button, Card, DemoBadge, SectionHeader } from "@/components/ui/primitives";
import { CopyButton } from "@/components/ui/Markdown";
import { useToast } from "@/components/ui/toast";

const input = "h-9 w-full rounded-[10px] border border-line bg-card-2 px-3 text-[13.5px] outline-none focus:border-accent";

const ACTIONS: { key: string; label: string; risk: "read" | "external" | "financial" | "destructive" }[] = [
  { key: "social.publish", label: "Publish social posts", risk: "external" },
  { key: "ads.performance_read", label: "Read ad performance", risk: "read" },
  { key: "ads.budget_change", label: "Change ad budgets", risk: "financial" },
  { key: "seo.keywords", label: "Keyword data", risk: "read" },
  { key: "calendar.read", label: "Read calendar", risk: "read" },
  { key: "calendar.create_event", label: "Create calendar events", risk: "external" },
  { key: "email.send", label: "Send email (instead of SMTP)", risk: "external" },
  { key: "automation.run", label: "Run automations", risk: "external" },
  { key: "payments.execute", label: "Make payments", risk: "financial" },
  { key: "purchase.execute", label: "Make purchases / bookings", risk: "financial" },
  { key: "deploy.preview", label: "Deploy previews", risk: "external" },
  { key: "deploy.production", label: "Deploy to production", risk: "destructive" },
];

const KINDS: Record<ConnectionKind, { label: string; icon: LucideIcon; blurb: string; secret: string }> = {
  github: { label: "GitHub", icon: GitBranch, blurb: "Repositories for the Engineer agent. It only writes agent/* branches; pull requests and deploys need approval.", secret: "Fine-grained token (repository-scoped)" },
  webhook: { label: "Automation webhook", icon: Webhook, blurb: "Route actions to n8n, Zapier, Make or your own service. Requests are HMAC-signed and carry an Idempotency-Key.", secret: "Signing secret (leave empty to generate one)" },
  smtp: { label: "Email (SMTP)", icon: Mail, blurb: "Sends emails the Assistant drafted, only after approval. TLS ports 465 or 587.", secret: "Password or app password" },
  gn7t: { label: "GN7T", icon: Database, blurb: "Read-only data for the BI agent. Write statements are refused before they're sent.", secret: "API key" },
};

function describe(c: Connection): string {
  const cfg = c.config as Record<string, unknown>;
  if (c.kind === "github") return (cfg.repositories as string[] | undefined)?.join(", ") ?? "";
  if (c.kind === "webhook") return `${String(cfg.url ?? "")} · ${(cfg.actions as string[] | undefined)?.length ?? 0} actions`;
  if (c.kind === "smtp") return `${String(cfg.from_address ?? "")} via ${String(cfg.host ?? "")}:${String(cfg.port ?? "")}`;
  return String(cfg.base_url ?? "");
}

function AddDialog({ kind, onClose }: { kind: ConnectionKind; onClose: () => void }) {
  const toast = useToast();
  const meta = KINDS[kind];
  const [name, setName] = useState(meta.label);
  const [secret, setSecret] = useState("");
  const [repos, setRepos] = useState("");
  const [url, setUrl] = useState("");
  const [actions, setActions] = useState<string[]>([]);
  const [host, setHost] = useState("");
  const [port, setPort] = useState(587);
  const [from, setFrom] = useState("");
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [generated, setGenerated] = useState<string | null>(null);

  const config = (): Record<string, unknown> => {
    if (kind === "github") return { repositories: repos.split(/[\s,]+/).filter(Boolean) };
    if (kind === "webhook") return { url, actions };
    if (kind === "smtp") return { host, port, from_address: from, username: username || from };
    return { base_url: url };
  };

  const submit = async () => {
    setBusy(true);
    try {
      const c = await api.integrations.create({ kind, name, config: config(), secret: secret || undefined });
      refresh("integrations");
      if (c.signingSecret) setGenerated(c.signingSecret);
      else {
        toast({ tone: "success", title: `${meta.label} connected` });
        onClose();
      }
    } catch (e) {
      toast({ tone: "error", title: "Couldn't connect", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-[8vh] z-50 max-h-[84vh] w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 overflow-y-auto rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-[16px] font-semibold">Connect {meta.label}</Dialog.Title>
              <Dialog.Description className="mt-1 text-[13px] text-fg-2">{meta.blurb}</Dialog.Description>
            </div>
            <Dialog.Close className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card-2" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>

          {generated ? (
            <div className="mt-4 space-y-3">
              <p className="text-[13.5px]">Copy this signing secret into your automation now. It won&apos;t be shown again.</p>
              <div className="flex items-center gap-2 rounded-[10px] border border-line bg-card-2 p-2.5 font-mono text-[12.5px]">
                <span className="min-w-0 flex-1 break-all">{generated}</span>
                <CopyButton text={generated} label="" />
              </div>
              <p className="text-[12px] text-fg-3">
                Verify each request: <code>X-AgentFirm-Signature: t=…,v1=HMAC-SHA256(secret, &quot;t.body&quot;)</code>; reject signatures older than 5 minutes and de-duplicate on <code>Idempotency-Key</code>.
              </p>
              <Button variant="primary" onClick={onClose}>
                Done
              </Button>
            </div>
          ) : (
            <form
              className="mt-4 space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              <Field label="Name">
                <input className={input} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required />
              </Field>
              {kind === "github" && (
                <Field label="Repositories the agents may use" hint="owner/name, separated by commas">
                  <input className={input} value={repos} onChange={(e) => setRepos(e.target.value)} placeholder="acme/web, acme/api" required />
                </Field>
              )}
              {(kind === "webhook" || kind === "gn7t") && (
                <Field label={kind === "webhook" ? "Endpoint URL" : "GN7T base URL"} hint="Public HTTPS only">
                  <input className={input} type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" required />
                </Field>
              )}
              {kind === "webhook" && (
                <fieldset>
                  <legend className="text-[13px] font-medium">Actions this endpoint handles</legend>
                  <p className="text-[12px] text-fg-3">Agents still need an approval for anything external, financial or destructive.</p>
                  <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                    {ACTIONS.map((a) => (
                      <label key={a.key} className="flex items-center gap-2 text-[13px]">
                        <input type="checkbox" className="accent-[var(--accent)]" checked={actions.includes(a.key)} onChange={(e) => setActions((x) => (e.target.checked ? [...x, a.key] : x.filter((y) => y !== a.key)))} />
                        <span className="min-w-0 flex-1 truncate">{a.label}</span>
                        {a.risk !== "read" && <Badge tone={a.risk === "external" ? "warn" : "err"}>{a.risk}</Badge>}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
              {kind === "smtp" && (
                <>
                  <div className="grid grid-cols-[1fr_110px] gap-2">
                    <Field label="SMTP host">
                      <input className={input} value={host} onChange={(e) => setHost(e.target.value)} placeholder="smtp.example.com" required />
                    </Field>
                    <Field label="Port">
                      <select className={input} value={port} onChange={(e) => setPort(Number(e.target.value))}>
                        <option value={587}>587 (STARTTLS)</option>
                        <option value={465}>465 (TLS)</option>
                      </select>
                    </Field>
                  </div>
                  <Field label="From address">
                    <input className={input} type="email" value={from} onChange={(e) => setFrom(e.target.value)} required />
                  </Field>
                  <Field label="Username" hint="Defaults to the from address">
                    <input className={input} value={username} onChange={(e) => setUsername(e.target.value)} />
                  </Field>
                </>
              )}
              <Field label={meta.secret} hint="Encrypted on the server; only the last 4 characters are ever shown.">
                <input className={input} type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} required={kind !== "webhook"} />
              </Field>
              <div className="flex justify-end gap-2 pt-2">
                <Dialog.Close asChild>
                  <Button variant="ghost" type="button">
                    Cancel
                  </Button>
                </Dialog.Close>
                <Button variant="primary" type="submit" disabled={busy || (kind === "webhook" && !actions.length)}>
                  {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />} Connect
                </Button>
              </div>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[13px] font-medium">{label}</span>
      {hint && <span className="ml-2 text-[12px] text-fg-3">{hint}</span>}
      <span className="mt-1 block">{children}</span>
    </label>
  );
}

function Connections() {
  const toast = useToast();
  const conns = useResource("integrations", () => api.integrations.list());
  const [adding, setAdding] = useState<ConnectionKind | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (id: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(id);
    try {
      await fn();
      refresh("integrations");
      toast({ tone: "success", title: ok });
    } catch (e) {
      toast({ tone: "error", title: "That didn't work", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {(Object.keys(KINDS) as ConnectionKind[]).map((k) => {
          const { label, icon: Icon, blurb } = KINDS[k];
          const count = conns.filter((c) => c.kind === k).length;
          return (
            <Card key={k} className="flex flex-col p-4">
              <div className="flex items-center gap-2.5">
                <span className="grid size-9 place-items-center rounded-[10px] border border-line bg-card-2">
                  <Icon className="size-4" />
                </span>
                <span className="text-[14px] font-semibold">{label}</span>
                {count ? <Badge tone="ok">{count} connected</Badge> : null}
              </div>
              <p className="mt-2 flex-1 text-[12.5px] text-fg-2">{blurb}</p>
              <Button className="mt-3" size="sm" onClick={() => setAdding(k)}>
                <Plus className="size-3.5" /> Connect
              </Button>
            </Card>
          );
        })}
      </div>

      <Card className="p-5">
        <SectionHeader title="Connections" subtitle="Disconnected or disabled tools make the agent stop and ask instead of guessing." action={api.isDemo ? <DemoBadge /> : undefined} />
        <ul className="mt-4 divide-y divide-[var(--border)]">
          {conns.length === 0 && <li className="py-6 text-center text-[13px] text-fg-3">Nothing connected yet.</li>}
          {conns.map((c) => {
            const Icon = KINDS[c.kind].icon;
            return (
              <li key={c.id} className="flex flex-wrap items-center gap-3 py-3">
                <Icon className="size-4 text-fg-3" />
                <div className="min-w-0 flex-1">
                  <p className="text-[13.5px] font-medium">
                    {c.name} <span className="text-fg-3">· {KINDS[c.kind].label}</span>
                  </p>
                  <p className="truncate text-[12px] text-fg-3">{describe(c)}</p>
                </div>
                <span className="flex items-center gap-1 font-mono text-[12px] text-fg-3">
                  <KeyRound className="size-3.5" /> {c.secretLast4 ? `••••${c.secretLast4}` : "no secret"}
                </span>
                <Badge tone={c.status === "active" ? "ok" : "muted"}>{c.status}</Badge>
                <Button size="sm" variant="ghost" disabled={busy === c.id} onClick={() => act(c.id, () => api.integrations.update(c.id, { status: c.status === "active" ? "disabled" : "active" }), c.status === "active" ? "Disabled" : "Enabled")}>
                  <Power className="size-3.5" /> {c.status === "active" ? "Disable" : "Enable"}
                </Button>
                <Button size="sm" variant="ghost" aria-label={`Disconnect ${c.name}`} disabled={busy === c.id} onClick={() => act(c.id, () => api.integrations.remove(c.id), "Disconnected")}>
                  <Trash2 className="size-3.5" />
                </Button>
              </li>
            );
          })}
        </ul>
      </Card>
      {adding && <AddDialog kind={adding} onClose={() => setAdding(null)} />}
    </div>
  );
}

export function IntegrationsView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-[24px] font-semibold tracking-tight">Integrations</h2>
        <p className="mt-1 max-w-2xl text-[14px] text-fg-2">
          Connect the systems your agents may act on. Connecting a tool never skips an approval: anything external, financial or destructive still needs a person to approve the exact action.
        </p>
      </div>
      <LiveBoundary>
        <Connections />
      </LiveBoundary>
    </div>
  );
}
