"use client";

import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import * as Select from "@radix-ui/react-select";
import { Bell, Building2, Check, ChevronDown, KeyRound, Laptop, Megaphone, Monitor, Moon, Palette, Shield, ShieldCheck, Smartphone, Sun, UserPlus, Users } from "lucide-react";
import type { Member, OrgRole } from "@/lib/types";
import { applyThemePreference, type ThemePreference } from "@/lib/theme";
import { useThemePreference } from "@/lib/stores";
import { cn } from "@/lib/cn";
import { Badge, Button, Card, DemoBadge } from "@/components/ui/primitives";
import { Switch } from "@/components/ui/Switch";
import { TimeAgo } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { LiveBoundary } from "@/lib/live";
import { StandingApprovals } from "./StandingApprovals";

const ROLES: Record<OrgRole, string> = {
  owner: "Full control, billing and deletion",
  admin: "Manage members, agents, integrations",
  member: "Create tasks, approve own agents' actions",
  viewer: "Read-only access to results",
};

const TABS = [
  { v: "general", l: "General", icon: Building2 },
  { v: "members", l: "Members & roles", icon: Users },
  { v: "brand", l: "Brand voice", icon: Megaphone },
  { v: "appearance", l: "Appearance", icon: Palette },
  { v: "notifications", l: "Notifications", icon: Bell },
  { v: "security", l: "Security", icon: Shield },
  { v: "approvals", l: "Standing approvals", icon: ShieldCheck },
] as const;

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 py-4 sm:grid-cols-[220px_minmax(0,1fr)] sm:gap-6">
      <div>
        <p className="text-[13.5px] font-medium">{label}</p>
        {hint ? <p className="mt-0.5 text-[12px] text-fg-3">{hint}</p> : null}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

const input = "h-9 w-full max-w-md rounded-[10px] border border-line bg-card-2 px-3 text-[13.5px] outline-none focus:border-accent";

function RoleSelect({ value, onChange, disabled, label }: { value: OrgRole; onChange: (r: OrgRole) => void; disabled?: boolean; label: string }) {
  return (
    <Select.Root value={value} onValueChange={(v) => onChange(v as OrgRole)} disabled={disabled}>
      <Select.Trigger aria-label={label} className="flex h-8 w-[120px] items-center justify-between rounded-[9px] border border-line bg-card-2 px-2.5 text-[12.5px] capitalize outline-none hover:border-line-strong disabled:opacity-60">
        <Select.Value />
        <Select.Icon>
          <ChevronDown className="size-3.5 text-fg-3" />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content position="popper" sideOffset={4} className="z-50 w-64 rounded-[12px] border border-line bg-card p-1.5 shadow-[var(--shadow)]">
          <Select.Viewport>
            {(Object.keys(ROLES) as OrgRole[]).map((r) => (
              <Select.Item key={r} value={r} className="relative cursor-pointer rounded-md py-1.5 pl-2 pr-7 outline-none data-[highlighted]:bg-card-2">
                <Select.ItemText>
                  <span className="text-[13px] capitalize">{r}</span>
                </Select.ItemText>
                <p className="text-[11.5px] text-fg-3">{ROLES[r]}</p>
                <Select.ItemIndicator className="absolute right-2 top-2">
                  <Check className="size-3.5 text-accent" />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

export function SettingsView({ members: initialMembers, demo }: { members: Member[]; demo: boolean }) {
  const toast = useToast();
  const pref = useThemePreference();
  const [members, setMembers] = useState(initialMembers);
  const [invite, setInvite] = useState({ email: "", role: "member" as OrgRole });
  const [tones, setTones] = useState(["Confident", "Warm", "Plain language"]);
  const [notif, setNotif] = useState<Record<string, { email: boolean; app: boolean }>>({
    "Approval requested": { email: true, app: true },
    "Task completed": { email: false, app: true },
    "Task failed": { email: true, app: true },
    "Usage alert": { email: true, app: true },
    "Weekly digest": { email: true, app: false },
  });

  const saved = (what: string) => toast({ tone: "success", title: `${what} saved`, description: demo ? "Demo mode — stored locally for this session only." : undefined });

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <h2 className="text-[22px] font-semibold tracking-tight">Settings</h2>
        {demo ? <DemoBadge /> : null}
      </div>

      <Tabs.Root defaultValue="general" orientation="vertical" className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <Tabs.List className="flex gap-1 overflow-x-auto lg:flex-col" aria-label="Settings sections">
          {TABS.map(({ v, l, icon: Icon }) => (
            <Tabs.Trigger
              key={v}
              value={v}
              className="flex h-9 shrink-0 items-center gap-2.5 rounded-[9px] px-3 text-left text-[13.5px] text-fg-2 outline-none hover:bg-card-2 hover:text-fg data-[state=active]:bg-card-2 data-[state=active]:text-fg"
            >
              <Icon className="size-4 text-fg-3" /> {l}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <div className="min-w-0">
          <Tabs.Content value="general">
            <Card className="px-5 py-1">
              <div className="divide-y divide-[var(--border)]">
                <Field label="Workspace name" hint="Shown to members and in invoices">
                  <input className={input} defaultValue="Northwind Labs" aria-label="Workspace name" />
                </Field>
                <Field label="Workspace URL" hint="Lowercase letters, numbers and dashes">
                  <div className="flex max-w-md items-center rounded-[10px] border border-line bg-card-2 pl-3 text-[13.5px] focus-within:border-accent">
                    <span className="text-fg-3">agentfirm.app/</span>
                    <input className="h-9 min-w-0 flex-1 bg-transparent pr-3 outline-none" defaultValue="northwind" aria-label="Workspace URL slug" />
                  </div>
                </Field>
                <Field label="Default agent selection" hint="For new tasks without explicit agents">
                  <div className="flex flex-wrap gap-2">
                    {["Auto-select (orchestrator)", "Ask me every time"].map((o, i) => (
                      <label key={o} className="flex cursor-pointer items-center gap-2 rounded-[10px] border border-line px-3 py-2 text-[13px] has-[:checked]:border-accent has-[:checked]:bg-[color-mix(in_oklab,var(--accent)_8%,transparent)]">
                        <input type="radio" name="agent-select" defaultChecked={i === 0} className="accent-[var(--accent)]" /> {o}
                      </label>
                    ))}
                  </div>
                </Field>
                <Field label="Default project" hint="Optional">
                  <input className={input} defaultValue="Tutoring launch" aria-label="Default project" />
                </Field>
              </div>
              <div className="flex justify-end border-t border-line py-4">
                <Button variant="primary" onClick={() => saved("Workspace settings")}>
                  Save changes
                </Button>
              </div>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="members" className="space-y-5">
            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">Invite a member</h3>
              <form
                className="mt-3 flex flex-col gap-2 sm:flex-row"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!invite.email.includes("@")) return;
                  setMembers((m) => [...m, { id: `inv-${m.length}`, name: "", email: invite.email, role: invite.role, lastActiveSecondsAgo: 0, status: "invited" }]);
                  toast({ tone: "success", title: "Invitation queued", description: `${invite.email} · ${invite.role}${demo ? " (demo — no email sent)" : ""}` });
                  setInvite({ email: "", role: "member" });
                }}
              >
                <input type="email" required value={invite.email} onChange={(e) => setInvite((i) => ({ ...i, email: e.target.value }))} placeholder="name@company.com" className={cn(input, "max-w-none flex-1")} aria-label="Email address" />
                <RoleSelect value={invite.role} onChange={(r) => setInvite((i) => ({ ...i, role: r }))} label="Role for invitee" />
                <Button type="submit" variant="primary">
                  <UserPlus className="size-4" /> Invite
                </Button>
              </form>
            </Card>
            <Card className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-[13px]">
                  <thead>
                    <tr className="border-b border-line bg-card-2 text-left text-[11px] font-semibold uppercase tracking-wider text-fg-3">
                      <th className="px-5 py-2.5">Member</th>
                      <th className="px-3 py-2.5">Role</th>
                      <th className="px-3 py-2.5">Last active</th>
                      <th className="px-5 py-2.5" />
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((m) => (
                      <tr key={m.id} className="border-b border-line last:border-0">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2.5">
                            <span className="grid size-8 place-items-center rounded-full bg-card-2 text-[11.5px] font-semibold text-fg-2 ring-1 ring-line">
                              {(m.name || m.email).split(/\s|@/).map((x) => x[0]).slice(0, 2).join("").toUpperCase()}
                            </span>
                            <div className="min-w-0">
                              <p className="truncate">{m.name || <span className="text-fg-3">Pending invite</span>}</p>
                              <p className="truncate text-[12px] text-fg-3">{m.email}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <RoleSelect
                            value={m.role}
                            disabled={m.role === "owner"}
                            label={`Role for ${m.name || m.email}`}
                            onChange={(r) => {
                              setMembers((xs) => xs.map((x) => (x.id === m.id ? { ...x, role: r } : x)));
                              toast({ tone: "success", title: "Role updated", description: `${m.name || m.email} is now ${r}. Recorded in the audit log.` });
                            }}
                          />
                        </td>
                        <td className="px-3 py-3 text-fg-2">{m.status === "invited" ? <Badge tone="warn">Invited</Badge> : <TimeAgo secondsAgo={m.lastActiveSecondsAgo} />}</td>
                        <td className="px-5 py-3 text-right">
                          {m.role !== "owner" ? (
                            <button type="button" className="text-[12.5px] text-fg-3 hover:text-err" onClick={() => setMembers((xs) => xs.filter((x) => x.id !== m.id))}>
                              Remove
                            </button>
                          ) : (
                            <span className="text-[12px] text-fg-3">Owner</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="border-t border-line px-5 py-3 text-[12px] text-fg-3">Roles are enforced by the API on every request and every change is written to the audit log.</p>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="brand">
            <Card className="px-5 py-1">
              <div className="divide-y divide-[var(--border)]">
                <Field label="Tone of voice" hint="Used by Marketing and Assistant agents">
                  <div className="flex flex-wrap gap-1.5">
                    {["Confident", "Warm", "Plain language", "Playful", "Formal", "Technical", "Bold"].map((t) => {
                      const on = tones.includes(t);
                      return (
                        <button key={t} type="button" aria-pressed={on} onClick={() => setTones((x) => (on ? x.filter((y) => y !== t) : [...x, t]))} className={cn("h-8 rounded-full border px-3 text-[12.5px]", on ? "border-accent bg-[color-mix(in_oklab,var(--accent)_12%,transparent)] text-fg" : "border-line text-fg-2")}>
                          {t}
                        </button>
                      );
                    })}
                  </div>
                </Field>
                <Field label="Languages" hint="Agents write in the request's language when supported">
                  <input className={input} defaultValue="English, Spanish, German" aria-label="Languages" />
                </Field>
                <Field label="Avoid" hint="Words or claims agents must not use">
                  <textarea rows={3} className="w-full max-w-md rounded-[10px] border border-line bg-card-2 px-3 py-2 text-[13.5px] outline-none focus:border-accent" defaultValue={"revolutionary\nguaranteed results\nAI-powered (in headlines)"} aria-label="Phrases to avoid" />
                </Field>
                <Field label="Sample" hint="A short example in your voice">
                  <textarea rows={3} className="w-full max-w-md rounded-[10px] border border-line bg-card-2 px-3 py-2 text-[13.5px] outline-none focus:border-accent" defaultValue="Learning English shouldn't feel like homework. Real tutors, short sessions, progress you can see." aria-label="Voice sample" />
                </Field>
              </div>
              <div className="flex justify-end border-t border-line py-4">
                <Button variant="primary" onClick={() => saved("Brand voice")}>
                  Save brand voice
                </Button>
              </div>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="appearance">
            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">Theme</h3>
              <p className="mt-0.5 text-[12.5px] text-fg-2">Saved in this browser. “System” follows your operating system.</p>
              <div className="mt-4 grid max-w-xl grid-cols-3 gap-3" role="radiogroup" aria-label="Theme">
                {[
                  { v: "system" as ThemePreference, l: "System", icon: Monitor },
                  { v: "dark" as ThemePreference, l: "Dark", icon: Moon },
                  { v: "light" as ThemePreference, l: "Light", icon: Sun },
                ].map(({ v, l, icon: Icon }) => {
                  const on = pref === v;
                  return (
                    <button
                      key={v}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => applyThemePreference(v)}
                      className={cn("rounded-[12px] border p-3 text-left transition-colors", on ? "border-accent shadow-[var(--glow)]" : "border-line hover:border-line-strong")}
                    >
                      <div
                        className={cn(
                          "h-16 rounded-[8px] border border-line",
                          v === "dark" && "bg-[#090B12]",
                          v === "light" && "bg-[#F5F7FC]",
                          v === "system" && "bg-[linear-gradient(135deg,#F5F7FC_50%,#090B12_50%)]",
                        )}
                      />
                      <div className="mt-2 flex items-center gap-1.5 text-[13px]">
                        <Icon className="size-3.5 text-fg-3" /> {l}
                        {on ? <Check className="ml-auto size-3.5 text-accent" /> : null}
                      </div>
                    </button>
                  );
                })}
              </div>
              <p className="mt-5 text-[12.5px] text-fg-3">Animations automatically reduce when your system has “Reduce motion” turned on.</p>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="notifications">
            <Card className="overflow-hidden">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b border-line bg-card-2 text-left text-[11px] font-semibold uppercase tracking-wider text-fg-3">
                    <th className="px-5 py-2.5">Event</th>
                    <th className="w-24 px-3 py-2.5 text-center">In-app</th>
                    <th className="w-24 px-5 py-2.5 text-center">Email</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(notif).map(([k, v]) => (
                    <tr key={k} className="border-b border-line last:border-0">
                      <td className="px-5 py-3">{k}</td>
                      <td className="px-3 py-3 text-center">
                        <Switch checked={v.app} label={`${k} in-app`} onCheckedChange={(x) => setNotif((n) => ({ ...n, [k]: { ...n[k], app: x } }))} className="mx-auto" />
                      </td>
                      <td className="px-5 py-3 text-center">
                        <Switch checked={v.email} label={`${k} email`} onCheckedChange={(x) => setNotif((n) => ({ ...n, [k]: { ...n[k], email: x } }))} className="mx-auto" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </Tabs.Content>

          <Tabs.Content value="approvals">
            {demo ? (
              <Card className="p-5 text-[13px] text-fg-2">Standing approvals need the live API.</Card>
            ) : (
              <LiveBoundary>
                <StandingApprovals />
              </LiveBoundary>
            )}
          </Tabs.Content>

          <Tabs.Content value="security" className="space-y-5">
            <Card className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-[15px] font-semibold">Two-step verification</h3>
                  <p className="mt-0.5 text-[12.5px] text-fg-2">Required for owners and admins on this workspace.</p>
                </div>
                <Badge tone="ok">Enabled</Badge>
              </div>
            </Card>
            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">Active sessions</h3>
              <ul className="mt-3 divide-y divide-[var(--border)]">
                {[
                  { icon: Laptop, d: "Chrome · macOS", where: "Berlin, DE", now: true },
                  { icon: Smartphone, d: "Safari · iOS", where: "Berlin, DE", now: false },
                ].map((s) => (
                  <li key={s.d} className="flex items-center justify-between gap-3 py-3 text-[13px]">
                    <span className="flex items-center gap-2.5">
                      <s.icon className="size-4 text-fg-3" /> {s.d} <span className="text-fg-3">· {s.where}</span>
                    </span>
                    {s.now ? <Badge tone="accent">This device</Badge> : <button type="button" className="text-[12.5px] text-fg-3 hover:text-err">Sign out</button>}
                  </li>
                ))}
              </ul>
            </Card>
            <Card className="p-5">
              <h3 className="flex items-center gap-1.5 text-[15px] font-semibold">
                <KeyRound className="size-4 text-fg-3" /> Provider API keys
              </h3>
              <p className="mt-1 text-[12.5px] text-fg-2">Model provider keys are managed by platform admins, encrypted at rest and never sent to browsers.</p>
            </Card>
          </Tabs.Content>
        </div>
      </Tabs.Root>
    </div>
  );
}
