import type { Metadata } from "next";
import { ModelRouting } from "@/components/admin/ModelRouting";

export const metadata: Metadata = { title: "Models & Routing" };

/**
 * Super-admin only. Phase 3 adds a server-side guard here (session role check →
 * notFound()) in addition to API-level authorization on every routing endpoint.
 */
export default function ModelsAdminPage() {
  return <ModelRouting />;
}
