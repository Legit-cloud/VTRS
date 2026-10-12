"use client";

import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { AdminShell } from "./admin-shell";
import { AppShell } from "./shell";

/** Platform operators get the admin chrome; everyone else gets the party portal. */
export function ShellSwitch({ children }: { children: ReactNode }) {
  const { me, status } = useAuth();
  if (status === "authenticated" && me?.role === "PLATFORM_ADMIN") {
    return <AdminShell>{children}</AdminShell>;
  }
  return <AppShell>{children}</AppShell>;
}
