import type { Metadata } from "next";
import { History } from "lucide-react";
import { PlannedScreen } from "@/components/ui/EmptyState";

export const metadata: Metadata = { title: "History" };

export default function Page() {
  return (
    <PlannedScreen
      icon={History}
      title="History"
      phase="Planned · Phase 3–4 (needs backend)"
      description="A complete, auditable record of finished work."
      bullets={["Filter by agent, project and status", "Traceable to the agent version that ran", "Re-run with the same configuration"]}
    />
  );
}
