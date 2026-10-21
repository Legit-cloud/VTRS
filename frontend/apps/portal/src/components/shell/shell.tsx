"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import { ROLE_LABEL, type RoleCode, electionStatus } from "@vtrs/core";
import { Bell, ChevronDown, LogOut, Menu, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/ui/chip";
import { Select } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/card";
import { ScopeBar } from "@/components/vtrs/scope-bar";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { useElection } from "@/lib/election";
import { useStates } from "@/lib/geo-names";
import { NAV } from "./nav";

const COLLAPSE_KEY = "vtrs.sidebar.collapsed";

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

export function AppShell({ children }: { children: ReactNode }) {
  const { status, me, can, logout } = useAuth();
  const pathname = usePathname();
  const { election } = useElection();
  const [collapsed, setCollapsed] = useCollapsed();
  const [drawer, setDrawer] = useState(false);

  useEffect(() => setDrawer(false), [pathname]);

  // Roles that must use a second factor get nothing else until it is set up; the API would
  // refuse every other call anyway, so say so up front instead of showing errors.
  const router = useRouter();
  // Party users have no business on the platform surface.
  useEffect(() => {
    // Only once we know who this is: an operator's session is still loading when this first runs.
    if (me && me.role !== "PLATFORM_ADMIN" && pathname.startsWith("/platform")) {
      router.replace("/war-room");
    }
  }, [me, pathname, router]);

  const flags = useQuery({
    queryKey: ["flags", "summary", election?.id],
    queryFn: () => ep.flags.summary(election!.id),
    enabled: !!election && can("anomalies.view"),
    refetchInterval: 60_000,
  });
  const unread = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => ep.me.unreadCount(),
    enabled: status === "authenticated",
    refetchInterval: 60_000,
  });

  if (status !== "authenticated" || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <div className="flex w-72 flex-col gap-3" aria-busy="true" aria-label="Loading">
          <Skeleton className="h-10" />
          <Skeleton className="h-24" />
        </div>
      </div>
    );
  }

  const visible = NAV.filter((item) => {
    if (!item.permission) return true;
    const needed = Array.isArray(item.permission) ? item.permission : [item.permission];
    return needed.some((p) => can(p));
  });

  const openFlags = flags.data
    ? Object.values(flags.data.active_by_severity ?? {}).reduce(
        (sum: number, n) => sum + Number(n),
        0,
      )
    : 0;

  const nav = (compact: boolean) => (
    <nav aria-label="Main" className="flex flex-col gap-1 p-3">
      {visible.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        const badge = item.href === "/anomalies" && openFlags > 0 ? openFlags : null;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            title={compact ? item.label : undefined}
            className={cn(
              "flex h-10 items-center gap-3 rounded-md px-3 text-body-sm font-medium transition-colors duration-fast",
              active
                ? "bg-primary-soft font-semibold text-primary-soft-foreground"
                : "text-strong-foreground hover:bg-muted",
              compact && "justify-center px-0",
            )}
          >
            <Icon className="h-5 w-5 shrink-0" aria-hidden />
            {compact ? (
              <span className="sr-only">{item.label}</span>
            ) : (
              <span className="truncate">{item.label}</span>
            )}
            {badge && !compact ? (
              <span className="ml-auto rounded-full bg-signal-red-soft px-2 text-caption font-semibold tabular-nums text-signal-red-text">
                {badge}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-screen bg-canvas">
      {/* Sidebar, large screens */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-card lg:flex",
          collapsed ? "w-sidebar-collapsed" : "w-sidebar",
        )}
      >
        <div
          className={cn(
            "flex h-topbar items-center gap-3 px-4",
            collapsed && "justify-center px-0",
          )}
        >
          <Image src="/logo-mark.svg" alt="" width={32} height={32} priority />
          {collapsed ? null : <span className="text-h2 font-extrabold tracking-tight">VTRS</span>}
        </div>
        <div className="px-3 pb-1">
          <Button
            variant="ghost"
            size="sm"
            className={cn("w-full text-strong-foreground", collapsed && "px-0")}
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
          >
            {collapsed ? (
              <PanelLeftOpen className="h-5 w-5" aria-hidden />
            ) : (
              <PanelLeftClose className="h-5 w-5" aria-hidden />
            )}
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{nav(collapsed)}</div>
      </aside>

      {/* Drawer, small screens */}
      {drawer ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-foreground/50"
            onClick={() => setDrawer(false)}
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-card shadow-sheet">
            <div className="flex h-topbar items-center justify-between px-4">
              <span className="flex items-center gap-3">
                <Image src="/logo-mark.svg" alt="" width={32} height={32} />
                <span className="text-h2 font-extrabold">VTRS</span>
              </span>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Close menu"
                onClick={() => setDrawer(false)}
              >
                <X className="h-5 w-5" aria-hidden />
              </Button>
            </div>
            <div className="overflow-y-auto">{nav(false)}</div>
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-topbar items-center gap-3 border-b border-border bg-card px-4 lg:px-8">
          <Button
            variant="ghost"
            size="icon-sm"
            className="lg:hidden"
            aria-label="Open menu"
            onClick={() => setDrawer(true)}
          >
            <Menu className="h-5 w-5" aria-hidden />
          </Button>
          <ElectionPicker />
          <div className="hidden min-w-0 flex-1 md:block">
            <ScopeBar />
          </div>
          <div className="ml-auto flex items-center gap-1">
            <Link
              href="/settings#notifications"
              className="relative flex h-control-dense w-control-dense items-center justify-center rounded-md text-strong-foreground hover:bg-muted"
              aria-label={`Notifications${unread.data?.unread ? `, ${unread.data.unread} unread` : ""}`}
            >
              <Bell className="h-5 w-5" aria-hidden />
              {unread.data?.unread ? (
                <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-destructive px-1 text-center text-[11px] font-semibold leading-4 text-destructive-foreground tabular-nums">
                  {unread.data.unread > 99 ? "99+" : unread.data.unread}
                </span>
              ) : null}
            </Link>
            <Dropdown.Root>
              <Dropdown.Trigger asChild>
                <Button variant="ghost" size="sm" className="gap-1 text-foreground">
                  <span className="max-w-32 truncate">{me.full_name}</span>
                  <ChevronDown className="h-4 w-4" aria-hidden />
                </Button>
              </Dropdown.Trigger>
              <Dropdown.Portal>
                <Dropdown.Content
                  align="end"
                  sideOffset={6}
                  className="z-50 min-w-56 rounded-md border border-border bg-popover p-1 shadow-float"
                >
                  <div className="px-3 py-2">
                    <p className="text-body-sm font-semibold">{me.full_name}</p>
                    <p className="text-caption text-subtle-foreground">
                      {ROLE_LABEL[me.role as RoleCode] ?? me.role}
                    </p>
                    <p className="text-caption text-subtle-foreground">
                      {String((me.organization as { name?: string }).name ?? "")}
                    </p>
                  </div>
                  <Dropdown.Separator className="my-1 h-px bg-border" />
                  <Dropdown.Item
                    onSelect={() => void logout()}
                    className="flex h-9 cursor-pointer items-center gap-2 rounded-sm px-3 text-body-sm outline-none data-[highlighted]:bg-muted"
                  >
                    <LogOut className="h-4 w-4" aria-hidden /> Sign out
                  </Dropdown.Item>
                </Dropdown.Content>
              </Dropdown.Portal>
            </Dropdown.Root>
          </div>
        </header>
        <div className="border-b border-border bg-card px-4 py-2 md:hidden">
          <ScopeBar />
        </div>
        <main id="main" className="mx-auto w-full max-w-page flex-1 p-4 md:p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}

function ElectionPicker() {
  const { elections, election, select, loading } = useElection();
  const { states } = useStates();
  const stateOf = (id: string) => states.find((s) => s.id === id)?.name;
  if (loading) return <Skeleton className="h-control-dense w-48" />;
  if (!election)
    return <span className="text-body-sm text-subtle-foreground">No election yet</span>;
  return (
    <div className="flex min-w-0 items-center gap-2">
      <label htmlFor="election-picker" className="sr-only">
        Election
      </label>
      <Select
        id="election-picker"
        value={election.id}
        onChange={(e) => select(e.target.value)}
        className="h-control-dense max-w-56 bg-card py-0 text-body-sm font-semibold"
      >
        {elections.map((e) => (
          <option key={e.id} value={e.id}>
            {stateOf(e.state_id) ? `${e.name} (${stateOf(e.state_id)})` : e.name}
          </option>
        ))}
      </Select>
      <span className="hidden sm:inline">
        <StatusChip status={electionStatus(election.status ?? "DRAFT")} />
      </span>
    </div>
  );
}
