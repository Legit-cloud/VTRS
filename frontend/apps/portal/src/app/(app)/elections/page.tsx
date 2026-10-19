"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  constituencyKind,
  electionStatus,
  formatDate,
  formatDateTime,
  formatNumber,
  toastVerb,
  type ConfigIssue,
  type Constituency,
  type Contestant,
  type Election,
  type ElectionParty,
} from "@vtrs/core";
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CheckCircle2,
  Circle,
  Flag,
  Lock,
  Pencil,
  Plus,
  Trash2,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { ConfirmDialog, SidePanel } from "@/components/ui/dialog";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import {
  useConfiguration,
  type Configuration,
  type ConstituencySetup,
} from "@/components/elections/use-configuration";
import { StageTracker } from "@/components/elections/workflow";
import { PartyMark } from "@/components/vtrs/contestant-bar";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useElection } from "@/lib/election";
import { errorLines } from "@/lib/errors";
import { useStates } from "@/lib/geo-names";
import { useStepUp } from "@/lib/step-up";

/** Which count the War Room shows first. Both are always stored; this only picks the default. */
const DISPLAY = [
  {
    value: "REPORTED" as const,
    title: "All results as they arrive",
    body: "Every result counts as soon as it arrives. Coordinators verify them against the sheet, and anyone can switch to verified results only.",
  },
  {
    value: "VERIFIED" as const,
    title: "Verified results only",
    body: "The War Room opens on results a coordinator has verified against the uploaded sheet. Slower, but every number has been checked. All results stay one click away.",
  },
];

const displayOf = (e: Pick<Election, "count_policy">) =>
  DISPLAY.find((d) => d.value === (e.count_policy ?? "REPORTED")) ?? DISPLAY[0]!;

export default function ElectionsPage() {
  const { elections, election, select, loading, error, refetch } = useElection();
  const { states } = useStates();
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader
        title="Elections"
        description="Set up an election, lock it, then run it. Each step unlocks the next, and this page always says what to do now."
        actions={
          elections.length > 0 ? (
            <Button
              leading={<Plus className="h-4 w-4" aria-hidden />}
              onClick={() => setCreating(true)}
            >
              New election
            </Button>
          ) : undefined
        }
      />

      {loading ? (
        <Skeleton className="h-48" />
      ) : error ? (
        <QueryError error={error} onRetry={refetch} />
      ) : elections.length === 0 ? (
        <FirstElection onStart={() => setCreating(true)} />
      ) : (
        <div className="flex flex-col gap-8">
          {elections.length > 1 ? (
            <section aria-label="Your elections">
              <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {elections.map((e) => {
                  const active = e.id === election?.id;
                  const where = states.find((s) => s.id === e.state_id)?.name;
                  return (
                    <li key={e.id}>
                      <button
                        type="button"
                        onClick={() => select(e.id)}
                        aria-pressed={active}
                        className={cn(
                          "flex w-full flex-col items-start gap-2 rounded-lg border p-4 text-left transition-colors",
                          active
                            ? "border-primary bg-primary-soft"
                            : "border-border bg-card hover:bg-muted",
                        )}
                      >
                        <span className="text-body font-semibold">{e.name}</span>
                        <span className="text-body-sm text-subtle-foreground">
                          {e.election_type_name}
                          {where ? ` · ${where}` : ""} · {formatDate(e.election_date)}
                        </span>
                        <StatusChip status={electionStatus(e.status ?? "DRAFT")} />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
          {election ? <Workspace key={election.id} electionId={election.id} /> : null}
        </div>
      )}

      <CreateElectionPanel
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(id) => select(id)}
      />
    </>
  );
}

/** The first thing someone sees: what they are about to do, in four steps. */
function FirstElection({ onStart }: { onStart: () => void }) {
  const steps: [string, string][] = [
    ["Create the election", "Its type, the state and the election day."],
    [
      "Choose the parties and contestants",
      "Which parties contest, in the order agents see them, and each party's candidate per constituency.",
    ],
    ["Lock it", "Freezes the setup so agents and coordinators work from one fixed list."],
    ["Go live", "Agents send results; the War Room fills in as they arrive."],
  ];
  return (
    <Card className="p-6 md:p-8">
      <h2 className="text-h2">Set up your first election</h2>
      <p className="mt-1 max-w-2xl text-body text-subtle-foreground">
        It takes a few minutes. You can change anything until you lock it.{" "}
        <Link href="/parties" className="font-semibold text-primary">
          Add your party list first
        </Link>{" "}
        if you have not yet.
      </p>
      <ol className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        {steps.map(([title, body], i) => (
          <li key={title} className="flex gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-label font-bold text-primary-soft-foreground">
              {i + 1}
            </span>
            <span>
              <span className="block text-body font-semibold">{title}</span>
              <span className="block text-body-sm text-subtle-foreground">{body}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="mt-8">
        <Button onClick={onStart} trailing={<ArrowRight className="h-4 w-4" aria-hidden />}>
          Create an election
        </Button>
      </div>
    </Card>
  );
}

// ---- the workspace for one election ------------------------------------------------------

function Workspace({ electionId }: { electionId: string }) {
  const queryClient = useQueryClient();
  const config = useConfiguration(electionId);
  const detail = useQuery({
    queryKey: ["election", electionId],
    queryFn: () => ep.elections.get(electionId),
  });
  const [adding, setAdding] = useState<{ constituency: Constituency | null } | null>(null);
  const [editing, setEditing] = useState(false);

  const election = detail.data?.data;
  const etag = detail.data?.etag ?? "";
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["election", electionId] });
    void queryClient.invalidateQueries({ queryKey: ["elections"] });
    void queryClient.invalidateQueries({ queryKey: ["election-parties", electionId] });
    void queryClient.invalidateQueries({ queryKey: ["contestants", electionId] });
  };

  if (detail.isLoading) return <Skeleton className="h-64" />;
  if (detail.isError || !election) {
    return <QueryError error={detail.error} onRetry={() => void detail.refetch()} />;
  }
  const editable = election.status === "DRAFT" || election.status === "CONFIGURED";

  return (
    <div className="flex flex-col gap-6">
      <Card className="p-5 md:p-6">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <h2 className="text-h2">{election.name}</h2>
          <StatusChip status={electionStatus(election.status ?? "DRAFT")} />
        </div>
        <StageTracker status={election.status ?? "DRAFT"} />
      </Card>

      <NextStep
        election={election}
        config={config}
        onChanged={refresh}
        onAddContestants={() => setAdding({ constituency: null })}
      />

      <IssuesCard electionId={electionId} />

      <DetailsCard
        election={election}
        etag={etag}
        editable={editable}
        editing={editing}
        setEditing={setEditing}
        onSaved={refresh}
      />

      <PartiesCard
        electionId={electionId}
        parties={config.parties}
        loading={config.loading}
        editable={editable}
        onSaved={refresh}
      />

      <ContestantsCard
        election={election}
        config={config}
        editable={editable}
        onAdd={(constituency) => setAdding({ constituency })}
        onChanged={refresh}
      />

      {editable ? (
        <DeleteElection
          election={election}
          contestants={config.contestantCount}
          onDeleted={refresh}
        />
      ) : null}

      <AddContestantPanel
        // A fresh panel each time it opens, starting from the constituency it was opened for.
        key={adding ? `open-${adding.constituency?.id ?? "any"}` : "closed"}
        open={!!adding}
        election={election}
        parties={config.parties}
        constituencies={config.constituencies}
        initial={adding?.constituency ?? null}
        onClose={() => setAdding(null)}
        onAdded={refresh}
      />
    </div>
  );
}

// ---- what to do now -----------------------------------------------------------------------

function NextStep({
  election,
  config,
  onChanged,
  onAddContestants,
}: {
  election: Election;
  config: Configuration;
  onChanged: () => void;
  onAddContestants: () => void;
}) {
  const toast = useToast();
  const stepUp = useStepUp();
  const [confirm, setConfirm] = useState<"lock" | "live" | "close" | "reconcile" | null>(null);
  const [problem, setProblem] = useState<string[]>([]);
  const status = election.status ?? "DRAFT";

  const readiness = useQuery({
    queryKey: ["election", election.id, "readiness"],
    enabled: status === "CLOSED" || status === "RECONCILED",
    queryFn: () => ep.elections.readiness(election.id),
  });

  const move = useMutation({
    mutationFn: async (action: "ready" | "draft" | "lock" | "live" | "close" | "reconcile") => {
      switch (action) {
        case "lock":
          return stepUp(() => ep.elections.lock(election.id));
        case "reconcile":
          return stepUp(() => ep.elections.reconcile(election.id));
        case "ready":
          return ep.elections.transition(election.id, "CONFIGURED");
        case "draft":
          return ep.elections.transition(election.id, "DRAFT");
        case "live":
          return ep.elections.transition(election.id, "LIVE");
        case "close":
          return ep.elections.transition(election.id, "CLOSED");
      }
    },
    onSuccess: () => {
      setConfirm(null);
      setProblem([]);
      onChanged();
      toast("Election updated");
    },
    onError: (e) => {
      setConfirm(null);
      setProblem(errorLines(e, "That change was refused."));
    },
  });

  const counts = `${formatNumber(config.parties.length)} ${
    config.parties.length === 1 ? "party" : "parties"
  } and ${formatNumber(config.contestantCount)} ${
    config.contestantCount === 1 ? "contestant" : "contestants"
  }`;

  let heading = "";
  let body: React.ReactNode = null;
  let actions: React.ReactNode = null;

  if (status === "DRAFT") {
    heading = "Finish setting up";
    body = (
      <>
        <p className="text-body text-subtle-foreground">
          Choose the contesting parties and add each party&apos;s contestant per constituency.
          When the checklist is complete, mark the election ready.
        </p>
        <Checklist config={config} onAddContestants={onAddContestants} />
      </>
    );
    actions = (
      <Button
        disabled={!config.ready}
        loading={move.isPending}
        onClick={() => move.mutate("ready")}
        trailing={<ArrowRight className="h-4 w-4" aria-hidden />}
      >
        Mark as ready
      </Button>
    );
  } else if (status === "CONFIGURED") {
    heading = "Ready to lock";
    body = (
      <>
        <p className="text-body text-subtle-foreground">
          Setup is complete: {counts}. Locking freezes them, so everyone works from the same list.
          You can still go back and edit until you lock.
        </p>
        <Checklist config={config} onAddContestants={onAddContestants} />
      </>
    );
    actions = (
      <>
        <Button
          disabled={!config.ready}
          leading={<Lock className="h-4 w-4" aria-hidden />}
          onClick={() => setConfirm("lock")}
        >
          Lock the election
        </Button>
        <Button variant="outline" loading={move.isPending} onClick={() => move.mutate("draft")}>
          Back to editing
        </Button>
      </>
    );
  } else if (status === "LOCKED") {
    heading = "Locked. Now place your agents";
    body = (
      <p className="text-body text-subtle-foreground">
        The setup is frozen{election.locked_at ? ` (${formatDateTime(election.locked_at)})` : ""}.
        Invite agents and assign each to a polling unit. When polling starts, open result capture so
        they can send results.
      </p>
    );
    actions = (
      <>
        <Link href="/agents">
          <Button leading={<Users className="h-4 w-4" aria-hidden />}>Assign agents</Button>
        </Link>
        <Button variant="secondary" onClick={() => setConfirm("live")}>
          Open result capture
        </Button>
      </>
    );
  } else if (status === "LIVE") {
    heading = "Live. Agents can send results";
    body = (
      <p className="text-body text-subtle-foreground">
        Results appear in the War Room as they arrive. Close result capture when voting and
        collation are over.
      </p>
    );
    actions = (
      <>
        <Link href="/war-room">
          <Button>Open the War Room</Button>
        </Link>
        <Button variant="outline" onClick={() => setConfirm("close")}>
          Close result capture
        </Button>
      </>
    );
  } else if (status === "CLOSED") {
    heading = "Closed. Confirm the results";
    body = (
      <>
        <p className="text-body text-subtle-foreground">
          No more results can be sent. Reconciling checks every figure a second time and stores a
          permanent record. After that, results cannot change.
        </p>
        {readiness.data ? (
          readiness.data.can_reconcile ? (
            <p className="flex items-center gap-2 text-body-sm font-medium">
              <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden /> Ready to reconcile.
            </p>
          ) : (
            <InlineAlert tone="warning" title="Not ready yet">
              {formatNumber(readiness.data.unverified_results)} results still need a decision
              {readiness.data.rollup_differences.length
                ? `, and ${readiness.data.rollup_differences.length} totals differ from a fresh count`
                : ""}
              .
            </InlineAlert>
          )
        ) : null}
      </>
    );
    actions = (
      <Button
        disabled={readiness.data ? !readiness.data.can_reconcile : true}
        onClick={() => setConfirm("reconcile")}
      >
        Reconcile results
      </Button>
    );
  } else {
    heading = "Finished";
    body = (
      <p className="text-body text-subtle-foreground">
        The results are confirmed and permanently recorded.
        {readiness.data?.snapshot_sha256
          ? ` Record ${readiness.data.snapshot_sha256.slice(0, 12)}…`
          : ""}
      </p>
    );
  }

  return (
    <Card className="border-primary/40 p-5 md:p-6">
      <p className="text-label font-semibold text-primary">Next step</p>
      <h2 className="mt-0.5 text-h2">{heading}</h2>
      <div className="mt-2 flex flex-col gap-4">{body}</div>
      {problem.length > 0 ? (
        <div className="mt-4">
          <InlineAlert tone="danger" title="That could not be done yet">
            <ul className="list-disc pl-5">
              {problem.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </InlineAlert>
        </div>
      ) : null}
      {actions ? <div className="mt-5 flex flex-wrap gap-3">{actions}</div> : null}

      <ConfirmDialog
        open={confirm === "lock"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Lock this election?"
        description={`${counts} will be frozen. You will not be able to add, remove or reorder parties or contestants afterwards. You will be asked for your authenticator code.`}
        confirmLabel="Lock the election"
        loading={move.isPending}
        onConfirm={() => move.mutate("lock")}
      />
      <ConfirmDialog
        open={confirm === "live"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Open result capture?"
        description="Agents who are assigned to polling units can send results from this moment."
        confirmLabel="Open result capture"
        loading={move.isPending}
        onConfirm={() => move.mutate("live")}
      />
      <ConfirmDialog
        open={confirm === "close"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Close result capture?"
        description="Agents will no longer be able to send results for this election. You can still verify what has arrived."
        confirmLabel="Close result capture"
        danger
        loading={move.isPending}
        onConfirm={() => move.mutate("close")}
      />
      <ConfirmDialog
        open={confirm === "reconcile"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Reconcile the results?"
        description="Every figure is checked a second time and a permanent record is stored. Results cannot change afterwards. You will be asked for your authenticator code."
        confirmLabel="Reconcile results"
        loading={move.isPending}
        onConfirm={() => move.mutate("reconcile")}
      />
    </Card>
  );
}

function Checklist({
  config,
  onAddContestants,
}: {
  config: Configuration;
  onAddContestants: () => void;
}) {
  if (config.loading) return <Skeleton className="h-24" />;
  const n = config.parties.length;
  return (
    <ul className="flex flex-col gap-2" aria-label="What is left to do">
      <Item done>The election has a type, a state and a date</Item>
      <Item done={n >= 2}>
        {n >= 2
          ? `${formatNumber(n)} contesting parties, in display order`
          : n === 1
            ? "One contesting party chosen. Choose at least one more"
            : "Choose the contesting parties"}
      </Item>
      <Item done={config.constituencies.length > 0}>
        {config.constituencies.length > 0
          ? `Contestants in ${formatNumber(config.constituencies.length)} ${
              config.constituencies.length === 1 ? "constituency" : "constituencies"
            }`
          : "Add each party's contestant for a constituency"}
        {config.constituencies.length === 0 && n >= 2 ? (
          <button
            type="button"
            className="ml-3 font-semibold text-primary"
            onClick={onAddContestants}
          >
            Add contestants
          </button>
        ) : null}
      </Item>
      {config.constituencies
        .filter((g) => g.problems.length > 0)
        .flatMap((g) => g.problems)
        .map((p) => (
          <Item key={p}>{p}</Item>
        ))}
      {config.advice.map((a) => (
        <li key={a} className="flex items-start gap-2 text-body-sm text-subtle-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {a}
        </li>
      ))}
    </ul>
  );
}

function Item({ done, children }: { done?: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-body-sm">
      {done ? (
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-label="Done" />
      ) : (
        <Circle
          className="mt-0.5 h-4 w-4 shrink-0 text-subtle-foreground"
          aria-label="Still to do"
        />
      )}
      <span>{children}</span>
    </li>
  );
}

// ---- configuration issues raised by agents -----------------------------------------------

function IssuesCard({ electionId }: { electionId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [resolving, setResolving] = useState<ConfigIssue | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string[]>([]);
  const issues = useQuery({
    queryKey: ["config-issues", electionId],
    queryFn: async () => (await ep.elections.issues(electionId, { status: "OPEN", limit: 100 })).results,
  });
  const resolve = useMutation({
    mutationFn: () => ep.configIssues.resolve(resolving!.id, note.trim()),
    onSuccess: () => {
      toast(toastVerb.issueResolved);
      setResolving(null);
      setNote("");
      setError([]);
      void queryClient.invalidateQueries({ queryKey: ["config-issues", electionId] });
    },
    onError: (e) => setError(errorLines(e, "Could not resolve the issue.")),
  });

  const open = issues.data ?? [];
  if (issues.isLoading || open.length === 0) return null;

  return (
    <Card className="border-signal-amber-mark">
      <CardHeader
        title={`${formatNumber(open.length)} ${open.length === 1 ? "report" : "reports"} from agents`}
        description="An agent could not find a party or contestant on their result form. Fix the setup if they are right, then resolve the report with a note."
      />
      <ul className="divide-y divide-border p-5 pt-0">
        {open.map((issue) => (
          <li key={issue.id} className="flex flex-wrap items-start gap-3 py-3">
            <Flag className="mt-1 h-4 w-4 shrink-0 text-signal-amber-text" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-body-sm font-semibold">
                {issue.kind === "PARTY_MISSING" ? "Party missing" : "Contestant missing"} ·{" "}
                {issue.polling_unit_name}{" "}
                <span className="mono font-normal text-subtle-foreground">
                  {issue.polling_unit_code}
                </span>
              </p>
              <p className="text-body-sm">&ldquo;{issue.note}&rdquo;</p>
              <p className="text-caption text-subtle-foreground">
                {issue.raised_by_name} · {issue.ward_name}, {issue.lga_name} ·{" "}
                {formatDateTime(issue.created_at)}
              </p>
            </div>
            <Button size="sm" variant="secondary" onClick={() => setResolving(issue)}>
              Resolve
            </Button>
          </li>
        ))}
      </ul>
      <SidePanel
        open={!!resolving}
        onOpenChange={(next) => {
          if (!next) {
            setResolving(null);
            setError([]);
          }
        }}
        title="Resolve this report"
        description="Say what you did, or why nothing needed changing. The note is kept with the report."
        footer={
          <>
            <Button variant="outline" onClick={() => setResolving(null)}>
              Cancel
            </Button>
            <Button
              loading={resolve.isPending}
              disabled={note.trim().length < 3}
              onClick={() => resolve.mutate()}
            >
              Resolve
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {error.length > 0 ? (
            <InlineAlert tone="danger" title="Not resolved">
              {error.join(" ")}
            </InlineAlert>
          ) : null}
          {resolving ? (
            <p className="rounded-md bg-muted p-3 text-body-sm">&ldquo;{resolving.note}&rdquo;</p>
          ) : null}
          <Field label="Resolution note">
            {(p) => (
              <Textarea
                {...p}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={500}
              />
            )}
          </Field>
        </div>
      </SidePanel>
    </Card>
  );
}

// ---- election details ---------------------------------------------------------------------

function DetailsCard({
  election,
  etag,
  editable,
  editing,
  setEditing,
  onSaved,
}: {
  election: Election;
  etag: string;
  editable: boolean;
  editing: boolean;
  setEditing: (v: boolean) => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(election.name);
  const [date, setDate] = useState(election.election_date);
  const [display, setDisplay] = useState(displayOf(election).value);
  const [error, setError] = useState<string[]>([]);
  const { states } = useStates();

  const save = useMutation({
    mutationFn: () =>
      ep.elections.update(
        election.id,
        { name: name.trim(), election_date: date, count_policy: display },
        etag,
      ),
    onSuccess: () => {
      toast("Election saved");
      setError([]);
      setEditing(false);
      onSaved();
    },
    onError: (e) => setError(errorLines(e, "Could not save.")),
  });

  const stateLabel = states.find((s) => s.id === election.state_id)?.name ?? "Selected state";

  return (
    <Card>
      <CardHeader
        title="Election details"
        actions={
          editable && !editing ? (
            <Button
              size="sm"
              variant="outline"
              leading={<Pencil className="h-4 w-4" aria-hidden />}
              onClick={() => setEditing(true)}
            >
              Edit
            </Button>
          ) : undefined
        }
      />
      {editing ? (
        <form
          className="flex flex-col gap-4 p-5 pt-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          {error.length > 0 ? (
            <InlineAlert tone="danger" title="Not saved">
              {error.join(" ")}
            </InlineAlert>
          ) : null}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Election name">
              {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
            </Field>
            <Field label="Election day">
              {(p) => (
                <Input {...p} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              )}
            </Field>
          </div>
          <DisplayChoice value={display} onChange={setDisplay} />
          <div className="flex gap-3">
            <Button type="submit" loading={save.isPending}>
              Save changes
            </Button>
            <Button type="button" variant="outline" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <dl className="grid grid-cols-1 gap-x-8 gap-y-3 p-5 pt-2 md:grid-cols-2">
          <Row label="Type">
            {election.election_type_name} ({constituencyKind(election.constituency_kind)}{" "}
            constituencies)
          </Row>
          <Row label="State">{stateLabel}</Row>
          <Row label="Election day">{formatDate(election.election_date)}</Row>
          <Row label="The War Room opens on">{displayOf(election).title}</Row>
          {election.locked_at ? (
            <Row label="Locked">{formatDateTime(election.locked_at)}</Row>
          ) : null}
        </dl>
      )}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-caption text-subtle-foreground">{label}</dt>
      <dd className="text-body font-medium">{children}</dd>
    </div>
  );
}

function DisplayChoice({
  value,
  onChange,
}: {
  value: "REPORTED" | "VERIFIED";
  onChange: (value: "REPORTED" | "VERIFIED") => void;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-label text-strong-foreground">
        What should the War Room show first?
      </legend>
      {DISPLAY.map((d) => (
        <label
          key={d.value}
          className={cn(
            "flex cursor-pointer items-start gap-3 rounded-md border p-3",
            value === d.value ? "border-primary bg-primary-soft" : "border-border hover:bg-muted",
          )}
        >
          <input
            type="radio"
            name="display"
            className="mt-1 h-4 w-4 accent-[rgb(var(--primary))]"
            checked={value === d.value}
            onChange={() => onChange(d.value)}
          />
          <span>
            <span className="block text-body-sm font-semibold">{d.title}</span>
            <span className="block text-caption text-subtle-foreground">{d.body}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

// ---- contesting parties -------------------------------------------------------------------

function PartiesCard({
  electionId,
  parties,
  loading,
  editable,
  onSaved,
}: {
  electionId: string;
  parties: ElectionParty[];
  loading: boolean;
  editable: boolean;
  onSaved: () => void;
}) {
  const toast = useToast();
  const master = useQuery({ queryKey: ["parties"], queryFn: () => ep.parties.list() });
  const [order, setOrder] = useState<string[] | null>(null);
  const [adding, setAdding] = useState("");
  const [error, setError] = useState<string[]>([]);

  // Until the person changes something, show what the server has.
  const current = useMemo(() => parties.map((p) => p.party_id), [parties]);
  const ids = order ?? current;
  const dirty = order !== null && order.join() !== current.join();
  const byId = useMemo(() => {
    const map: Record<string, { abbreviation: string; full_name: string; logo_url: string | null; is_own: boolean }> = {};
    for (const p of master.data ?? []) {
      map[p.id] = {
        abbreviation: p.abbreviation,
        full_name: p.full_name,
        logo_url: p.logo_url,
        is_own: !!p.is_own,
      };
    }
    for (const p of parties) map[p.party_id] = p;
    return map;
  }, [master.data, parties]);
  const available = (master.data ?? []).filter((p) => !ids.includes(p.id));

  const save = useMutation({
    mutationFn: () => ep.elections.setParties(electionId, ids),
    onSuccess: () => {
      toast("Contesting parties saved");
      setOrder(null);
      setError([]);
      onSaved();
    },
    onError: (e) => setError(errorLines(e, "Could not save the parties.")),
  });

  const move = (index: number, by: -1 | 1) => {
    const next = [...ids];
    const [item] = next.splice(index, 1);
    next.splice(index + by, 0, item!);
    setOrder(next);
  };

  return (
    <Card>
      <CardHeader
        title="Contesting parties"
        description="The parties on this election's result form, in the order agents see them. Agents never type a party name."
        actions={
          <Link href="/parties" className="text-label font-semibold text-primary">
            Party list
          </Link>
        }
      />
      <div className="flex flex-col gap-4 p-5 pt-2">
        {error.length > 0 ? (
          <InlineAlert tone="danger" title="Not saved">
            {error.join(" ")}
          </InlineAlert>
        ) : null}
        {loading || master.isLoading ? (
          <Skeleton className="h-24" />
        ) : ids.length === 0 ? (
          <p className="text-body text-subtle-foreground">
            No parties chosen yet.{" "}
            {(master.data ?? []).length === 0 ? (
              <>
                Your party list is empty:{" "}
                <Link href="/parties" className="font-semibold text-primary">
                  add the parties first
                </Link>
                .
              </>
            ) : (
              "Add them below in the order they appear on the result sheet."
            )}
          </p>
        ) : (
          <ol className="divide-y divide-border rounded-md border border-border">
            {ids.map((id, i) => {
              const p = byId[id];
              return (
                <li key={id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-label font-bold tabular-nums">
                    {i + 1}
                  </span>
                  <PartyMark abbreviation={p?.abbreviation ?? "?"} logoUrl={p?.logo_url} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-body font-semibold">{p?.abbreviation}</span>
                    <span className="block text-body-sm text-subtle-foreground">
                      {p?.full_name}
                    </span>
                  </span>
                  {p?.is_own ? (
                    <StatusChip status={{ label: "Your party", tone: "teal", icon: "star" }} />
                  ) : null}
                  {editable ? (
                    <span className="flex gap-1">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Move ${p?.abbreviation} up`}
                        disabled={i === 0}
                        onClick={() => move(i, -1)}
                      >
                        <ArrowUp className="h-4 w-4" aria-hidden />
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Move ${p?.abbreviation} down`}
                        disabled={i === ids.length - 1}
                        onClick={() => move(i, 1)}
                      >
                        <ArrowDown className="h-4 w-4" aria-hidden />
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Remove ${p?.abbreviation}`}
                        onClick={() => setOrder(ids.filter((x) => x !== id))}
                      >
                        <X className="h-4 w-4" aria-hidden />
                      </Button>
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
        {editable ? (
          <div className="flex flex-wrap items-end gap-3">
            {available.length > 0 ? (
              <>
                <Field label="Add a party" className="w-64">
                  {(p) => (
                    <Select {...p} value={adding} onChange={(e) => setAdding(e.target.value)}>
                      <option value="">Choose a party…</option>
                      {available.map((party) => (
                        <option key={party.id} value={party.id}>
                          {party.abbreviation} · {party.full_name}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
                <Button
                  variant="secondary"
                  disabled={!adding}
                  leading={<Plus className="h-4 w-4" aria-hidden />}
                  onClick={() => {
                    setOrder([...ids, adding]);
                    setAdding("");
                  }}
                >
                  Add
                </Button>
              </>
            ) : null}
            {dirty ? (
              <>
                <Button loading={save.isPending} onClick={() => save.mutate()}>
                  Save order
                </Button>
                <Button variant="outline" onClick={() => setOrder(null)}>
                  Undo changes
                </Button>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// ---- contestants by constituency ----------------------------------------------------------

function ContestantsCard({
  election,
  config,
  editable,
  onAdd,
  onChanged,
}: {
  election: Election;
  config: Configuration;
  editable: boolean;
  onAdd: (constituency: Constituency | null) => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [removing, setRemoving] = useState<Contestant | null>(null);
  const [renaming, setRenaming] = useState<Contestant | null>(null);
  const [newName, setNewName] = useState("");

  const remove = useMutation({
    mutationFn: (c: Contestant) => ep.contestants.remove(c.id),
    onSuccess: () => {
      setRemoving(null);
      toast("Contestant removed");
      onChanged();
    },
    onError: (e) => {
      setRemoving(null);
      toast(errorLines(e, "Could not remove the contestant.").join(" "));
    },
  });
  const rename = useMutation({
    mutationFn: async () => {
      const current = await ep.contestants.get(renaming!.id);
      return ep.contestants.rename(renaming!.id, newName.trim(), current.etag ?? "");
    },
    onSuccess: () => {
      setRenaming(null);
      toast("Contestant renamed");
      onChanged();
    },
    onError: (e) => toast(errorLines(e, "Could not rename the contestant.").join(" ")),
  });

  const kind = constituencyKind(election.constituency_kind).toLowerCase();

  return (
    <section aria-label="Contestants">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-h2">Contestants</h2>
          <p className="text-body-sm text-subtle-foreground">
            A contestant is a party&apos;s candidate in one {kind}. Each {kind} with results needs
            contestants from at least two parties.
          </p>
        </div>
        {editable && config.parties.length >= 2 ? (
          <Button
            variant="secondary"
            size="sm"
            leading={<Plus className="h-4 w-4" aria-hidden />}
            onClick={() => onAdd(null)}
          >
            Add contestants
          </Button>
        ) : null}
      </div>
      {config.loading ? (
        <Skeleton className="h-32" />
      ) : config.constituencies.length === 0 ? (
        <Card className="flex flex-col items-start gap-3 p-6">
          <Users className="h-8 w-8 text-primary" aria-hidden />
          <h3 className="text-h3">No contestants yet</h3>
          <p className="max-w-xl text-body text-subtle-foreground">
            {config.parties.length < 2
              ? "Choose the contesting parties first. Then add each party's candidate for the constituencies you are tracking."
              : `Pick a ${kind} and add each contesting party's candidate there.`}
          </p>
          {editable && config.parties.length >= 2 ? (
            <Button leading={<Plus className="h-4 w-4" aria-hidden />} onClick={() => onAdd(null)}>
              Add contestants
            </Button>
          ) : null}
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {config.constituencies.map((g) => (
            <ConstituencyCard
              key={g.constituencyId}
              group={g}
              parties={config.parties}
              editable={editable}
              onAdd={() =>
                onAdd({
                  id: g.constituencyId,
                  name: g.constituencyName,
                  kind: election.constituency_kind,
                  code: "",
                  state_id: election.state_id,
                })
              }
              onRemove={setRemoving}
              onRename={(c) => {
                setRenaming(c);
                setNewName(c.name);
              }}
            />
          ))}
        </div>
      )}
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.name ?? "this contestant"}?`}
        description={`${removing?.party_abbreviation ?? "The party"} will have no contestant in ${removing?.constituency_name ?? "this constituency"}.`}
        confirmLabel="Remove contestant"
        danger
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
      <SidePanel
        open={!!renaming}
        onOpenChange={(next) => !next && setRenaming(null)}
        title="Rename contestant"
        description={
          renaming ? `${renaming.party_abbreviation} in ${renaming.constituency_name}` : undefined
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setRenaming(null)}>
              Cancel
            </Button>
            <Button
              loading={rename.isPending}
              disabled={!newName.trim()}
              onClick={() => rename.mutate()}
            >
              Save
            </Button>
          </>
        }
      >
        <Field label="Candidate's name">
          {(p) => <Input {...p} value={newName} onChange={(e) => setNewName(e.target.value)} />}
        </Field>
      </SidePanel>
    </section>
  );
}

function ConstituencyCard({
  group,
  parties,
  editable,
  onAdd,
  onRemove,
  onRename,
}: {
  group: ConstituencySetup;
  parties: ElectionParty[];
  editable: boolean;
  onAdd: () => void;
  onRemove: (c: Contestant) => void;
  onRename: (c: Contestant) => void;
}) {
  const ok = group.problems.length === 0;
  const logos = Object.fromEntries(parties.map((p) => [p.party_id, p.logo_url]));
  const missing = parties.filter((p) => !group.contestants.some((c) => c.party_id === p.party_id));
  return (
    <Card>
      <CardHeader
        title={group.constituencyName}
        description={`${formatNumber(group.contestants.length)} of ${formatNumber(parties.length)} parties have a contestant`}
        actions={
          <>
            {ok ? (
              <StatusChip status={{ label: "Ready", tone: "teal", icon: "check-circle-2" }} />
            ) : (
              <StatusChip
                status={{ label: "Needs attention", tone: "amber", icon: "alert-triangle" }}
              />
            )}
            {editable && missing.length > 0 ? (
              <Button
                size="sm"
                variant={ok ? "secondary" : "primary"}
                leading={<Plus className="h-4 w-4" aria-hidden />}
                onClick={onAdd}
              >
                Add contestant
              </Button>
            ) : null}
          </>
        }
      />
      <div className="p-5 pt-2">
        {group.problems.length > 0 ? (
          <ul className="mb-3 flex flex-col gap-1">
            {group.problems.map((p) => (
              <li key={p} className="flex items-start gap-2 text-body-sm text-signal-amber-text">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {p}
              </li>
            ))}
          </ul>
        ) : null}
        <ul className="divide-y divide-border rounded-md border border-border">
          {group.contestants.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <PartyMark abbreviation={c.party_abbreviation} logoUrl={logos[c.party_id]} />
              <span className="min-w-0 flex-1">
                <span className="block text-body font-semibold">{c.name}</span>
                <span className="block text-body-sm text-subtle-foreground">
                  {c.party_abbreviation}
                </span>
              </span>
              {editable ? (
                <span className="flex gap-1">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`Rename ${c.name}`}
                    onClick={() => onRename(c)}
                  >
                    <Pencil className="h-4 w-4" aria-hidden />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`Remove ${c.name}`}
                    onClick={() => onRemove(c)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        {missing.length > 0 ? (
          <p className="mt-2 text-caption text-subtle-foreground">
            No contestant yet: {missing.map((p) => p.abbreviation).join(", ")}. Leave a party out
            only if it has no candidate here.
          </p>
        ) : null}
      </div>
    </Card>
  );
}

// ---- forms --------------------------------------------------------------------------------

function CreateElectionPanel({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { states, loading } = useStates();
  const types = useQuery({
    queryKey: ["election-types"],
    queryFn: () => ep.geography.electionTypes(),
    staleTime: 60 * 60_000,
  });
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [stateId, setStateId] = useState("");
  const [date, setDate] = useState("");
  const [display, setDisplay] = useState<"REPORTED" | "VERIFIED">("REPORTED");
  const [error, setError] = useState<string[]>([]);

  // One state loaded: nothing to choose. Several: the person must say which.
  const effectiveState = stateId || (states.length === 1 ? states[0]!.id : "");
  const chosenType = (types.data ?? []).find((t) => t.code === type);

  const create = useMutation({
    mutationFn: () =>
      ep.elections.create({
        name: name.trim(),
        election_type: type,
        state_id: effectiveState,
        election_date: date,
        count_policy: display,
      }),
    onSuccess: (created) => {
      toast("Election created. Now choose the contesting parties.");
      void queryClient.invalidateQueries({ queryKey: ["elections"] });
      onCreated(created.id);
      setName("");
      setType("");
      setDate("");
      setError([]);
      onClose();
    },
    onError: (e) => setError(errorLines(e, "Could not create the election.")),
  });

  const missing = !name.trim() || !date || !effectiveState || !type;

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setError([]);
          onClose();
        }
      }}
      title="New election"
      description="Four details now. You choose the parties and contestants next, and can change anything until you lock it."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={missing} onClick={() => create.mutate()}>
            Create and continue
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {error.length > 0 ? (
          <InlineAlert tone="danger" title="Not created">
            {error.join(" ")}
          </InlineAlert>
        ) : null}
        {!loading && states.length === 0 ? (
          <InlineAlert tone="warning" title="No polling unit data is loaded yet">
            An election needs a state&apos;s polling unit directory. Ask your platform operator to
            load it.
          </InlineAlert>
        ) : null}
        <Field
          label="Type of election"
          hint={
            chosenType
              ? `Contestants are set per ${constituencyKind(chosenType.constituency_kind).toLowerCase()}.`
              : "The type decides which constituency each polling unit reports for."
          }
        >
          {(p) => (
            <Select {...p} value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">Choose a type…</option>
              {(types.data ?? []).map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Election name" hint="For example: Oyo State governorship election 2027">
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field
          label="State"
          hint={
            states.length === 1
              ? "The only state with polling unit data loaded."
              : "Agents can only be placed at polling units in this state. It cannot be changed later."
          }
        >
          {(p) => (
            <Select
              {...p}
              value={effectiveState}
              disabled={states.length === 1}
              onChange={(e) => setStateId(e.target.value)}
            >
              {states.length !== 1 ? <option value="">Choose a state…</option> : null}
              {states.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({formatNumber(s.lgas)} LGAs)
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Election day">
          {(p) => (
            <Input {...p} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          )}
        </Field>
        <DisplayChoice value={display} onChange={setDisplay} />
      </div>
    </SidePanel>
  );
}

function AddContestantPanel({
  open,
  election,
  parties,
  constituencies,
  initial,
  onClose,
  onAdded,
}: {
  open: boolean;
  election: Election;
  parties: ElectionParty[];
  constituencies: ConstituencySetup[];
  initial: Constituency | null;
  onClose: () => void;
  onAdded: () => void;
}) {
  const toast = useToast();
  const [constituency, setConstituency] = useState<Constituency | null>(initial);
  const [search, setSearch] = useState("");
  const [partyId, setPartyId] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string[]>([]);

  const options = useQuery({
    queryKey: ["constituencies", election.constituency_kind, election.state_id, search],
    enabled: open && !constituency,
    queryFn: async () =>
      (
        await ep.geography.constituencies({
          kind: election.constituency_kind,
          state: election.state_id,
          search: search.trim() || undefined,
          limit: 25,
        })
      ).results,
  });
  // A state-wide race has one constituency: nothing to pick.
  const only = !search && options.data?.length === 1 ? options.data[0]! : null;
  const chosen = constituency ?? only;

  const taken = new Set(
    constituencies
      .find((g) => g.constituencyId === chosen?.id)
      ?.contestants.map((c) => c.party_id) ?? [],
  );
  const free = parties.filter((p) => !taken.has(p.party_id));
  const effectiveParty = partyId && free.some((p) => p.party_id === partyId) ? partyId : (free[0]?.party_id ?? "");

  const create = useMutation({
    mutationFn: () =>
      ep.elections.createContestant(election.id, {
        constituency_id: chosen!.id,
        party_id: effectiveParty,
        name: name.trim(),
      }),
    onSuccess: () => {
      const party = parties.find((p) => p.party_id === effectiveParty);
      toast(`${name.trim()} (${party?.abbreviation ?? ""}) added`);
      setName("");
      setPartyId("");
      setError([]);
      if (!constituency && chosen) setConstituency(chosen);
      onAdded();
    },
    onError: (e) => setError(errorLines(e, "Could not add the contestant.")),
  });

  const kind = constituencyKind(election.constituency_kind);
  const close = () => {
    setConstituency(null);
    setSearch("");
    setName("");
    setPartyId("");
    setError([]);
    onClose();
  };

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => !next && close()}
      title="Add contestants"
      description={`Each contesting party's candidate in one ${kind.toLowerCase()}. Add them one after another; close this when you are done.`}
      footer={
        <>
          <Button variant="outline" onClick={close}>
            Done
          </Button>
          <Button
            loading={create.isPending}
            disabled={!chosen || !effectiveParty || !name.trim()}
            onClick={() => create.mutate()}
          >
            Add contestant
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {error.length > 0 ? (
          <InlineAlert tone="danger" title="Not added">
            {error.join(" ")}
          </InlineAlert>
        ) : null}
        {chosen ? (
          <div className="flex items-center justify-between gap-3 rounded-md bg-muted p-3">
            <div>
              <p className="text-caption text-subtle-foreground">{kind}</p>
              <p className="text-body font-semibold">{chosen.name}</p>
            </div>
            {!only || constituency ? (
              <Button size="sm" variant="ghost" onClick={() => setConstituency(null)}>
                Change
              </Button>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <Field label={`Find the ${kind.toLowerCase()}`}>
              {(p) => (
                <Input
                  {...p}
                  value={search}
                  placeholder="Type a name or code"
                  onChange={(e) => setSearch(e.target.value)}
                />
              )}
            </Field>
            {options.isLoading ? (
              <Skeleton className="h-24" />
            ) : options.isError ? (
              <QueryError error={options.error} onRetry={() => void options.refetch()} />
            ) : (options.data ?? []).length === 0 ? (
              <p className="text-body-sm text-subtle-foreground">
                No {kind.toLowerCase()} matches. If none is listed at all, the constituency mapping
                for this state has not been loaded yet; ask your platform operator.
              </p>
            ) : (
              <ul className="max-h-64 divide-y divide-border overflow-y-auto rounded-md border border-border">
                {options.data!.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-body-sm hover:bg-muted"
                      onClick={() => setConstituency(c)}
                    >
                      <span className="font-semibold">{c.name}</span>
                      <span className="mono text-caption text-subtle-foreground">{c.code}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {chosen ? (
          free.length === 0 ? (
            <InlineAlert tone="info" title="Every party has a contestant here">
              Pick another {kind.toLowerCase()}, or close this panel.
            </InlineAlert>
          ) : (
            <>
              <Field label="Party">
                {(p) => (
                  <Select
                    {...p}
                    value={effectiveParty}
                    onChange={(e) => setPartyId(e.target.value)}
                  >
                    {free.map((party) => (
                      <option key={party.party_id} value={party.party_id}>
                        {party.abbreviation} · {party.full_name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Candidate's name" hint="As it appears on the result sheet.">
                {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
              </Field>
            </>
          )
        ) : null}
      </div>
    </SidePanel>
  );
}

function DeleteElection({
  election,
  contestants,
  onDeleted,
}: {
  election: Election;
  contestants: number;
  onDeleted: () => void;
}) {
  const toast = useToast();
  const stepUp = useStepUp();
  const [open, setOpen] = useState(false);
  const remove = useMutation({
    mutationFn: () => stepUp(() => ep.elections.remove(election.id)),
    onSuccess: () => {
      setOpen(false);
      toast(`${election.name} was deleted`);
      onDeleted();
    },
    onError: (e) => {
      setOpen(false);
      toast(errorLines(e, "Could not delete the election.").join(" "));
    },
  });

  return (
    <section aria-label="Delete this election">
      <Card className="flex flex-wrap items-center justify-between gap-4 border-danger/40 p-5">
        <div className="max-w-xl">
          <h2 className="text-h3">Delete this election</h2>
          <p className="text-body-sm text-subtle-foreground">
            Only possible while it is being set up. Once it is locked it becomes part of the record
            and can no longer be deleted.
          </p>
        </div>
        <Button
          variant="outline"
          className="text-danger"
          leading={<Trash2 className="h-4 w-4" aria-hidden />}
          onClick={() => setOpen(true)}
        >
          Delete election
        </Button>
      </Card>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete ${election.name}?`}
        description={`This removes the election, its contesting parties and ${formatNumber(contestants)} ${
          contestants === 1 ? "contestant" : "contestants"
        }, and any agent placements made for it. Your party list, agents and polling units are not affected. This cannot be undone. You will be asked for your authenticator code.`}
        confirmLabel="Delete election"
        danger
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </section>
  );
}
