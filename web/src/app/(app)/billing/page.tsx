import type { Metadata } from "next";
import { api } from "@/data/api";
import { LIVE_DATA } from "@/lib/mode";
import { LiveBillingPage } from "@/components/live/LivePages";
import { UsageBilling } from "@/components/billing/UsageBilling";

export const metadata: Metadata = { title: "Usage & Billing" };

export default async function BillingPage() {
  if (LIVE_DATA) return <LiveBillingPage />;
  const report = await api.usage.report("30d");
  return <UsageBilling initial={report} demo={api.isDemo} />;
}
