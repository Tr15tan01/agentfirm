import type { Metadata } from "next";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveTasksPage } from "@/components/live/LivePages";
import { TaskTable } from "@/components/tasks/TaskTable";

export const metadata: Metadata = { title: "Tasks & Runs" };

export default async function TasksPage() {
  if (LIVE_DATA) return <LiveTasksPage />;
  const [tasks, approvals] = await Promise.all([api.tasks.list(), api.approvals.pending()]);
  return <TaskTable tasks={tasks} approvals={approvals} demo={api.isDemo} />;
}
