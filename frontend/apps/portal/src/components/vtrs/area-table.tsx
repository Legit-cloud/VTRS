import {
  formatNumber,
  reviewState,
  SUBMISSION_STATUS,
  type AreaResult,
  type BallotParty,
  type Level,
} from "@vtrs/core";
import { StatusChip } from "@/components/ui/chip";
import type { Column } from "./data-table";
import { LeaderChip, leaderColor } from "./contestant-bar";
import { TallyMeter } from "./tally-meter";

const NOUN: Record<Level, string> = { lga: "LGA", ward: "Ward", pu: "Polling unit" };

/**
 * Columns for a drill-down list: the area (with a bar in its leader's colour), "X of Y
 * reported", one column per party, the leader (or "Tied" / "Narrow margin") and anomalies.
 * At polling-unit level, whether the result is verified and whether its sheet is in.
 */
export function areaColumns(level: Level, parties: readonly BallotParty[]): Column<AreaResult>[] {
  const isPu = level === "pu";
  const ordered = [...parties].sort((a, b) => a.ballot_order - b.ballot_order);
  const columns: Column<AreaResult>[] = [
    {
      key: "name",
      header: NOUN[level],
      cell: (r) => {
        const color = leaderColor(r.position, parties);
        return (
          <span className="flex items-center gap-2">
            <span
              aria-hidden
              className="h-6 w-1.5 shrink-0 rounded-full"
              style={
                color
                  ? { backgroundColor: color }
                  : { border: "1.5px dashed rgb(var(--input))", backgroundColor: "transparent" }
              }
            />
            <span className="font-semibold">
              {r.area_name}
              {isPu ? (
                <span className="mono ml-2 text-caption font-normal text-subtle-foreground">
                  {r.area_code}
                </span>
              ) : null}
            </span>
          </span>
        );
      },
      sortValue: (r) => r.area_name,
    },
  ];
  if (isPu) {
    columns.push({
      key: "status",
      header: "Result",
      cell: (r) =>
        r.status && r.status !== "NO_RESULT" ? (
          <span className="flex flex-wrap gap-1">
            <StatusChip status={reviewState(r.status)} />
            {r.completion ? (
              <StatusChip
                status={SUBMISSION_STATUS[r.completion === "COMPLETE" ? "COMPLETE" : "NUMBERS_SUBMITTED"]}
              />
            ) : null}
          </span>
        ) : (
          <span className="text-subtle-foreground">Not reported</span>
        ),
      sortValue: (r) => r.status ?? "",
    });
  } else {
    columns.push({
      key: "reported",
      header: "Reported",
      numeric: true,
      cell: (r) => (
        <div className="flex items-center justify-end gap-4">
          {r.expected_pus <= 24 ? (
            <TallyMeter
              reported={r.reported_pus}
              total={r.expected_pus}
              caption={false}
              className="hidden xl:flex"
            />
          ) : null}
          <span className="whitespace-nowrap">
            {formatNumber(r.reported_pus)} of {formatNumber(r.expected_pus)}
          </span>
        </div>
      ),
      sortValue: (r) => r.reported_pct,
    });
  }
  for (const party of ordered) {
    columns.push({
      key: `p-${party.party_id}`,
      header: party.abbreviation,
      numeric: true,
      cell: (r) => {
        const vote = r.votes.find((v) => v.party_id === party.party_id);
        return vote ? formatNumber(vote.votes) : <span className="text-subtle-foreground">–</span>;
      },
      sortValue: (r) => r.votes.find((v) => v.party_id === party.party_id)?.votes ?? -1,
    });
  }
  columns.push({
    key: "leader",
    header: "Leading",
    cell: (r) => <LeaderChip position={r.position} parties={parties} />,
    sortValue: (r) => r.position.leader_abbreviation ?? "",
  });
  columns.push({
    key: "flags",
    header: "Anomalies",
    numeric: true,
    cell: (r) =>
      r.open_flags > 0 ? (
        <span className="font-semibold text-signal-red-text">{r.open_flags}</span>
      ) : (
        <span className="text-subtle-foreground">0</span>
      ),
    sortValue: (r) => r.open_flags,
    hideOnNarrow: true,
  });
  return columns;
}
