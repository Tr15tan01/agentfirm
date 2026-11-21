import type { Metadata } from "next";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveCollaborationPage } from "@/components/live/LivePages";
import { CollaborationView } from "@/components/collaboration/CollaborationView";

export const metadata: Metadata = { title: "Agent Collaboration" };

export default async function CollaborationPage() {
  if (LIVE_DATA) return <LiveCollaborationPage />;
  const tasks = await api.tasks.list();
  const multi = tasks.filter((t) => t.agents.length > 1);
  const live = multi.find((t) => t.status === "running" || t.status === "waiting_approval");
  const active = live ? await api.tasks.get(live.id) : null;
  return <CollaborationView active={active} others={multi.filter((t) => t.id !== live?.id)} demo={api.isDemo} />;
}
