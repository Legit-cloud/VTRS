"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  OFFICE_LABEL,
  electionStatus,
  formatDate,
  formatDateTime,
  formatNumber,
  type Candidate,
  type Contest,
  type Election,
} from "@vtrs/core";
import {
  AlertTriangle,
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Circle,
  Lock,
  Pencil,
  Plus,
  Trash2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { ConfirmDialog, SidePanel } from "@/components/ui/dialog";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import {
  useConfiguration,
  type Configuration,
  type ContestSetup,
} from "@/components/elections/use-configuration";
import { StageTracker } from "@/components/elections/workflow";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useElection } from "@/lib/election";
import { errorLines } from "@/lib/errors";
import { useElectionLgas, useStates } from "@/lib/geo-names";
import { useStepUp } from "@/lib/step-up";

const OFFICES = Object.keys(OFFICE_LABEL);

const SHEET_FIELDS = [
  ["valid", "Valid votes", "Always recorded. The total of all candidates' votes."],
  ["accredited", "Accredited voters", "How many people were checked in to vote."],
  ["rejected", "Rejected ballots", "Spoiled or invalid ballot papers."],
  ["total_cast", "Total votes cast", "Valid plus rejected."],
] as const;

/** How results should appear on the dashboard, in words, mapped to the two server settings. */
const DISPLAY = [
  {
    value: "AS_SENT",
    title: "As agents send them",
    body: "Every result appears on the dashboard as soon as it arrives. There is no review step.",
    policy: "REPORTED" as const,
    review: false,
  },
  {
    value: "REVIEWED",
    title: "As they arrive, with officer review",
    body: "Results appear straight away. Ward officers can approve or reject them, and you can switch the dashboard between all results and approved ones.",
    policy: "REPORTED" as const,
    review: true,
  },
  {
    value: "APPROVED_ONLY",
    title: "Only after an officer approves",
    body: "The dashboard counts a result only once a ward officer has approved it. Slower, but every number has been checked.",
    policy: "VERIFIED" as const,
    review: true,
  },
];

const displayOf = (e: Pick<Election, "count_policy" | "review_enabled">) =>
  DISPLAY.find(
    (d) => d.policy === (e.count_policy ?? "REPORTED") && d.review === !!e.review_enabled,
  ) ?? DISPLAY[0]!;

export default function ElectionsPage() {
  const { elections, election, select, loading, error, refetch } = useElection();
  const { states } = useStates();
  const [creating, setCreating] = useState(false);
  // After creating an election, walk straight into adding its first contest.
  const [guidedFor, setGuidedFor] = useState<string | null>(null);

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
                          {where ? `${where} · ` : ""}
                          {formatDate(e.election_date)}
                        </span>
                        <StatusChip status={electionStatus(e.status ?? "DRAFT")} />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
          {election ? (
            <Workspace
              key={election.id}
              electionId={election.id}
              openContestFirst={guidedFor === election.id}
              onGuidedDone={() => setGuidedFor(null)}
            />
          ) : null}
        </div>
      )}

      <CreateElectionPanel
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(id) => {
          select(id);
          setGuidedFor(id);
        }}
      />
    </>
  );
}

/** The first thing someone sees: what they are about to do, in four steps. */
function FirstElection({ onStart }: { onStart: () => void }) {
  const steps: [string, string][] = [
    ["Create the election", "Name it, choose the state and the election day."],
    ["Add what you are tracking", "A contest such as Governorship, and its candidates."],
    ["Lock it", "Freezes the setup so agents and officers work from one fixed list."],
    ["Go live", "Agents send results; the War Room fills in as they arrive."],
  ];
  return (
    <Card className="p-6 md:p-8">
      <h2 className="text-h2">Set up your first election</h2>
      <p className="mt-1 max-w-2xl text-body text-subtle-foreground">
        It takes a few minutes. You can change anything until you lock it.
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

function Workspace({
  electionId,
  openContestFirst,
  onGuidedDone,
}: {
  electionId: string;
  openContestFirst: boolean;
  onGuidedDone: () => void;
}) {
  const queryClient = useQueryClient();
  const config = useConfiguration(electionId);
  const detail = useQuery({
    queryKey: ["election", electionId],
    queryFn: () => ep.elections.get(electionId),
  });
  const [addContest, setAddContest] = useState(openContestFirst);
  const [addCandidateFor, setAddCandidateFor] = useState<Contest | null>(null);
  const [editing, setEditing] = useState(false);

  const election = detail.data?.data;
  const etag = detail.data?.etag ?? "";
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["election", electionId] });
    void queryClient.invalidateQueries({ queryKey: ["elections"] });
    void queryClient.invalidateQueries({ queryKey: ["contests", electionId] });
    void queryClient.invalidateQueries({ queryKey: ["candidates"] });
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
        onAddContest={() => setAddContest(true)}
        onAddCandidate={(c) => setAddCandidateFor(c)}
      />

      <DetailsCard
        election={election}
        etag={etag}
        editable={editable}
        editing={editing}
        setEditing={setEditing}
        onSaved={refresh}
      />

      <section aria-label="Contests and candidates">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-h2">Contests and candidates</h2>
            {editable ? (
              <p className="text-body-sm text-subtle-foreground">
                A contest is one race on the ballot. Each needs at least two candidates.
              </p>
            ) : null}
          </div>
          {editable && config.contests.length > 0 ? (
            <Button
              variant="secondary"
              size="sm"
              leading={<Plus className="h-4 w-4" aria-hidden />}
              onClick={() => setAddContest(true)}
            >
              Add another contest
            </Button>
          ) : null}
        </div>
        {config.loading ? (
          <Skeleton className="h-32" />
        ) : config.contests.length === 0 ? (
          <Card className="flex flex-col items-start gap-3 p-6">
            <BookOpenCheck className="h-8 w-8 text-primary" aria-hidden />
            <h3 className="text-h3">No contests yet</h3>
            <p className="max-w-xl text-body text-subtle-foreground">
              Add the contest you are tracking, for example the governorship. Then add its
              candidates, in the order they appear on the ballot paper.
            </p>
            {editable ? (
              <Button
                leading={<Plus className="h-4 w-4" aria-hidden />}
                onClick={() => setAddContest(true)}
              >
                Add a contest
              </Button>
            ) : null}
          </Card>
        ) : (
          <div className="flex flex-col gap-4">
            {config.contests.map((setup) => (
              <ContestCard
                key={setup.contest.id}
                setup={setup}
                editable={editable}
                onAddCandidate={() => setAddCandidateFor(setup.contest)}
                onChanged={refresh}
              />
            ))}
          </div>
        )}
      </section>

      <AddContestPanel
        open={addContest}
        electionId={electionId}
        stateId={election.state_id}
        onClose={() => {
          setAddContest(false);
          onGuidedDone();
        }}
        onAdded={(contest) => {
          refresh();
          setAddContest(false);
          onGuidedDone();
          // The next thing needed is its candidates.
          setAddCandidateFor(contest);
        }}
      />
      <AddCandidatePanel
        contest={addCandidateFor}
        existing={
          config.contests.find((c) => c.contest.id === addCandidateFor?.id)?.candidates ?? []
        }
        onClose={() => setAddCandidateFor(null)}
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
  onAddContest,
  onAddCandidate,
}: {
  election: Election;
  config: Configuration;
  onChanged: () => void;
  onAddContest: () => void;
  onAddCandidate: (contest: Contest) => void;
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

  const counts = `${formatNumber(config.contests.length)} ${
    config.contests.length === 1 ? "contest" : "contests"
  } and ${formatNumber(config.candidateCount)} ${
    config.candidateCount === 1 ? "candidate" : "candidates"
  }`;

  let heading = "";
  let body: React.ReactNode = null;
  let actions: React.ReactNode = null;

  if (status === "DRAFT") {
    heading = "Finish setting up";
    body = (
      <>
        <p className="text-body text-subtle-foreground">
          Add your contests and their candidates. When the checklist is complete, mark the election
          ready.
        </p>
        <Checklist config={config} onAddContest={onAddContest} onAddCandidate={onAddCandidate} />
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
        <Checklist config={config} onAddContest={onAddContest} onAddCandidate={onAddCandidate} />
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
              {formatNumber(readiness.data.undecided_results)} results still need a decision
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
        description={`${counts} will be frozen. You will not be able to add, remove or reorder candidates afterwards. You will be asked for your authenticator code.`}
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
        description="Agents will no longer be able to send results for this election. You can still review what has arrived."
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
  onAddContest,
  onAddCandidate,
}: {
  config: Configuration;
  onAddContest: () => void;
  onAddCandidate: (contest: Contest) => void;
}) {
  if (config.loading) return <Skeleton className="h-24" />;
  return (
    <ul className="flex flex-col gap-2" aria-label="What is left to do">
      <Item done>The election has a name, a state and a date</Item>
      <Item done={config.contests.length > 0}>
        {config.contests.length > 0
          ? `${formatNumber(config.contests.length)} ${config.contests.length === 1 ? "contest" : "contests"} added`
          : "Add the contest you are tracking"}
        {config.contests.length === 0 ? (
          <button type="button" className="ml-3 font-semibold text-primary" onClick={onAddContest}>
            Add a contest
          </button>
        ) : null}
      </Item>
      {config.contests.map((s) => (
        <ContestItem key={s.contest.id} setup={s} onAddCandidate={onAddCandidate} />
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

function ContestItem({
  setup,
  onAddCandidate,
}: {
  setup: ContestSetup;
  onAddCandidate: (contest: Contest) => void;
}) {
  const n = setup.candidates.length;
  const ok = n >= 2 && setup.problems.length === 0;
  return (
    <Item done={ok}>
      <span className="font-semibold">{setup.contest.title}:</span>{" "}
      {n === 0 ? "no candidates yet" : `${n} ${n === 1 ? "candidate" : "candidates"}`}
      {n < 2 ? " (needs at least 2)" : ""}
      {!ok ? (
        <button
          type="button"
          className="ml-3 font-semibold text-primary"
          onClick={() => onAddCandidate(setup.contest)}
        >
          Add a candidate
        </button>
      ) : null}
    </Item>
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

  const chosen = DISPLAY.find((d) => d.value === display)!;
  const save = useMutation({
    mutationFn: () =>
      ep.elections.update(
        election.id,
        {
          name: name.trim(),
          election_date: date,
          count_policy: chosen.policy,
          review_enabled: chosen.review,
        },
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
          <Row label="State">{stateLabel}</Row>
          <Row label="Election day">{formatDate(election.election_date)}</Row>
          <Row label="Results appear on the dashboard">{displayOf(election).title}</Row>
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

function DisplayChoice({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-label text-strong-foreground">
        How should results appear on the dashboard?
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

// ---- contests -----------------------------------------------------------------------------

function ContestCard({
  setup,
  editable,
  onAddCandidate,
  onChanged,
}: {
  setup: ContestSetup;
  editable: boolean;
  onAddCandidate: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const { contest, candidates } = setup;
  const [removing, setRemoving] = useState<Candidate | null>(null);
  const [removingContest, setRemovingContest] = useState(false);

  const removeCandidate = useMutation({
    mutationFn: (c: Candidate) => ep.candidates.remove(c.id, `"${c.row_version ?? 0}"`),
    onSuccess: () => {
      setRemoving(null);
      toast("Candidate removed");
      onChanged();
    },
    onError: (e) => {
      setRemoving(null);
      toast(errorLines(e, "Could not remove the candidate.").join(" "));
    },
  });
  const removeContest = useMutation({
    mutationFn: async () => {
      const current = await ep.contests.get(contest.id);
      return ep.contests.remove(contest.id, current.etag ?? "");
    },
    onSuccess: () => {
      setRemovingContest(false);
      toast("Contest removed");
      onChanged();
    },
    onError: (e) => {
      setRemovingContest(false);
      toast(errorLines(e, "Could not remove the contest.").join(" "));
    },
  });

  const ok = candidates.length >= 2;
  const sorted = [...candidates].sort((a, b) => a.ballot_order - b.ballot_order);

  return (
    <Card>
      <CardHeader
        title={contest.title}
        description={`${OFFICE_LABEL[contest.office] ?? contest.office} · ${
          contest.jurisdiction_level === "STATE"
            ? "whole state"
            : `${formatNumber(contest.jurisdiction_ids.length)} ${contest.jurisdiction_ids.length === 1 ? "LGA" : "LGAs"}`
        }`}
        actions={
          <>
            {!ok ? (
              <StatusChip
                status={{ label: "Needs 2 candidates", tone: "amber", icon: "alert-triangle" }}
              />
            ) : (
              <StatusChip status={{ label: "Ready", tone: "teal", icon: "check-circle-2" }} />
            )}
            {editable ? (
              <Button
                size="sm"
                variant={ok ? "secondary" : "primary"}
                leading={<Plus className="h-4 w-4" aria-hidden />}
                onClick={onAddCandidate}
              >
                Add candidate
              </Button>
            ) : null}
          </>
        }
      />
      <div className="p-5 pt-2">
        {sorted.length === 0 ? (
          <p className="text-body text-subtle-foreground">
            No candidates yet. Add them in the order they appear on the ballot paper.
          </p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {sorted.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-label font-bold tabular-nums">
                  {c.ballot_order}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-semibold">{c.name}</span>
                  <span className="block text-body-sm text-subtle-foreground">
                    {c.party_acronym} · {c.party_name}
                  </span>
                </span>
                {c.is_own_party ? (
                  <StatusChip status={{ label: "Your candidate", tone: "teal", icon: "star" }} />
                ) : null}
                {editable ? (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`Remove ${c.name}`}
                    onClick={() => setRemoving(c)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {editable ? (
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              className="text-caption font-semibold text-danger hover:underline"
              onClick={() => setRemovingContest(true)}
            >
              Remove this contest
            </button>
          </div>
        ) : null}
      </div>
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.name ?? "this candidate"}?`}
        description={`They will no longer appear on the ${contest.title} result sheet.`}
        confirmLabel="Remove candidate"
        danger
        loading={removeCandidate.isPending}
        onConfirm={() => removing && removeCandidate.mutate(removing)}
      />
      <ConfirmDialog
        open={removingContest}
        onOpenChange={setRemovingContest}
        title={`Remove ${contest.title}?`}
        description="The contest and all its candidates are removed from this election."
        confirmLabel="Remove contest"
        danger
        loading={removeContest.isPending}
        onConfirm={() => removeContest.mutate()}
      />
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
  const [name, setName] = useState("");
  const [stateId, setStateId] = useState("");
  const [date, setDate] = useState("");
  const [display, setDisplay] = useState("AS_SENT");
  const [error, setError] = useState<string[]>([]);

  // One state loaded: nothing to choose. Several: the person must say which.
  const effectiveState = stateId || (states.length === 1 ? states[0]!.id : "");
  const chosen = DISPLAY.find((d) => d.value === display)!;

  const create = useMutation({
    mutationFn: () =>
      ep.elections.create({
        name: name.trim(),
        state_id: effectiveState,
        election_date: date,
        count_policy: chosen.policy,
        review_enabled: chosen.review,
      }),
    onSuccess: (created) => {
      toast("Election created. Now add what you are tracking.");
      void queryClient.invalidateQueries({ queryKey: ["elections"] });
      onCreated(created.id);
      setName("");
      setDate("");
      setError([]);
      onClose();
    },
    onError: (e) => setError(errorLines(e, "Could not create the election.")),
  });

  const missing = !name.trim() || !date || !effectiveState;

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
      description="Three details now. You add the contests and candidates next, and can change anything until you lock it."
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

function AddContestPanel({
  open,
  electionId,
  stateId,
  onClose,
  onAdded,
}: {
  open: boolean;
  electionId: string;
  stateId: string;
  onClose: () => void;
  onAdded: (contest: Contest) => void;
}) {
  const toast = useToast();
  const { lgas } = useElectionLgas();
  const { states } = useStates();
  const [office, setOffice] = useState("GOVERNORSHIP");
  const [title, setTitle] = useState("Governorship");
  const [titleEdited, setTitleEdited] = useState(false);
  const [level, setLevel] = useState<"STATE" | "LGA">("STATE");
  const [lgaIds, setLgaIds] = useState<string[]>([]);
  const [fields, setFields] = useState<string[]>(["valid", "accredited", "rejected", "total_cast"]);
  const [error, setError] = useState<string[]>([]);

  const create = useMutation({
    mutationFn: () =>
      ep.elections.createContest(electionId, {
        office: office as never,
        title: title.trim(),
        jurisdiction_level: level as never,
        jurisdiction_ids: level === "STATE" ? [stateId] : lgaIds,
        sheet_fields: fields as never,
      }),
    onSuccess: (contest) => {
      toast("Contest added. Now add its candidates.");
      setError([]);
      onAdded(contest);
    },
    onError: (e) => setError(errorLines(e, "Could not add the contest.")),
  });

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  const state = states.find((s) => s.id === stateId)?.name ?? "the state";

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title="Add a contest"
      description="A contest is one race on the ballot, such as the governorship or a Senate seat."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={create.isPending}
            disabled={!title.trim() || (level === "LGA" && lgaIds.length === 0)}
            onClick={() => create.mutate()}
          >
            Add contest
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
        <Field label="What is the race?">
          {(p) => (
            <Select
              {...p}
              value={office}
              onChange={(e) => {
                setOffice(e.target.value);
                if (!titleEdited) setTitle(OFFICE_LABEL[e.target.value] ?? "");
              }}
            >
              {OFFICES.map((o) => (
                <option key={o} value={o}>
                  {OFFICE_LABEL[o]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Name shown to agents" hint="Agents see this on the result sheet in the app.">
          {(p) => (
            <Input
              {...p}
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                setTitleEdited(true);
              }}
            />
          )}
        </Field>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-label text-strong-foreground">Where is it held?</legend>
          {(
            [
              ["STATE", `Across all of ${state}`, "Every polling unit in the state takes part."],
              ["LGA", "Only in some LGAs", "For example a senatorial district or a House seat."],
            ] as const
          ).map(([value, label, hint]) => (
            <label
              key={value}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-md border p-3",
                level === value ? "border-primary bg-primary-soft" : "border-border hover:bg-muted",
              )}
            >
              <input
                type="radio"
                name="level"
                className="mt-1 h-4 w-4 accent-[rgb(var(--primary))]"
                checked={level === value}
                onChange={() => setLevel(value)}
              />
              <span>
                <span className="block text-body-sm font-semibold">{label}</span>
                <span className="block text-caption text-subtle-foreground">{hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {level === "LGA" ? (
          <fieldset className="max-h-56 overflow-y-auto rounded-md border border-border p-3">
            <legend className="px-1 text-label text-strong-foreground">Choose the LGAs</legend>
            {lgas.map((l) => (
              <label key={l.id} className="flex min-h-9 items-center gap-3 text-body-sm">
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-[rgb(var(--primary))]"
                  checked={lgaIds.includes(l.id)}
                  onChange={() => setLgaIds((cur) => toggle(cur, l.id))}
                />
                {l.name}
              </label>
            ))}
          </fieldset>
        ) : null}
        <fieldset className="rounded-md border border-border p-3">
          <legend className="px-1 text-label text-strong-foreground">
            Numbers agents copy from the result sheet
          </legend>
          {SHEET_FIELDS.map(([value, label, hint]) => (
            <label key={value} className="flex items-start gap-3 py-1.5">
              <input
                type="checkbox"
                className="mt-0.5 h-5 w-5 accent-[rgb(var(--primary))]"
                checked={fields.includes(value)}
                disabled={value === "valid"}
                onChange={() => setFields((cur) => toggle(cur, value))}
              />
              <span>
                <span className="block text-body-sm font-medium">{label}</span>
                <span className="block text-caption text-subtle-foreground">{hint}</span>
              </span>
            </label>
          ))}
        </fieldset>
      </div>
    </SidePanel>
  );
}

function AddCandidatePanel({
  contest,
  existing,
  onClose,
  onAdded,
}: {
  contest: Contest | null;
  existing: Candidate[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [party, setParty] = useState("");
  const [acronym, setAcronym] = useState("");
  const [orderOverride, setOrderOverride] = useState<string | null>(null);
  const [own, setOwn] = useState(false);
  const [error, setError] = useState<string[]>([]);

  const suggested = String(Math.max(0, ...existing.map((c) => c.ballot_order)) + 1);
  const order = orderOverride ?? suggested;
  const ownTaken = existing.some((c) => c.is_own_party);

  const reset = () => {
    setName("");
    setParty("");
    setAcronym("");
    setOrderOverride(null);
    setOwn(false);
    setError([]);
  };

  const create = useMutation({
    mutationFn: () =>
      ep.contests.createCandidate(contest!.id, {
        name: name.trim(),
        party_name: party.trim(),
        party_acronym: acronym.trim(),
        ballot_order: Number(order),
        is_own_party: own,
      }),
    onSuccess: () => {
      toast(`${name.trim()} added`);
      reset();
      onAdded();
    },
    onError: (e) => setError(errorLines(e, "Could not add the candidate.")),
  });

  const remaining = Math.max(0, 2 - existing.length);

  return (
    <SidePanel
      open={!!contest}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
      title="Add a candidate"
      description={
        contest
          ? `For ${contest.title}. ${
              remaining > 0
                ? `You need at least ${remaining} more.`
                : "You can add more, or close this when you are done."
            }`
          : undefined
      }
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Done
          </Button>
          <Button
            loading={create.isPending}
            disabled={!name.trim() || !party.trim() || !acronym.trim() || !(Number(order) >= 1)}
            onClick={() => create.mutate()}
          >
            Add candidate
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {existing.length > 0 ? (
          <div className="rounded-md bg-muted p-3 text-body-sm">
            <p className="font-semibold">Added so far</p>
            <ul className="mt-1 text-subtle-foreground">
              {[...existing]
                .sort((a, b) => a.ballot_order - b.ballot_order)
                .map((c) => (
                  <li key={c.id}>
                    {c.ballot_order}. {c.name} ({c.party_acronym})
                  </li>
                ))}
            </ul>
          </div>
        ) : null}
        {error.length > 0 ? (
          <InlineAlert tone="danger" title="Not added">
            {error.join(" ")}
          </InlineAlert>
        ) : null}
        <Field label="Candidate's name">
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Party">
          {(p) => <Input {...p} value={party} onChange={(e) => setParty(e.target.value)} />}
        </Field>
        <Field label="Party acronym" hint="As printed on the ballot paper, for example APC.">
          {(p) => (
            <Input
              {...p}
              value={acronym}
              onChange={(e) => setAcronym(e.target.value.toUpperCase())}
              maxLength={20}
            />
          )}
        </Field>
        <Field
          label="Position on the ballot paper"
          hint="1 is the top of the ballot paper. Agents see candidates in this order."
        >
          {(p) => (
            <Input
              {...p}
              type="number"
              min={1}
              max={200}
              value={order}
              onChange={(e) => setOrderOverride(e.target.value)}
              className="max-w-28"
            />
          )}
        </Field>
        <label
          className={cn(
            "flex items-start gap-3 rounded-md border p-3",
            ownTaken ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-muted",
          )}
        >
          <input
            type="checkbox"
            className="mt-0.5 h-5 w-5 accent-[rgb(var(--primary))]"
            checked={own}
            disabled={ownTaken}
            onChange={(e) => setOwn(e.target.checked)}
          />
          <span>
            <span className="block text-body-sm font-semibold">
              This is our party&apos;s candidate
            </span>
            <span className="block text-caption text-subtle-foreground">
              {ownTaken
                ? "Another candidate in this contest is already marked as yours."
                : "The dashboard highlights your candidate and shows how they are doing."}
            </span>
          </span>
        </label>
      </div>
    </SidePanel>
  );
}
