import type { Metadata } from "next";
import { PlatformAdmin } from "@/components/admin/PlatformAdmin";

export const metadata: Metadata = { title: "Platform" };

/** Super-admin only: the API refuses every call from anyone else (403), whatever this page shows. */
export default function PlatformAdminPage() {
  return <PlatformAdmin />;
}
