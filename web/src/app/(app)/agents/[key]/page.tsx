import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveAgentWorkspacePage } from "@/components/live/LivePages";
import { AGENT_IDENTITIES } from "@/lib/agents";
import type { AgentKey } from "@/lib/types";
import { AgentWorkspace } from "@/components/workspace/AgentWorkspace";
import { IdeaBoard } from "@/components/creative/IdeaBoard";

export function generateStaticParams() {
  return Object.keys(AGENT_IDENTITIES).map((key) => ({ key }));
}

export async function generateMetadata({ params }: PageProps<"/agents/[key]">): Promise<Metadata> {
  const { key } = await params;
  return { title: AGENT_IDENTITIES[key as AgentKey]?.name ?? "Agent" };
}

export default async function AgentWorkspacePage({ params }: PageProps<"/agents/[key]">) {
  const { key } = await params;
  if (!(key in AGENT_IDENTITIES)) notFound();
  const agent = key as AgentKey;
  if (LIVE_DATA) return <LiveAgentWorkspacePage agent={agent} />;

  const [profile, conversations] = await Promise.all([api.agents.get(agent), api.conversations.list(agent)]);
  if (!profile) notFound();

  const first = conversations.find((c) => c.pinned) ?? conversations[0] ?? null;
  const live = profile.recentExecutions.find((e) => e.status === "running" || e.status === "waiting_approval");
  const [messages, execution, ideas] = await Promise.all([
    first ? api.conversations.messages(first.id) : Promise.resolve([]),
    live ? api.tasks.get(live.taskId) : Promise.resolve(null),
    agent === "creative" ? api.ideas.list() : Promise.resolve(null),
  ]);

  return (
    <AgentWorkspace
      profile={profile}
      conversations={conversations}
      initialConversationId={first?.id ?? null}
      initialMessages={messages}
      execution={execution}
      demo={api.isDemo}
      board={ideas ? <IdeaBoard initialIdeas={ideas} /> : undefined}
    />
  );
}
