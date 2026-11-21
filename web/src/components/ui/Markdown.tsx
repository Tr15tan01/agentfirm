"use client";

import { useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { Check, Copy } from "lucide-react";

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable */
        }
      }}
      className="flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] text-fg-3 transition-colors hover:bg-card hover:text-fg"
      aria-label={copied ? "Copied" : label}
    >
      {copied ? <Check className="size-3 text-ok" /> : <Copy className="size-3" />}
      {copied ? "Copied" : label}
    </button>
  );
}

const components: Components = {
  pre({ children }) {
    const code = textOf(children);
    const lang = (() => {
      const child = Array.isArray(children) ? children[0] : children;
      const cls = (child as { props?: { className?: string } })?.props?.className ?? "";
      return /language-(\w+)/.exec(cls)?.[1] ?? "text";
    })();
    return (
      <div className="af-code my-3 overflow-hidden rounded-[10px] border border-line bg-[var(--bg)]">
        <div className="flex items-center justify-between border-b border-line px-3 py-1">
          <span className="font-mono text-[11px] text-fg-3">{lang}</span>
          <CopyButton text={code.replace(/\n$/, "")} />
        </div>
        <pre className="overflow-x-auto p-3 font-mono text-[12.5px] leading-relaxed">{children}</pre>
      </div>
    );
  },
  table({ children }) {
    return (
      <div className="my-3 overflow-x-auto rounded-[10px] border border-line">
        <table className="w-full text-[13px]">{children}</table>
      </div>
    );
  },
  a({ children, href }) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener" className="text-accent underline-offset-2 hover:underline">
        {children}
      </a>
    );
  },
};

/** Markdown for agent output. Raw HTML is not rendered (react-markdown default) — agent text is untrusted. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="af-prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeHighlight, { detect: false, ignoreMissing: true }]]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
