"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  FLAG_STATUS,
  SEVERITY_ORDER,
  cursorFrom,
  copy,
  flagStatus,
  formatDateTime,
  ruleTitle,
  severity,
  toastVerb,
  type Flag,
  type FlagDetail,
} from "@vtrs/core";
import { AlertTriangle, CheckCircle2, Eye, MessageSquare, RotateCcw, UserPlus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, QueryError } from "@/components/ui/feedback";
import { Field, Select, Textarea } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { AnomalyCard } from "@/components/vtrs/anomaly-card";
import { PageHeader } from "@/components/vtrs/page-header";
import { PuDetailPanel } from "@/components/vtrs/pu-detail";
import { Timeline } from "@/components/vtrs/timeline";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useElection } from "@/lib/election";

const ACTION_LABEL: Record<string, string> = {
  RAISED: "Raised",
  ESCALATED: "Escalated",
  ACKNOWLEDGED: "Acknowledged",
  ASSIGNED: "Assigned",
  COMMENTED: "Comment",
  RESOLVED: "Resolved",
  FALSE_POSITIVE: "Marked as a false positive",
  REOPENED: "Reopened",
};

export default function AnomaliesPage() {
  const { election } = useElection();
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [sev, setSev] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const list = useInfiniteQuery({
    queryKey: ["flags", election?.id, "list", status, sev],
    enabled: !!election,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      ep.flags.list(election!.id, {
        status: status || undefined,
        severity: sev || undefined,
        cursor: pageParam,
        limit: 50,
      }),
    getNextPageParam: (last) => cursorFrom(last.next),
  });
  const flags = useMemo(() => list.data?.pages.flatMap((p) => p.results) ?? [], [list.data]);

  // Most severe first, then newest, so the queue starts where attention is needed.
  const ordered = useMemo(
    () =>
      [...flags].sort(
        (a, b) =>
          severity(b.severity).rank - severity(a.severity).rank ||
          b.created_at.localeCompare(a.created_at),
      ),
    [flags],
  );

  const active = selected ?? ordered[0]?.id ?? null;

  const move = useCallback(
    (delta: number) => {
      if (ordered.length === 0) return;
      const index = ordered.findIndex((f) => f.id === active);
      const next = ordered[Math.min(ordered.length - 1, Math.max(0, index + delta))];
      if (next) setSelected(next.id);
    },
    [ordered, active],
  );

  // J and K step through the queue, as in the design system's keyboard model.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "j") move(1);
      else if (event.key === "k") move(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [move]);

  if (!election) {
    return (
      <>
        <PageHeader title="Anomalies" />
        <EmptyState
          icon={<AlertTriangle className="h-8 w-8" aria-hidden />}
          title="No election yet"
          description="Flags raised on results appear here once an election is live."
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Anomalies"
        description="Flags never remove a result from the count. They route it to a person to look at."
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Status" className="w-44">
          {(props) => (
            <Select {...props} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              {Object.entries(FLAG_STATUS).map(([value, v]) => (
                <option key={value} value={value}>
                  {v.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Severity" className="w-44">
          {(props) => (
            <Select {...props} value={sev} onChange={(e) => setSev(e.target.value)}>
              <option value="">All</option>
              {SEVERITY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {severity(value).label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <p className="pb-2 text-caption text-subtle-foreground">
          Press <kbd className="rounded border border-border px-1">J</kbd> and{" "}
          <kbd className="rounded border border-border px-1">K</kbd> to move through the list.
        </p>
      </div>

      {list.isError ? (
        <QueryError error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isLoading ? (
        <Skeleton className="h-96" />
      ) : ordered.length === 0 ? (
        <EmptyState
          icon={<CheckCircle2 className="h-8 w-8" aria-hidden />}
          title="No anomalies"
          description={copy.emptyAnomalies}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(320px,2fr)_3fr]">
          <div className="flex max-h-[calc(100vh-280px)] min-h-[320px] flex-col gap-2 overflow-y-auto pr-1">
            {ordered.map((flag) => (
              <AnomalyCard
                key={flag.id}
                flag={flag}
                selected={flag.id === active}
                onSelect={() => setSelected(flag.id)}
              />
            ))}
            {list.hasNextPage ? (
              <Button
                variant="outline"
                onClick={() => void list.fetchNextPage()}
                loading={list.isFetchingNextPage}
              >
                Load more
              </Button>
            ) : null}
          </div>
          <div className="min-w-0">
            {active ? (
              <FlagPanel
                flagId={active}
                canResolve={can("anomalies.resolve")}
                onOpenUnit={(pu) => setOpen(pu)}
                fallback={ordered.find((f) => f.id === active)}
              />
            ) : null}
          </div>
        </div>
      )}

      <PuDetailPanel
        electionId={open ? election.id : null}
        pollingUnitId={open}
        onClose={() => setOpen(null)}
      />
    </>
  );
}

function FlagPanel({
  flagId,
  canResolve,
  onOpenUnit,
  fallback,
}: {
  flagId: string;
  canResolve: boolean;
  onOpenUnit: (pollingUnitId: string) => void;
  fallback?: Flag;
}) {
  const { me } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [assignee, setAssignee] = useState("");
  const [resolveAs, setResolveAs] = useState<"RESOLVED" | "FALSE_POSITIVE" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["flags", "detail", flagId],
    queryFn: () => ep.flags.get(flagId),
  });
  const members = useQuery({
    queryKey: ["team", "assignees"],
    retry: false,
    queryFn: async () => (await ep.team.users({ limit: 200 })).results,
  });

  const refresh = (updated: FlagDetail) => {
    queryClient.setQueryData(["flags", "detail", flagId], updated);
    void queryClient.invalidateQueries({ queryKey: ["flags"] });
    setNote("");
    setError(null);
  };
  const fail = (e: unknown) =>
    setError(e instanceof ApiError ? e.detail : "That did not go through.");

  const acknowledge = useMutation({
    mutationFn: () => ep.flags.acknowledge(flagId),
    onSuccess: (d) => (refresh(d), toast(toastVerb.acknowledge)),
    onError: fail,
  });
  const comment = useMutation({
    mutationFn: () => ep.flags.comment(flagId, note.trim()),
    onSuccess: refresh,
    onError: fail,
  });
  const assign = useMutation({
    mutationFn: (id: string | null) => ep.flags.assign(flagId, id),
    onSuccess: (d) => (refresh(d), toast(toastVerb.assign)),
    onError: fail,
  });
  const resolve = useMutation({
    mutationFn: (outcome: "RESOLVED" | "FALSE_POSITIVE") =>
      ep.flags.resolve(flagId, { outcome, note: note.trim() }),
    onSuccess: (d) => {
      refresh(d);
      setResolveAs(null);
      toast(toastVerb.resolve);
    },
    onError: fail,
  });
  const reopen = useMutation({
    mutationFn: () => ep.flags.reopen(flagId, note.trim() || "Reopened"),
    onSuccess: refresh,
    onError: fail,
  });

  const flag = detail.data ?? (fallback as FlagDetail | undefined);
  if (detail.isLoading && !flag) return <Skeleton className="h-96" />;
  if (detail.isError && !flag)
    return <QueryError error={detail.error} onRetry={() => void detail.refetch()} />;
  if (!flag) return null;

  const closed = flag.status === "RESOLVED" || flag.status === "FALSE_POSITIVE";
  const events = "events" in flag ? flag.events : [];
  const sev = severity(flag.severity);
  const detailEntries = Object.entries((flag.details ?? {}) as Record<string, unknown>);

  return (
    <article className="flex flex-col gap-5 rounded-lg border border-border bg-card p-5 shadow-card">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={sev} />
          <StatusChip status={flagStatus(flag.status)} />
          {flag.escalation_level > 0 && !closed ? (
            <StatusChip status={{ label: "Escalated", tone: "amber", icon: "arrow-up-circle" }} />
          ) : null}
        </div>
        <h2 className="text-h2">{flag.title || ruleTitle(flag.rule_code)}</h2>
        {(flag.title || ruleTitle(flag.rule_code)) !== ruleTitle(flag.rule_code) ? (
          <p className="text-body text-strong-foreground">{ruleTitle(flag.rule_code)}</p>
        ) : null}
        <p className="text-body-sm text-subtle-foreground">
          {flag.polling_unit_name} <span className="mono">({flag.polling_unit_code})</span> ·{" "}
          {flag.ward_name} · {flag.lga_name} · raised {formatDateTime(flag.created_at)}
        </p>
        {flag.sla_due_at && !closed ? (
          <p className="text-body-sm text-signal-amber-text">
            Acknowledge by {formatDateTime(flag.sla_due_at)} or it escalates.
          </p>
        ) : null}
      </header>

      {detailEntries.length > 0 ? (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-md bg-muted p-4 sm:grid-cols-2">
          {detailEntries.map(([key, value]) => (
            <div key={key}>
              <dt className="text-caption text-subtle-foreground">{key.replace(/_/g, " ")}</dt>
              <dd className="tabular-nums text-body-sm font-semibold">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {flag.contest_id ? (
          <Button
            variant="outline"
            size="sm"
            leading={<Eye className="h-4 w-4" aria-hidden />}
            onClick={() => onOpenUnit(flag.polling_unit_id)}
          >
            Open polling unit
          </Button>
        ) : null}
        {canResolve && flag.status === "OPEN" ? (
          <Button
            size="sm"
            variant="secondary"
            loading={acknowledge.isPending}
            onClick={() => acknowledge.mutate()}
          >
            Acknowledge
          </Button>
        ) : null}
        {canResolve && !closed ? (
          <>
            <Button
              size="sm"
              onClick={() => setResolveAs("RESOLVED")}
              leading={<CheckCircle2 className="h-4 w-4" aria-hidden />}
            >
              Mark resolved
            </Button>
            <Button size="sm" variant="outline" onClick={() => setResolveAs("FALSE_POSITIVE")}>
              False positive
            </Button>
          </>
        ) : null}
        {canResolve && closed ? (
          <Button
            size="sm"
            variant="outline"
            loading={reopen.isPending}
            leading={<RotateCcw className="h-4 w-4" aria-hidden />}
            onClick={() => reopen.mutate()}
          >
            Reopen
          </Button>
        ) : null}
      </div>

      {canResolve && !closed ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Assign to" className="min-w-52 flex-1">
            {(props) => (
              <Select {...props} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                <option value="">Choose a person…</option>
                {me ? <option value={me.user_id}>Me</option> : null}
                {(members.data ?? [])
                  .filter(
                    (m) =>
                      m.user_id !== me?.user_id && m.status === "ACTIVE" && m.role !== "PU_AGENT",
                  )
                  .map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name}
                    </option>
                  ))}
              </Select>
            )}
          </Field>
          <Button
            variant="secondary"
            leading={<UserPlus className="h-4 w-4" aria-hidden />}
            disabled={!assignee}
            loading={assign.isPending}
            onClick={() => assign.mutate(assignee)}
          >
            Assign
          </Button>
        </div>
      ) : null}

      <Field label="Note" hint="Visible in this flag's history.">
        {(props) => (
          <Textarea
            {...props}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={1000}
          />
        )}
      </Field>
      <div>
        <Button
          variant="outline"
          size="sm"
          disabled={note.trim().length === 0}
          loading={comment.isPending}
          leading={<MessageSquare className="h-4 w-4" aria-hidden />}
          onClick={() => comment.mutate()}
        >
          Add note
        </Button>
      </div>

      {error ? (
        <p role="alert" className="text-body-sm font-medium text-signal-red-text">
          {error}
        </p>
      ) : null}

      <section>
        <h3 className="mb-3 text-h3">History</h3>
        <Timeline
          items={events.map((e, i) => ({
            id: `${e.at}-${i}`,
            title: ACTION_LABEL[e.action] ?? e.action,
            meta: formatDateTime(e.at),
            system: e.actor_id === null,
            detail: e.note || undefined,
          }))}
        />
      </section>

      <ConfirmDialog
        open={resolveAs !== null}
        onOpenChange={(next) => !next && setResolveAs(null)}
        title={
          resolveAs === "FALSE_POSITIVE" ? "Mark as a false positive?" : "Mark this flag resolved?"
        }
        description="A note is required. It is kept with the flag and in the audit log."
        confirmLabel={resolveAs === "FALSE_POSITIVE" ? "Mark false positive" : "Mark resolved"}
        loading={resolve.isPending}
        onConfirm={() => {
          if (!resolveAs) return;
          if (note.trim().length === 0) {
            setError("Add a note saying what you found.");
            setResolveAs(null);
            return;
          }
          resolve.mutate(resolveAs);
        }}
      >
        <Field label="Note">
          {(props) => (
            <Textarea
              {...props}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
            />
          )}
        </Field>
      </ConfirmDialog>
    </article>
  );
}
