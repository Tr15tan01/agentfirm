import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveTaskPage } from "@/components/live/LivePages";
import { TaskMonitor } from "@/components/tasks/TaskMonitor";

export async function generateStaticParams() {
  // Live runs are per-user and rendered on request; demo runs are prerendered.
  if (LIVE_DATA) return [{ id: "_" }];
  const tasks = await api.tasks.list();
  return tasks.map((t) => ({ id: t.id }));
}

export async function generateMetadata({ params }: PageProps<"/tasks/[id]">): Promise<Metadata> {
  const { id } = await params;
  if (LIVE_DATA) return { title: "Task" };
  const task = await api.tasks.get(id);
  return { title: task?.title ?? "Task" };
}

export default async function TaskPage({ params }: PageProps<"/tasks/[id]">) {
  const { id } = await params;
  if (LIVE_DATA) return <LiveTaskPage id={id} />;
  const task = await api.tasks.get(id);
  if (!task) notFound();
  return <TaskMonitor task={task} demo={api.isDemo} />;
}
