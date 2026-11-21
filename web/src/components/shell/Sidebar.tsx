"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as Tooltip from "@radix-ui/react-tooltip";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ChevronsLeft, ChevronsUpDown, Check, Plus, Sparkles } from "lucide-react";
import { NAV, type NavItem } from "./nav";
import { Wordmark } from "./Logo";
import { cn } from "@/lib/cn";
import { initials, switchOrganization, type Me } from "@/lib/session-client";
import { LIVE_DATA } from "@/lib/mode";

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate?: () => void;
  /** From the server session; the API enforces it independently. */
  isSuperAdmin: boolean;
  me: Me | null;
}

export function Sidebar({ collapsed, onToggleCollapsed, onNavigate, isSuperAdmin, me }: SidebarProps) {
  const pathname = usePathname();

  return (
    <Tooltip.Provider delayDuration={150}>
      <nav aria-label="Primary" className="flex h-full flex-col">
        <div className={cn("flex h-16 shrink-0 items-center px-4", collapsed && "justify-center px-0")}>
          <Link href="/" onClick={onNavigate} aria-label="AgentFirm home">
            <Wordmark collapsed={collapsed} />
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 pb-4">
          {NAV.filter((s) => !s.requiresSuperAdmin || isSuperAdmin).map((section) => (
            <div key={section.title} className="mt-5 first:mt-2">
              {collapsed ? (
                <div className="mx-auto mb-2 h-px w-6 bg-line" />
              ) : (
                <div className="af-label mb-2 px-2.5">{section.title}</div>
              )}
              <ul className="space-y-0.5">
                {section.items.map((item) => (
                  <li key={item.href}>
                    <NavLink item={item} collapsed={collapsed} pathname={pathname} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Plan / credits — illustrative in demo mode only; real balances arrive with billing (Phase 6). */}
        {collapsed || LIVE_DATA ? null : (
          <div className="mx-3 mb-3 rounded-[12px] border border-line bg-card-2 p-3">
            <div className="flex items-center justify-between text-[12px]">
              <span className="flex items-center gap-1.5 font-medium text-fg">
                <Sparkles className="size-3.5 text-accent-2" /> Growth plan
              </span>
              <span className="font-mono text-fg-2">64%</span>
            </div>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-[color-mix(in_oklab,var(--fg-3)_18%,transparent)]">
              <div className="h-full w-[64%] rounded-full bg-[linear-gradient(90deg,var(--accent),var(--accent-2))]" />
            </div>
            <div className="mt-1.5 text-[11px] text-fg-3">
              <span className="font-mono">6,420</span> of <span className="font-mono">10,000</span> credits left
            </div>
          </div>
        )}

        <div className={cn("border-t border-line p-3", collapsed && "px-2")}>
          <WorkspaceMenu collapsed={collapsed} me={me} />
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="mt-2 hidden h-8 w-full items-center justify-center gap-2 rounded-[8px] text-[12px] text-fg-3 transition-colors hover:bg-card-2 hover:text-fg lg:flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <ChevronsLeft className={cn("size-4 transition-transform", collapsed && "rotate-180")} />
            {collapsed ? null : "Collapse"}
          </button>
        </div>
      </nav>
    </Tooltip.Provider>
  );
}

function NavLink({ item, collapsed, pathname, onNavigate }: { item: NavItem; collapsed: boolean; pathname: string; onNavigate?: () => void }) {
  const active = item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`);
  const Icon = item.icon;
  const link = (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-9 items-center gap-3 rounded-[9px] px-2.5 text-[13.5px] transition-colors",
        collapsed && "justify-center px-0",
        active ? "bg-card-2 text-fg" : "text-fg-2 hover:bg-card-2/70 hover:text-fg",
      )}
    >
      {active ? (
        <span aria-hidden className="absolute -left-3 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-[linear-gradient(var(--accent),var(--accent-2))]" />
      ) : null}
      <Icon className={cn("size-[17px] shrink-0", active ? "text-accent" : "text-fg-3 group-hover:text-fg-2")} strokeWidth={1.8} />
      {collapsed ? null : <span className="truncate">{item.label}</span>}
      {!collapsed && item.badge && !LIVE_DATA ? (
        <span className="ml-auto rounded-md bg-[color-mix(in_oklab,var(--cyan)_14%,transparent)] px-1.5 font-mono text-[11px] text-cyan">{item.badge}</span>
      ) : null}
    </Link>
  );
  if (!collapsed) return link;
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="right" sideOffset={10} className="z-50 rounded-md border border-line bg-card px-2 py-1 text-[12px] text-fg shadow-[var(--shadow)]">
          {item.label}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function WorkspaceMenu({ collapsed, me }: { collapsed: boolean; me: Me | null }) {
  const name = me?.user.name ?? "Demo User";
  const orgName = me?.organization?.name ?? (me ? "No workspace" : "Northwind Labs");
  const role = me?.role ?? (me ? "" : "owner");
  const workspaces = me ? me.memberships.map((m) => ({ id: m.organization.id, name: m.organization.name, role: m.role })) : [
    { id: "demo-1", name: "Northwind Labs", role: "owner" },
    { id: "demo-2", name: "Personal", role: "owner" },
  ];
  const currentId = me?.organization?.id ?? "demo-1";

  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button
          type="button"
          className={cn(
            "flex w-full items-center gap-2.5 rounded-[10px] p-1.5 text-left transition-colors hover:bg-card-2",
            collapsed && "justify-center",
          )}
          aria-label="Switch workspace or open account menu"
        >
          <span className="grid size-8 shrink-0 place-items-center rounded-[9px] bg-[linear-gradient(135deg,var(--accent),var(--accent-2))] text-[12px] font-semibold text-white">
            {initials(name)}
          </span>
          {collapsed ? null : (
            <>
              <span className="min-w-0 flex-1 leading-tight">
                <span className="block truncate text-[13px] font-medium">{name}</span>
                <span className="block truncate text-[11.5px] capitalize text-fg-3">
                  {orgName}
                  {role ? ` · ${role}` : ""}
                </span>
              </span>
              <ChevronsUpDown className="size-4 text-fg-3" />
            </>
          )}
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content side="top" align="start" sideOffset={8} className="z-50 w-64 rounded-[12px] border border-line bg-card p-1.5 shadow-[var(--shadow)]">
          <div className="af-label px-2 py-1.5">Workspaces</div>
          {workspaces.map((w) => (
            <Dropdown.Item
              key={w.id}
              onSelect={async () => {
                if (!me || w.id === currentId) return;
                if (await switchOrganization(w.id)) window.location.assign("/");
              }}
              className="flex h-9 cursor-pointer items-center gap-2 rounded-md px-2 text-[13px] outline-none data-[highlighted]:bg-card-2"
            >
              <span className="grid size-5 place-items-center rounded bg-card-2 text-[10px] font-semibold text-fg-2">{w.name[0]}</span>
              <span className="min-w-0 flex-1 truncate">{w.name}</span>
              <span className="text-[11px] capitalize text-fg-3">{w.role}</span>
              {w.id === currentId ? <Check className="size-3.5 text-accent" /> : null}
            </Dropdown.Item>
          ))}
          <Dropdown.Separator className="my-1 h-px bg-line" />
          <Dropdown.Item className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 text-[13px] text-fg-2 outline-none data-[highlighted]:bg-card-2">
            <Plus className="size-3.5" /> Create workspace
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}
