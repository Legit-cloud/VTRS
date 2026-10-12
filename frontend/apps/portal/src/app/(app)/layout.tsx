import type { ReactNode } from "react";
import { ShellSwitch } from "@/components/shell/shell-switch";

export default function AppLayout({ children }: { children: ReactNode }) {
  return <ShellSwitch>{children}</ShellSwitch>;
}
