export default function AuthLayout({ children }: LayoutProps<"/">) {
  return <div className="min-h-dvh" style={{ backgroundImage: "var(--canvas-wash)" }}>{children}</div>;
}
