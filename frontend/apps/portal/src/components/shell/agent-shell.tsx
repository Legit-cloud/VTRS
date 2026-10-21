"use client";

import { LogOut } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Skeleton } from "@/components/ui/card";
import { InlineAlert } from "@/components/ui/feedback";
import { useAuth } from "@/lib/auth";
import { useOnline } from "@/lib/capture/online";

/** Where an agent may go. Everything else in the app is for coordinators and admins. */
const AGENT_PATHS = ["/capture", "/settings"];

/**
 * Phone-first chrome for polling unit agents: one column, the unit and the form, nothing else.
 * Agents use the same web app as everyone, in their phone's browser; their role decides what
 * they see.
 */
export function AgentShell({ children }: { children: ReactNode }) {
  const { status, me, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const online = useOnline();

  useEffect(() => {
    if (me && !AGENT_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
      router.replace("/capture");
    }
  }, [me, pathname, router]);

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

  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-20 border-b border-border bg-card">
        <div className="mx-auto flex h-14 max-w-xl items-center gap-3 px-4">
          <Link href="/capture" className="flex items-center gap-2">
            <Image src="/logo-mark.svg" alt="" width={28} height={28} priority />
            <span className="text-body font-bold">VTRS</span>
          </Link>
          <span className="ml-auto truncate text-body-sm text-subtle-foreground">
            {me.full_name}
          </span>
          <button
            type="button"
            onClick={() => void logout()}
            className="flex h-10 items-center gap-1.5 rounded-md px-2 text-label font-semibold text-strong-foreground hover:bg-muted"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </button>
        </div>
      </header>
      {!online ? (
        <div className="mx-auto max-w-xl px-4 pt-3">
          <InlineAlert tone="warning" title="No connection">
            Anything you type stays on this phone. Keep this page open: sending starts again when
            the connection is back.
          </InlineAlert>
        </div>
      ) : null}
      <main className="mx-auto max-w-xl px-4 pb-16 pt-5">{children}</main>
    </div>
  );
}
