import type { Metadata } from "next";
import { FolderKanban } from "lucide-react";
import { PlannedScreen } from "@/components/ui/EmptyState";

export const metadata: Metadata = { title: "Projects" };

export default function Page() {
  return (
    <PlannedScreen
      icon={FolderKanban}
      title="Projects"
      phase="Planned · Phase 3–4 (needs backend)"
      description="Group tasks, conversations and knowledge around an outcome."
      bullets={["Shared project context for agents", "Deliverables and history per project", "Member permissions per project"]}
    />
  );
}
