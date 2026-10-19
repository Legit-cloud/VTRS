import {
  AlertTriangle,
  BookOpenCheck,
  FileDown,
  FileSearch,
  Gauge,
  History,
  ListChecks,
  Settings,
  Users,
  UsersRound,
  Vote,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Permission needed to see the item. Absent means every signed-in user. */
  permission?: string | string[];
}

/** Order from the design system (10.1). Items show only if the role permits them. */
export const NAV: NavItem[] = [
  { href: "/war-room", label: "War Room", icon: Gauge, permission: "dashboard.view" },
  { href: "/results", label: "Results", icon: ListChecks, permission: "results.view" },
  { href: "/anomalies", label: "Anomalies", icon: AlertTriangle, permission: "anomalies.view" },
  { href: "/agents", label: "Agents", icon: UsersRound, permission: "assignments.manage" },
  {
    href: "/elections",
    label: "Elections and contestants",
    icon: BookOpenCheck,
    permission: "elections.configure",
  },
  { href: "/parties", label: "Parties", icon: Vote, permission: "candidates.manage" },
  { href: "/evidence", label: "Evidence", icon: FileSearch, permission: "evidence.view" },
  { href: "/reports", label: "Reports", icon: FileDown, permission: "reports.export" },
  { href: "/team", label: "Team and permissions", icon: Users, permission: "users.manage" },
  { href: "/audit", label: "Audit log", icon: History, permission: "audit.view" },
  { href: "/settings", label: "Settings", icon: Settings },
];
