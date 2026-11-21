/** Data source switch, safe to import from server and client modules alike. */
export const LIVE_DATA = process.env.NEXT_PUBLIC_AGENTFIRM_API === "http";
