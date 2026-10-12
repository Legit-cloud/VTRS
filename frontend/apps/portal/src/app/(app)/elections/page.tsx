"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  OFFICE_LABEL,
  electionStatus,
  formatDate,
  formatDateTime,
  type Candidate,
  type Contest,
  type Election,
} from "@vtrs/core";
import { BookOpenCheck, Lock, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { ConfirmDialog, SidePanel } from "@/components/ui/dialog";
import { EmptyState, InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { DataTable } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { useElection } from "@/lib/election";
import { useElectionLgas } from "@/lib/geo-names";
import { useStepUp } from "@/lib/step-up";

const STEPS = ["DRAFT", "CONFIGURED", "LOCKED", "LIVE", "CLOSED", "RECONCILED"] as const;
const OFFICES = Object.keys(OFFICE_LABEL);
const SHEET_FIELDS = [
  ["valid", "Valid votes", true],
  ["accredited", "Accredited voters", false],
  ["rejected", "Rejected ballots", false],
  ["total_cast", "Total cast", false],
] as const;

const fail = (e: unknown, fallback: string) => (e instanceof ApiError ? e.detail : fallback);

export default function ElectionsPage() {
  const { elections, election, select, loading, error, refetch } = useElection();
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader
        title="Elections and candidates"
        description="Set up an election, add contests and candidates, then lock the configuration before polls open."
        actions={
          <Button
            leading={<Plus className="h-4 w-4" aria-hidden />}
            onClick={() => setCreating(true)}
          >
            New election
          </Button>
        }
      />

      {loading ? (
        <Skeleton className="h-48" />
      ) : error ? (
        <QueryError error={error} onRetry={refetch} />
      ) : (
        <DataTable<Election>
          caption="Elections"
          rows={elections}
          rowKey={(e) => e.id}
          selectedKey={election?.id}
          onRowClick={(e) => select(e.id)}
          columns={[
            {
              key: "name",
              header: "Election",
              cell: (e) => <span className="font-semibold">{e.name}</span>,
            },
            {
              key: "date",
              header: "Date",
              cell: (e) => formatDate(e.election_date),
              sortValue: (e) => e.election_date,
            },
            {
              key: "status",
              header: "Status",
              cell: (e) => <StatusChip status={electionStatus(e.status ?? "DRAFT")} />,
            },
            {
              key: "policy",
              header: "Counts",
              cell: (e) => (e.count_policy === "VERIFIED" ? "Verified only" : "All reported"),
              hideOnNarrow: true,
            },
            {
              key: "review",
              header: "Review",
              cell: (e) => (e.review_enabled ? "On" : "Off"),
              hideOnNarrow: true,
            },
          ]}
          empty={
            <EmptyState
              icon={<BookOpenCheck className="h-8 w-8" aria-hidden />}
              title="No elections yet"
              description="Create the election you are tracking, then add its contests and candidates."
              action={<Button onClick={() => setCreating(true)}>New election</Button>}
            />
          }
        />
      )}

      {election ? <ElectionDetail key={election.id} electionId={election.id} /> : null}

      <CreateElectionPanel
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(id) => select(id)}
      />
    </>
  );
}

function ElectionDetail({ electionId }: { electionId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const [confirm, setConfirm] = useState<"lock" | "live" | "close" | "reconcile" | null>(null);
  const [addContest, setAddContest] = useState(false);
  const [addCandidateFor, setAddCandidateFor] = useState<Contest | null>(null);

  const detail = useQuery({
    queryKey: ["election", electionId],
    queryFn: () => ep.elections.get(electionId),
  });
  const contests = useQuery({
    queryKey: ["contests", electionId],
    queryFn: async () => {
      const data = await ep.elections.contests(electionId);
      return Array.isArray(data) ? data : data.results;
    },
  });
  const readiness = useQuery({
    queryKey: ["election", electionId, "readiness"],
    enabled: detail.data?.data.status === "CLOSED",
    queryFn: () => ep.elections.readiness(electionId),
  });

  const election = detail.data?.data;
  const etag = detail.data?.etag ?? "";
  const editable = election?.status === "DRAFT" || election?.status === "CONFIGURED";

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["election", electionId] });
    void queryClient.invalidateQueries({ queryKey: ["elections"] });
    void queryClient.invalidateQueries({ queryKey: ["contests", electionId] });
  };

  const transition = useMutation({
    mutationFn: async (action: "configure" | "draft" | "lock" | "live" | "close" | "reconcile") => {
      if (action === "lock") return stepUp(() => ep.elections.lock(electionId));
      if (action === "reconcile") return stepUp(() => ep.elections.reconcile(electionId));
      const to = { configure: "CONFIGURED", draft: "DRAFT", live: "LIVE", close: "CLOSED" }[
        action
      ] as "CONFIGURED" | "DRAFT" | "LIVE" | "CLOSED";
      return ep.elections.transition(electionId, to);
    },
    onSuccess: () => {
      setConfirm(null);
      refresh();
      toast("Election updated");
    },
    onError: (e) => {
      setConfirm(null);
      toast(fail(e, "That change was refused."));
    },
  });

  if (detail.isLoading) return <Skeleton className="mt-6 h-64" />;
  if (detail.isError || !election) {
    return (
      <div className="mt-6">
        <QueryError error={detail.error} onRetry={() => void detail.refetch()} />
      </div>
    );
  }

  const stepIndex = STEPS.indexOf((election.status ?? "DRAFT") as (typeof STEPS)[number]);

  return (
    <div className="mt-8 flex flex-col gap-6">
      <Card>
        <CardHeader
          title={election.name}
          description={`Config version ${election.config_version ?? 0}${
            election.locked_at ? ` · locked ${formatDateTime(election.locked_at)}` : ""
          }`}
        />
        <div className="flex flex-col gap-5 p-5 pt-2">
          <ol className="flex flex-wrap gap-2" aria-label="Election stages">
            {STEPS.map((step, i) => (
              <li
                key={step}
                aria-current={i === stepIndex ? "step" : undefined}
                className={
                  i < stepIndex
                    ? "flex h-8 items-center rounded-full bg-primary-soft px-3 text-label font-semibold text-primary-soft-foreground"
                    : i === stepIndex
                      ? "flex h-8 items-center rounded-full bg-primary px-3 text-label font-semibold text-primary-foreground"
                      : "flex h-8 items-center rounded-full border border-border px-3 text-label text-subtle-foreground"
                }
              >
                {electionStatus(step).label}
              </li>
            ))}
          </ol>

          <div className="flex flex-wrap gap-2">
            {election.status === "DRAFT" ? (
              <Button
                loading={transition.isPending}
                disabled={(contests.data ?? []).length === 0}
                onClick={() => transition.mutate("configure")}
              >
                Mark as configured
              </Button>
            ) : null}
            {election.status === "CONFIGURED" ? (
              <>
                <Button variant="outline" onClick={() => transition.mutate("draft")}>
                  Back to draft
                </Button>
                <Button
                  leading={<Lock className="h-4 w-4" aria-hidden />}
                  onClick={() => setConfirm("lock")}
                >
                  Lock configuration
                </Button>
              </>
            ) : null}
            {election.status === "LOCKED" ? (
              <Button onClick={() => setConfirm("live")}>Open result capture</Button>
            ) : null}
            {election.status === "LIVE" ? (
              <Button variant="outline" onClick={() => setConfirm("close")}>
                Close result capture
              </Button>
            ) : null}
            {election.status === "CLOSED" ? (
              <Button
                disabled={readiness.data ? !readiness.data.can_reconcile : true}
                onClick={() => setConfirm("reconcile")}
              >
                Reconcile results
              </Button>
            ) : null}
          </div>

          {election.status === "CLOSED" && readiness.data ? (
            <InlineAlert
              tone={readiness.data.can_reconcile ? "success" : "warning"}
              title={readiness.data.can_reconcile ? "Ready to reconcile" : "Not ready to reconcile"}
            >
              {readiness.data.can_reconcile
                ? "Every counting result has been decided and the figures agree."
                : `${readiness.data.undecided_results} results still need a decision${
                    readiness.data.rollup_differences.length
                      ? `, and ${readiness.data.rollup_differences.length} totals differ from a fresh count`
                      : ""
                  }.`}
            </InlineAlert>
          ) : null}
          {election.status === "RECONCILED" && readiness.data?.snapshot_sha256 ? (
            <p className="text-body-sm text-subtle-foreground">
              Reconciled snapshot{" "}
              <code className="mono">{readiness.data.snapshot_sha256.slice(0, 16)}…</code>
            </p>
          ) : null}
        </div>
      </Card>

      {editable ? <ElectionSettings election={election} etag={etag} onSaved={refresh} /> : null}

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-h2">Contests and candidates</h2>
          {editable ? (
            <Button
              variant="secondary"
              size="sm"
              leading={<Plus className="h-4 w-4" aria-hidden />}
              onClick={() => setAddContest(true)}
            >
              Add contest
            </Button>
          ) : null}
        </div>
        {contests.isLoading ? (
          <Skeleton className="h-32" />
        ) : (contests.data ?? []).length === 0 ? (
          <EmptyState
            icon={<BookOpenCheck className="h-8 w-8" aria-hidden />}
            title="No contests yet"
            description="Add the contest you are tracking (for example, Governorship), then its candidates."
          />
        ) : (
          <div className="flex flex-col gap-4">
            {contests.data!.map((contest) => (
              <ContestCard
                key={contest.id}
                contest={contest}
                editable={editable}
                onAddCandidate={() => setAddCandidateFor(contest)}
              />
            ))}
          </div>
        )}
      </section>

      <AddContestPanel
        open={addContest}
        electionId={electionId}
        stateId={election.state_id}
        onClose={() => setAddContest(false)}
        onDone={refresh}
      />
      <AddCandidatePanel
        contest={addCandidateFor}
        onClose={() => setAddCandidateFor(null)}
        onDone={() => void queryClient.invalidateQueries({ queryKey: ["candidates"] })}
      />

      <ConfirmDialog
        open={confirm === "lock"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Lock this configuration?"
        description="Contests and candidates cannot change after this. The configuration is fingerprinted and agents sync against it. You will be asked for your authenticator code."
        confirmLabel="Lock configuration"
        loading={transition.isPending}
        onConfirm={() => transition.mutate("lock")}
      />
      <ConfirmDialog
        open={confirm === "live"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Open result capture?"
        description="Agents can send results from this moment."
        confirmLabel="Open result capture"
        loading={transition.isPending}
        onConfirm={() => transition.mutate("live")}
      />
      <ConfirmDialog
        open={confirm === "close"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Close result capture?"
        description="Agents will no longer be able to send new results for this election."
        confirmLabel="Close result capture"
        danger
        loading={transition.isPending}
        onConfirm={() => transition.mutate("close")}
      />
      <ConfirmDialog
        open={confirm === "reconcile"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Reconcile results?"
        description="This rebuilds the totals from the counting results, checks them a second time, and stores an immutable snapshot. Results cannot change afterwards."
        confirmLabel="Reconcile results"
        loading={transition.isPending}
        onConfirm={() => transition.mutate("reconcile")}
      />
    </div>
  );
}

function ElectionSettings({
  election,
  etag,
  onSaved,
}: {
  election: Election;
  etag: string;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(election.name);
  const [date, setDate] = useState(election.election_date);
  const [policy, setPolicy] = useState(election.count_policy ?? "REPORTED");
  const [review, setReview] = useState(!!election.review_enabled);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      ep.elections.update(
        election.id,
        { name: name.trim(), election_date: date, count_policy: policy, review_enabled: review },
        etag,
      ),
    onSuccess: () => {
      toast("Election saved");
      setError(null);
      onSaved();
    },
    onError: (e) =>
      setError(
        e instanceof ApiError && e.isStale
          ? "Someone else changed this election. Reload the page and try again."
          : fail(e, "Could not save."),
      ),
  });

  return (
    <Card>
      <CardHeader
        title="Settings"
        description="You can change these until the configuration is locked."
      />
      <form
        className="grid grid-cols-1 gap-4 p-5 pt-2 md:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {error ? (
          <div className="md:col-span-2">
            <InlineAlert tone="danger" title="Not saved">
              {error}
            </InlineAlert>
          </div>
        ) : null}
        <Field label="Name">
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Election date">
          {(p) => (
            <Input {...p} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          )}
        </Field>
        <Field
          label="What counts on the dashboard"
          hint="Verified only counts results a reviewer has approved."
        >
          {(p) => (
            <Select
              {...p}
              value={policy}
              onChange={(e) => setPolicy(e.target.value as "REPORTED" | "VERIFIED")}
            >
              <option value="REPORTED">All reported results</option>
              <option value="VERIFIED">Verified results only</option>
            </Select>
          )}
        </Field>
        <label className="flex items-center gap-3 self-end pb-2 text-body">
          <input
            type="checkbox"
            className="h-5 w-5 accent-[rgb(var(--primary))]"
            checked={review}
            onChange={(e) => setReview(e.target.checked)}
          />
          Officers review results before they count as verified
        </label>
        <div className="md:col-span-2">
          <Button type="submit" loading={save.isPending}>
            Save settings
          </Button>
        </div>
      </form>
    </Card>
  );
}

function ContestCard({
  contest,
  editable,
  onAddCandidate,
}: {
  contest: Contest;
  editable: boolean;
  onAddCandidate: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [removing, setRemoving] = useState<Candidate | null>(null);

  const candidates = useQuery({
    queryKey: ["candidates", contest.id],
    queryFn: async () => {
      const data = await ep.contests.candidates(contest.id);
      return Array.isArray(data) ? data : data.results;
    },
  });

  const remove = useMutation({
    mutationFn: (c: Candidate) => ep.candidates.remove(c.id, `"${c.row_version ?? 0}"`),
    onSuccess: () => {
      setRemoving(null);
      toast("Candidate removed");
      void queryClient.invalidateQueries({ queryKey: ["candidates", contest.id] });
    },
    onError: (e) => {
      setRemoving(null);
      toast(fail(e, "Could not remove the candidate. Reload and try again."));
    },
  });

  return (
    <Card>
      <CardHeader
        title={contest.title}
        description={`${OFFICE_LABEL[contest.office] ?? contest.office} · ${contest.jurisdiction_level.toLowerCase()} level · records ${contest.sheet_fields?.join(", ") ?? "valid"}`}
        actions={
          editable ? (
            <Button
              size="sm"
              variant="secondary"
              leading={<Plus className="h-4 w-4" aria-hidden />}
              onClick={onAddCandidate}
            >
              Add candidate
            </Button>
          ) : undefined
        }
      />
      <div className="p-5 pt-2">
        <DataTable<Candidate>
          caption={`Candidates for ${contest.title}`}
          dense
          rows={[...(candidates.data ?? [])].sort((a, b) => a.ballot_order - b.ballot_order)}
          rowKey={(c) => c.id}
          columns={[
            {
              key: "order",
              header: "Ballot",
              numeric: true,
              cell: (c) => c.ballot_order,
              width: "80px",
            },
            {
              key: "name",
              header: "Candidate",
              cell: (c) => <span className="font-semibold">{c.name}</span>,
            },
            { key: "party", header: "Party", cell: (c) => `${c.party_acronym} · ${c.party_name}` },
            {
              key: "own",
              header: "",
              cell: (c) =>
                c.is_own_party ? (
                  <StatusChip status={{ label: "Your candidate", tone: "teal", icon: "star" }} />
                ) : null,
            },
            {
              key: "actions",
              header: "",
              cell: (c) =>
                editable ? (
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={`Remove ${c.name}`}
                    onClick={() => setRemoving(c)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                ) : null,
            },
          ]}
          empty={<p className="py-4 text-body text-subtle-foreground">No candidates yet.</p>}
        />
      </div>
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.name ?? "this candidate"}?`}
        description={`They will no longer appear on the ${contest.title} result sheet in the app.`}
        confirmLabel="Remove candidate"
        danger
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </Card>
  );
}

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
  const [name, setName] = useState("");
  const [date, setDate] = useState("");
  const [policy, setPolicy] = useState<"REPORTED" | "VERIFIED">("REPORTED");
  const [review, setReview] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lgas = useQuery({
    queryKey: ["geo", "lgas"],
    queryFn: async () => (await ep.geography.lgas({ limit: 200 })).results,
    staleTime: 10 * 60_000,
  });
  const stateId = lgas.data?.[0]?.state_id;

  const create = useMutation({
    mutationFn: () =>
      ep.elections.create({
        name: name.trim(),
        state_id: stateId!,
        election_date: date,
        count_policy: policy,
        review_enabled: review,
      }),
    onSuccess: (created) => {
      toast("Election created");
      void queryClient.invalidateQueries({ queryKey: ["elections"] });
      onCreated(created.id);
      setName("");
      setDate("");
      setError(null);
      onClose();
    },
    onError: (e) => setError(fail(e, "Could not create the election.")),
  });

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setError(null);
          onClose();
        }
      }}
      title="New election"
      description="You add contests and candidates next."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={create.isPending}
            disabled={!name.trim() || !date || !stateId}
            onClick={() => create.mutate()}
          >
            Create election
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <InlineAlert tone="danger" title="Not created">
            {error}
          </InlineAlert>
        ) : null}
        {!stateId && !lgas.isLoading ? (
          <InlineAlert tone="warning" title="No master data loaded">
            The polling unit directory for your state has not been imported yet.
          </InlineAlert>
        ) : null}
        <Field label="Name" hint="For example: Oyo State governorship election 2027">
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Election date">
          {(p) => (
            <Input {...p} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          )}
        </Field>
        <Field label="What counts on the dashboard">
          {(p) => (
            <Select
              {...p}
              value={policy}
              onChange={(e) => setPolicy(e.target.value as "REPORTED" | "VERIFIED")}
            >
              <option value="REPORTED">All reported results</option>
              <option value="VERIFIED">Verified results only</option>
            </Select>
          )}
        </Field>
        <label className="flex items-center gap-3 text-body">
          <input
            type="checkbox"
            className="h-5 w-5 accent-[rgb(var(--primary))]"
            checked={review}
            onChange={(e) => setReview(e.target.checked)}
          />
          Officers review results before they count as verified
        </label>
      </div>
    </SidePanel>
  );
}

function AddContestPanel({
  open,
  electionId,
  stateId,
  onClose,
  onDone,
}: {
  open: boolean;
  electionId: string;
  stateId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [office, setOffice] = useState("GOVERNORSHIP");
  const [title, setTitle] = useState("");
  const [level, setLevel] = useState<"STATE" | "LGA">("STATE");
  const [lgaIds, setLgaIds] = useState<string[]>([]);
  const [fields, setFields] = useState<string[]>(["accredited", "valid", "rejected", "total_cast"]);
  const [error, setError] = useState<string | null>(null);

  const { lgas } = useElectionLgas();

  const create = useMutation({
    mutationFn: () =>
      ep.elections.createContest(electionId, {
        office: office as never,
        title: title.trim(),
        jurisdiction_level: level as never,
        jurisdiction_ids: level === "STATE" ? [stateId] : lgaIds,
        sheet_fields: fields as never,
      }),
    onSuccess: () => {
      toast("Contest added");
      setTitle("");
      setError(null);
      onDone();
      onClose();
    },
    onError: (e) => setError(fail(e, "Could not add the contest.")),
  });

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title="Add contest"
      description="A contest covers a state or a set of LGAs. It decides which totals agents capture."
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
      <div className="flex flex-col gap-4">
        {error ? (
          <InlineAlert tone="danger" title="Not added">
            {error}
          </InlineAlert>
        ) : null}
        <Field label="Office">
          {(p) => (
            <Select {...p} value={office} onChange={(e) => setOffice(e.target.value)}>
              {OFFICES.map((o) => (
                <option key={o} value={o}>
                  {OFFICE_LABEL[o]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Title" hint="Shown to agents on the result sheet.">
          {(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} />}
        </Field>
        <Field label="Covers">
          {(p) => (
            <Select
              {...p}
              value={level}
              onChange={(e) => setLevel(e.target.value as "STATE" | "LGA")}
            >
              <option value="STATE">The whole state</option>
              <option value="LGA">Selected LGAs (for example, a senatorial district)</option>
            </Select>
          )}
        </Field>
        {level === "LGA" ? (
          <fieldset className="max-h-56 overflow-y-auto rounded-md border border-border p-3">
            <legend className="px-1 text-label text-strong-foreground">LGAs</legend>
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
          <legend className="px-1 text-label text-strong-foreground">Totals agents record</legend>
          {SHEET_FIELDS.map(([value, label, required]) => (
            <label key={value} className="flex min-h-9 items-center gap-3 text-body-sm">
              <input
                type="checkbox"
                className="h-5 w-5 accent-[rgb(var(--primary))]"
                checked={fields.includes(value)}
                disabled={required}
                onChange={() => setFields((cur) => toggle(cur, value))}
              />
              {label}
              {required ? (
                <span className="text-caption text-subtle-foreground">(always)</span>
              ) : null}
            </label>
          ))}
        </fieldset>
      </div>
    </SidePanel>
  );
}

function AddCandidatePanel({
  contest,
  onClose,
  onDone,
}: {
  contest: Contest | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [party, setParty] = useState("");
  const [acronym, setAcronym] = useState("");
  const [order, setOrder] = useState("1");
  const [own, setOwn] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      toast("Candidate added");
      setName("");
      setParty("");
      setAcronym("");
      setOrder(String(Number(order) + 1));
      setOwn(false);
      setError(null);
      onDone();
      onClose();
    },
    onError: (e) => setError(fail(e, "Could not add the candidate.")),
  });

  return (
    <SidePanel
      open={!!contest}
      onOpenChange={(next) => !next && onClose()}
      title="Add candidate"
      description={
        contest ? `For ${contest.title}. Ballot order follows the printed ballot paper.` : undefined
      }
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
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
      <div className="flex flex-col gap-4">
        {error ? (
          <InlineAlert tone="danger" title="Not added">
            {error}
          </InlineAlert>
        ) : null}
        <Field label="Candidate name">
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Party name">
          {(p) => <Input {...p} value={party} onChange={(e) => setParty(e.target.value)} />}
        </Field>
        <Field label="Party acronym" hint="Letters, numbers and hyphens. Up to 20.">
          {(p) => (
            <Input
              {...p}
              value={acronym}
              onChange={(e) => setAcronym(e.target.value)}
              maxLength={20}
            />
          )}
        </Field>
        <Field label="Ballot order">
          {(p) => (
            <Input
              {...p}
              type="number"
              min={1}
              max={200}
              value={order}
              onChange={(e) => setOrder(e.target.value)}
            />
          )}
        </Field>
        <label className="flex items-center gap-3 text-body">
          <input
            type="checkbox"
            className="h-5 w-5 accent-[rgb(var(--primary))]"
            checked={own}
            onChange={(e) => setOwn(e.target.checked)}
          />
          This is our party&apos;s candidate
        </label>
      </div>
    </SidePanel>
  );
}
