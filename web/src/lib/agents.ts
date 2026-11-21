import {
  BookOpenText,
  Megaphone,
  CodeXml,
  ChartNoAxesCombined,
  CalendarCheck,
  Lightbulb,
  type LucideIcon,
} from "lucide-react";
import type { AgentKey } from "./types";

export type AgentTone = "blue" | "violet" | "cyan";

export interface AgentIdentity {
  key: AgentKey;
  name: string;
  shortName: string;
  description: string;
  icon: LucideIcon;
  tone: AgentTone;
}

/**
 * Visual identity registry. In Phase 3+ name/description come from the
 * `agents` table; only icon + tone stay client-side, keyed by agent key, with
 * a generic fallback so admin-created agents render without code changes.
 */
export const AGENT_IDENTITIES: Record<AgentKey, AgentIdentity> = {
  research: {
    key: "research",
    name: "Research & Knowledge",
    shortName: "Research",
    description: "Structured research, document analysis and cited reports.",
    icon: BookOpenText,
    tone: "cyan",
  },
  marketing: {
    key: "marketing",
    name: "AI Marketing",
    shortName: "Marketing",
    description: "Strategy, positioning, campaigns, SEO and on-brand content.",
    icon: Megaphone,
    tone: "violet",
  },
  engineer: {
    key: "engineer",
    name: "Project Engineer",
    shortName: "Engineer",
    description: "Architecture, code, reviews, tests and technical documentation.",
    icon: CodeXml,
    tone: "blue",
  },
  bi: {
    key: "bi",
    name: "Business Intelligence & Automation",
    shortName: "BI & Automation",
    description: "KPIs, forecasting, opportunity analysis and approved automations.",
    icon: ChartNoAxesCombined,
    tone: "cyan",
  },
  assistant: {
    key: "assistant",
    name: "Personal Assistant",
    shortName: "Assistant",
    description: "Scheduling, drafting, discovery — and delegating to specialists.",
    icon: CalendarCheck,
    tone: "blue",
  },
  creative: {
    key: "creative",
    name: "Creative & Brainstorming",
    shortName: "Creative",
    description: "Divergent ideation, SCAMPER, Six Hats and critical evaluation.",
    icon: Lightbulb,
    tone: "violet",
  },
};

export const TONE_VAR: Record<AgentTone, string> = {
  blue: "var(--accent)",
  violet: "var(--accent-2)",
  cyan: "var(--cyan)",
};

/** Display name for an agent key, including the orchestrator (which isn't an agent). */
export function agentShortName(key: string): string {
  if (key === "orchestrator") return "Orchestrator";
  return (AGENT_IDENTITIES as Record<string, AgentIdentity | undefined>)[key]?.shortName ?? key;
}
