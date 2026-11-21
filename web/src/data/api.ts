/**
 * The single switch between demo and real backends.
 * NEXT_PUBLIC_AGENTFIRM_API=http → FastAPI via the BFF. Default: demo.
 * Sign-in is switched separately (NEXT_PUBLIC_AGENTFIRM_AUTH=api) and is live from Phase 3;
 * live screens load through the HTTP adapter in the browser (components/live, ADR 0004).
 */
import type { AgentFirmApi } from "@/lib/api/contracts";
import { httpApi } from "@/lib/api/http";
import { LIVE_DATA } from "@/lib/mode";
import { mockApi } from "@/mocks/adapter";

export const api: AgentFirmApi = LIVE_DATA ? httpApi : mockApi;
