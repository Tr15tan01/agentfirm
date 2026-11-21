import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { QuickTask } from "@/components/dashboard/QuickTask";
import { LiveCorePanel } from "@/components/dashboard/LiveCorePanel";
import { ExecutionPanel } from "@/components/dashboard/ExecutionPanel";
import { UsageOverview } from "@/components/dashboard/UsageOverview";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { AgentCard } from "@/components/agent/AgentCard";
import { TaskCard } from "@/components/tasks/TaskCard";
import { DemoBadge, SectionHeader } from "@/components/ui/primitives";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveOverviewPage } from "@/components/live/LivePages";

export default async function OverviewPage() {
  if (LIVE_DATA) return <LiveOverviewPage />;
  const [agents, allTasks] = await Promise.all([api.agents.list(), api.tasks.list()]);
  const tasks = allTasks.filter((t) => t.status === "running" || t.status === "waiting_approval");
  const working = agents.filter((a) => a.status === "working").length;

  return (
    <div className="space-y-6">
      {/* Hero row */}
      <div className="grid gap-6 xl:grid-cols-12 [&>*]:min-w-0">
        <div className="xl:col-span-8">
          <QuickTask />
        </div>
        <div className="xl:col-span-4">
          <LiveCorePanel />
        </div>
      </div>

      {/* Workforce */}
      <section aria-labelledby="workforce">
        <SectionHeader
          title="Active workforce"
          subtitle={`${agents.length} specialised agents · ${working} working now`}
          action={
            <div className="flex items-center gap-3">
              <DemoBadge />
              <Link href="/agents" className="flex items-center gap-1 text-[13px] font-medium text-fg-2 hover:text-fg">
                All agents <ArrowRight className="size-3.5" />
              </Link>
            </div>
          }
        />
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3 min-[1920px]:grid-cols-6">
          {agents.map((a, i) => (
            <AgentCard key={a.key} agent={a} index={i} />
          ))}
        </div>
      </section>

      {/* Tasks + live execution */}
      <div className="grid gap-6 xl:grid-cols-12 [&>*]:min-w-0">
        <section className="xl:col-span-7" aria-labelledby="active-tasks">
          <SectionHeader
            title="Active tasks"
            subtitle="Progress comes from completed plan steps; unknown progress is shown as indeterminate."
            action={
              <Link href="/tasks" className="flex items-center gap-1 text-[13px] font-medium text-fg-2 hover:text-fg">
                All runs <ArrowRight className="size-3.5" />
              </Link>
            }
          />
          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
            {tasks.map((t) => (
              <TaskCard key={t.id} task={t} />
            ))}
          </div>
        </section>
        <div className="xl:col-span-5">
          <ExecutionPanel />
        </div>
      </div>

      {/* Usage + activity */}
      <div className="grid gap-6 xl:grid-cols-12 [&>*]:min-w-0">
        <div className="xl:col-span-8">
          <UsageOverview />
        </div>
        <div className="xl:col-span-4">
          <RecentActivity />
        </div>
      </div>
    </div>
  );
}
