"use client";

import { useQuery } from "@tanstack/react-query";
import {
  formatDate,
  formatDateTime,
  reviewState,
  SUBMISSION_STATUS,
  type MyAssignment,
} from "@vtrs/core";
import { ArrowRight, ClipboardList, MapPin } from "lucide-react";
import Link from "next/link";
import { useSyncExternalStore } from "react";
import { buttonStyles } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { EmptyState, InlineAlert, QueryError } from "@/components/ui/feedback";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { hasDraft } from "@/lib/capture/draft";
import { cn } from "@/lib/cn";

/** FR-6.2.5: the agent sees their election and polling unit before they capture anything. */
export default function CapturePage() {
  const { me } = useAuth();
  const assignments = useQuery({
    queryKey: ["me", "assignments"],
    queryFn: () => ep.me.assignments(),
    refetchInterval: 60_000,
  });

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-h2">Hello, {me?.full_name.split(" ")[0]}</h1>
        <p className="text-body text-subtle-foreground">
          Your polling {assignments.data?.length === 1 ? "unit" : "units"} for result capture.
        </p>
      </div>
      {assignments.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      ) : assignments.isError ? (
        <QueryError error={assignments.error} onRetry={() => void assignments.refetch()} />
      ) : (assignments.data ?? []).length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="h-8 w-8" aria-hidden />}
          title="No polling unit yet"
          description="Your coordinator has not placed you at a polling unit for an election yet. Check again later, or ask them."
        />
      ) : (
        <ul className="flex flex-col gap-4">
          {assignments.data!.map((a) => (
            <li key={a.assignment_id}>
              <AssignmentCard assignment={a} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const noSubscription = () => () => {};

function AssignmentCard({ assignment }: { assignment: MyAssignment }) {
  const { election, polling_unit: pu } = assignment;
  // The draft lives in this browser only; the server render never has one.
  const draft = useSyncExternalStore(
    noSubscription,
    () => hasDraft(election.id, pu.id),
    () => false,
  );

  const result = assignment.result;
  const mine = assignment.my_latest;
  const base = `/capture/unit?election=${election.id}&pu=${pu.id}`;

  let phase: keyof typeof SUBMISSION_STATUS | null = null;
  if (result) phase = result.completion === "COMPLETE" ? "COMPLETE" : "NUMBERS_SUBMITTED";
  else if (draft) phase = "DRAFT";

  let action: { href: string; label: string; primary: boolean } | null = null;
  if (election.capture_open) {
    if (!result) {
      action = { href: base, label: draft ? "Continue your result" : "Enter the result", primary: true };
    } else if (result.state === "REJECTED") {
      action = { href: `${base}&correct=1`, label: "Send a corrected result", primary: true };
    } else if (result.completion !== "COMPLETE" && mine?.version_id === result.version_id) {
      action = {
        href: `${base}&step=sheet&version=${result.version_id}`,
        label: "Attach the result sheet",
        primary: true,
      };
    } else {
      action = { href: `${base}&correct=1`, label: "Correct this result", primary: false };
    }
  }

  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex flex-col gap-1">
        <p className="text-caption font-semibold uppercase tracking-wide text-subtle-foreground">
          {election.name} · {formatDate(election.election_date)}
        </p>
        <h2 className="text-h3">{pu.name}</h2>
        <p className="flex items-center gap-1.5 text-body-sm text-subtle-foreground">
          <MapPin className="h-4 w-4 shrink-0" aria-hidden />
          <span className="mono">{pu.inec_code}</span> · {pu.ward}, {pu.lga}
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {phase ? (
          <StatusChip status={SUBMISSION_STATUS[phase]} />
        ) : (
          <StatusChip status={{ label: "Not started", tone: "ink", icon: "circle-dashed" }} />
        )}
        {result ? <StatusChip status={reviewState(result.state)} /> : null}
      </div>

      {result?.state === "REJECTED" && result.review?.reason ? (
        <InlineAlert tone="danger" title="Your coordinator rejected this result">
          &ldquo;{result.review.reason}&rdquo; Send a corrected result with its sheet.
        </InlineAlert>
      ) : null}
      {result && result.completion !== "COMPLETE" && result.state !== "REJECTED" ? (
        <p className="text-body-sm text-signal-amber-text">
          {SUBMISSION_STATUS.NUMBERS_SUBMITTED.hint}
        </p>
      ) : null}
      {result ? (
        <p className="text-caption text-subtle-foreground">
          Version {result.version_no}, received {formatDateTime(result.server_received_at)}
        </p>
      ) : null}

      {!election.capture_open ? (
        <p className="text-body-sm text-subtle-foreground">
          {election.status === "LIVE"
            ? "Result capture is not open for this unit right now."
            : election.status === "CLOSED" || election.status === "RECONCILED"
              ? "Result capture has closed for this election."
              : "Result capture opens on election day, when polls close."}
        </p>
      ) : null}

      {action ? (
        <Link
          href={action.href}
          className={cn(
            buttonStyles({ variant: action.primary ? "primary" : "outline" }),
            "inline-flex w-full items-center justify-center gap-2 rounded-md font-semibold",
          )}
        >
          {action.label}
          <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      ) : null}
    </Card>
  );
}
