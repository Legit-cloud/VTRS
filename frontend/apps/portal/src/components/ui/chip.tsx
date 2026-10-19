import {
  AlertCircle,
  AlertOctagon,
  AlertTriangle,
  ArrowUpCircle,
  BadgeCheck,
  Ban,
  Check,
  CheckCircle2,
  Circle,
  CircleDashed,
  CircleDot,
  Clock,
  Equal,
  Eye,
  FileClock,
  FilePenLine,
  Flag,
  GitBranch,
  Inbox,
  Info,
  Lock,
  Mail,
  Pencil,
  Radio,
  Scale,
  RefreshCw,
  Settings,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Siren,
  Square,
  Star,
  TimerOff,
  TrendingUp,
  UserX,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { StatusView, Tone } from "@vtrs/core";
import { cn } from "@/lib/cn";

const toneClass: Record<Tone, string> = {
  ink: "bg-signal-ink-soft text-signal-ink-text",
  blue: "bg-signal-blue-soft text-signal-blue-text",
  teal: "bg-signal-teal-soft text-signal-teal-text",
  amber: "bg-signal-amber-soft text-signal-amber-text",
  red: "bg-signal-red-soft text-signal-red-text",
};

/**
 * The status vocabulary names icons by their Lucide kebab-case name. A fixed table keeps the
 * bundle to the icons actually used and lets a typo fall back to a plain circle.
 */
const ICONS: Record<string, LucideIcon> = {
  "alert-circle": AlertCircle,
  "alert-octagon": AlertOctagon,
  "alert-triangle": AlertTriangle,
  "arrow-up-circle": ArrowUpCircle,
  "badge-check": BadgeCheck,
  ban: Ban,
  check: Check,
  "check-circle-2": CheckCircle2,
  circle: Circle,
  "circle-dashed": CircleDashed,
  "circle-dot": CircleDot,
  clock: Clock,
  equal: Equal,
  eye: Eye,
  "file-clock": FileClock,
  "file-pen-line": FilePenLine,
  flag: Flag,
  "git-branch": GitBranch,
  inbox: Inbox,
  info: Info,
  lock: Lock,
  mail: Mail,
  pencil: Pencil,
  radio: Radio,
  scale: Scale,
  "refresh-cw": RefreshCw,
  settings: Settings,
  "settings-2": Settings2,
  "shield-alert": ShieldAlert,
  "shield-check": ShieldCheck,
  "sliders-horizontal": SlidersHorizontal,
  siren: Siren,
  square: Square,
  star: Star,
  "timer-off": TimerOff,
  "trending-up": TrendingUp,
  "user-x": UserX,
  "x-circle": XCircle,
};

/** Fill = signal 50, text = signal 700, always an icon and a word (never a bare dot). */
export function StatusChip({
  status,
  label,
  className,
}: {
  status: StatusView;
  label?: string;
  className?: string;
}) {
  const Icon = ICONS[status.icon] ?? Circle;
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full px-2 text-label font-semibold",
        toneClass[status.tone],
        className,
      )}
    >
      <Icon className={cn("h-3.5 w-3.5", status.icon === "refresh-cw" && "spin")} aria-hidden />
      {label ?? status.label}
    </span>
  );
}
