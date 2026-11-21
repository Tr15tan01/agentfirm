"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowUpRight,
  BookOpen,
  Database,
  FileText,
  FolderKanban,
  GitBranch,
  Globe,
  Brain,
  PanelLeft,
  PanelRight,
  Pin,
  Plus,
  Search,
  MessagesSquare,
  LayoutGrid,
  X,
  Activity,
} from "lucide-react";
import type { AgentProfile, ChatMessage, Conversation, TaskDetail } from "@/lib/types";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { api } from "@/data/api";
import { AgentGlyph } from "@/components/agent/AgentCard";
import { AgentActivityCore } from "@/components/agent/AgentActivityCore";
import { AGENT_STATUS_META, Badge, DemoBadge, EXECUTION_STATUS_META, Progress } from "@/components/ui/primitives";
import { Elapsed, TimeAgo } from "@/components/ui/time";
import { ApprovalCard, ArtifactList, PanelEmpty, StepList, ToolCallList } from "@/components/tasks/ExecutionParts";
import { ChatPanel } from "./ChatPanel";

interface Props {
  profile: AgentProfile;
  conversations: Conversation[];
  initialConversationId: string | null;
  initialMessages: ChatMessage[];
  execution: TaskDetail | null;
  demo: boolean;
  /** Optional alternative main view (e.g. the Creative agent's idea board). */
  board?: ReactNode;
}

const KNOWLEDGE_ICON = { file: FileText, repo: GitBranch, web: Globe, connector: Database, memory: Brain } as const;

export function AgentWorkspace({ profile, conversations, initialConversationId, initialMessages, execution, demo, board }: Props) {
  const [convId, setConvId] = useState<string | null>(initialConversationId);
  const [messages, setMessages] = useState(initialMessages);
  const [loading, setLoading] = useState(false);
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [view, setView] = useState<"board" | "chat">(board ? "board" : "chat");
  const [q, setQ] = useState("");

  const openConversation = async (id: string | null) => {
    setConvId(id);
    setLeftOpen(false);
    setView("chat");
    if (!id) {
      setMessages([]);
      return;
    }
    setLoading(true);
    try {
      setMessages(await api.conversations.messages(id));
    } finally {
      setLoading(false);
    }
  };

  const meta = AGENT_STATUS_META[profile.status];
  const filtered = conversations.filter((c) => !q || `${c.title} ${c.preview}`.toLowerCase().includes(q.toLowerCase()));
  const pinned = filtered.filter((c) => c.pinned);
  const recent = filtered.filter((c) => !c.pinned);
  const projects = Array.from(new Set(conversations.map((c) => c.project).filter(Boolean))) as string[];
  const showBoard = view === "board" && board;

  const left = (
    <div className="flex h-full flex-col">
      <div className="space-y-2 p-3">
        <button
          type="button"
          onClick={() => openConversation(null)}
          className="flex h-9 w-full items-center justify-center gap-2 rounded-[10px] border border-line bg-card-2 text-[13px] font-medium hover:border-line-strong"
        >
          <Plus className="size-4" /> New conversation
        </button>
        <label className="flex h-8 items-center gap-2 rounded-[9px] border border-line px-2.5 text-[12.5px] focus-within:border-accent">
          <Search className="size-3.5 text-fg-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search conversations" className="w-full bg-transparent outline-none placeholder:text-fg-3" aria-label="Search conversations" />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {[
          { title: "Pinned", items: pinned },
          { title: "Recent", items: recent },
        ].map((g) =>
          g.items.length ? (
            <div key={g.title} className="mb-3">
              <div className="af-label px-2 pb-1.5 pt-1 !text-[10px]">{g.title}</div>
              <ul className="space-y-0.5">
                {g.items.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => openConversation(c.id)}
                      aria-current={c.id === convId ? "true" : undefined}
                      className={cn("w-full rounded-[9px] px-2.5 py-2 text-left transition-colors", c.id === convId ? "bg-card-2" : "hover:bg-card-2/60")}
                    >
                      <div className="flex items-center gap-1.5">
                        {c.pinned ? <Pin className="size-3 shrink-0 text-fg-3" /> : null}
                        <span className={cn("truncate text-[13px]", c.id === convId ? "font-medium text-fg" : "text-fg-2")}>{c.title}</span>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between gap-2 text-[11.5px] text-fg-3">
                        <span className="truncate">{c.preview}</span>
                        <span className="shrink-0">
                          <TimeAgo secondsAgo={c.updatedSecondsAgo} />
                        </span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
        {filtered.length === 0 ? <p className="px-2 text-[12.5px] text-fg-3">No conversations found.</p> : null}

        {projects.length ? (
          <div className="mb-3">
            <div className="af-label px-2 pb-1.5 pt-1 !text-[10px]">Projects</div>
            {projects.map((p) => (
              <Link key={p} href="/projects" className="flex items-center gap-2 rounded-[9px] px-2.5 py-1.5 text-[13px] text-fg-2 hover:bg-card-2/60 hover:text-fg">
                <FolderKanban className="size-3.5 text-fg-3" /> {p}
              </Link>
            ))}
          </div>
        ) : null}

        <div>
          <div className="af-label px-2 pb-1.5 pt-1 !text-[10px]">Context & knowledge</div>
          {profile.knowledgeSources.map((k) => {
            const Icon = KNOWLEDGE_ICON[k.kind];
            return (
              <div key={k.name} className="flex items-start gap-2 rounded-[9px] px-2.5 py-1.5">
                <Icon className="mt-0.5 size-3.5 shrink-0 text-fg-3" />
                <div className="min-w-0">
                  <div className="truncate text-[12.5px] text-fg-2">{k.name}</div>
                  <div className={cn("truncate text-[11px]", k.detail.includes("expired") ? "text-warn" : "text-fg-3")}>{k.detail}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );

  const right = <ExecutionSidebar execution={execution} profile={profile} />;

  return (
    <div className="af-card relative flex h-[calc(100dvh-7rem)] min-h-[600px] flex-col overflow-hidden lg:h-[calc(100dvh-8rem)]">
      {/* Header */}
      <div className="flex shrink-0 items-center gap-3 border-b border-line px-3 py-2.5 sm:px-4">
        {!showBoard ? (
          <button type="button" className="grid size-8 place-items-center rounded-md text-fg-2 hover:bg-card-2 lg:hidden" onClick={() => setLeftOpen(true)} aria-label="Show conversations">
            <PanelLeft className="size-4" />
          </button>
        ) : null}
        <AgentGlyph agent={profile.key} live={profile.status === "working"} size={34} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[14.5px] font-semibold tracking-tight">{profile.name}</h2>
            <span className="hidden rounded-md border border-line px-1.5 font-mono text-[10.5px] text-fg-3 sm:inline">{profile.version}</span>
          </div>
          <p className="hidden truncate text-[12px] text-fg-3 sm:block">{AGENT_IDENTITIES[profile.key].description}</p>
        </div>
        {board ? (
          <div className="flex rounded-[10px] border border-line bg-card-2 p-0.5" role="tablist" aria-label="Workspace view">
            {[
              { k: "board" as const, label: "Idea board", icon: LayoutGrid },
              { k: "chat" as const, label: "Chat", icon: MessagesSquare },
            ].map(({ k, label, icon: Icon }) => (
              <button
                key={k}
                role="tab"
                aria-selected={view === k}
                type="button"
                onClick={() => setView(k)}
                className={cn("flex h-7 items-center gap-1.5 rounded-[8px] px-2.5 text-[12.5px]", view === k ? "bg-card text-fg shadow-[var(--shadow)]" : "text-fg-3 hover:text-fg-2")}
              >
                <Icon className="size-3.5" /> <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>
        ) : null}
        <Badge tone={meta.tone} live={meta.live} className="hidden md:inline-flex">
          {meta.label}
        </Badge>
        {demo ? <DemoBadge className="hidden md:inline-flex" /> : null}
        {!showBoard ? (
          <button type="button" className="relative grid size-8 place-items-center rounded-md text-fg-2 hover:bg-card-2 xl:hidden" onClick={() => setRightOpen(true)} aria-label="Show execution panel">
            <PanelRight className="size-4" />
            {execution?.approvals.some((a) => a.status === "pending") ? <span className="absolute right-1 top-1 size-2 rounded-full bg-warn" /> : null}
          </button>
        ) : null}
      </div>

      {/* Body */}
      {showBoard ? (
        <div className="min-h-0 flex-1 overflow-y-auto">{board}</div>
      ) : (
        <div className="grid min-h-0 flex-1 lg:grid-cols-[264px_minmax(0,1fr)] xl:grid-cols-[264px_minmax(0,1fr)_340px]">
          <aside className="hidden min-h-0 border-r border-line lg:block" aria-label="Conversations and context">
            {left}
          </aside>
          <section className="min-h-0 min-w-0" aria-label="Chat">
            <ChatPanel profile={profile} conversationId={convId} initialMessages={messages} loading={loading} />
          </section>
          <aside className="hidden min-h-0 overflow-y-auto border-l border-line xl:block" aria-label="Current execution">
            {right}
          </aside>
        </div>
      )}

      {/* Mobile / tablet drawers */}
      <AnimatePresence>
        {leftOpen || rightOpen ? (
          <motion.div className="absolute inset-0 z-20 bg-black/40" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => { setLeftOpen(false); setRightOpen(false); }} />
        ) : null}
        {leftOpen ? (
          <motion.aside key="l" initial={{ x: "-100%" }} animate={{ x: 0 }} exit={{ x: "-100%" }} transition={{ type: "spring", stiffness: 420, damping: 40 }} className="absolute inset-y-0 left-0 z-30 w-[290px] max-w-[85%] border-r border-line bg-card lg:hidden">
            <button type="button" className="absolute right-2 top-2 z-10 grid size-7 place-items-center rounded-md text-fg-3 hover:bg-card-2" onClick={() => setLeftOpen(false)} aria-label="Close">
              <X className="size-4" />
            </button>
            <div className="h-full pt-8">{left}</div>
          </motion.aside>
        ) : null}
        {rightOpen ? (
          <motion.aside key="r" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 420, damping: 40 }} className="absolute inset-y-0 right-0 z-30 w-[360px] max-w-[90%] overflow-y-auto border-l border-line bg-card xl:hidden">
            <button type="button" className="absolute right-2 top-2 z-10 grid size-7 place-items-center rounded-md text-fg-3 hover:bg-card-2" onClick={() => setRightOpen(false)} aria-label="Close">
              <X className="size-4" />
            </button>
            {right}
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function ExecutionSidebar({ execution, profile }: { execution: TaskDetail | null; profile: AgentProfile }) {
  if (!execution) {
    return (
      <div className="space-y-4 p-4">
        <div className="af-label">Current execution</div>
        <div className="flex justify-center py-2">
          <AgentActivityCore agent={profile.key} state="idle" size={120} showDetails={false} />
        </div>
        <PanelEmpty icon={Activity} title="No active execution" body="Tasks you start from this chat appear here with live steps, tools and approvals." />
        <div>
          <div className="af-label mb-2">Recent</div>
          <ul className="space-y-1">
            {profile.recentExecutions.map((e) => (
              <li key={e.id}>
                <Link href={`/tasks/${e.taskId}`} className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-[12.5px] text-fg-2 hover:bg-card-2 hover:text-fg">
                  <span className="truncate">{e.title}</span>
                  <Badge tone={EXECUTION_STATUS_META[e.status].tone}>{EXECUTION_STATUS_META[e.status].label}</Badge>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  const st = EXECUTION_STATUS_META[execution.status];
  const pending = execution.approvals.filter((a) => a.status === "pending");
  const coreState = execution.status === "failed" ? "failed" : execution.status === "completed" ? "completed" : execution.agents.length > 1 ? "collaborating" : "working";

  return (
    <div className="space-y-5 p-4">
      <div>
        <div className="flex items-center justify-between gap-2">
          <span className="af-label">Current execution</span>
          <Badge tone={st.tone} live={st.live}>
            {st.label}
          </Badge>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <AgentActivityCore agent={profile.key} state={coreState} progress={execution.progress} size={84} showDetails={false} />
          <div className="min-w-0">
            <p className="line-clamp-2 text-[13.5px] font-medium">{execution.title}</p>
            <p className="mt-0.5 font-mono text-[11px] text-fg-3">{execution.executionId}</p>
          </div>
        </div>
        <div className="mt-3">
          <div className="mb-1.5 flex justify-between text-[11.5px]">
            <span className="truncate text-fg-2">{execution.stage}</span>
            <span className="shrink-0 font-mono text-fg-3">
              {execution.progress === null ? "—" : `${Math.round(execution.progress * 100)}%`} · <Elapsed startedSecondsAgo={execution.startedSecondsAgo} running={execution.status === "running"} />
            </span>
          </div>
          <Progress value={execution.progress} tone={execution.status === "waiting_approval" ? "warn" : "accent"} label="Execution progress" />
        </div>
      </div>

      {pending.length ? (
        <div>
          <div className="af-label mb-2 text-warn">Approval needed</div>
          <div className="space-y-2">
            {pending.map((a) => (
              <ApprovalCard key={a.id} approval={a} />
            ))}
          </div>
        </div>
      ) : null}

      <div>
        <div className="af-label mb-2">Steps</div>
        <StepList steps={execution.plan} compact />
      </div>

      <div>
        <div className="af-label mb-2">Tools in use</div>
        <ToolCallList calls={execution.toolCalls.slice(-3).reverse()} compact />
      </div>

      <div>
        <div className="af-label mb-2">Artifacts</div>
        <ArtifactList artifacts={execution.artifacts} />
      </div>

      <Link href={`/tasks/${execution.id}`} className="flex h-9 items-center justify-center gap-1.5 rounded-[10px] border border-line text-[13px] font-medium text-fg-2 hover:border-line-strong hover:text-fg">
        Open full monitor <ArrowUpRight className="size-3.5" />
      </Link>
      <p className="flex items-center gap-1.5 text-[11px] text-fg-3">
        <BookOpen className="size-3" /> State comes from execution events — never simulated progress.
      </p>
    </div>
  );
}
