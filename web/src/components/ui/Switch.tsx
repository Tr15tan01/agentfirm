"use client";

import * as RSwitch from "@radix-ui/react-switch";
import { cn } from "@/lib/cn";

export function Switch({ checked, onCheckedChange, label, disabled, className }: { checked: boolean; onCheckedChange: (v: boolean) => void; label: string; disabled?: boolean; className?: string }) {
  return (
    <RSwitch.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full border border-line bg-card-2 transition-colors disabled:opacity-40 data-[state=checked]:border-transparent data-[state=checked]:bg-accent",
        className,
      )}
    >
      <RSwitch.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[17px]" />
    </RSwitch.Root>
  );
}
