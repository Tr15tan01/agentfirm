"use client";

import { useRef, useState } from "react";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "motion/react";
import {
  Atom,
  Check,
  ChevronRight,
  Combine,
  Compass,
  Crosshair,
  Footprints,
  GitCompare,
  Hammer,
  Lightbulb,
  Loader2,
  MoreHorizontal,
  Pencil,
  Scale,
  Send,
  Shuffle,
  Skull,
  Sparkles,
  Square,
  Swords,
  Trophy,
  Wand2,
  X,
  type LucideIcon,
} from "lucide-react";
import type { AgentKey, Idea, IdeaColumn, ThinkingApproach } from "@/lib/types";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { api } from "@/data/api";
import { Button } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";

export const APPROACHES: Record<ThinkingApproach, { label: string; icon: LucideIcon; hint: string }> = {
  divergent: { label: "Divergent", icon: Sparkles, hint: "Go wide: many ideas, no judgement yet." },
  convergent: { label: "Convergent", icon: Crosshair, hint: "Cluster, compare and pick the strongest." },
  first_principles: { label: "First principles", icon: Atom, hint: "Strip to fundamentals and rebuild." },
  lateral: { label: "Lateral", icon: Shuffle, hint: "Provocations and random entry points." },
  scamper: { label: "SCAMPER", icon: Combine, hint: "Substitute, combine, adapt, modify, put to use, eliminate, reverse." },
  six_hats: { label: "Six Thinking Hats", icon: Compass, hint: "Facts, feelings, risks, benefits, creativity, process." },
  analogical: { label: "Analogies", icon: Footprints, hint: "Borrow what works in other industries." },
  debate: { label: "Structured debate", icon: Swords, hint: "Argue for and against, then synthesise." },
  premortem: { label: "Premortem", icon: Skull, hint: "Assume it failed — find out why first." },
};

const COLUMNS: { key: IdeaColumn; label: string; hint: string }[] = [
  { key: "new", label: "New", hint: "Fresh from the agent" },
  { key: "shortlisted", label: "Shortlisted", hint: "Worth a closer look" },
  { key: "developing", label: "Developing", hint: "Being worked on" },
  { key: "parked", label: "Parked", hint: "Not now" },
];

const HANDOFF: AgentKey[] = ["research", "marketing", "bi", "engineer"];

const total = (i: Idea) => i.scores.impact + i.scores.feasibility + i.scores.novelty;

export function IdeaBoard({ initialIdeas }: { initialIdeas: Idea[] }) {
  const toast = useToast();
  const [ideas, setIdeas] = useState(initialIdeas);
  const [objective, setObjective] = useState("Names and positioning for our tutoring product");
  const [approach, setApproach] = useState<ThinkingApproach>("lateral");
  const [generating, setGenerating] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [dragOver, setDragOver] = useState<IdeaColumn | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const generate = async () => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setGenerating(true);
    try {
      for await (const idea of api.ideas.generate(objective, approach, ctrl.signal)) {
        setIdeas((xs) => [idea, ...xs]);
      }
      toast({ tone: "success", title: "New ideas added", description: `${APPROACHES[approach].label} session complete.` });
    } catch (e) {
      if ((e as Error).name !== "AbortError") throw e;
    } finally {
      setGenerating(false);
    }
  };

  const move = (id: string, column: IdeaColumn) => {
    const before = ideas.find((x) => x.id === id)?.column;
    setIdeas((xs) => xs.map((x) => (x.id === id ? { ...x, column } : x)));
    // Persist; "rejected" also teaches the Creative agent not to suggest it again (server-side memory).
    api.ideas.move(id, column).catch(() => setIdeas((xs) => xs.map((x) => (x.id === id && before ? { ...x, column: before } : x))));
  };
  const update = (id: string, patch: Partial<Pick<Idea, "title" | "summary">>) => setIdeas((xs) => xs.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const toggleSelect = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 4 ? s : [...s, id]));

  const handoff = async (idea: Idea, agent: AgentKey) => {
    const { taskId } = await api.ideas.handoff(idea.id, agent);
    move(idea.id, "developing");
    toast({ tone: "success", title: `Sent to ${AGENT_IDENTITIES[agent].shortName}`, description: `“${idea.title}” → ${taskId}` });
  };

  const compared = ideas.filter((i) => selected.includes(i.id));
  const A = APPROACHES[approach];

  return (
    <div className="flex min-h-full flex-col">
      {/* Session setup */}
      <div className="border-b border-line bg-[radial-gradient(80%_120%_at_0%_0%,color-mix(in_oklab,var(--accent-2)_10%,transparent),transparent)] p-4 sm:p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <label className="min-w-0 flex-1">
            <span className="af-label mb-1.5 block">What are we thinking about?</span>
            <input
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              className="h-10 w-full rounded-[10px] border border-line bg-card px-3 text-[14px] outline-none focus:border-accent-2"
            />
          </label>
          {generating ? (
            <Button variant="secondary" className="h-10" onClick={() => abortRef.current?.abort()}>
              <Square className="size-3 fill-current" /> Stop
            </Button>
          ) : (
            <Button variant="primary" className="h-10" disabled={!objective.trim()} onClick={generate}>
              <Wand2 className="size-4" /> Generate ideas
            </Button>
          )}
        </div>
        <div className="mt-3">
          <span className="af-label mb-1.5 block">Thinking approach</span>
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Thinking approach">
            {(Object.keys(APPROACHES) as ThinkingApproach[]).map((k) => {
              const a = APPROACHES[k];
              const Icon = a.icon;
              const on = k === approach;
              return (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => setApproach(k)}
                  className={cn(
                    "flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] transition-colors",
                    on ? "border-[color-mix(in_oklab,var(--accent-2)_55%,transparent)] bg-[color-mix(in_oklab,var(--accent-2)_14%,transparent)] text-fg" : "border-line text-fg-2 hover:text-fg",
                  )}
                >
                  <Icon className={cn("size-3.5", on && "text-accent-2")} /> {a.label}
                </button>
              );
            })}
          </div>
          <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-fg-2">
            <A.icon className="size-3.5 text-accent-2" /> {A.hint}
            <span className="text-fg-3">· Ideas are speculative — not verified facts.</span>
          </p>
        </div>
      </div>

      {/* Board */}
      <div className="flex-1 overflow-x-auto p-4 sm:p-5">
        <div className="grid min-w-[880px] grid-cols-4 gap-4">
          {COLUMNS.map((col) => {
            const items = ideas.filter((i) => i.column === col.key);
            return (
              <section
                key={col.key}
                aria-label={`${col.label} ideas`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(col.key);
                }}
                onDragLeave={() => setDragOver((d) => (d === col.key ? null : d))}
                onDrop={(e) => {
                  e.preventDefault();
                  const id = e.dataTransfer.getData("text/idea");
                  if (id) move(id, col.key);
                  setDragOver(null);
                }}
                className={cn(
                  "flex min-h-[360px] flex-col rounded-[14px] border bg-card-2/50 p-2.5 transition-colors",
                  dragOver === col.key ? "border-accent-2 bg-[color-mix(in_oklab,var(--accent-2)_7%,transparent)]" : "border-line",
                )}
              >
                <div className="mb-2 flex items-center justify-between px-1">
                  <div>
                    <h3 className="text-[13px] font-semibold">{col.label}</h3>
                    <p className="text-[11px] text-fg-3">{col.hint}</p>
                  </div>
                  <span className="rounded-md bg-card px-1.5 font-mono text-[11px] text-fg-3">{items.length}</span>
                </div>
                <div className="flex flex-1 flex-col gap-2">
                  {col.key === "new" && generating ? (
                    <div className="flex items-center gap-2 rounded-[12px] border border-dashed border-[color-mix(in_oklab,var(--accent-2)_50%,var(--border))] px-3 py-3 text-[12.5px] text-fg-2">
                      <Loader2 className="size-3.5 animate-spin text-accent-2" /> Generating with {A.label}…
                    </div>
                  ) : null}
                  <AnimatePresence initial={false}>
                    {items.map((i) => (
                      <IdeaCard
                        key={i.id}
                        idea={i}
                        selected={selected.includes(i.id)}
                        onSelect={() => toggleSelect(i.id)}
                        onMove={(c) => move(i.id, c)}
                        onHandoff={(a) => handoff(i, a)}
                        onEdit={(p) => update(i.id, p)}
                      />
                    ))}
                  </AnimatePresence>
                  {items.length === 0 && !(col.key === "new" && generating) ? (
                    <div className="grid flex-1 place-items-center rounded-[12px] border border-dashed border-line p-4 text-center text-[12px] text-fg-3">
                      Drop ideas here
                    </div>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      </div>

      {/* Compare tray */}
      <AnimatePresence>
        {selected.length ? (
          <motion.div
            initial={{ y: 40, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 40, opacity: 0 }}
            className="sticky bottom-3 z-10 mx-auto mb-3 flex w-fit items-center gap-3 rounded-full border border-line bg-card px-4 py-2 shadow-[var(--shadow)]"
          >
            <GitCompare className="size-4 text-accent-2" />
            <span className="text-[13px]">
              <span className="font-mono">{selected.length}</span> selected <span className="text-fg-3">(max 4)</span>
            </span>
            <Button size="sm" variant="primary" disabled={selected.length < 2} onClick={() => setCompareOpen(true)}>
              Compare
            </Button>
            <button type="button" className="text-[12.5px] text-fg-3 hover:text-fg" onClick={() => setSelected([])}>
              Clear
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <CompareDialog open={compareOpen} onOpenChange={setCompareOpen} ideas={compared} />
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-[62px] text-[10.5px] text-fg-3">{label}</span>
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-[color-mix(in_oklab,var(--fg-3)_18%,transparent)]">
        <div className="h-full rounded-full bg-accent-2" style={{ width: `${value * 10}%` }} />
      </div>
      <span className="w-4 text-right font-mono text-[10.5px] text-fg-2">{value}</span>
    </div>
  );
}

function IdeaCard({
  idea,
  selected,
  onSelect,
  onMove,
  onHandoff,
  onEdit,
}: {
  idea: Idea;
  selected: boolean;
  onSelect: () => void;
  onMove: (c: IdeaColumn) => void;
  onHandoff: (a: AgentKey) => void;
  onEdit: (p: { title: string; summary: string }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(idea.title);
  const [summary, setSummary] = useState(idea.summary);
  const A = APPROACHES[idea.approach];

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.22 }}
      draggable={!editing}
      onDragStartCapture={(e) => e.dataTransfer.setData("text/idea", idea.id)}
      className={cn(
        "group cursor-grab rounded-[12px] border bg-card p-3 shadow-[var(--shadow)] active:cursor-grabbing",
        selected ? "border-accent-2 ring-1 ring-[color-mix(in_oklab,var(--accent-2)_40%,transparent)]" : "border-line hover:border-line-strong",
      )}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          role="checkbox"
          aria-checked={selected}
          aria-label={`Select “${idea.title}” for comparison`}
          onClick={onSelect}
          className={cn("mt-0.5 grid size-4 shrink-0 place-items-center rounded border", selected ? "border-accent-2 bg-accent-2 text-white" : "border-line-strong")}
        >
          {selected ? <Check className="size-3" /> : null}
        </button>
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="space-y-1.5">
              <input value={title} onChange={(e) => setTitle(e.target.value)} className="w-full rounded-md border border-line bg-card-2 px-2 py-1 text-[13px] font-medium outline-none focus:border-accent-2" aria-label="Idea title" />
              <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={3} className="w-full resize-none rounded-md border border-line bg-card-2 px-2 py-1 text-[12.5px] outline-none focus:border-accent-2" aria-label="Idea summary" />
              <div className="flex gap-1.5">
                <Button size="sm" variant="primary" onClick={() => { onEdit({ title, summary }); setEditing(false); }}>
                  Save
                </Button>
                <Button size="sm" variant="ghost" onClick={() => { setTitle(idea.title); setSummary(idea.summary); setEditing(false); }}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <>
              <h4 className="text-[13.5px] font-medium leading-snug">{idea.title}</h4>
              <p className="mt-1 text-[12.5px] leading-snug text-fg-2">{idea.summary}</p>
            </>
          )}
        </div>
        {!editing ? (
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <button type="button" aria-label="Idea actions" className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 opacity-70 hover:bg-card-2 hover:text-fg group-hover:opacity-100">
                <MoreHorizontal className="size-4" />
              </button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content align="end" sideOffset={4} className="z-50 w-52 rounded-[12px] border border-line bg-card p-1.5 text-[13px] shadow-[var(--shadow)]">
                <Dropdown.Item onSelect={() => setEditing(true)} className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 outline-none data-[highlighted]:bg-card-2">
                  <Pencil className="size-3.5 text-fg-3" /> Edit
                </Dropdown.Item>
                <Dropdown.Item onSelect={() => onMove("developing")} className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 outline-none data-[highlighted]:bg-card-2">
                  <Hammer className="size-3.5 text-fg-3" /> Develop further
                </Dropdown.Item>
                <Dropdown.Sub>
                  <Dropdown.SubTrigger className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 outline-none data-[highlighted]:bg-card-2 data-[state=open]:bg-card-2">
                    <Scale className="size-3.5 text-fg-3" /> Move to <ChevronRight className="ml-auto size-3.5" />
                  </Dropdown.SubTrigger>
                  <Dropdown.Portal>
                    <Dropdown.SubContent sideOffset={6} className="z-50 w-40 rounded-[12px] border border-line bg-card p-1.5 shadow-[var(--shadow)]">
                      {COLUMNS.filter((c) => c.key !== idea.column).map((c) => (
                        <Dropdown.Item key={c.key} onSelect={() => onMove(c.key)} className="flex h-8 cursor-pointer items-center rounded-md px-2 outline-none data-[highlighted]:bg-card-2">
                          {c.label}
                        </Dropdown.Item>
                      ))}
                    </Dropdown.SubContent>
                  </Dropdown.Portal>
                </Dropdown.Sub>
                <Dropdown.Item onSelect={() => onMove("rejected")} className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 text-[var(--err)] outline-none data-[highlighted]:bg-card-2">
                  <X className="size-3.5" /> Reject — don&apos;t suggest again
                </Dropdown.Item>
                <Dropdown.Separator className="my-1 h-px bg-line" />
                <Dropdown.Label className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-fg-3">Send to agent</Dropdown.Label>
                {HANDOFF.map((a) => {
                  const Icon = AGENT_IDENTITIES[a].icon;
                  return (
                    <Dropdown.Item key={a} onSelect={() => onHandoff(a)} className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 outline-none data-[highlighted]:bg-card-2">
                      <Icon className="size-3.5 text-fg-3" /> {AGENT_IDENTITIES[a].shortName}
                      <Send className="ml-auto size-3 text-fg-3" />
                    </Dropdown.Item>
                  );
                })}
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
        ) : null}
      </div>

      <div className="mt-2.5 space-y-1">
        <ScoreBar label="Impact" value={idea.scores.impact} />
        <ScoreBar label="Feasibility" value={idea.scores.feasibility} />
        <ScoreBar label="Novelty" value={idea.scores.novelty} />
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1">
        <span className="flex items-center gap-1 rounded-md bg-[color-mix(in_oklab,var(--accent-2)_12%,transparent)] px-1.5 py-0.5 text-[11px] text-accent-2">
          <A.icon className="size-3" /> {idea.lens ?? A.label}
        </span>
        {idea.tags.map((t) => (
          <span key={t} className="rounded-md border border-line px-1.5 py-0.5 text-[11px] text-fg-3">
            {t}
          </span>
        ))}
      </div>
    </motion.article>
  );
}

function CompareDialog({ open, onOpenChange, ideas }: { open: boolean; onOpenChange: (o: boolean) => void; ideas: Idea[] }) {
  const rows: { label: string; get: (i: Idea) => number }[] = [
    { label: "Impact", get: (i) => i.scores.impact },
    { label: "Feasibility", get: (i) => i.scores.feasibility },
    { label: "Novelty", get: (i) => i.scores.novelty },
    { label: "Total", get: total },
  ];
  const best = ideas.length ? ideas.reduce((a, b) => (total(b) > total(a) ? b : a)) : null;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-[10vh] z-50 max-h-[80vh] w-[min(860px,calc(100vw-2rem))] -translate-x-1/2 overflow-y-auto rounded-[18px] border border-line bg-card p-5 shadow-[var(--shadow)]">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-[17px] font-semibold tracking-tight">Compare ideas</Dialog.Title>
              <Dialog.Description className="mt-0.5 text-[13px] text-fg-2">Scores are the agent&apos;s judgement (1–10) — use them to discuss, not to decide for you.</Dialog.Description>
            </div>
            <Dialog.Close className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card-2 hover:text-fg" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <div className="overflow-x-auto rounded-[12px] border border-line">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-card-2">
                  <th className="w-28 p-3 text-left text-[11px] font-semibold uppercase tracking-wider text-fg-3">Criterion</th>
                  {ideas.map((i) => (
                    <th key={i.id} className="min-w-[160px] p-3 text-left align-top font-medium">
                      <div className="flex items-start gap-1.5">
                        {best?.id === i.id ? <Trophy className="mt-0.5 size-3.5 shrink-0 text-warn" aria-label="Highest total" /> : <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-fg-3" />}
                        {i.title}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const max = Math.max(...ideas.map(r.get));
                  return (
                    <tr key={r.label} className="border-t border-line">
                      <td className={cn("p-3 text-fg-2", r.label === "Total" && "font-medium text-fg")}>{r.label}</td>
                      {ideas.map((i) => (
                        <td key={i.id} className="p-3">
                          <span className={cn("font-mono", r.get(i) === max ? "font-semibold text-fg" : "text-fg-2")}>{r.get(i)}</span>
                          {r.label !== "Total" ? (
                            <div className="mt-1 h-1 w-full max-w-[120px] overflow-hidden rounded-full bg-[color-mix(in_oklab,var(--fg-3)_18%,transparent)]">
                              <div className="h-full rounded-full bg-accent-2" style={{ width: `${r.get(i) * 10}%` }} />
                            </div>
                          ) : null}
                        </td>
                      ))}
                    </tr>
                  );
                })}
                <tr className="border-t border-line">
                  <td className="p-3 text-fg-2">Approach</td>
                  {ideas.map((i) => (
                    <td key={i.id} className="p-3 text-fg-2">
                      {APPROACHES[i.approach].label}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
