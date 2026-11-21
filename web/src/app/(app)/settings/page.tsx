import type { Metadata } from "next";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveSettingsPage } from "@/components/live/LivePages";
import { SettingsView } from "@/components/settings/SettingsView";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  if (LIVE_DATA) return <LiveSettingsPage />;
  const members = await api.workspace.members();
  return <SettingsView members={members} demo={api.isDemo} />;
}
