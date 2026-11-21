import type { Metadata } from "next";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveAgentsPage } from "@/components/live/LivePages";
import { AgentDirectory } from "@/components/agent/AgentDirectory";

export const metadata: Metadata = { title: "My Agents" };

export default async function AgentsPage() {
  if (LIVE_DATA) return <LiveAgentsPage />;
  const profiles = await api.agents.profiles();
  return <AgentDirectory profiles={profiles} demo={api.isDemo} />;
}
