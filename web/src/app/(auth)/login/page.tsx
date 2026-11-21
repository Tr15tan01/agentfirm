import type { Metadata } from "next";
import { SignIn } from "@/components/auth/SignIn";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return <SignIn live={process.env.NEXT_PUBLIC_AGENTFIRM_AUTH === "api"} />;
}
