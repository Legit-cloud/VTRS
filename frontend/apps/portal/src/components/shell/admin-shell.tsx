"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Building2,
  Database,
  History,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShieldCheck,
  Vote,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";

const COLLAPSE_KEY = "vtrs.admin.sidebar.collapsed";

function readCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false; // storage unavailable: stay expanded
  }
}

function useCollapsed(): [boolean, (next: boolean) => void] {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  return [
    collapsed,
    (next) => {
      setCollapsed(next);
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
    },
  ];
}

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
  const [collapsed, setCollapsed] = useCollapsed();

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
      <div className="flex min-h-0 flex-1">
        <aside
          className={cn(
            "sticky top-0 hidden h-screen shrink-0 flex-col bg-chrome-sidebar text-chrome-text lg:flex",
            collapsed ? "w-sidebar-collapsed" : "w-sidebar",
          )}
        >
          <div
            className={cn(
              "flex h-topbar items-center gap-3 px-4",
              collapsed && "justify-center px-0",
            )}
          >
            <Image src="/logo-mark.svg" alt="" width={32} height={32} />
            {collapsed ? null : <span className="text-h2 font-extrabold tracking-tight">VTRS</span>}
          </div>
          <div className="px-3 pb-1">
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!collapsed}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className={cn(
                "flex h-10 w-full items-center gap-3 rounded-md px-3 text-body-sm font-medium text-chrome-text transition-colors duration-fast hover:bg-black/10",
                collapsed && "justify-center px-0",
              )}
            >
              {collapsed ? (
                <PanelLeftOpen className="h-5 w-5" aria-hidden />
              ) : (
                <PanelLeftClose className="h-5 w-5" aria-hidden />
              )}
            </button>
          </div>
          <nav aria-label="Main" className="flex min-h-0 flex-col gap-1 overflow-y-auto p-3">
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
                  title={collapsed ? item.label : undefined}
                  className={cn(
                    "relative flex h-10 items-center gap-3 rounded-md px-3 text-body-sm font-medium transition-colors duration-fast",
                    collapsed && "justify-center px-0",
                    active
                      ? "bg-black/20 font-semibold text-white"
                      : "text-chrome-text hover:bg-black/10",
                  )}
                >
                  <Icon className="h-5 w-5 shrink-0" aria-hidden />
                  <span className={cn("truncate", collapsed && "sr-only")}>{item.label}</span>
                  {badge && collapsed ? (
                    <span
                      className="absolute right-2 top-2 h-2.5 w-2.5 rounded-full bg-signal-amber-mark"
                      aria-hidden
                    />
                  ) : null}
                  {badge && !collapsed ? (
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
          <header className="sticky top-0 z-30 flex h-topbar items-center gap-3 border-b border-border bg-card px-4 lg:px-8">
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
