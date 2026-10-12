"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Building2,
  Database,
  History,
  Landmark,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Settings,
  ShieldCheck,
  Vote,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";

const ENVIRONMENT = process.env.NEXT_PUBLIC_ENVIRONMENT ?? "Development";
const IS_PRODUCTION = /^prod/i.test(ENVIRONMENT);

const NAV = [
  { href: "/platform", label: "Overview", icon: LayoutDashboard },
  { href: "/platform/organizations", label: "Organisations", icon: Building2 },
  { href: "/platform/verification", label: "Verification queue", icon: ShieldCheck },
  { href: "/platform/elections", label: "Elections", icon: Vote },
  { href: "/platform/master-data", label: "Master data", icon: Database },
  { href: "/platform/health", label: "System health", icon: Activity },
  { href: "/platform/messaging", label: "Messaging providers", icon: MessageSquareText },
  { href: "/platform/audit", label: "Audit log", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

/**
 * Same grid and components as the party portal, with chrome nobody can mistake for it: an ink
 * sidebar and a strip across the top that always names the surface and the environment.
 */
export function AdminShell({ children }: { children: ReactNode }) {
  const { me, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const onAllowedPage = pathname.startsWith("/platform") || pathname.startsWith("/settings");
  useEffect(() => {
    if (!onAllowedPage) router.replace("/platform");
  }, [onAllowedPage, router]);

  // Operators must have a second factor before anything else is shown.
  const mustEnrol = !!me && me.mfa_required && !me.mfa_enabled;
  useEffect(() => {
    if (mustEnrol && !pathname.startsWith("/settings")) router.replace("/settings?enrol=1");
  }, [mustEnrol, pathname, router]);

  const pending = useQuery({
    queryKey: ["platform", "overview", "nav"],
    queryFn: () => ep.platform.overview(),
    enabled: !mustEnrol,
    refetchInterval: 60_000,
  });

  return (
    <div data-surface="admin" className="flex min-h-screen flex-col bg-canvas">
      <div className="flex h-strip items-center gap-3 bg-chrome-strip px-4 text-label font-semibold text-chrome-strip-text">
        <Landmark className="h-4 w-4" aria-hidden />
        Platform admin
        <span
          className={cn(
            "rounded-full px-2 text-caption font-semibold",
            IS_PRODUCTION ? "bg-white/15 text-white" : "bg-signal-amber-mark text-ink-900",
          )}
        >
          {ENVIRONMENT}
        </span>
        <span className="ml-auto hidden text-caption font-medium text-chrome-muted sm:inline">
          Every action here is logged
        </span>
      </div>
      <div className="flex min-h-0 flex-1">
        <aside className="sticky top-0 hidden h-[calc(100vh-32px)] w-sidebar shrink-0 flex-col bg-chrome-sidebar text-chrome-text lg:flex">
          <div className="flex h-topbar items-center gap-3 px-4">
            <Image src="/logo-mark.svg" alt="" width={32} height={32} />
            <span className="text-h2 font-extrabold tracking-tight">VTRS</span>
          </div>
          <nav aria-label="Main" className="flex flex-col gap-1 overflow-y-auto p-3">
            {NAV.map((item) => {
              const active =
                item.href === "/platform"
                  ? pathname === "/platform"
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
              const Icon = item.icon;
              const badge =
                item.href === "/platform/verification"
                  ? pending.data?.organizations.pending_approval
                  : 0;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-10 items-center gap-3 rounded-md px-3 text-body-sm font-medium transition-colors duration-fast",
                    active
                      ? "bg-white/12 font-semibold text-white"
                      : "text-chrome-text hover:bg-white/8",
                  )}
                >
                  <Icon className="h-5 w-5 shrink-0" aria-hidden />
                  <span className="truncate">{item.label}</span>
                  {badge ? (
                    <span className="ml-auto rounded-full bg-signal-amber-mark px-2 text-caption font-semibold tabular-nums text-ink-900">
                      {badge}
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </nav>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-8 z-30 flex h-topbar items-center gap-3 border-b border-border bg-card px-4 lg:px-8">
            <nav aria-label="Sections" className="flex min-w-0 gap-1 overflow-x-auto lg:hidden">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "whitespace-nowrap rounded-md px-3 py-1.5 text-body-sm font-medium",
                    pathname.startsWith(item.href) && item.href !== "/platform"
                      ? "bg-primary-soft text-primary-soft-foreground"
                      : pathname === item.href
                        ? "bg-primary-soft text-primary-soft-foreground"
                        : "text-strong-foreground",
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto flex items-center gap-3">
              <span className="hidden text-body-sm text-subtle-foreground sm:inline">
                {me?.full_name}
              </span>
              <Button
                variant="ghost"
                size="sm"
                leading={<LogOut className="h-4 w-4" aria-hidden />}
                onClick={() => void logout()}
              >
                Sign out
              </Button>
            </div>
          </header>
          <main id="main" className="mx-auto w-full max-w-page flex-1 p-4 md:p-6 lg:p-8">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
