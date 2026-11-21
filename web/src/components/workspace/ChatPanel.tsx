"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, Cpu, FileText, Paperclip, Square, X } from "lucide-react";
import type { AgentKey, AgentProfile, ChatMessage } from "@/lib/types";
import { AGENT_IDENTITIES } from "@/lib/agents";
import { cn } from "@/lib/cn";
import { api } from "@/data/api";
import { AgentGlyph } from "@/components/agent/AgentCard";
import { CopyButton, Markdown } from "@/components/ui/Markdown";
import { TimeAgo } from "@/components/ui/time";
import { formatSize } from "@/components/tasks/ExecutionParts";

const STARTERS: Record<AgentKey, string[]> = {
  research: ["Compare the top 5 competitors with sources", "Summarise the attached PDF and flag weak claims"],
  marketing: ["Draft a 4-week launch content calendar", "Rewrite this in our brand voice"],
  engineer: ["Review this module for bugs", "Write tests for the billing webhooks"],
  bi: ["Explain last month's churn change", "Build a weekly KPI report"],
  assistant: ["Plan my week around 3 focus blocks", "Draft a polite follow-up email"],
  creative: ["20 names for a tutoring product", "Run a premortem on our launch plan"],
};

interface Props {
  profile: AgentProfile;
  conversationId: string | null;
  initialMessages: ChatMessage[];
  loading: boolean;
}

export function ChatPanel({ profile, conversationId, initialMessages, loading }: Props) {
  const [messages, setMessages] = useState(initialMessages);
  const [draft, setDraft] = useState("");
  const [files, setFiles] = useState<string[]>([]);
  const [streaming, setStreaming] = useState<{ status: string; text: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const nextId = (p: string) => `${p}-${(seq.current += 1)}`;
  const [prevConv, setPrevConv] = useState(conversationId);
  const [prevInitial, setPrevInitial] = useState(initialMessages);

  // Reset local thread when the selected conversation (or its loaded messages) changes.
  if (prevConv !== conversationId || prevInitial !== initialMessages) {
    setPrevConv(conversationId);
    setPrevInitial(initialMessages);
    setMessages(initialMessages);
    setStreaming(null);
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming?.text]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = async (text: string) => {
    const prompt = text.trim();
    if (!prompt || streaming) return;
    const userMsg: ChatMessage = {
      id: nextId("u"),
      role: "user",
      content: prompt,
      createdSecondsAgo: 0,
      attachments: files.map((name) => ({ name, kind: "pdf", sizeKb: 0 })),
    };
    setMessages((m) => [...m, userMsg]);
    setDraft("");
    setFiles([]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let acc = "";
    setStreaming({ status: "Connecting…", text: "" });
    try {
      for await (const chunk of api.conversations.streamReply(profile.key, prompt, ctrl.signal)) {
        if (chunk.type === "status") setStreaming({ status: chunk.text, text: acc });
        else if (chunk.type === "delta") {
          acc += chunk.text;
          setStreaming({ status: "", text: acc });
        } else {
          setMessages((m) => [...m, { id: nextId("a"), role: "assistant", content: acc, createdSecondsAgo: 0, model: chunk.model, executionId: chunk.executionId }]);
          setStreaming(null);
        }
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        if (acc) setMessages((m) => [...m, { id: nextId("a"), role: "assistant", content: `${acc}\n\n_— stopped by you_`, createdSecondsAgo: 0 }]);
      }
      setStreaming(null);
    }
  };

  const stop = () => abortRef.current?.abort();
  const primaryModel = profile.models[0];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6" aria-live="polite">
        {loading ? (
          <ChatSkeleton />
        ) : messages.length === 0 && !streaming ? (
          <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center text-center">
            <AgentGlyph agent={profile.key} size={56} />
            <h3 className="mt-4 text-[17px] font-semibold tracking-tight">Start a conversation with {AGENT_IDENTITIES[profile.key].shortName}</h3>
            <p className="mt-1 text-[13px] text-fg-2">{profile.mission}</p>
            <div className="mt-5 flex flex-col gap-2">
              {STARTERS[profile.key].map((s) => (
                <button key={s} type="button" onClick={() => send(s)} className="rounded-[10px] border border-line bg-card-2 px-3 py-2 text-left text-[13px] text-fg-2 hover:border-line-strong hover:text-fg">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.map((m) => (
              <Message key={m.id} m={m} agent={profile.key} />
            ))}
            {streaming ? (
              <div className="flex gap-3">
                <AgentGlyph agent={profile.key} size={30} live />
                <div className="min-w-0 flex-1 pt-1">
                  {streaming.text ? (
                    <div className="af-stream-caret">
                      <Markdown>{streaming.text}</Markdown>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-[13px] text-fg-2">
                      <span className="flex gap-1" aria-hidden>
                        {[0, 1, 2].map((i) => (
                          <span key={i} className="size-1.5 animate-bounce rounded-full bg-cyan motion-reduce:animate-none" style={{ animationDelay: `${i * 120}ms` }} />
                        ))}
                      </span>
                      {streaming.status}
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>

      {/* Composer */}
      <div className="border-t border-line bg-bg-2/60 px-4 py-3 sm:px-6">
        <form
          className="mx-auto max-w-3xl rounded-[14px] border border-line bg-card p-2 focus-within:border-[color-mix(in_oklab,var(--accent)_60%,var(--border))] focus-within:shadow-[var(--glow)]"
          onSubmit={(e) => {
            e.preventDefault();
            void send(draft);
          }}
        >
          {files.length ? (
            <div className="flex flex-wrap gap-1.5 px-1.5 pb-1.5">
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
          <label htmlFor="chat-input" className="sr-only">
            Message {profile.name}
          </label>
          <textarea
            id="chat-input"
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(draft);
              }
            }}
            placeholder={`Message ${AGENT_IDENTITIES[profile.key].shortName}…  (Shift+Enter for a new line)`}
            className="block w-full resize-none bg-transparent px-2 py-1.5 text-[14px] outline-none placeholder:text-fg-3"
          />
          <div className="flex items-center gap-2 px-1">
            <label className="grid size-8 cursor-pointer place-items-center rounded-[8px] text-fg-3 hover:bg-card-2 hover:text-fg" aria-label="Attach files">
              <Paperclip className="size-4" />
              <input type="file" multiple className="sr-only" onChange={(e) => setFiles((f) => [...f, ...Array.from(e.target.files ?? []).map((x) => x.name)])} />
            </label>
            {primaryModel ? (
              <span className="flex min-w-0 items-center gap-1.5 truncate text-[11.5px] text-fg-3" title="Resolved by the Model Gateway routing policy">
                <Cpu className="size-3.5 shrink-0" />
                <span className="truncate">
                  {primaryModel.capability} → <span className="font-mono text-fg-2">{primaryModel.model}</span>
                </span>
              </span>
            ) : null}
            <div className="ml-auto">
              {streaming ? (
                <button type="button" onClick={stop} className="flex h-8 items-center gap-1.5 rounded-[9px] border border-line px-2.5 text-[12.5px] text-fg-2 hover:text-fg" aria-label="Stop generating">
                  <Square className="size-3 fill-current" /> Stop
                </button>
              ) : (
                <button type="submit" disabled={!draft.trim()} className="grid size-8 place-items-center rounded-[9px] bg-[linear-gradient(135deg,var(--accent),var(--accent-2))] text-white disabled:opacity-40" aria-label="Send message">
                  <ArrowUp className="size-4" />
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

function Message({ m, agent }: { m: ChatMessage; agent: AgentKey }) {
  if (m.role === "user") {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[85%] rounded-[14px] rounded-br-[4px] border border-line bg-card-2 px-3.5 py-2.5 text-[14px] leading-relaxed text-fg">
          <p className="whitespace-pre-wrap">{m.content}</p>
        </div>
        {m.attachments?.length ? (
          <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
            {m.attachments.map((a) => (
              <span key={a.name} className="flex items-center gap-1.5 rounded-md border border-line bg-card px-2 py-1 text-[11.5px] text-fg-2">
                <FileText className="size-3.5" /> {a.name}
                {a.sizeKb ? <span className="text-fg-3">· {formatSize(a.sizeKb)}</span> : null}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <div className="group flex gap-3">
      <AgentGlyph agent={agent} size={30} />
      <div className="min-w-0 flex-1 pt-1">
        <Markdown>{m.content}</Markdown>
        <div className={cn("mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-fg-3")}>
          <TimeAgo secondsAgo={m.createdSecondsAgo} />
          {m.model ? (
            <span className="flex items-center gap-1">
              <Cpu className="size-3" /> <span className="font-mono">{m.model}</span>
            </span>
          ) : null}
          {m.executionId ? (
            <Link href="/tasks" className="font-mono hover:text-accent">
              {m.executionId}
            </Link>
          ) : null}
          <span className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <CopyButton text={m.content} />
          </span>
        </div>
      </div>
    </div>
  );
}

function ChatSkeleton() {
  return (
    <div className="mx-auto max-w-3xl space-y-6" aria-label="Loading messages">
      <div className="ml-auto h-12 w-2/3 rounded-[14px] af-skeleton" />
      <div className="flex gap-3">
        <div className="size-[30px] shrink-0 rounded-[10px] af-skeleton" />
        <div className="flex-1 space-y-2 pt-1">
          <div className="h-3 w-11/12 rounded af-skeleton" />
          <div className="h-3 w-4/5 rounded af-skeleton" />
          <div className="h-3 w-2/3 rounded af-skeleton" />
          <div className="mt-4 h-24 w-full rounded-[10px] af-skeleton" />
        </div>
      </div>
    </div>
  );
}
