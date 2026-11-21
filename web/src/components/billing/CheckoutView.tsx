"use client";

import { Loader2, Lock } from "lucide-react";
import Script from "next/script";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/data/api";
import { Button, Card } from "@/components/ui/primitives";

declare global {
  interface Window {
    Paddle?: {
      Environment: { set(env: string): void };
      Initialize(opts: { token: string; eventCallback?: (e: { name?: string }) => void }): void;
    };
  }
}

const TOKEN = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN ?? "";
const ENV = process.env.NEXT_PUBLIC_PADDLE_ENV ?? "sandbox";

/**
 * Paddle's checkout runs in Paddle's own overlay (card details never touch AgentFirm). This page is
 * the approved "default payment link": Paddle.js reads `_ptxn` from the URL and opens the checkout
 * for the transaction our server created. Plans and credits change only when Paddle's signed
 * webhook arrives, never because this page says so.
 */
export function CheckoutView() {
  const params = useSearchParams();
  const router = useRouter();
  const txn = params.get("_ptxn") ?? "";
  const fixture = txn.startsWith("txn_fixture");
  // Keyed by transaction: Next may keep this page's state when it's visited again for a new checkout.
  const [busyTxn, setBusyTxn] = useState<string | null>(null);
  const [error, setError] = useState<{ txn: string; message: string } | null>(null);
  const busy = busyTxn === txn;

  if (!txn) {
    return <Shell title="Nothing to pay">This page opens Paddle checkouts started from Usage & Billing.</Shell>;
  }

  if (fixture) {
    return (
      <Shell title="Test checkout">
        <p>This server runs Paddle in test (fixture) mode, so no payment is taken. Completing it sends the same signed webhooks Paddle would.</p>
        {error?.txn === txn ? <p className="mt-2 text-[color:var(--err)]">{error.message}</p> : null}
        <div className="mt-4 flex gap-2">
          <Button
            variant="primary"
            disabled={busy}
            onClick={async () => {
              setBusyTxn(txn);
              try {
                await api.account.completeFixtureCheckout(txn);
                router.push("/billing?paid=1");
              } catch (e) {
                setError({ txn, message: e instanceof Error ? e.message : String(e) });
                setBusyTxn(null);
              }
            }}
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Lock className="size-4" />} Complete test payment
          </Button>
          <Button onClick={() => router.push("/billing")}>Cancel</Button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell title="Secure checkout">
      {TOKEN ? (
        <>
          <p>Paddle&apos;s checkout opens over this page. If it doesn&apos;t, check that pop-ups and third-party scripts from paddle.com aren&apos;t blocked.</p>
          <Script
            src="https://cdn.paddle.com/paddle/v2/paddle.js"
            strategy="afterInteractive"
            onLoad={() => {
              if (!window.Paddle) return;
              if (ENV === "sandbox") window.Paddle.Environment.set("sandbox");
              window.Paddle.Initialize({
                token: TOKEN,
                eventCallback: (e) => {
                  if (e.name === "checkout.completed") setTimeout(() => router.push("/billing?paid=1"), 1500);
                },
              });
            }}
          />
        </>
      ) : (
        <p className="text-[color:var(--err)]">Checkout isn&apos;t configured: set NEXT_PUBLIC_PADDLE_CLIENT_TOKEN for this deployment.</p>
      )}
    </Shell>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-lg py-10">
      <Card className="p-6 text-[13.5px] text-fg-2">
        <h1 className="mb-2 text-[18px] font-semibold text-fg">{title}</h1>
        {children}
      </Card>
    </div>
  );
}
