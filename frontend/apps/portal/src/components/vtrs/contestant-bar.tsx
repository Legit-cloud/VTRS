import {
  formatNumber,
  formatPercent,
  leaderStatus,
  type BallotParty,
  type PartyVote,
  type Position,
} from "@vtrs/core";
import { cn } from "@/lib/cn";
import { StatusChip } from "@/components/ui/chip";
import { ProvisionalBadge } from "./provisional";

/**
 * Contestant series (design system 2.1). The organisation's own party is always series 1
 * (teal); the others take the next colours in the election's ballot order. A series colour is
 * never the party's real colour, and it always comes with the abbreviation.
 */
const SERIES = ["#00907F", "#3D4FD6", "#C2408A", "#E0701A", "#7A5AC8", "#5B6B7A"];

export function partyColors(parties: readonly BallotParty[]): Record<string, string> {
  const colors: Record<string, string> = {};
  let next = 0;
  for (const party of [...parties].sort((a, b) => a.ballot_order - b.ballot_order)) {
    colors[party.party_id] = party.is_own
      ? SERIES[0]!
      : SERIES[1 + (next++ % (SERIES.length - 1))]!;
  }
  return colors;
}

/** The party's logo if it has one, otherwise its first letter on a quiet square. */
export function PartyMark({
  abbreviation,
  logoUrl,
  size = 24,
  className,
}: {
  abbreviation: string;
  logoUrl?: string | null;
  size?: number;
  className?: string;
}) {
  const style = { width: size, height: size };
  if (logoUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- short-lived signed URL
      <img
        src={logoUrl}
        alt=""
        style={style}
        className={cn("shrink-0 rounded-sm object-contain", className)}
      />
    );
  }
  return (
    <span
      aria-hidden
      style={style}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-sm bg-muted text-caption font-bold text-strong-foreground",
        className,
      )}
    >
      {abbreviation.charAt(0)}
    </span>
  );
}

export interface ContestantRow {
  partyId: string;
  abbreviation: string;
  logoUrl?: string | null;
  /** Set when the area is one constituency, where each party has one contestant. */
  candidateName?: string | null;
  votes: number;
  color: string;
}

export function toContestantRows(
  votes: readonly PartyVote[],
  parties: readonly BallotParty[],
): ContestantRow[] {
  const colors = partyColors(parties);
  const logos = Object.fromEntries(parties.map((p) => [p.party_id, p.logo_url]));
  return votes.map((v) => ({
    partyId: v.party_id,
    abbreviation: v.abbreviation,
    logoUrl: logos[v.party_id] ?? null,
    candidateName: v.candidate_name,
    votes: v.votes,
    color: colors[v.party_id] ?? SERIES[5]!,
  }));
}

/**
 * Every contestant side by side, largest first. The leader gets the provisional badge; tied
 * parties each get the "Tied" chip and a narrow lead the "Narrow margin" chip, so no single
 * winner is named where the count does not support one.
 */
export function ContestantBars({
  rows,
  position,
  className,
}: {
  rows: ContestantRow[];
  position: Position;
  className?: string;
}) {
  const total = rows.reduce((sum, r) => sum + r.votes, 0);
  const max = Math.max(1, ...rows.map((r) => r.votes));
  const leading = new Set(position.leading_party_ids);
  const sorted = [...rows].sort((a, b) => b.votes - a.votes);
  return (
    <ul className={cn("flex flex-col gap-4", className)}>
      {sorted.map((row) => {
        const pct = total === 0 ? 0 : (row.votes / total) * 100;
        const top = total > 0 && leading.has(row.partyId);
        return (
          <li key={row.partyId} className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <PartyMark abbreviation={row.abbreviation} logoUrl={row.logoUrl} />
                <span className="text-body font-semibold">{row.abbreviation}</span>
                {row.candidateName ? (
                  <span className="truncate text-body-sm text-subtle-foreground">
                    {row.candidateName}
                  </span>
                ) : null}
                {top && position.status === "LEADING" ? <ProvisionalBadge /> : null}
                {top && position.status !== "LEADING" ? (
                  <StatusChip status={leaderStatus(position.status)} />
                ) : null}
              </div>
              <span className="tabular-nums text-h3 font-bold">{formatNumber(row.votes)}</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${(row.votes / max) * 100}%`, backgroundColor: row.color }}
                />
              </div>
              <span className="w-14 text-right tabular-nums text-body-sm text-subtle-foreground">
                {formatPercent(pct)}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Who leads an area, in words and colour: the leader's abbreviation on its series colour, or
 * "Tied: A, B", or "Narrow margin" with the leader, or "No results yet".
 */
export function LeaderChip({
  position,
  parties,
  className,
}: {
  position: Position;
  parties: readonly BallotParty[];
  className?: string;
}) {
  const colors = partyColors(parties);
  const names = Object.fromEntries(parties.map((p) => [p.party_id, p.abbreviation]));
  if (position.status === "NO_VOTES") {
    return <StatusChip status={leaderStatus("NO_VOTES")} className={className} />;
  }
  if (position.status === "TIED") {
    const tied = position.leading_party_ids.map((id) => names[id] ?? "?").join(", ");
    return (
      <StatusChip status={leaderStatus("TIED")} label={`Tied: ${tied}`} className={className} />
    );
  }
  const leader = position.leader_party_id ?? "";
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
      <span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-border bg-card px-2 text-label font-semibold">
        <span
          aria-hidden
          className="h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: colors[leader] }}
        />
        {position.leader_abbreviation ?? names[leader]}
      </span>
      {position.status === "NARROW" ? <StatusChip status={leaderStatus("NARROW")} /> : null}
    </span>
  );
}

/** The leader's series colour for a row's left bar; none for ties or empty areas. */
export function leaderColor(position: Position, parties: readonly BallotParty[]): string | null {
  if (position.status !== "LEADING" && position.status !== "NARROW") return null;
  return partyColors(parties)[position.leader_party_id ?? ""] ?? null;
}
