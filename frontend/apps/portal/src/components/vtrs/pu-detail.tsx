"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Checkbox from "@radix-ui/react-checkbox";
import {
  ApiError,
  flagStatus,
  formatDateTime,
  formatNumber,
  reviewState,
  ruleTitle,
  severity,
  SUBMISSION_STATUS,
  toastVerb,
  type HistoryVersion,
} from "@vtrs/core";
import { Check } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/ui/chip";
import { SidePanel } from "@/components/ui/dialog";
import { QueryError } from "@/components/ui/feedback";
import { Field, Textarea } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EvidenceCard } from "./evidence-card";
import { ProvisionalBadge } from "./provisional";
import { Timeline } from "./timeline";

interface Props {
  electionId: string | null;
  pollingUnitId: string | null;
  onClose: () => void;
}

/** One polling unit's result: the head version, its evidence, its history and the review actions. */
export function PuDetailPanel({ electionId, pollingUnitId, onClose }: Props) {
  const open = !!electionId && !!pollingUnitId;
  const { can } = useAuth();
  const history = useQuery({
    queryKey: ["results", "history", electionId, pollingUnitId],
    enabled: open,
    queryFn: () => ep.elections.history(electionId!, pollingUnitId!),
  });

  const data = history.data;
  const head = data?.versions.find((v) => v.is_head) ?? data?.versions[0];

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={data ? data.polling_unit_name : "Polling unit"}
      description={
        data
          ? `${data.polling_unit_code} · ${data.constituency_name}`
          : undefined
      }
      width={560}
    >
      {history.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-40" />
        </div>
      ) : history.isError ? (
        <QueryError error={history.error} onRetry={() => void history.refetch()} />
      ) : data && head ? (
        <div className="flex flex-col gap-6">
          <VersionSummary version={head} />
          {can("results.review") &&
          (head.state === "REQUIRES_REVIEW" || head.state === "SUBMITTED") ? (
            <ReviewActions version={head} onDone={onClose} />
          ) : null}

          <section>
            <h3 className="mb-2 text-h3">Result sheet</h3>
            {(head.evidence ?? []).length === 0 ? (
              <p className="text-body-sm text-subtle-foreground">
                No result sheet has been received for this version yet.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                {head.evidence!.map((e) => (
                  <EvidenceCard
                    key={e.evidence_id}
                    item={e}
                    canView={can("evidence.view")}
                    place={data.polling_unit_code}
                    capturedAt={formatDateTime(head.device_captured_at)}
                  />
                ))}
              </div>
            )}
          </section>

          {head.flags.length > 0 ? (
            <section>
              <h3 className="mb-2 text-h3">Flags on this version</h3>
              <ul className="flex flex-col gap-2">
                {head.flags.map((f) => (
                  <li
                    key={f.id}
                    className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3"
                  >
                    <StatusChip status={severity(f.severity)} />
                    <span className="text-body-sm font-semibold">{ruleTitle(f.rule_code)}</span>
                    <StatusChip status={flagStatus(f.status)} className="ml-auto" />
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section>
            <h3 className="mb-3 text-h3">History</h3>
            <Timeline
              items={data.versions.flatMap((v) => [
                {
                  id: v.version_id,
                  title: `Version ${v.version_no} ${v.is_head ? "(counting)" : ""}`.trim(),
                  meta: `${v.submitted_by.name} · received ${formatDateTime(v.server_received_at)}`,
                  system: false,
                  detail: (
                    <span>
                      {formatNumber(v.totals.valid)} valid votes · {reviewState(v.state).label}
                    </span>
                  ),
                },
                ...v.reviews.map((r, i) => ({
                  id: `${v.version_id}-r${i}`,
                  title: `${r.decision === "APPROVED" ? "Verified" : "Rejected"} version ${v.version_no}`,
                  meta: `${r.decided_by.name} · ${formatDateTime(r.decided_at)}`,
                  system: false,
                  detail: r.reason || undefined,
                })),
              ])}
            />
          </section>
        </div>
      ) : (
        <p className="text-body text-subtle-foreground">
          No result has been received for this unit yet.
        </p>
      )}
    </SidePanel>
  );
}

function VersionSummary({ version }: { version: HistoryVersion }) {
  const state = reviewState(version.state);
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={state} />
        <StatusChip
          status={SUBMISSION_STATUS[version.completion === "COMPLETE" ? "COMPLETE" : "NUMBERS_SUBMITTED"]}
        />
        {version.version_no > 1 ? (
          <StatusChip
            status={{ label: `Version ${version.version_no}`, tone: "amber", icon: "git-branch" }}
          />
        ) : null}
        <ProvisionalBadge className="ml-auto" />
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(
          [
            ["Accredited", version.totals.accredited],
            ["Valid", version.totals.valid],
            ["Rejected", version.totals.rejected],
            ["Total cast", version.totals.total_cast],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="rounded-md bg-muted p-3">
            <dd className="tabular-nums text-h2 font-bold">{formatNumber(value)}</dd>
            <dt className="text-caption text-subtle-foreground">{label}</dt>
          </div>
        ))}
      </dl>
      <table className="w-full text-left text-body-sm">
        <caption className="sr-only">Votes by party</caption>
        <thead>
          <tr className="border-b border-border text-label text-strong-foreground">
            <th className="py-2 pr-4 font-semibold">Party</th>
            <th className="py-2 pr-4 font-semibold">Contestant</th>
            <th className="py-2 text-right font-semibold">Votes</th>
          </tr>
        </thead>
        <tbody>
          {[...version.votes]
            .sort((a, b) => b.votes - a.votes)
            .map((v) => (
              <tr key={v.candidate_id} className="border-b border-border last:border-0">
                <td className="py-2 pr-4 font-semibold">{v.party_abbreviation}</td>
                <td className="py-2 pr-4 text-subtle-foreground">{v.name}</td>
                <td className="py-2 text-right tabular-nums">{formatNumber(v.votes)}</td>
              </tr>
            ))}
        </tbody>
      </table>
      <p className="text-caption text-subtle-foreground">
        Captured {formatDateTime(version.device_captured_at)} · received{" "}
        {formatDateTime(version.server_received_at)} (Africa/Lagos)
        {version.gps ? ` · GPS ${version.gps.lat}, ${version.gps.lng}` : " · no GPS position"}
      </p>
    </section>
  );
}

function ReviewActions({ version, onDone }: { version: HistoryVersion; onDone: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [acknowledge, setAcknowledge] = useState(false);
  const [mode, setMode] = useState<"idle" | "reject">("idle");
  const [error, setError] = useState<string | null>(null);
  const activeFlags = version.flags.filter(
    (f) => f.status === "OPEN" || f.status === "ACKNOWLEDGED",
  );
  // A result is verified against its sheet, so there is nothing to verify until it is in.
  const sheetIn = version.completion === "COMPLETE";

  const decide = useMutation({
    mutationFn: (decision: "APPROVED" | "REJECTED") =>
      ep.review.decide(version.version_id, {
        decision,
        reason: decision === "REJECTED" ? reason.trim() : undefined,
        acknowledge_flags: decision === "APPROVED" ? acknowledge : undefined,
      }),
    onSuccess: (_result, decision) => {
      toast(decision === "APPROVED" ? toastVerb.verify : toastVerb.reject);
      void queryClient.invalidateQueries({ queryKey: ["results"] });
      void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      void queryClient.invalidateQueries({ queryKey: ["dash"] });
      void queryClient.invalidateQueries({ queryKey: ["flags"] });
      onDone();
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "Could not record the decision."),
  });

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-canvas p-4">
      <h3 className="text-h3">Verify this result</h3>
      <p className="text-body-sm text-subtle-foreground">
        {sheetIn
          ? "Compare every number with the result sheet before you verify it."
          : "The agent has not attached the result sheet yet. You can reject the result now, or verify it once the sheet is in."}
      </p>
      {activeFlags.length > 0 ? (
        <label className="flex cursor-pointer items-start gap-3 text-body-sm">
          <Checkbox.Root
            checked={acknowledge}
            onCheckedChange={(v) => setAcknowledge(v === true)}
            className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-sm border-[1.5px] border-input bg-input-fill data-[state=checked]:border-primary data-[state=checked]:bg-primary"
          >
            <Checkbox.Indicator>
              <Check className="h-4 w-4 text-primary-foreground" aria-hidden />
            </Checkbox.Indicator>
          </Checkbox.Root>
          <span>
            I have looked at the {activeFlags.length} open{" "}
            {activeFlags.length === 1 ? "flag" : "flags"} on this result and it matches the sheet.
          </span>
        </label>
      ) : null}

      {mode === "reject" ? (
        <Field
          label="Why is it rejected?"
          hint="The agent sees this and sends a corrected result."
          error={error}
        >
          {(props) => (
            <Textarea
              {...props}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
            />
          )}
        </Field>
      ) : error ? (
        <p className="text-body-sm text-signal-red-text">{error}</p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {mode === "idle" ? (
          <>
            <Button
              leading={<Check className="h-4 w-4" aria-hidden />}
              loading={decide.isPending}
              disabled={!sheetIn || (activeFlags.length > 0 && !acknowledge)}
              onClick={() => decide.mutate("APPROVED")}
            >
              Verify result
            </Button>
            <Button variant="outline" onClick={() => setMode("reject")}>
              Reject result
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="danger"
              loading={decide.isPending}
              disabled={reason.trim().length < 3}
              onClick={() => decide.mutate("REJECTED")}
            >
              Reject result
            </Button>
            <Button variant="outline" onClick={() => setMode("idle")}>
              Cancel
            </Button>
          </>
        )}
      </div>
    </section>
  );
}
