"use client";

import Link from "next/link";
import { LIVE_DATA } from "@/lib/mode";
import { usePathname } from "next/navigation";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Bell, ChevronRight, Menu, Plus, Search, LogOut, User, KeyRound } from "lucide-react";
import { findNavItem } from "./nav";
import { ThemeToggle } from "./ThemeToggle";
import { Button, Kbd } from "@/components/ui/primitives";
import { NewTaskDialog } from "@/components/tasks/NewTaskDialog";
import { initials, type Me } from "@/lib/session-client";

export function Topbar({ onOpenMobileNav, me }: { onOpenMobileNav: () => void; me: Me | null }) {
  const pathname = usePathname();
  const match = findNavItem(pathname);
  const title = match?.item.label ?? "AgentFirm";
  const name = me?.user.name ?? "Demo User";
  const orgName = me?.organization?.name ?? "Northwind Labs";

  return (
    <header className="af-glass sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line px-4 sm:px-6">
      <button
        type="button"
        onClick={onOpenMobileNav}
        className="grid size-9 place-items-center rounded-[10px] text-fg-2 hover:bg-card-2 hover:text-fg lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="size-5" />
      </button>

      <div className="min-w-0">
        <nav aria-label="Breadcrumb" className="hidden items-center gap-1 text-[12px] text-fg-3 sm:flex">
          <Link href="/" className="hover:text-fg-2">{orgName}</Link>
          <ChevronRight className="size-3" />
          <span>{match?.section.title ?? "Workspace"}</span>
        </nav>
        <h1 className="truncate text-[16px] font-semibold tracking-tight">{title}</h1>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          className="hidden h-9 w-[clamp(180px,22vw,320px)] items-center gap-2 rounded-[10px] border border-line bg-card-2 px-3 text-[13px] text-fg-3 transition-colors hover:border-line-strong md:flex"
          aria-label="Search agents, tasks and files"
        >
          <Search className="size-4" />
          <span className="truncate">Search agents, tasks, files…</span>
          <span className="ml-auto flex gap-0.5">
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>
        <button type="button" className="grid size-9 place-items-center rounded-[10px] text-fg-2 hover:bg-card-2 md:hidden" aria-label="Search">
          <Search className="size-[18px]" />
        </button>

        <NewTaskDialog
          trigger={
            <Button variant="primary" className="size-9 px-0 sm:size-auto sm:px-3.5" aria-label="New task">
              <Plus className="size-4" /> <span className="hidden sm:inline">New Task</span>
            </Button>
          }
        />

        <button type="button" className="relative grid size-9 place-items-center rounded-[10px] text-fg-2 hover:bg-card-2 hover:text-fg" aria-label={LIVE_DATA ? "Notifications" : "Notifications, 3 unread"}>
          <Bell className="size-[18px]" />
          {LIVE_DATA ? null : <span className="absolute right-2 top-2 size-2 rounded-full bg-warn ring-2 ring-[var(--bg-2)]" />}
        </button>

        <ThemeToggle className="hidden sm:flex" />

        <Dropdown.Root>
          <Dropdown.Trigger asChild>
            <button type="button" aria-label="Profile menu" className="grid size-9 place-items-center rounded-full bg-[linear-gradient(135deg,var(--accent),var(--accent-2))] text-[12px] font-semibold text-white ring-2 ring-line">
              {initials(name)}
            </button>
          </Dropdown.Trigger>
          <Dropdown.Portal>
            <Dropdown.Content align="end" sideOffset={8} className="z-50 w-56 rounded-[12px] border border-line bg-card p-1.5 shadow-[var(--shadow)]">
              <div className="px-2 py-2">
                <div className="text-[13px] font-medium">{name}</div>
                <div className="text-[12px] capitalize text-fg-3">
                  {me?.role ?? (me ? "no role" : "owner")} · {orgName}
                </div>
                {me ? <div className="mt-0.5 truncate text-[11.5px] text-fg-3">{me.user.email}</div> : null}
              </div>
              <Dropdown.Separator className="my-1 h-px bg-line" />
              {[
                { icon: User, label: "Profile" },
                { icon: KeyRound, label: "Security & sessions" },
              ].map(({ icon: Icon, label }) => (
                <Dropdown.Item key={label} className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 text-[13px] outline-none data-[highlighted]:bg-card-2">
                  <Icon className="size-3.5 text-fg-3" /> {label}
                </Dropdown.Item>
              ))}
              <div className="flex items-center justify-between px-2 py-1.5 text-[13px] sm:hidden">
                Theme <ThemeToggle />
              </div>
              <Dropdown.Separator className="my-1 h-px bg-line" />
              <Dropdown.Item
                onSelect={async () => {
                  if (process.env.NEXT_PUBLIC_AGENTFIRM_AUTH === "api") {
                    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
                  }
                  window.location.assign("/login");
                }}
                className="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 text-[13px] text-err outline-none data-[highlighted]:bg-card-2"
              >
                <LogOut className="size-3.5" /> Sign out
              </Dropdown.Item>
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
      </div>
    </header>
  );
}
