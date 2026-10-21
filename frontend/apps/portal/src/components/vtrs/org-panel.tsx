"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { electionStatus, formatDate, formatDateTime, formatNumber } from "@vtrs/core";
import { Ban, Check, RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/card";
import { SidePanel } from "@/components/ui/dialog";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { describeError } from "@/lib/errors";
import { ep } from "@/lib/api";
import { orgStatus } from "@/lib/platform";
import { useStepUp } from "@/lib/step-up";
import { Timeline } from "./timeline";
import { TypedConfirm } from "./typed-confirm";

type Action = "approve" | "reject" | "suspend" | "reinstate";

const COPY: Record<
  Action,
  { title: string; confirm: string; danger: boolean; reason: string | null }
> = {
  approve: {
    title: "Approve this organisation?",
    confirm: "Approve organisation",
    danger: false,
    reason: null,
  },
  reject: {
    title: "Reject this organisation?",
    confirm: "Reject organisation",
    danger: true,
    reason: "Why is it rejected?",
  },
  suspend: {
    title: "Suspend this organisation?",
    confirm: "Suspend organisation",
    danger: true,
    reason: "Why is it suspended?",
  },
  reinstate: {
    title: "Reinstate this organisation?",
    confirm: "Reinstate organisation",
    danger: false,
    reason: null,
  },
};

const CONSEQUENCE: Record<Action, string> = {
  approve:
    "Its admin can sign in and set up elections. You will be asked for your authenticator code.",
  reject: "It cannot sign in. The reason is shown to the person who registered it.",
  suspend:
    "Everyone in this organisation is signed out at once, including agents in the field. Results already sent stay on record.",
  reinstate: "Everyone in this organisation can sign in again.",
};

/** One organisation: who is behind it, its elections, recent activity, and the decisions. */
export function OrgPanel({
  organizationId,
  onClose,
}: {
  organizationId: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const [action, setAction] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["platform", "org", organizationId],
    enabled: !!organizationId,
    queryFn: () => ep.platform.organization(organizationId!),
  });
  const org = detail.data?.organization;

  const decide = useMutation({
    mutationFn: (args: { action: Action; reason: string }) =>
      stepUp(() => {
        const id = organizationId!;
        switch (args.action) {
          case "approve":
            return ep.platform.approve(id);
          case "reject":
            return ep.platform.reject(id, args.reason);
          case "suspend":
            return ep.platform.suspend(id, args.reason);
          case "reinstate":
            return ep.platform.reinstate(id);
        }
      }),
    onSuccess: () => {
      toast("Decision recorded");
      setAction(null);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["platform"] });
    },
    onError: (e) => setError(describeError(e)),
  });

  const status = org?.status;
  return (
    <SidePanel
      open={!!organizationId}
      onOpenChange={(open) => !open && onClose()}
      title={org?.name ?? "Organisation"}
      description={org?.legal_name || undefined}
      width={600}
    >
      {detail.isLoading ? (
        <Skeleton className="h-64" />
      ) : detail.isError ? (
        <QueryError error={detail.error} onRetry={() => void detail.refetch()} />
      ) : org ? (
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip status={orgStatus(org.status)} />
            <span className="text-body-sm text-subtle-foreground">
              Registered {formatDate(org.created_at)}
              {org.approved_at ? ` · approved ${formatDate(org.approved_at)}` : ""}
            </span>
          </div>
          {org.status_reason ? (
            <InlineAlert tone="warning" title="Reason on record">
              {org.status_reason}
            </InlineAlert>
          ) : null}

          <dl className="grid grid-cols-3 gap-3">
            {(
              [
                ["People", org.people],
                ["Agents", org.agents],
                ["Elections", org.election_count],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-md bg-muted p-3">
                <dd className="tabular-nums text-h2 font-bold">{formatNumber(value)}</dd>
                <dt className="text-caption text-subtle-foreground">{label}</dt>
              </div>
            ))}
          </dl>

          <div className="flex flex-wrap gap-2">
            {status === "PENDING_APPROVAL" ? (
              <>
                <Button
                  leading={<Check className="h-4 w-4" aria-hidden />}
                  onClick={() => setAction("approve")}
                >
                  Approve
                </Button>
                <Button
                  variant="outline"
                  leading={<X className="h-4 w-4" aria-hidden />}
                  onClick={() => setAction("reject")}
                >
                  Reject
                </Button>
              </>
            ) : null}
            {status === "ACTIVE" ? (
              <Button
                variant="outline"
                leading={<Ban className="h-4 w-4" aria-hidden />}
                onClick={() => setAction("suspend")}
              >
                Suspend
              </Button>
            ) : null}
            {status === "SUSPENDED" ? (
              <Button
                leading={<RotateCcw className="h-4 w-4" aria-hidden />}
                onClick={() => setAction("reinstate")}
              >
                Reinstate
              </Button>
            ) : null}
          </div>

          <section>
            <h3 className="mb-2 text-h3">Who runs it</h3>
            {detail.data!.admins.length === 0 ? (
              <p className="text-body-sm text-subtle-foreground">No admin has been set up yet.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {detail.data!.admins.map((a) => (
                  <li key={a.user_id} className="rounded-md border border-border p-3 text-body-sm">
                    <p className="font-semibold">{a.full_name}</p>
                    <p className="text-subtle-foreground">
                      {a.email} · {a.phone || "no phone"}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {detail.data!.elections.length > 0 ? (
            <section>
              <h3 className="mb-2 text-h3">Elections</h3>
              <ul className="flex flex-col gap-2">
                {detail.data!.elections.map((e) => (
                  <li
                    key={e.id}
                    className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3"
                  >
                    <span className="text-body-sm font-semibold">{e.name}</span>
                    <StatusChip status={electionStatus(e.status)} />
                    <span className="ml-auto text-caption text-subtle-foreground">
                      {formatDate(e.election_date)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section>
            <h3 className="mb-3 text-h3">Recent activity</h3>
            <Timeline
              items={detail.data!.activity.map((a) => ({
                id: a.id,
                title: a.action.replace(/[._]/g, " "),
                meta: `${formatDateTime(a.at)} · ${a.actor_role || "system"}`,
                system: !a.actor_role,
              }))}
            />
          </section>
        </div>
      ) : null}

      {action && org ? (
        <TypedConfirm
          open
          onOpenChange={(open) => {
            if (!open) {
              setAction(null);
              setError(null);
            }
          }}
          title={COPY[action].title}
          description={`${org.name}. ${CONSEQUENCE[action]}`}
          phrase={org.name}
          confirmLabel={COPY[action].confirm}
          danger={COPY[action].danger}
          reasonLabel={COPY[action].reason ?? undefined}
          loading={decide.isPending}
          error={error}
          onConfirm={(reason) => decide.mutate({ action, reason })}
        />
      ) : null}
    </SidePanel>
  );
}
