"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, ArrowRight, Eye, EyeOff, KeyRound, Loader2, Lock, ShieldCheck, Users } from "lucide-react";
import { LogoMark } from "@/components/shell/Logo";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { AgentCollaborationCore } from "@/components/agent/AgentCollaborationCore";
import { cn } from "@/lib/cn";

type Mode = "signin" | "register";

const ERRORS: Record<string, string> = {
  invalid_credentials: "Email or password is incorrect.",
  account_locked: "Too many failed attempts. Try again in 15 minutes.",
  rate_limited: "Too many attempts. Please wait a minute.",
  weak_password: "",
  email_taken: "An account with this email already exists. Sign in instead.",
  csrf: "Your request was blocked. Reload the page and try again.",
};

const field = "h-11 w-full rounded-[11px] border border-line bg-card-2 px-3.5 text-[14px] outline-none transition-colors placeholder:text-fg-3 focus:border-accent focus:shadow-[var(--glow)]";

export function SignIn({ live }: { live: boolean }) {
  const [mode, setMode] = useState<Mode>("signin");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState(false);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    if (!live) {
      setError("This build runs on demo data. Start the API and set NEXT_PUBLIC_AGENTFIRM_AUTH=api to sign in.");
      return;
    }
    const data = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    setBusy(true);
    try {
      const r = await fetch(mode === "signin" ? "/api/auth/login" : "/api/auth/register", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          mode === "signin"
            ? { email: data.email, password: data.password }
            : { email: data.email, password: data.password, name: data.name, organization_name: data.organization },
        ),
      });
      if (!r.ok) {
        const p = (await r.json().catch(() => ({}))) as { title?: string; detail?: unknown };
        const detail = typeof p.detail === "string" ? p.detail : null;
        setError((p.title && ERRORS[p.title]) || detail || "Something went wrong. Please try again.");
        return;
      }
      const next = new URLSearchParams(window.location.search).get("next");
      // Only same-site relative paths — never an open redirect.
      window.location.assign(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch {
      setError("Can't reach AgentFirm. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      {/* Brand panel */}
      <aside className="relative hidden overflow-hidden border-r border-line bg-bg-2/60 lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div aria-hidden className="pointer-events-none absolute -left-32 top-1/4 size-[520px] rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent)_18%,transparent),transparent)]" />
        <div aria-hidden className="pointer-events-none absolute -right-24 bottom-0 size-[440px] rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--accent-2)_16%,transparent),transparent)]" />
        <div className="relative flex items-center gap-3">
          <LogoMark className="size-9" />
          <span className="text-[17px] font-semibold tracking-tight">AgentFirm</span>
        </div>
        <div className="relative">
          <AgentCollaborationCore
            size={440}
            participants={[
              { agent: "research", state: "done", subtask: "" },
              { agent: "bi", state: "done", subtask: "" },
              { agent: "creative", state: "active", subtask: "" },
              { agent: "marketing", state: "pending", subtask: "" },
              { agent: "engineer", state: "pending", subtask: "" },
              { agent: "assistant", state: "pending", subtask: "" },
            ]}
          />
          <h1 className="mt-8 max-w-md text-[34px] font-semibold leading-[1.1] tracking-tight">
            <span className="af-gradient-text">Your AI team.</span> Ready to work.
          </h1>
          <p className="mt-3 max-w-md text-[15px] text-fg-2">Six specialised agents, one orchestrator, and you in control of every action that matters.</p>
        </div>
        <ul className="relative grid gap-3 text-[13px] text-fg-2">
          {[
            { icon: ShieldCheck, t: "Workspace data isolated at the database level" },
            { icon: KeyRound, t: "Tokens stay server-side — never in your browser's JavaScript" },
            { icon: Users, t: "Roles, approvals and a tamper-proof audit trail" },
          ].map(({ icon: Icon, t }) => (
            <li key={t} className="flex items-center gap-2.5">
              <Icon className="size-4 text-accent" /> {t}
            </li>
          ))}
        </ul>
      </aside>

      {/* Form */}
      <main className="flex flex-col px-5 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5 lg:invisible">
            <LogoMark />
            <span className="text-[15px] font-semibold">AgentFirm</span>
          </div>
          <ThemeToggle />
        </div>

        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-10">
          <h2 className="text-[26px] font-semibold tracking-tight">{mode === "signin" ? "Welcome back" : "Create your workspace"}</h2>
          <p className="mt-1.5 text-[14px] text-fg-2">
            {mode === "signin" ? "Sign in to your AI workforce." : "You'll be the owner. Invite your team afterwards."}
          </p>

          <div className="mt-6 grid grid-cols-2 rounded-[11px] border border-line bg-card-2 p-1" role="tablist" aria-label="Sign in or register">
            {(["signin", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => {
                  setMode(m);
                  setError(null);
                }}
                className={cn("h-8 rounded-[8px] text-[13px] font-medium transition-colors", mode === m ? "bg-card text-fg shadow-[var(--shadow)]" : "text-fg-3 hover:text-fg-2")}
              >
                {m === "signin" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          {!live ? (
            <div className="mt-4 rounded-[11px] border border-dashed border-line-strong bg-card-2 px-3.5 py-3 text-[12.5px] text-fg-2">
              Demo build — no backend connected.{" "}
              <Link href="/" className="font-medium text-accent hover:underline">
                Continue to the demo →
              </Link>
            </div>
          ) : null}

          <form onSubmit={submit} className="mt-5 space-y-3.5" noValidate={false}>
            <AnimatePresence initial={false}>
              {mode === "register" ? (
                <motion.div key="reg" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="space-y-3.5 overflow-hidden">
                  <label className="block">
                    <span className="mb-1.5 block text-[12.5px] font-medium text-fg-2">Your name</span>
                    <input name="name" required autoComplete="name" className={field} placeholder="Ada Lovelace" />
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-[12.5px] font-medium text-fg-2">Workspace name</span>
                    <input name="organization" required minLength={2} autoComplete="organization" className={field} placeholder="Northwind Labs" />
                  </label>
                </motion.div>
              ) : null}
            </AnimatePresence>
            <label className="block">
              <span className="mb-1.5 block text-[12.5px] font-medium text-fg-2">Work email</span>
              <input name="email" type="email" required autoComplete="email" className={field} placeholder="you@company.com" />
            </label>
            <label className="block">
              <span className="mb-1.5 flex items-center justify-between text-[12.5px] font-medium text-fg-2">
                Password
                {mode === "signin" ? <span className="text-fg-3">Forgot? Ask a workspace admin</span> : null}
              </span>
              <span className="relative block">
                <input
                  name="password"
                  type={show ? "text" : "password"}
                  required
                  minLength={mode === "register" ? 12 : 1}
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  className={cn(field, "pr-11")}
                  placeholder={mode === "register" ? "At least 12 characters" : "••••••••••••"}
                />
                <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"} className="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-fg-3 hover:text-fg">
                  {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </span>
              {mode === "register" ? <span className="mt-1.5 block text-[11.5px] text-fg-3">12+ characters, not containing your email name.</span> : null}
            </label>

            <AnimatePresence>
              {error ? (
                <motion.p
                  role="alert"
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="flex items-start gap-2 rounded-[10px] border border-[color-mix(in_oklab,var(--err)_35%,transparent)] bg-[color-mix(in_oklab,var(--err)_8%,transparent)] px-3 py-2.5 text-[13px] text-fg"
                >
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-err" /> {error}
                </motion.p>
              ) : null}
            </AnimatePresence>

            <button
              type="submit"
              disabled={busy}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-[11px] bg-[linear-gradient(135deg,var(--accent),color-mix(in_oklab,var(--accent)_55%,var(--accent-2)))] text-[14px] font-medium text-white shadow-[0_8px_24px_-10px_var(--accent)] transition-[filter] hover:brightness-110 disabled:opacity-60"
            >
              {busy ? <Loader2 className="size-4 animate-spin" /> : null}
              {mode === "signin" ? "Sign in" : "Create workspace"}
              {!busy ? <ArrowRight className="size-4" /> : null}
            </button>
          </form>

          <p className="mt-6 flex items-center justify-center gap-1.5 text-[12px] text-fg-3">
            <Lock className="size-3.5" /> Secured by AgentFirm sign-in · argon2id · rotating sessions
          </p>
        </div>
      </main>
    </div>
  );
}
