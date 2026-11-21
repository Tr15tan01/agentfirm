"use client";

import { useState } from "react";
import { ArrowUp, Paperclip, Wand2, Users, X, FileText } from "lucide-react";
import { AGENT_IDENTITIES } from "@/lib/agents";
import type { AgentKey } from "@/lib/types";
import { cn } from "@/lib/cn";
import { Kbd } from "@/components/ui/primitives";

export interface TaskDraft {
  instruction: string;
  /** Empty = let the orchestrator choose. */
  agents: AgentKey[];
  files: string[];
}

const SUGGESTIONS = [
  "Research the English-learning market and draft a launch strategy",
  "Summarise last quarter's churn drivers",
  "Brainstorm 20 names for our tutoring product",
];

/** Shared task composer: natural language, attachments, auto or manual agent selection, multi-agent. */
export function TaskComposer({ onSubmit, autoFocus, showSuggestions = true }: { onSubmit: (d: TaskDraft) => void; autoFocus?: boolean; showSuggestions?: boolean }) {
  const [value, setValue] = useState("");
  const [selected, setSelected] = useState<AgentKey[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const auto = selected.length === 0;
  const multi = selected.length > 1;

  const toggle = (k: AgentKey) => setSelected((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));
  const submit = () => {
    if (!value.trim()) return;
    onSubmit({ instruction: value.trim(), agents: selected, files });
    setValue("");
    setFiles([]);
  };

  return (
    <div>
        <form
          className="rounded-[14px] border border-line bg-card/80 p-2 transition-[border-color,box-shadow] focus-within:border-[color-mix(in_oklab,var(--accent)_60%,var(--border))] focus-within:shadow-[var(--glow)]"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label htmlFor="quick-task" className="sr-only">
            What would you like your AI team to do?
          </label>
          <textarea
            id="quick-task"
            rows={2}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoFocus={autoFocus}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="What would you like your AI team to do?"
            className="block w-full resize-none bg-transparent px-2.5 py-2 text-[15px] text-fg outline-none placeholder:text-fg-3"
          />
          {files.length ? (
            <div className="flex flex-wrap gap-1.5 px-2 pb-1">
              {files.map((f) => (
                <span key={f} className="flex h-7 items-center gap-1.5 rounded-md border border-line bg-card-2 pl-2 pr-1 text-[12px] text-fg-2">
                  <FileText className="size-3.5" /> {f}
                  <button type="button" aria-label={`Remove ${f}`} onClick={() => setFiles((x) => x.filter((y) => y !== f))} className="rounded p-0.5 hover:text-fg">
                    <X className="size-3" />
                  </button>
                </span>
              ))}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-2 px-1 pb-0.5 pt-1">
            <label className="grid size-8 cursor-pointer place-items-center rounded-[8px] text-fg-3 hover:bg-card-2 hover:text-fg" aria-label="Attach files">
              <Paperclip className="size-4" />
              <input
                type="file"
                multiple
                className="sr-only"
                onChange={(e) => setFiles((f) => [...f, ...Array.from(e.target.files ?? []).map((x) => x.name)])}
              />
            </label>
            <div className="h-5 w-px bg-line" />
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Choose agents">
              <button
                type="button"
                onClick={() => setSelected([])}
                aria-pressed={auto}
                className={cn(
                  "flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium transition-colors",
                  auto ? "border-[color-mix(in_oklab,var(--accent)_50%,transparent)] bg-[color-mix(in_oklab,var(--accent)_14%,transparent)] text-accent" : "border-line text-fg-2 hover:text-fg",
                )}
              >
                <Wand2 className="size-3.5" /> Auto-select
              </button>
              {(Object.keys(AGENT_IDENTITIES) as AgentKey[]).map((k) => {
                const on = selected.includes(k);
                const Icon = AGENT_IDENTITIES[k].icon;
                return (
                  <button
                    key={k}
                    type="button"
                    onClick={() => toggle(k)}
                    aria-pressed={on}
                    className={cn(
                      "flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] transition-colors",
                      on ? "border-[color-mix(in_oklab,var(--accent-2)_50%,transparent)] bg-[color-mix(in_oklab,var(--accent-2)_14%,transparent)] text-fg" : "border-line text-fg-2 hover:text-fg",
                    )}
                  >
                    <Icon className="size-3.5" /> <span className="hidden sm:inline">{AGENT_IDENTITIES[k].shortName}</span>
                  </button>
                );
              })}
            </div>
            <div className="ml-auto flex items-center gap-2">
              {multi ? (
                <span className="hidden items-center gap-1 text-[12px] text-accent-2 md:flex">
                  <Users className="size-3.5" /> Multi-agent run
                </span>
              ) : null}
              <span className="hidden items-center gap-1 text-[11px] text-fg-3 lg:flex">
                <Kbd>⌘</Kbd>
                <Kbd>↵</Kbd>
              </span>
              <button
                type="submit"
                disabled={!value.trim()}
                className="grid size-9 place-items-center rounded-[10px] bg-[linear-gradient(135deg,var(--accent),var(--accent-2))] text-white shadow-[0_6px_18px_-8px_var(--accent)] transition-opacity disabled:opacity-40"
                aria-label="Start task"
              >
                <ArrowUp className="size-4" />
              </button>
            </div>
          </div>
        </form>

      {showSuggestions ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setValue(s)}
              className="rounded-full border border-dashed border-line px-3 py-1 text-[12px] text-fg-2 transition-colors hover:border-line-strong hover:text-fg"
            >
              {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
