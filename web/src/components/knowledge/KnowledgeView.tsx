"use client";

import { useRef, useState } from "react";
import { BookMarked, FileText, Loader2, Plus, Trash2, Upload } from "lucide-react";
import { api } from "@/data/api";
import { LiveBoundary, refresh, useResource } from "@/lib/live";
import type { KnowledgeDoc, MemoryEntry } from "@/lib/types";
import { Badge, Button, Card, DemoBadge, SectionHeader } from "@/components/ui/primitives";
import { TimeAgo } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";

const input = "h-9 w-full rounded-[10px] border border-line bg-card-2 px-3 text-[13.5px] outline-none focus:border-accent";
const area = "w-full rounded-[10px] border border-line bg-card-2 px-3 py-2 text-[13.5px] leading-relaxed outline-none focus:border-accent";
const ago = (iso: string) => Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));

/** Memories agents read. Saving one changes every future run, so it's an admin action. */
const MEMORY_KEYS: { key: string; label: string; hint: string }[] = [
  { key: "brand_voice", label: "Brand voice", hint: "How Marketing should sound, e.g. confident, warm, plain language." },
  { key: "banned_claims", label: "Banned claims", hint: "Phrases Marketing must never use — one per line." },
  { key: "product", label: "Product", hint: "What you sell, in two or three sentences." },
  { key: "audience", label: "Audience", hint: "Who you sell to." },
  { key: "writing_style", label: "Writing style", hint: "How the Assistant drafts emails for you." },
  { key: "signature", label: "Email signature", hint: "Appended to drafted emails." },
  { key: "rejected_ideas", label: "Rejected ideas", hint: "Ideas Creative won't suggest again (also filled from the idea board)." },
];

function Documents() {
  const toast = useToast();
  const docs = useResource("knowledge:docs", () => api.knowledge.list());
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      refresh("knowledge:");
      toast({ tone: "success", title: ok });
    } catch (e) {
      toast({ tone: "error", title: "That didn't work", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px] [&>*]:min-w-0">
      <Card className="p-5">
        <SectionHeader title="Documents" subtitle="Agents retrieve from these with keyword search. Content is treated as untrusted data, never as instructions." action={api.isDemo ? <DemoBadge /> : undefined} />
        <ul className="mt-4 divide-y divide-[var(--border)]">
          {docs.length === 0 && <li className="py-6 text-center text-[13px] text-fg-3">No documents yet. Upload a PDF, text or Markdown file, or paste text.</li>}
          {docs.map((d: KnowledgeDoc) => (
            <li key={d.id} className="flex items-center gap-3 py-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-[9px] border border-line bg-card-2 text-fg-3">
                <FileText className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13.5px] font-medium">{d.title}</p>
                <p className="text-[12px] text-fg-3">
                  {d.chars.toLocaleString()} characters · {d.chunks} {d.chunks === 1 ? "chunk" : "chunks"} · added <TimeAgo secondsAgo={ago(d.createdAt)} />
                </p>
              </div>
              <Badge tone="muted">{d.mime === "application/pdf" ? "PDF" : d.source === "upload" ? "File" : "Text"}</Badge>
              <Button variant="ghost" size="sm" aria-label={`Delete ${d.title}`} disabled={busy} onClick={() => run(() => api.knowledge.remove(d.id), "Document deleted")}>
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      </Card>

      <div className="space-y-6">
        <Card className="p-5">
          <h3 className="text-[15px] font-semibold">Upload a file</h3>
          <p className="mt-1 text-[12.5px] text-fg-2">PDF or UTF-8 text/Markdown, up to 15 MB.</p>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.txt,.md,.markdown,.csv,text/plain,text/markdown,application/pdf,text/csv"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void run(() => api.knowledge.upload(f), `Added ${f.name}`);
            }}
          />
          <Button className="mt-3" onClick={() => fileRef.current?.click()} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />} Choose file
          </Button>
        </Card>
        <Card className="p-5">
          <h3 className="text-[15px] font-semibold">Paste text</h3>
          <form
            className="mt-3 space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!title.trim() || !content.trim()) return;
              void run(async () => {
                await api.knowledge.add(title.trim(), content);
                setTitle("");
                setContent("");
              }, "Document added");
            }}
          >
            <input className={input} placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Document title" maxLength={300} />
            <textarea className={area} rows={6} placeholder="Paste notes, a policy, interview transcripts…" value={content} onChange={(e) => setContent(e.target.value)} aria-label="Document text" />
            <Button type="submit" variant="primary" disabled={busy || !title.trim() || !content.trim()}>
              <Plus className="size-4" /> Add document
            </Button>
          </form>
        </Card>
      </div>
    </div>
  );
}

function Memories() {
  const toast = useToast();
  const memories = useResource("knowledge:memories", () => api.memories.list());
  const byKey = new Map(memories.map((m: MemoryEntry) => [m.key, m]));
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);

  const save = async (key: string) => {
    setSaving(key);
    try {
      await api.memories.put(key, drafts[key] ?? "");
      refresh("knowledge:memories");
      setDrafts((d) => Object.fromEntries(Object.entries(d).filter(([k]) => k !== key)));
      toast({ tone: "success", title: "Memory saved", description: "Agents use it from their next run." });
    } catch (e) {
      toast({ tone: "error", title: "Couldn't save", description: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(null);
    }
  };

  return (
    <Card className="p-5">
      <SectionHeader title="Organisation memory" subtitle="Facts and preferences every agent reads. Only admins can change them, and every change is audit-logged." />
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {MEMORY_KEYS.map(({ key, label, hint }) => {
          const current = byKey.get(key)?.value ?? "";
          const value = drafts[key] ?? current;
          const dirty = key in drafts && drafts[key] !== current;
          return (
            <div key={key} className="rounded-[12px] border border-line bg-card-2/50 p-3.5">
              <label htmlFor={`mem-${key}`} className="flex items-center gap-1.5 text-[13px] font-medium">
                <BookMarked className="size-3.5 text-fg-3" /> {label}
              </label>
              <p className="mt-0.5 text-[12px] text-fg-3">{hint}</p>
              <textarea id={`mem-${key}`} className={`${area} mt-2`} rows={3} value={value} onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))} />
              <div className="mt-2 flex items-center justify-between">
                <span className="text-[11.5px] text-fg-3">{byKey.get(key) ? <>Updated <TimeAgo secondsAgo={ago(byKey.get(key)!.updatedAt)} /></> : "Not set"}</span>
                <Button size="sm" variant={dirty ? "primary" : "secondary"} disabled={!dirty || saving === key} onClick={() => void save(key)}>
                  {saving === key ? <Loader2 className="size-3.5 animate-spin" /> : null} Save
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function KnowledgeView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-[24px] font-semibold tracking-tight">Knowledge & Files</h2>
        <p className="mt-1 max-w-2xl text-[14px] text-fg-2">What your agents know about your organisation. Everything here is private to this workspace.</p>
      </div>
      <LiveBoundary>
        <Documents />
      </LiveBoundary>
      <LiveBoundary>
        <Memories />
      </LiveBoundary>
    </div>
  );
}
