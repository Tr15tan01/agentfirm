"use client";

import { useState } from "react";
import { FlaskConical, Globe, KeyRound, Loader2 } from "lucide-react";
import type { SearchProviderKey, SearchTestResult } from "@/lib/types";
import { api } from "@/data/api";
import { LiveBoundary, refresh, useResource } from "@/lib/live";
import { useToast } from "@/components/ui/toast";
import { Badge, Button, Card } from "@/components/ui/primitives";

const LABEL: Record<SearchProviderKey, string> = { brave: "Brave Search", gemini: "Gemini · Google Search grounding", none: "None (no web search)" };
const inputClass = "mt-1 h-9 w-full rounded-[10px] border border-line bg-card-2 px-3 text-[13px] outline-none focus:border-accent";

/** Super-admin: which web search the research tools use. Keys are write-only (encrypted server-side). */
export function SearchSettings() {
  return (
    <LiveBoundary>
      <Inner />
    </LiveBoundary>
  );
}

function Inner() {
  const s = useResource("admin:search", () => api.admin.search());
  const toast = useToast();
  const [provider, setProvider] = useState<SearchProviderKey>(s.provider);
  const [fallback, setFallback] = useState<SearchProviderKey>(s.fallback);
  const [model, setModel] = useState(s.geminiModel);
  const [braveKey, setBraveKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [test, setTest] = useState<(SearchTestResult & { for: string }) | null>(null);

  // Follow the server's copy after a save or refresh (adjusting state during render, not in an effect).
  const serverKey = `${s.provider}|${s.fallback}|${s.geminiModel}`;
  const [seen, setSeen] = useState(serverKey);
  if (seen !== serverKey) {
    setSeen(serverKey);
    setProvider(s.provider);
    setFallback(s.fallback);
    setModel(s.geminiModel);
  }

  const act = async (name: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(name);
    try {
      await fn();
      refresh("admin:search");
      if (ok) toast({ tone: "success", title: ok });
      return true;
    } catch (e) {
      toast({ tone: "error", title: "Not saved", description: e instanceof Error ? e.message : String(e) });
      return false;
    } finally {
      setBusy(null);
    }
  };

  const ready = (p: SearchProviderKey) => p === "none" || (p === "brave" ? s.brave.configured : s.gemini.configured);
  const dirty = provider !== s.provider || fallback !== s.fallback || model !== s.geminiModel;

  const runTest = async (p: "brave" | "gemini") => {
    setBusy(`test-${p}`);
    setTest(null);
    try {
      setTest({ ...(await api.admin.testSearch(p)), for: p });
    } catch (e) {
      setTest({ ok: false, provider: p, results: 0, sample: [], error: e instanceof Error ? e.message : String(e), for: p });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Globe className="size-4 text-fg-3" />
        <h3 className="text-[15px] font-semibold">Web search</h3>
        {s.usingEnvironmentDefaults ? <Badge tone="muted">using server defaults</Badge> : null}
      </div>
      <p className="mt-1 text-[12.5px] text-fg-3">
        Used by the Research and Assistant agents. Brave is a paid search API (a small monthly credit is included). Gemini grounding lets Gemini search Google itself, using the Gemini key you already saved; Google lists a monthly free allowance, then charges per search query the model runs. Gemini returns the sources it used, not a ranked list, so it may return fewer results.
      </p>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <label className="block text-[13px] font-medium">
          Primary search
          <select className={inputClass} value={provider} onChange={(e) => setProvider(e.target.value as SearchProviderKey)} aria-label="Primary search provider">
            {(["brave", "gemini", "none"] as const).map((p) => (
              <option key={p} value={p}>
                {LABEL[p]}
                {!ready(p) ? " — key needed" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[13px] font-medium">
          Fallback <span className="font-normal text-fg-3">· used if the primary fails</span>
          <select className={inputClass} value={fallback} onChange={(e) => setFallback(e.target.value as SearchProviderKey)} aria-label="Fallback search provider">
            {(["none", "brave", "gemini"] as const).map((p) => (
              <option key={p} value={p} disabled={p === provider && p !== "none"}>
                {p === "none" ? "No fallback" : LABEL[p]}
                {p !== "none" && !ready(p) ? " — key needed" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[13px] font-medium">
          Gemini model for grounding <span className="font-normal text-fg-3">· any model from your Gemini list</span>
          <input className={`${inputClass} font-mono`} value={model} onChange={(e) => setModel(e.target.value)} aria-label="Gemini model for grounded search" />
        </label>
        <div className="flex items-end justify-end">
          <Button variant="primary" disabled={!dirty || busy !== null} onClick={() => act("save", () => api.admin.saveSearch({ provider, fallback, geminiModel: model.trim() }), "Search settings saved")}>
            {busy === "save" ? <Loader2 className="size-4 animate-spin" /> : null} Save
          </Button>
        </div>
      </div>

      <div className="mt-5 grid gap-4 border-t border-line pt-4 md:grid-cols-2">
        <div>
          <div className="flex items-center gap-2 text-[13px] font-medium">
            <KeyRound className="size-3.5 text-fg-3" /> Brave API key
            {s.brave.configured ? <Badge tone="ok">…{s.brave.last4}{s.brave.source === "environment" ? " · from server env" : ""}</Badge> : <Badge tone="muted">not set</Badge>}
          </div>
          <form
            className="mt-2 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (braveKey.trim()) void act("key", () => api.admin.setBraveKey(braveKey.trim()), "Brave key saved").then((ok) => ok && setBraveKey(""));
            }}
          >
            <input type="password" autoComplete="off" value={braveKey} onChange={(e) => setBraveKey(e.target.value)} placeholder={s.brave.configured ? "Paste a new key to replace it" : "Paste your Brave API key"} className={`${inputClass} mt-0 font-mono`} aria-label="Brave API key" />
            <Button type="submit" disabled={!braveKey.trim() || busy !== null}>
              Save key
            </Button>
          </form>
          {s.brave.source === "admin" ? (
            <button type="button" className="mt-1.5 text-[12px] text-fg-3 hover:text-err hover:underline" onClick={() => act("clear", () => api.admin.clearBraveKey(), "Brave key removed")}>
              Remove saved key
            </button>
          ) : null}
        </div>
        <div>
          <div className="flex items-center gap-2 text-[13px] font-medium">
            <KeyRound className="size-3.5 text-fg-3" /> Gemini key
            {s.gemini.configured ? <Badge tone="ok">…{s.gemini.last4} · from Gemini provider</Badge> : <Badge tone="warn">not set</Badge>}
          </div>
          <p className="mt-2 text-[12.5px] text-fg-3">Grounded search re-uses the key saved on the Gemini provider card above. Nothing to enter here.</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <span className="text-[12.5px] text-fg-3">Run one real query to check a back-end:</span>
        {(["brave", "gemini"] as const).map((p) => (
          <Button key={p} size="sm" disabled={busy !== null || !(p === "brave" ? s.brave.configured : s.gemini.configured)} onClick={() => runTest(p)}>
            {busy === `test-${p}` ? <Loader2 className="size-3.5 animate-spin" /> : <FlaskConical className="size-3.5" />} Test {p === "brave" ? "Brave" : "Gemini"}
          </Button>
        ))}
      </div>
      {test ? (
        <div role="status" className={`mt-3 rounded-[10px] border px-3 py-2 text-[12.5px] ${test.ok ? "border-ok/40 bg-ok/5" : "border-err/40 bg-err/5"}`}>
          {test.ok ? (
            <>
              <span className="font-medium">{test.for === "brave" ? "Brave" : "Gemini"} works</span> — {test.results} result{test.results === 1 ? "" : "s"}
              {test.sample.length ? `: ${test.sample.join(" · ")}` : test.for === "gemini" ? ". Gemini answered without citing sources for this query; try again or use a different query." : ""}
            </>
          ) : (
            <>
              <span className="font-medium">{test.for === "brave" ? "Brave" : "Gemini"} failed</span> — {test.error}
            </>
          )}
        </div>
      ) : null}
    </Card>
  );
}
