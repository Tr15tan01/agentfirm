import type { Metadata } from "next";
import { MessagesSquare } from "lucide-react";
import { PlannedScreen } from "@/components/ui/EmptyState";

export const metadata: Metadata = { title: "Conversations" };

export default function Page() {
  return (
    <PlannedScreen
      icon={MessagesSquare}
      title="Conversations"
      phase="Planned · Phase 3–4 (needs backend)"
      description="All chats with your agents in one place."
      bullets={["Streaming responses with markdown & code", "Search and pin conversations", "Continue any thread as a task"]}
    />
  );
}
