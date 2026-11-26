import {
  LayoutDashboard,
  Bot,
  Network,
  ListChecks,
  FolderKanban,
  Library,
  MessagesSquare,
  History,
  Bell,
  Gauge,
  Plug,
  Settings,
  Waypoints,
  Search,
  Building2,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: string;
}

export interface NavSection {
  title: string;
  items: NavItem[];
  /** Server must also enforce this — hiding links is not authorization. */
  requiresSuperAdmin?: boolean;
}

export const NAV: NavSection[] = [
  {
    title: "Workspace",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/agents", label: "My Agents", icon: Bot },
      { href: "/collaboration", label: "Agent Collaboration", icon: Network },
      { href: "/tasks", label: "Tasks & Runs", icon: ListChecks, badge: "4" },
      { href: "/projects", label: "Projects", icon: FolderKanban },
      { href: "/knowledge", label: "Knowledge & Files", icon: Library },
    ],
  },
  {
    title: "Activity",
    items: [
      { href: "/conversations", label: "Conversations", icon: MessagesSquare },
      { href: "/history", label: "History", icon: History },
      { href: "/notifications", label: "Notifications", icon: Bell },
    ],
  },
  {
    title: "Management",
    items: [
      { href: "/billing", label: "Usage & Billing", icon: Gauge },
      { href: "/integrations", label: "Integrations", icon: Plug },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
  {
    title: "Platform admin",
    requiresSuperAdmin: true,
    items: [
      { href: "/admin/models", label: "Models & Routing", icon: Waypoints },
      { href: "/admin/search", label: "Web search", icon: Search },
      { href: "/admin/platform", label: "Plans, Workspaces & Tools", icon: Building2 },
    ],
  },
];

export function findNavItem(pathname: string): { section: NavSection; item: NavItem } | null {
  for (const section of NAV) {
    for (const item of section.items) {
      if (item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`)) {
        return { section, item };
      }
    }
  }
  return null;
}
