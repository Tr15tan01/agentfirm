import type { Metadata } from "next";
import { KnowledgeView } from "@/components/knowledge/KnowledgeView";

export const metadata: Metadata = { title: "Knowledge & Files" };

export default function Page() {
  return <KnowledgeView />;
}
