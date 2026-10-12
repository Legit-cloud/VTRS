"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  cursorFrom,
  normalizePhone,
  pluralize,
  toastVerb,
  userStatus,
  type Assignment,
  type Member,
  type PollingUnit,
} from "@vtrs/core";
import { Upload, UserPlus, UsersRound } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { ConfirmDialog, SidePanel } from "@/components/ui/dialog";
import { EmptyState, InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { DataTable } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { PollingUnitPicker, type PickedUnit } from "@/components/vtrs/pu-picker";
import { ep } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { describeError, errorLines } from "@/lib/errors";
import { useStates } from "@/lib/geo-names";
import { readInviteCsv, type InviteRow } from "@/lib/csv";
import { useElection } from "@/lib/election";
import { useStepUp } from "@/lib/step-up";

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Statuses in which the server accepts new assignments. */
const ASSIGNABLE = ["DRAFT", "CONFIGURED", "LOCKED", "LIVE"];

export default function AgentsPage() {
  const { election } = useElection();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const [invite, setInvite] = useState(false);
  const [bulk, setBulk] = useState(false);
  const [assignTo, setAssignTo] = useState<Member | null>(null);
  const [deactivate, setDeactivate] = useState<Member | null>(null);

  const canInvite = can("users.manage");

  const agents = useQuery({
    queryKey: ["team", "agents"],
    queryFn: async () => (await ep.team.users({ role: "PU_AGENT", limit: 200 })).results,
    enabled: canInvite,
  });
  const assignments = useQuery({
    queryKey: ["assignments", election?.id],
    enabled: !!election,
    queryFn: async () =>
      (await ep.assignments.list({ election: election!.id, status: "ACTIVE", limit: 200 })).results,
  });
  const invitations = useQuery({
    queryKey: ["team", "invitations"],
    enabled: canInvite,
    queryFn: async () => (await ep.team.invitations({ limit: 100 })).results,
  });

  const byAgent = useMemo(() => {
    const map = new Map<string, Assignment[]>();
    for (const a of assignments.data ?? []) {
      map.set(a.agent_id, [...(map.get(a.agent_id) ?? []), a]);
    }
    return map;
  }, [assignments.data]);

  const revoke = useMutation({
    mutationFn: (id: string) => stepUp(() => ep.assignments.revoke(id)),
    onSuccess: () => {
      toast("Assignment removed");
      void queryClient.invalidateQueries({ queryKey: ["assignments"] });
    },
    onError: (e) => toast(describeError(e, "Could not remove the assignment.")),
  });
  const revokeInvite = useMutation({
    mutationFn: (id: string) => stepUp(() => ep.team.revokeInvitation(id)),
    onSuccess: () => {
      toast(toastVerb.revoke);
      void queryClient.invalidateQueries({ queryKey: ["team"] });
    },
    onError: (e) => toast(describeError(e, "Could not revoke the invitation.")),
  });
  const deactivateMutation = useMutation({
    mutationFn: (id: string) => stepUp(() => ep.team.deactivate(id)),
    onSuccess: () => {
      toast(toastVerb.deactivate);
      setDeactivate(null);
      void queryClient.invalidateQueries({ queryKey: ["team"] });
      void queryClient.invalidateQueries({ queryKey: ["assignments"] });
    },
    onError: (e) => toast(describeError(e, "Could not deactivate this agent.")),
  });

  const pendingInvites = (invitations.data ?? []).filter((i) => i.role === "PU_AGENT");

  return (
    <>
      <PageHeader
        title="Agents"
        description="Invite polling unit agents and place them at the units they will cover."
        actions={
          canInvite ? (
            <>
              <Button
                variant="outline"
                leading={<Upload className="h-4 w-4" aria-hidden />}
                onClick={() => setBulk(true)}
              >
                Invite from CSV
              </Button>
              <Button
                leading={<UserPlus className="h-4 w-4" aria-hidden />}
                onClick={() => setInvite(true)}
              >
                Invite agent
              </Button>
            </>
          ) : undefined
        }
      />

      {!election ? (
        <InlineAlert tone="info" title="No election selected" className="mb-4">
          Assignments are per election. Set one up under Elections first.
        </InlineAlert>
      ) : null}

      {election ? (
        <ElectionContext
          name={election.name}
          stateId={election.state_id}
          status={election.status ?? "DRAFT"}
        />
      ) : null}

      {agents.isLoading || assignments.isLoading ? (
        <Skeleton className="h-72" />
      ) : agents.isError ? (
        <QueryError error={agents.error} onRetry={() => void agents.refetch()} />
      ) : (
        <DataTable<Member>
          caption="Polling unit agents"
          rows={agents.data ?? []}
          rowKey={(m) => m.user_id}
          initialSort={{ key: "name", dir: "asc" }}
          columns={[
            {
              key: "name",
              header: "Agent",
              cell: (m) => <span className="font-semibold">{m.full_name}</span>,
              sortValue: (m) => m.full_name,
            },
            {
              key: "status",
              header: "Status",
              cell: (m) => <StatusChip status={userStatus(m.status)} />,
              sortValue: (m) => m.status,
            },
            {
              key: "unit",
              header: "Assigned polling unit",
              cell: (m) => {
                const list = byAgent.get(m.user_id) ?? [];
                if (list.length === 0)
                  return <span className="text-subtle-foreground">Not assigned</span>;
                return (
                  <ul className="flex flex-col gap-1">
                    {list.map((a) => (
                      <li key={a.id} className="flex items-center gap-2">
                        <span className="mono">{a.polling_unit_code}</span>
                        <button
                          type="button"
                          className="text-caption font-semibold text-primary hover:underline"
                          onClick={() => revoke.mutate(a.id)}
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                );
              },
            },
            {
              key: "actions",
              header: "",
              cell: (m) =>
                m.status === "ACTIVE" ? (
                  <span className="flex justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setAssignTo(m)}
                      disabled={!election || !ASSIGNABLE.includes(election.status ?? "DRAFT")}
                    >
                      Assign
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-signal-red-text"
                      onClick={() => setDeactivate(m)}
                    >
                      Deactivate
                    </Button>
                  </span>
                ) : null,
            },
          ]}
          empty={
            <EmptyState
              icon={<UsersRound className="h-8 w-8" aria-hidden />}
              title="No agents yet"
              description="Invite an agent by phone number. They set up their account in the VTRS app."
              action={
                canInvite ? (
                  <Button
                    onClick={() => setInvite(true)}
                    leading={<UserPlus className="h-4 w-4" aria-hidden />}
                  >
                    Invite agent
                  </Button>
                ) : undefined
              }
            />
          }
        />
      )}

      {pendingInvites.length > 0 ? (
        <section className="mt-8">
          <h2 className="mb-3 text-h2">Waiting to accept</h2>
          <DataTable
            caption="Invitations not yet accepted"
            rows={pendingInvites}
            rowKey={(i) => i.id}
            dense
            columns={[
              {
                key: "name",
                header: "Name",
                cell: (i) => <span className="font-semibold">{i.full_name}</span>,
              },
              {
                key: "scope",
                header: "Polling units",
                cell: (i) => pluralize((i.scope_ids ?? []).length, "unit"),
                numeric: true,
              },
              {
                key: "expires",
                header: "Expires",
                cell: (i) =>
                  new Date(i.expires_at).toLocaleDateString("en-GB", { timeZone: "Africa/Lagos" }),
              },
              {
                key: "revoke",
                header: "",
                cell: (i) => (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-signal-red-text"
                    onClick={() => revokeInvite.mutate(i.id)}
                  >
                    Revoke
                  </Button>
                ),
              },
            ]}
            empty={null}
          />
        </section>
      ) : null}

      <InviteAgentPanel open={invite} onClose={() => setInvite(false)} />
      <BulkInvitePanel open={bulk} onClose={() => setBulk(false)} />
      <AssignPanel
        agent={assignTo}
        election={election ?? null}
        assigned={
          new Set((byAgent.get(assignTo?.user_id ?? "") ?? []).map((a) => a.polling_unit_id))
        }
        onClose={() => setAssignTo(null)}
      />
      <ConfirmDialog
        open={!!deactivate}
        onOpenChange={(next) => !next && setDeactivate(null)}
        title={`Deactivate ${deactivate?.full_name ?? "this agent"}?`}
        description={`${deactivate?.full_name ?? "This agent"} is signed out everywhere and their phone is cut off. They are removed from ${pluralize(
          (byAgent.get(deactivate?.user_id ?? "") ?? []).length,
          "polling unit",
        )} in this election, so someone else can be placed there. Results they already sent stay on record.`}
        confirmLabel="Deactivate agent"
        danger
        loading={deactivateMutation.isPending}
        onConfirm={() => deactivate && deactivateMutation.mutate(deactivate.user_id)}
      />
    </>
  );
}

function InviteAgentPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [units, setUnits] = useState<PickedUnit[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const reset = () => {
    setName("");
    setPhone("");
    setEmail("");
    setUnits([]);
    setErrors({});
  };

  const send = useMutation({
    mutationFn: () =>
      stepUp(() =>
        ep.team.invite({
          role: "PU_AGENT",
          full_name: name.trim(),
          phone: normalizePhone(phone) ?? phone,
          email: email.trim().toLowerCase(),
          scope_ids: units.map((u) => u.id),
        }),
      ),
    onSuccess: () => {
      toast(toastVerb.invite);
      void queryClient.invalidateQueries({ queryKey: ["team"] });
      reset();
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors({ ...e.fieldErrors(), _: describeError(e) });
    },
  });

  function submit() {
    const next: Record<string, string> = {};
    if (name.trim().length < 2) next.full_name = "Enter the agent's full name.";
    if (!normalizePhone(phone)) next.phone = "Enter a Nigerian phone number, like 0803 123 4567.";
    if (!EMAIL.test(email.trim())) next.email = "Enter a valid email address.";
    if (units.length === 0) next.scope_ids = "Choose at least one polling unit.";
    setErrors(next);
    if (Object.keys(next).length === 0) send.mutate();
  }

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title="Invite agent"
      description="We send an invitation by SMS. They accept it in the VTRS app."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={send.isPending} onClick={submit}>
            Send invitation
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {errors._ ? (
          <InlineAlert tone="danger" title="The invitation was not sent">
            {errors._}
          </InlineAlert>
        ) : null}
        <Field label="Full name" error={errors.full_name}>
          {(props) => <Input {...props} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Phone number" error={errors.phone}>
          {(props) => (
            <Input
              {...props}
              inputMode="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="0803 123 4567"
            />
          )}
        </Field>
        <Field label="Email" error={errors.email} hint="Used for account recovery.">
          {(props) => (
            <Input
              {...props}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          )}
        </Field>
        <div>
          <h3 className="mb-2 text-label text-strong-foreground">Polling units</h3>
          <PollingUnitPicker value={units} onChange={setUnits} />
          {errors.scope_ids ? (
            <p className="mt-1 text-caption text-signal-red-text">{errors.scope_ids}</p>
          ) : null}
        </div>
      </div>
    </SidePanel>
  );
}

type Checked = InviteRow & { problem: string | null; unit: PollingUnit | null };

function BulkInvitePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [rows, setRows] = useState<Checked[] | null>(null);
  const [checking, setChecking] = useState(false);
  const [progress, setProgress] = useState<{ done: number; failed: string[] } | null>(null);

  async function load(file: File) {
    setFileProblem(null);
    setRows(null);
    setProgress(null);
    const parsed = readInviteCsv(await file.text());
    if (parsed.problem) return setFileProblem(parsed.problem);
    if (parsed.rows.length > 500) return setFileProblem("Upload up to 500 agents at a time.");
    setChecking(true);
    try {
      // Validate codes against the directory this user is allowed to see.
      const index = new Map<string, PollingUnit>();
      let cursor: string | null = null;
      do {
        const page: Awaited<ReturnType<typeof ep.geography.pollingUnits>> =
          await ep.geography.pollingUnits({ limit: 200, cursor });
        page.results.forEach((u) => index.set(u.inec_code.toLowerCase(), u));
        cursor = cursorFrom(page.next);
      } while (cursor);
      const seenPhones = new Set<string>();
      setRows(
        parsed.rows.map((r) => {
          const unit = index.get(r.unitCode.toLowerCase()) ?? null;
          const phone = normalizePhone(r.phone);
          let problem: string | null = null;
          if (r.name.length < 2) problem = "Name is missing.";
          else if (!phone) problem = "Phone number is not valid.";
          else if (seenPhones.has(phone)) problem = "This phone number is listed twice.";
          else if (!EMAIL.test(r.email)) problem = "Email is not valid.";
          else if (!unit)
            problem = `Polling unit ${r.unitCode || "(blank)"} was not found in your scope.`;
          if (phone) seenPhones.add(phone);
          return { ...r, problem, unit };
        }),
      );
    } catch (e) {
      setFileProblem(describeError(e, "Could not check the polling unit codes."));
    } finally {
      setChecking(false);
    }
  }

  const valid = (rows ?? []).filter((r) => !r.problem);

  const send = useMutation({
    mutationFn: async () => {
      const failed: string[] = [];
      let done = 0;
      for (const row of valid) {
        try {
          await stepUp(() =>
            ep.team.invite({
              role: "PU_AGENT",
              full_name: row.name,
              phone: normalizePhone(row.phone)!,
              email: row.email.toLowerCase(),
              scope_ids: [row.unit!.id],
            }),
          );
        } catch (e) {
          failed.push(`Line ${row.line}: ${describeError(e, "not sent")}`);
        }
        done += 1;
        setProgress({ done, failed: [...failed] });
      }
      return failed;
    },
    onSuccess: (failed) => {
      toast(failed.length === 0 ? toastVerb.invite : `${failed.length} invitations were not sent`);
      void queryClient.invalidateQueries({ queryKey: ["team"] });
    },
  });

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title="Invite agents from a CSV"
      description="Columns: name, phone, email, polling_unit_code. Rows with problems are skipped, never sent."
      width={640}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button
            disabled={valid.length === 0 || send.isPending || progress?.done === valid.length}
            loading={send.isPending}
            onClick={() => send.mutate()}
          >
            {`Send ${pluralize(valid.length, "invitation")}`}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <input
          ref={fileInput}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(e) => e.target.files?.[0] && void load(e.target.files[0])}
        />
        <Button
          variant="secondary"
          onClick={() => fileInput.current?.click()}
          loading={checking}
          leading={<Upload className="h-4 w-4" aria-hidden />}
        >
          Choose a CSV file
        </Button>
        {fileProblem ? (
          <InlineAlert tone="danger" title="This file can't be used">
            {fileProblem}
          </InlineAlert>
        ) : null}
        {rows ? (
          <>
            <p className="text-body-sm text-strong-foreground">
              {valid.length} ready, {rows.length - valid.length} with problems.
            </p>
            <DataTable<Checked>
              caption="CSV preview"
              rows={rows}
              rowKey={(r) => String(r.line)}
              dense
              columns={[
                { key: "line", header: "Line", numeric: true, cell: (r) => r.line },
                { key: "name", header: "Name", cell: (r) => r.name || "–" },
                {
                  key: "unit",
                  header: "Polling unit",
                  cell: (r) => <span className="mono">{r.unitCode || "–"}</span>,
                },
                {
                  key: "check",
                  header: "Check",
                  cell: (r) =>
                    r.problem ? (
                      <span className="text-signal-red-text">{r.problem}</span>
                    ) : (
                      <span className="text-signal-teal-text">Ready</span>
                    ),
                },
              ]}
              empty={null}
            />
          </>
        ) : null}
        {progress ? (
          <InlineAlert
            tone={progress.failed.length ? "warning" : "success"}
            title={`${progress.done} of ${valid.length} processed`}
          >
            {progress.failed.length ? (
              <ul className="list-disc pl-4">
                {progress.failed.slice(0, 8).map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            ) : (
              "All invitations were sent."
            )}
          </InlineAlert>
        ) : null}
      </div>
    </SidePanel>
  );
}

function ElectionContext({
  name,
  stateId,
  status,
}: {
  name: string;
  stateId: string;
  status: string;
}) {
  const { states } = useStates();
  const where = states.find((x) => x.id === stateId)?.name;
  const closed = !ASSIGNABLE.includes(status);
  return (
    <InlineAlert
      tone={closed ? "warning" : "info"}
      title={`Assigning for ${name}${where ? ` (${where})` : ""}`}
      className="mb-4"
    >
      {closed
        ? "This election is closed, so agents can no longer be placed. Pick another election from the selector at the top."
        : "Agents can only be placed at polling units inside this election's state. To work on another election, switch it from the selector at the top."}
    </InlineAlert>
  );
}

function AssignPanel({
  agent,
  election,
  assigned,
  onClose,
}: {
  agent: Member | null;
  election: { id: string; name: string; state_id: string } | null;
  assigned: Set<string>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const [choice, setChoice] = useState<string>("");
  const [other, setOther] = useState<PickedUnit[]>([]);
  const [error, setError] = useState<string[]>([]);

  const authorised = (agent?.scope.type === "PU" ? agent.scope.ids : []).slice(0, 100);
  const units = useQuery({
    queryKey: ["geo", "units-by-id", authorised.join(",")],
    enabled: !!agent && authorised.length > 0,
    queryFn: async () =>
      (await ep.geography.pollingUnits({ ids: authorised.join(","), limit: 100 })).results,
  });

  const inState = (units.data ?? []).filter((u) => u.state_id === election?.state_id);
  const elsewhere = (units.data ?? []).length - inState.length;
  const free = inState.filter((u) => !assigned.has(u.id));
  const target = choice === "__other" ? other[0]?.id : choice;

  const reset = () => {
    setChoice("");
    setOther([]);
    setError([]);
  };

  const assign = useMutation({
    mutationFn: () =>
      stepUp(async () => {
        // A unit outside the agent's authorised list: widen their authorisation first.
        if (!authorised.includes(target!)) {
          await ep.team.updateMembership(agent!.user_id, {
            role: "PU_AGENT",
            scope_ids: [...authorised, target!],
          });
        }
        return ep.assignments.create({
          election_id: election!.id,
          agent_id: agent!.user_id,
          polling_unit_id: target!,
        });
      }),
    onSuccess: () => {
      toast("Agent assigned");
      void queryClient.invalidateQueries({ queryKey: ["assignments"] });
      void queryClient.invalidateQueries({ queryKey: ["team"] });
      reset();
      onClose();
    },
    onError: (e) => setError(errorLines(e, "Could not assign this agent.")),
  });

  return (
    <SidePanel
      open={!!agent}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
      title={agent ? `Assign ${agent.full_name}` : "Assign agent"}
      description={
        election ? `Choose the polling unit they will report from for ${election.name}.` : undefined
      }
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!target} loading={assign.isPending} onClick={() => assign.mutate()}>
            Assign agent
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error.length > 0 ? (
          <InlineAlert tone="danger" title="Could not assign">
            <ul className="list-disc pl-5">
              {error.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </InlineAlert>
        ) : null}
        {units.isLoading ? <Skeleton className="h-24" /> : null}
        {!units.isLoading && free.length > 0 ? (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-label text-strong-foreground">
              Polling units this agent is authorised for
            </legend>
            {free.map((u) => (
              <label
                key={u.id}
                className="flex cursor-pointer items-start gap-3 rounded-md border border-border p-3 hover:bg-muted"
              >
                <input
                  type="radio"
                  name="unit"
                  className="mt-1 h-4 w-4 accent-[rgb(var(--primary))]"
                  checked={choice === u.id}
                  onChange={() => setChoice(u.id)}
                />
                <span>
                  <span className="block text-body-sm font-semibold">{u.name}</span>
                  <span className="mono block text-caption text-subtle-foreground">
                    {u.inec_code}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
        ) : null}
        {!units.isLoading && free.length === 0 ? (
          <InlineAlert tone="info" title="No unit left to choose from">
            {inState.length > 0
              ? "This agent is already assigned to every unit they were authorised for in this state. Pick another unit below."
              : elsewhere > 0
                ? "The units this agent was authorised for are in a different state from this election. Pick a unit in this election's state below."
                : "This agent has no authorised units yet. Pick one below."}
          </InlineAlert>
        ) : null}
        <label className="flex cursor-pointer items-start gap-3 rounded-md border border-border p-3 hover:bg-muted">
          <input
            type="radio"
            name="unit"
            className="mt-1 h-4 w-4 accent-[rgb(var(--primary))]"
            checked={choice === "__other"}
            onChange={() => setChoice("__other")}
          />
          <span>
            <span className="block text-body-sm font-semibold">A different polling unit</span>
            <span className="block text-caption text-subtle-foreground">
              Their authorisation is extended to include it.
            </span>
          </span>
        </label>
        {choice === "__other" ? (
          <PollingUnitPicker value={other} onChange={(next) => setOther(next.slice(-1))} max={1} />
        ) : null}
      </div>
    </SidePanel>
  );
}
