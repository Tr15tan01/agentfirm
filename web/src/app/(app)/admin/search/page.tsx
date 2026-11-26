import type { Metadata } from "next";
import { SearchSettings } from "@/components/admin/SearchSettings";

export const metadata: Metadata = { title: "Web search" };

/** Super-admin only; every search endpoint is also authorized on the API. */
export default function SearchAdminPage() {
  return (
    <div className="space-y-8">
      <SearchSettings />
    </div>
  );
}
