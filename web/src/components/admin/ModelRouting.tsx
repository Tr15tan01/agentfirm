"use client";

import { useMemo, useState } from "react";
import * as Select from "@radix-ui/react-select";
import * as Switch from "@radix-ui/react-switch";
import { AnimatePresence, motion } from "motion/react";
import {
  AlertTriangle,
  Brain,
  Check,
  ChevronDown,
  Code2,
  Eye,
  FileStack,
  KeyRound,
  Layers,
  ListFilter,
  MessageSquareText,
  Plus,
  RotateCcw,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Tags,
  X,
  type LucideIcon,
} from "lucide-react";
import type { CapabilityKey, ProviderKey, RoutingData, RoutingProvider, RoutingRoute } from "@/lib/types";
import { api } from "@/data/api";
import { LiveBoundary, refresh, useResource } from "@/lib/live";
import { useToast } from "@/components/ui/toast";

type DemoProvider = RoutingProvider;
type DemoRoute = RoutingRoute;
import { cn } from "@/lib/cn";
import { Badge, Button, Card, DemoBadge, SectionHeader } from "@/components/ui/primitives";

const CAPABILITIES: Record<CapabilityKey, { label: string; hint: string; icon: LucideIcon }> = {
  reasoning: { label: "Reasoning & planning", hint: "Task decomposition, orchestration, analysis", icon: Brain },
  text: { label: "Text generation", hint: "Chat replies, drafting, general writing", icon: MessageSquareText },
  code: { label: "Code", hint: "Generation, review, debugging", icon: Code2 },
  summarize: { label: "Summarisation", hint: "Condensing sources, documents, threads", icon: FileStack },
  classify: { label: "Classification & routing", hint: "Intent detection, agent selection, tagging", icon: Tags },
  creative: { label: "Creative ideation", hint: "Brainstorming, naming, concepts", icon: Sparkles },
  vision: { label: "Vision", hint: "Images, screenshots, charts in documents", icon: Eye },
  long_context: { label: "Long context", hint: "Large documents and repositories", icon: Layers },
  embeddings: { label: "Embeddings", hint: "Knowledge indexing and semantic search", icon: ListFilter },
};

const PROVIDER_MONO: Record<ProviderKey, string> = { openai: "OA", gemini: "GE", gn7t: "G7" };

type ModelRef = { id: string; label: string; provider: DemoProvider };

function useCatalog(providers: DemoProvider[]) {
  return useMemo(() => {
    const map = new Map<string, ModelRef>();
    for (const p of providers) for (const m of p.models) map.set(m.id, { id: m.id, label: m.label, provider: p });
    return map;
  }, [providers]);
}

function ProviderChip({ provider, size = "md" }: { provider: DemoProvider; size?: "sm" | "md" }) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-[7px] border border-line bg-card-2 font-mono font-semibold text-fg-2",
        size === "sm" ? "size-5 text-[9px]" : "size-7 text-[10.5px]",
      )}
    >
      {PROVIDER_MONO[provider.key]}
    </span>
  );
}

function providerTone(status: DemoProvider["status"]) {
  return status === "healthy" || status === "configured" ? "ok" : status === "degraded" ? "warn" : "muted";
}

const STATUS_LABEL: Record<DemoProvider["status"], string> = { healthy: "Healthy", degraded: "Degraded", configured: "Configured", not_configured: "Not configured" };

function KeyDialog({ provider, onClose }: { provider: DemoProvider; onClose: () => void }) {
  const toast = useToast();
  const inHouse = provider.kind !== "External API";
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.baseUrl ?? "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      if (inHouse && baseUrl.trim() && baseUrl.trim() !== provider.baseUrl) await api.admin.updateProvider(provider.id, { baseUrl: baseUrl.trim() });
      const last4 = key.trim() ? (await api.admin.setCredential(provider.id, key.trim())).last4 : null;
      refresh("admin:routing");
      toast({ tone: "success", title: `${provider.name} saved`, description: last4 ? `Key stored encrypted · ••••${last4}` : "Base URL updated" });
      onClose();
    } catch (e) {
      toast({ tone: "error", title: "Couldn't save the key", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div role="dialog" aria-modal="true" aria-label={`API key for ${provider.name}`} className="fixed inset-0 z-50 grid place-items-center bg-black/55 p-4 backdrop-blur-sm" onClick={onClose}>
      <form
        className="w-[min(440px,100%)] rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow)]"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (key.trim() || (inHouse && baseUrl.trim())) void save();
        }}
      >
        <h3 className="text-[16px] font-semibold">Configure {provider.name}</h3>
        <p className="mt-1 text-[13px] text-fg-2">Keys are encrypted server-side with a per-key data key and never sent back to any browser; only the last 4 characters are shown.</p>
        {inHouse ? (
          <label className="mt-3 block text-[13px] font-medium">
            Base URL <span className="font-normal text-fg-3">· OpenAI-compatible endpoint, e.g. https://gn7t.internal/v1</span>
            <input autoFocus type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} className="mt-1 h-9 w-full rounded-[10px] border border-line bg-card-2 px-3 font-mono text-[13px] outline-none focus:border-accent" aria-label="Base URL" />
          </label>
        ) : null}
        <label className="mt-3 block text-[13px] font-medium">
          API key {inHouse ? <span className="font-normal text-fg-3">· optional</span> : null}
          <input autoFocus={!inHouse} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} className="mt-1 h-9 w-full rounded-[10px] border border-line bg-card-2 px-3 font-mono text-[13px] outline-none focus:border-accent" aria-label="API key" />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !(key.trim() || (inHouse && baseUrl.trim()))}>
            Save
          </Button>
        </div>
      </form>
    </div>
  );
}

function ModelSelect({
  value,
  onChange,
  capability,
  providers,
  enabled,
  placeholder = "Select model",
  exclude = [],
  compact,
}: {
  value: string | undefined;
  onChange: (v: string) => void;
  capability: CapabilityKey;
  providers: DemoProvider[];
  enabled: Record<ProviderKey, boolean>;
  placeholder?: string;
  exclude?: string[];
  compact?: boolean;
}) {
  const catalog = useCatalog(providers);
  const current = value ? catalog.get(value) : undefined;
  return (
    <Select.Root value={value} onValueChange={onChange}>
      <Select.Trigger
        className={cn(
          "flex h-9 w-full items-center gap-2 rounded-[9px] border border-line bg-card-2 px-2 text-left text-[13px] outline-none transition-colors hover:border-line-strong data-[state=open]:border-accent",
          compact && "h-8 w-auto",
        )}
        aria-label={`Model for ${CAPABILITIES[capability].label}`}
      >
        {current ? <ProviderChip provider={current.provider} size="sm" /> : compact ? <Plus className="size-3.5 text-fg-3" /> : null}
        <span className={cn("min-w-0 flex-1 truncate", !current && "text-fg-3")}>
          <Select.Value placeholder={placeholder} />
        </span>
        <Select.Icon>
          <ChevronDown className="size-3.5 text-fg-3" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content position="popper" sideOffset={6} className="z-50 max-h-80 min-w-[260px] overflow-hidden rounded-[12px] border border-line bg-card shadow-[var(--shadow)]">
          <Select.Viewport className="p-1.5">
            {providers.map((p) => {
              const models = p.models.filter((m) => m.capabilities.includes(capability) && !exclude.includes(m.id));
              if (!models.length) return null;
              const unavailable = !enabled[p.key] || p.status === "not_configured";
              return (
                <Select.Group key={p.key}>
                  <Select.Label className="flex items-center gap-2 px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-fg-3">
                    {p.name}
                    {unavailable ? <span className="normal-case tracking-normal text-warn">· unavailable</span> : null}
                  </Select.Label>
                  {models.map((m) => (
                    <Select.Item
                      key={m.id}
                      value={m.id}
                      disabled={unavailable}
                      className="relative flex h-8 cursor-pointer select-none items-center gap-2 rounded-md pl-2 pr-7 text-[13px] outline-none data-[disabled]:cursor-not-allowed data-[highlighted]:bg-card-2 data-[disabled]:opacity-45"
                    >
                      <Select.ItemText>{m.label}</Select.ItemText>
                      <span className="ml-auto font-mono text-[11px] text-fg-3">{m.priceIn === null ? "self-hosted" : `$${m.priceIn}/$${m.priceOut ?? "–"}`}</span>
                      <Select.ItemIndicator className="absolute right-2">
                        <Check className="size-3.5 text-accent" />
                      </Select.ItemIndicator>
                    </Select.Item>
                  ))}
                </Select.Group>
              );
            })}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

export function ModelRouting() {
  return (
    <LiveBoundary>
      <RoutingLoader />
    </LiveBoundary>
  );
}

function RoutingLoader() {
  const data = useResource("admin:routing", () => api.admin.routing());
  // Remount the editor when the server data changes (after a save or a key change).
  return <RoutingEditor key={JSON.stringify(data)} data={data} />;
}

function RoutingEditor({ data }: { data: RoutingData }) {
  const providers = data.providers;
  const catalog = useCatalog(providers);
  const initialEnabled = useMemo(() => Object.fromEntries(providers.map((p) => [p.key, p.enabled])) as Record<ProviderKey, boolean>, [providers]);
  const [routes, setRoutes] = useState<DemoRoute[]>(data.routes);
  const [enabled, setEnabled] = useState<Record<ProviderKey, boolean>>(initialEnabled);
  const [toast, setToast] = useState<string | null>(null);
  const [keyFor, setKeyFor] = useState<DemoProvider | null>(null);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);
  const notify = useToast();
  const importModels = async (p: DemoProvider) => {
    setImporting(p.key);
    try {
      const r = await api.admin.importModels(p.id);
      refresh("admin:routing");
      notify({
        tone: "success",
        title: `${p.name}: ${r.added.length} new ${r.added.length === 1 ? "model" : "models"}`,
        description: `${r.found} found upstream · ${r.alreadyPresent} already in catalog. ${r.note}`,
      });
    } catch (e) {
      notify({ tone: "error", title: `Couldn't import ${p.name} models`, description: e instanceof Error ? e.message : String(e) });
    } finally {
      setImporting(null);
    }
  };

  const dirty = JSON.stringify(routes) !== JSON.stringify(data.routes) || JSON.stringify(enabled) !== JSON.stringify(initialEnabled);

  const update = (cap: CapabilityKey, fn: (r: DemoRoute) => DemoRoute) => setRoutes((rs) => rs.map((r) => (r.capability === cap ? fn(r) : r)));

  const issuesFor = (r: DemoRoute): string[] => {
    const issues: string[] = [];
    const primary = catalog.get(r.primary);
    if (primary && !enabled[primary.provider.key]) issues.push(`${primary.provider.name} is disabled — requests will fail over.`);
    else if (primary?.provider.status === "not_configured") issues.push(`${primary.provider.name} isn't configured yet (${primary.provider.kind === "External API" ? "no API key" : "no base URL"}) — requests will fail over.`);
    else if (primary?.provider.status === "degraded") issues.push(`${primary.provider.name} is degraded — fallback likely.`);
    if (r.fallbacks.length === 0) issues.push("No fallback configured.");
    return issues;
  };

  const save = async () => {
    setSaving(true);
    try {
      const changed = routes.filter((r) => JSON.stringify(r) !== JSON.stringify(data.routes.find((x) => x.capability === r.capability)));
      for (const r of changed) await api.admin.saveRoute(r);
      for (const p of providers) if (enabled[p.key] !== initialEnabled[p.key]) await api.admin.updateProvider(p.id, { enabled: enabled[p.key] });
      setToast(api.isDemo ? "Demo mode — routing not persisted." : `Saved ${changed.length} ${changed.length === 1 ? "route" : "routes"}. Every change is audit-logged; running tasks keep their resolved model.`);
      refresh("admin:routing");
    } catch (e) {
      setToast(`Not saved: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
      window.setTimeout(() => setToast(null), 5200);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="violet">
              <ShieldCheck className="-ml-0.5 size-3" /> Super admin
            </Badge>
            {api.isDemo ? <DemoBadge /> : null}
          </div>
          <h2 className="mt-3 text-[24px] font-semibold tracking-tight">Model providers & routing</h2>
          <p className="mt-1 max-w-2xl text-[14px] text-fg-2">
            Choose which provider and model handles each kind of work. Agents request a <em className="not-italic text-fg">capability</em>, never a
            model name — so a change here applies to every agent at once, with ordered fallbacks.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" disabled={!dirty || saving} onClick={() => { setRoutes(data.routes); setEnabled(initialEnabled); }}>
            <RotateCcw className="size-4" /> Discard
          </Button>
          <Button variant="primary" disabled={!dirty || saving} onClick={() => void save()}>
            <Check className="size-4" /> Save routing
          </Button>
        </div>
      </div>

      {/* Providers */}
      <section aria-labelledby="providers">
        <SectionHeader title="Providers" subtitle="API keys are encrypted server-side and never sent to the browser — only the last 4 characters are shown." />
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {providers.map((p) => (
            <Card key={p.key} className={cn("p-4", !enabled[p.key] && "opacity-70")}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <ProviderChip provider={p} />
                  <div>
                    <div className="text-[14px] font-semibold">{p.name}</div>
                    <div className="text-[12px] text-fg-3">{p.kind}</div>
                  </div>
                </div>
                <Switch.Root
                  checked={enabled[p.key]}
                  disabled={p.status === "not_configured"}
                  onCheckedChange={(v) => setEnabled((e) => ({ ...e, [p.key]: v }))}
                  aria-label={`Enable ${p.name}`}
                  className="relative h-5 w-9 shrink-0 rounded-full border border-line bg-card-2 transition-colors disabled:opacity-40 data-[state=checked]:border-transparent data-[state=checked]:bg-accent"
                >
                  <Switch.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[17px]" />
                </Switch.Root>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <Badge tone={providerTone(p.status)}>{STATUS_LABEL[p.status]}</Badge>
                <span className="font-mono text-[12px] text-fg-3">{p.latencyMs ? `p50 ${p.latencyMs} ms` : "—"}</span>
              </div>
              <div className="mt-3 flex items-center justify-between rounded-[9px] border border-line bg-card-2 px-2.5 py-2">
                <span className="flex items-center gap-1.5 font-mono text-[12px] text-fg-2">
                  <KeyRound className="size-3.5 text-fg-3" />
                  {p.credentialHint ?? "No credential"}
                </span>
                <button type="button" className="text-[12px] font-medium text-accent hover:underline" onClick={() => setKeyFor(p)}>
                  {p.kind !== "External API" ? "Configure" : p.credentialHint ? "Rotate" : "Add key"}
                </button>
              </div>
              <div className="mt-3 flex items-center justify-between text-[12px] text-fg-3">
                <span>{p.models.length} {p.models.length === 1 ? "model" : "models"} in catalog</span>
                <button
                  type="button"
                  disabled={!enabled[p.key] || importing !== null}
                  onClick={() => importModels(p)}
                  className="font-medium text-accent hover:underline disabled:cursor-not-allowed disabled:text-fg-3 disabled:no-underline"
                  title={enabled[p.key] ? "Fetch this provider's model list. New models stay disabled until you review them." : "Enable the provider to import its models"}
                >
                  {importing === p.key ? "Importing…" : "Import models"}
                </button>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* Routing matrix */}
      <section aria-labelledby="routing">
        <SectionHeader
          title="Routing by task type"
          subtitle="Platform defaults. Resolution order: agent-version override → organisation override (plan-gated) → plan default → platform default."
        />
        <Card className="mt-4 overflow-hidden">
          <div className="hidden grid-cols-[minmax(220px,1.2fr)_minmax(220px,1fr)_minmax(260px,1.4fr)_110px] gap-4 border-b border-line bg-card-2 px-4 py-2.5 lg:grid">
            {["Task type", "Primary model", "Fallback chain (in order)", "Temperature"].map((h) => (
              <div key={h} className="af-label !text-[10.5px]">{h}</div>
            ))}
          </div>
          <ul className="divide-y divide-[var(--border)]">
            {routes.map((r) => {
              const cap = CAPABILITIES[r.capability];
              const Icon = cap.icon;
              const issues = issuesFor(r);
              return (
                <li key={r.capability} className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(220px,1.2fr)_minmax(220px,1fr)_minmax(260px,1.4fr)_110px] lg:items-start lg:gap-4">
                  <div className="flex items-start gap-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-[9px] border border-line bg-card-2">
                      <Icon className="size-4 text-accent" strokeWidth={1.8} />
                    </span>
                    <div className="min-w-0">
                      <div className="text-[13.5px] font-medium">{cap.label}</div>
                      <div className="text-[12px] text-fg-3">{cap.hint}</div>
                      {issues.length ? (
                        <div className="mt-1.5 space-y-0.5">
                          {issues.map((i) => (
                            <div key={i} className="flex items-center gap-1 text-[11.5px] text-warn">
                              <AlertTriangle className="size-3 shrink-0" /> {i}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div className="af-label mb-1 !text-[10px] lg:hidden">Primary</div>
                    <ModelSelect
                      value={r.primary}
                      capability={r.capability}
                      providers={providers}
                      enabled={enabled}
                      exclude={r.fallbacks}
                      onChange={(v) => update(r.capability, (x) => ({ ...x, primary: v }))}
                    />
                  </div>

                  <div>
                    <div className="af-label mb-1 !text-[10px] lg:hidden">Fallbacks</div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <AnimatePresence initial={false}>
                        {r.fallbacks.map((f, idx) => {
                          const m = catalog.get(f);
                          if (!m) return null;
                          return (
                            <motion.span
                              key={f}
                              layout
                              initial={{ opacity: 0, scale: 0.9 }}
                              animate={{ opacity: 1, scale: 1 }}
                              exit={{ opacity: 0, scale: 0.9 }}
                              className="flex h-8 items-center gap-1.5 rounded-[9px] border border-line bg-card-2 pl-2 pr-1 text-[12.5px]"
                            >
                                                            <span className="font-mono text-[10.5px] text-fg-3">{idx + 1}</span>
                              <ProviderChip provider={m.provider} size="sm" />
                              <span>{m.label}</span>
                              <button
                                type="button"
                                aria-label={`Remove ${m.label} fallback`}
                                className="grid size-5 place-items-center rounded text-fg-3 hover:bg-card hover:text-err"
                                onClick={() => update(r.capability, (x) => ({ ...x, fallbacks: x.fallbacks.filter((y) => y !== f) }))}
                              >
                                <X className="size-3" />
                              </button>
                            </motion.span>
                          );
                        })}
                      </AnimatePresence>
                      {r.fallbacks.length < 3 ? (
                        <ModelSelect
                          key={r.fallbacks.join(",")}
                          value={undefined}
                          compact
                          placeholder="Add fallback"
                          capability={r.capability}
                          providers={providers}
                          enabled={enabled}
                          exclude={[r.primary, ...r.fallbacks]}
                          onChange={(v) => update(r.capability, (x) => ({ ...x, fallbacks: [...x.fallbacks, v] }))}
                        />
                      ) : null}
                    </div>
                  </div>

                  <div>
                    <div className="af-label mb-1 !text-[10px] lg:hidden">Temperature</div>
                    {r.capability === "embeddings" ? (
                      <span className="text-[12px] text-fg-3">n/a</span>
                    ) : (
                      <input
                        type="number"
                        min={0}
                        max={2}
                        step={0.05}
                        value={r.temperature}
                        aria-label={`Temperature for ${cap.label}`}
                        onChange={(e) => update(r.capability, (x) => ({ ...x, temperature: Number(e.target.value) }))}
                        className="h-9 w-full rounded-[9px] border border-line bg-card-2 px-2.5 font-mono text-[13px] outline-none focus:border-accent"
                      />
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      </section>

      {/* Policy notes */}
      <div className="grid gap-4 md:grid-cols-3">
        {[
          { icon: ShieldCheck, title: "Enforced server-side", body: "Only platform super-admins can change routing. The API re-checks the role on every request; this screen is not the security boundary." },
          { icon: ScrollText, title: "Every change is audited", body: "Saving writes a new model_routes revision and an audit_logs entry with the before/after diff, actor and time." },
          { icon: Layers, title: "Traceable executions", body: "Each usage record stores the model actually used, including fallbacks, so costs and outputs remain explainable." },
        ].map(({ icon: Icon, title, body }) => (
          <Card key={title} className="p-4">
            <Icon className="size-4 text-accent-2" />
            <div className="mt-2 text-[13.5px] font-medium">{title}</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-fg-2">{body}</p>
          </Card>
        ))}
      </div>

      <AnimatePresence>
        {toast ? (
          <motion.div
            role="status"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            className="fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-2.5 rounded-[12px] border border-line bg-card p-3.5 text-[13px] shadow-[var(--shadow)]"
          >
            <Check className="mt-0.5 size-4 shrink-0 text-ok" />
            <span className="text-fg-2">{toast}</span>
          </motion.div>
        ) : null}
      </AnimatePresence>
      {keyFor ? <KeyDialog provider={keyFor} onClose={() => setKeyFor(null)} /> : null}
    </div>
  );
}
