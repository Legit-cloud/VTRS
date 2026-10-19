"use client";

import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { AdminShell } from "./admin-shell";
import { AgentShell } from "./agent-shell";
import { AppShell } from "./shell";

/** Platform operators get the admin chrome, agents the phone-first capture screens, and
 * everyone else the party portal. */
export function ShellSwitch({ children }: { children: ReactNode }) {
  const { me, status } = useAuth();
  if (status === "authenticated" && me?.role === "PLATFORM_ADMIN") {
    return <AdminShell>{children}</AdminShell>;
  }
  if (status === "authenticated" && me?.role === "PU_AGENT") {
    return <AgentShell>{children}</AgentShell>;
  }
  return <AppShell>{children}</AppShell>;
}
