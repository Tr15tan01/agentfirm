"use client";

import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  CheckCircle2,
  Circle,
  CircleDashed,
  CircleSlash,
  Download,
  Eye,
  X,
  FileCode2,
  FileSpreadsheet,
  FileText,
  Hourglass,
  Image as ImageIcon,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { AGENT_IDENTITIES, TONE_VAR } from "@/lib/agents";
import type {
  ApprovalRequest,
  Artifact,
  PlanStep,
  SideEffect,
  StepStatus,
  ToolCall,
} from "@/lib/types";
import { cn } from "@/lib/cn";
import { Badge, Button } from "@/components/ui/primitives";
import { formatDuration, TimeAgo } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { CopyButton, Markdown } from "@/components/ui/Markdown";

/* ── Side effects ───────────────────────────────────────────── */

const SIDE_EFFECT: Record<
  SideEffect,
  { label: string; tone: "muted" | "accent" | "warn" | "err" | "violet" }
> = {
  none: { label: "Read-only", tone: "muted" },
  internal: { label: "Internal", tone: "accent" },
  external: { label: "External", tone: "warn" },
  financial: { label: "Financial", tone: "err" },
  destructive: { label: "Destructive", tone: "err" },
};

export function SideEffectBadge({ effect }: { effect: SideEffect }) {
  const m = SIDE_EFFECT[effect];
  return <Badge tone={m.tone}>{m.label}</Badge>;
}

/* ── Plan steps ─────────────────────────────────────────────── */

const STEP: Record<
  StepStatus,
  { icon: LucideIcon; color: string; label: string; spin?: boolean }
> = {
  done: { icon: CheckCircle2, color: "var(--ok)", label: "Completed" },
  running: {
    icon: Loader2,
    color: "var(--cyan)",
    label: "Running",
    spin: true,
  },
  waiting: {
    icon: Hourglass,
    color: "var(--warn)",
    label: "Waiting for approval",
  },
  pending: { icon: Circle, color: "var(--fg-3)", label: "Pending" },
  failed: { icon: XCircle, color: "var(--err)", label: "Failed" },
  skipped: { icon: CircleSlash, color: "var(--fg-3)", label: "Skipped" },
};

export function StepIcon({
  status,
  className,
}: {
  status: StepStatus;
  className?: string;
}) {
  const s = STEP[status];
  const Icon = s.icon;
  return (
    <Icon
      aria-label={s.label}
      className={cn(
        "size-4 shrink-0",
        s.spin && "animate-spin motion-reduce:animate-none",
        className,
      )}
      style={{ color: s.color }}
    />
  );
}

export function StepList({
  steps,
  compact,
}: {
  steps: PlanStep[];
  compact?: boolean;
}) {
  return (
    <ol className="relative space-y-0.5">
      {steps.map((s, i) => {
        const who =
          s.agent === "orchestrator"
            ? { name: "Orchestrator", color: "var(--accent-2)" }
            : {
                name: AGENT_IDENTITIES[s.agent].shortName,
                color: TONE_VAR[AGENT_IDENTITIES[s.agent].tone],
              };
        const active = s.status === "running" || s.status === "waiting";
        return (
          <li
            key={s.id}
            className={cn(
              "relative flex gap-3 rounded-[10px] px-2.5 py-2",
              active && "bg-[color-mix(in_oklab,var(--cyan)_7%,transparent)]",
              s.status === "waiting" &&
                "bg-[color-mix(in_oklab,var(--warn)_8%,transparent)]",
              s.status === "failed" &&
                "bg-[color-mix(in_oklab,var(--err)_8%,transparent)]",
            )}
          >
            {i < steps.length - 1 ? (
              <span
                aria-hidden
                className="absolute left-[17.5px] top-7 -bottom-2 w-px bg-line"
              />
            ) : null}
            <span className="relative z-10 mt-0.5 rounded-full bg-card">
              <StepIcon status={s.status} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p
                  className={cn(
                    "text-[13px]",
                    s.status === "pending" || s.status === "skipped"
                      ? "text-fg-3"
                      : "text-fg",
                    active && "font-medium",
                  )}
                >
                  {s.title}
                </p>
                {s.durationSec !== undefined ? (
                  <span className="shrink-0 font-mono text-[11px] text-fg-3">
                    {formatDuration(s.durationSec)}
                  </span>
                ) : null}
              </div>
              {!compact || s.detail ? (
                <div className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-fg-3">
                  {!compact ? (
                    <>
                      <span
                        className="size-1.5 rounded-full"
                        style={{ background: who.color }}
                        aria-hidden
                      />
                      <span>{who.name}</span>
                    </>
                  ) : null}
                  {s.detail ? (
                    <>
                      {!compact ? <span aria-hidden>·</span> : null}
                      <span
                        className={cn(
                          s.status === "failed" && "text-err",
                          s.status === "waiting" && "text-warn",
                        )}
                      >
                        {s.detail}
                      </span>
                    </>
                  ) : null}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/* ── Tool calls ─────────────────────────────────────────────── */

const TOOL_STATUS: Record<
  ToolCall["status"],
  { tone: "ok" | "err" | "cyan" | "warn"; label: string }
> = {
  ok: { tone: "ok", label: "OK" },
  error: { tone: "err", label: "Error" },
  running: { tone: "cyan", label: "Running" },
  blocked: { tone: "warn", label: "Awaiting approval" },
};

export function ToolCallList({
  calls,
  compact,
}: {
  calls: ToolCall[];
  compact?: boolean;
}) {
  if (!calls.length)
    return <p className="px-1 text-[12.5px] text-fg-3">No tool calls yet.</p>;
  return (
    <ul className="space-y-1.5">
      {calls.map((c) => {
        const st = TOOL_STATUS[c.status];
        return (
          <li
            key={c.id}
            className="rounded-[10px] border border-line bg-card-2 px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-mono text-[12.5px] text-fg">
                {c.tool}
              </span>
              <Badge tone={st.tone} live={c.status === "running"}>
                {st.label}
              </Badge>
            </div>
            <div className="mt-1 flex items-center justify-between gap-2 text-[11.5px] text-fg-3">
              <span className="truncate font-mono">{c.input}</span>
              <span className="shrink-0 font-mono">
                {c.durationMs === null
                  ? "—"
                  : c.durationMs >= 1000
                    ? `${(c.durationMs / 1000).toFixed(1)}s`
                    : `${c.durationMs}ms`}
              </span>
            </div>
            {!compact ? (
              <div className="mt-1.5 flex items-center gap-2 text-[11.5px] text-fg-3">
                <span>{AGENT_IDENTITIES[c.agent].shortName}</span>
                <span aria-hidden>·</span>
                <span>+{formatDuration(c.atMs / 1000)}</span>
                <span className="ml-auto">
                  <SideEffectBadge effect={c.sideEffect} />
                </span>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/* ── Artifacts ──────────────────────────────────────────────── */

const ARTIFACT_ICON: Record<Artifact["kind"], LucideIcon> = {
  pdf: FileText,
  docx: FileText,
  md: FileText,
  xlsx: FileSpreadsheet,
  csv: FileSpreadsheet,
  code: FileCode2,
  image: ImageIcon,
};

export function formatSize(kb: number) {
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;
}

const READABLE: Artifact["kind"][] = ["md", "code", "csv"];
const MAX_VIEW_BYTES = 1_000_000;

/** Reads a text deliverable in the page instead of downloading it. The API serves files as attachments,
 *  but a same-origin fetch can still read the body; nothing is rendered as HTML (markdown only). */
function ArtifactViewer({
  artifact,
  onClose,
}: {
  artifact: Artifact;
  onClose: () => void;
}) {
  const [state, setState] = useState<
    { text: string } | { error: string } | null
  >(null);
  const url = `/api/v1/artifacts/${encodeURIComponent(artifact.id)}`;
  useEffect(() => {
    const ctl = new AbortController();
    fetch(url, { signal: ctl.signal, credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`The server answered ${r.status}.`);
        const text = await r.text();
        setState(
          text.length > MAX_VIEW_BYTES
            ? { error: "This file is too large to preview. Use Download." }
            : { text },
        );
      })
      .catch((e: unknown) => {
        if (!ctl.signal.aborted)
          setState({
            error: e instanceof Error ? e.message : "Could not load the file.",
          });
      });
    return () => ctl.abort();
  }, [url]);
  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-[6vh] z-50 flex max-h-[88vh] w-[min(860px,calc(100vw-2rem))] -translate-x-1/2 flex-col rounded-[16px] border border-line bg-card shadow-[var(--shadow)]">
          <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
            <Dialog.Title className="truncate text-[14px] font-semibold">
              {artifact.name}
            </Dialog.Title>
            <Dialog.Description className="sr-only">
              Preview of {artifact.name}
            </Dialog.Description>
            <div className="flex items-center gap-1">
              {state && "text" in state ? (
                <CopyButton text={state.text} />
              ) : null}
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Download ${artifact.name}`}
                className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card-2 hover:text-fg"
              >
                <Download className="size-4" />
              </a>
              <Dialog.Close
                aria-label="Close preview"
                className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card-2 hover:text-fg"
              >
                <X className="size-4" />
              </Dialog.Close>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
            {state === null ? (
              <p className="flex items-center gap-2 text-[13px] text-fg-3">
                <Loader2 className="size-4 animate-spin" /> Loading…
              </p>
            ) : "error" in state ? (
              <p className="text-[13px] text-fg-2">{state.error}</p>
            ) : artifact.kind === "md" ? (
              <div className="af-prose max-w-none text-[14px]">
                <Markdown>{state.text}</Markdown>
              </div>
            ) : (
              <pre className="whitespace-pre-wrap break-words font-mono text-[12.5px] text-fg-2">
                {state.text}
              </pre>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ArtifactList({ artifacts }: { artifacts: Artifact[] }) {
  const toast = useToast();
  const [viewing, setViewing] = useState<Artifact | null>(null);
  if (!artifacts.length)
    return <p className="px-1 text-[12.5px] text-fg-3">No deliverables yet.</p>;
  return (
    <>
      {viewing ? (
        <ArtifactViewer artifact={viewing} onClose={() => setViewing(null)} />
      ) : null}
      <ul className="space-y-1.5">
        {artifacts.map((a) => {
          const Icon = ARTIFACT_ICON[a.kind];
          return (
            <li
              key={a.id}
              className="group flex items-center gap-3 rounded-[10px] border border-line bg-card-2 px-3 py-2"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-[8px] border border-line bg-card text-accent">
                <Icon className="size-4" strokeWidth={1.8} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] text-fg">{a.name}</p>
                <p className="text-[11.5px] text-fg-3">
                  {formatSize(a.sizeKb)} · {AGENT_IDENTITIES[a.agent].shortName}{" "}
                  · <TimeAgo secondsAgo={a.createdSecondsAgo} />
                </p>
              </div>
              {LIVE_DATA && READABLE.includes(a.kind) ? (
                <button
                  type="button"
                  onClick={() => setViewing(a)}
                  aria-label={`Read ${a.name}`}
                  className="flex h-8 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium text-accent hover:bg-card"
                >
                  <Eye className="size-4" /> Read
                </button>
              ) : null}
              {LIVE_DATA ? (
                // Served by the API through the BFF: org-scoped, nosniff, sandboxed CSP, attachment unless an image.
                <a
                  href={`/api/v1/artifacts/${encodeURIComponent(a.id)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Download ${a.name}`}
                  className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card hover:text-fg"
                >
                  <Download className="size-4" />
                </a>
              ) : (
                <button
                  type="button"
                  aria-label={`Download ${a.name}`}
                  onClick={() =>
                    toast({
                      tone: "info",
                      title: "Demo mode",
                      description: "Downloads work with the live API.",
                    })
                  }
                  className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-card hover:text-fg"
                >
                  <Download className="size-4" />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}

/* ── Approvals ──────────────────────────────────────────────── */

export function ApprovalCard({
  approval,
  onDecided,
}: {
  approval: ApprovalRequest;
  onDecided?: (status: ApprovalRequest["status"]) => void;
}) {
  const toast = useToast();
  const [status, setStatus] = useState(approval.status);
  const [busy, setBusy] = useState<"approved" | "rejected" | null>(null);

  const decide = async (decision: "approved" | "rejected") => {
    setBusy(decision);
    try {
      const next = await api.approvals.decide(approval.id, decision);
      setStatus(next);
      onDecided?.(next);
      toast({
        tone: decision === "approved" ? "success" : "warning",
        title:
          decision === "approved"
            ? "Approved — execution resumes"
            : "Rejected — agent will re-plan",
        description: approval.title,
      });
    } catch (e) {
      // e.g. 403: approving a financial action needs billing:manage — the server decides, not the UI.
      toast({
        tone: "error",
        title: "Couldn't record your decision",
        description: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setBusy(null);
    }
  };

  const severe =
    approval.sideEffect === "financial" ||
    approval.sideEffect === "destructive";

  return (
    <div
      className={cn(
        "rounded-[12px] border p-3.5",
        status === "pending"
          ? "border-[color-mix(in_oklab,var(--warn)_45%,var(--border))] bg-[color-mix(in_oklab,var(--warn)_6%,var(--card))]"
          : "border-line bg-card-2",
      )}
    >
      <div className="flex items-start gap-2.5">
        {status === "approved" ? (
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" />
        ) : status === "rejected" ? (
          <ShieldX className="mt-0.5 size-4 shrink-0 text-err" />
        ) : (
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[13.5px] font-medium text-fg">
              {approval.title}
            </p>
            <SideEffectBadge effect={approval.sideEffect} />
          </div>
          <p className="mt-1 text-[12.5px] text-fg-2">{approval.reason}</p>
          {approval.preview ? (
            <p className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-[8px] border border-line bg-card px-2.5 py-2 text-[12.5px] text-fg-2">
              {approval.preview}
            </p>
          ) : null}
          <p className="mt-2 text-[11.5px] text-fg-3">
            Requested by {AGENT_IDENTITIES[approval.agent].shortName} ·{" "}
            <TimeAgo secondsAgo={approval.requestedSecondsAgo} /> ·{" "}
            <span className="font-mono">{approval.executionId}</span>
          </p>
          {status === "pending" ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant={severe ? "danger" : "primary"}
                disabled={busy !== null}
                onClick={() => decide("approved")}
              >
                {busy === "approved" ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ShieldCheck className="size-3.5" />
                )}
                Approve
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy !== null}
                onClick={() => decide("rejected")}
              >
                {busy === "rejected" ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ShieldX className="size-3.5" />
                )}
                Reject
              </Button>
            </div>
          ) : (
            <p
              className={cn(
                "mt-2 text-[12px] font-medium",
                status === "approved" ? "text-ok" : "text-err",
              )}
            >
              {status === "approved" ? "Approved by you" : "Rejected by you"}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function PanelEmpty({
  icon: Icon = CircleDashed,
  title,
  body,
}: {
  icon?: LucideIcon;
  title: string;
  body?: string;
}) {
  return (
    <div className="flex flex-col items-center rounded-[12px] border border-dashed border-line px-4 py-8 text-center">
      <Icon className="size-5 text-fg-3" strokeWidth={1.6} />
      <p className="mt-2 text-[13px] font-medium text-fg-2">{title}</p>
      {body ? (
        <p className="mt-1 max-w-[240px] text-[12px] text-fg-3">{body}</p>
      ) : null}
    </div>
  );
}
