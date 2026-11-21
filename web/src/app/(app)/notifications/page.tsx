import type { Metadata } from "next";
import { Bell } from "lucide-react";
import { PlannedScreen } from "@/components/ui/EmptyState";

export const metadata: Metadata = { title: "Notifications" };

export default function Page() {
  return (
    <PlannedScreen
      icon={Bell}
      title="Notifications"
      phase="Planned · Phase 3–4 (needs backend)"
      description="Approvals, completions and failures that need your attention."
      bullets={["Approval requests with one-click decisions", "Delivery to email and mobile", "Per-event preferences"]}
    />
  );
}
