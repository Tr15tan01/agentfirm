import type { Metadata } from "next";
import { Suspense } from "react";
import { CheckoutView } from "@/components/billing/CheckoutView";

export const metadata: Metadata = { title: "Checkout" };

/** Paddle default payment link page: Paddle.js opens the checkout for `?_ptxn=`. */
export default function CheckoutPage() {
  return (
    <Suspense>
      <CheckoutView />
    </Suspense>
  );
}
