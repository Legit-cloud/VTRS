"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  ROLE_LABEL,
  formatDate,
  normalizePhone,
  toastVerb,
  userStatus,
  type Member,
  type RoleCode,
} from "@vtrs/core";
import { Pencil, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { ConfirmDialog, SidePanel } from "@/components/ui/dialog";
import { EmptyState, InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { DataTable } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { useAuth } from "@/lib/auth";
import { useElectionLgas, useGeoNames } from "@/lib/geo-names";
import { useStepUp } from "@/lib/step-up";

const OFFICER_ROLES: RoleCode[] = ["WARD_OFFICER", "LGA_OFFICER", "PARTY_ADMIN"];
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const fail = (e: unknown, fallback: string) => describeError(e, fallback);

export default function TeamPage() {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const geo = useGeoNames();
  const [invite, setInvite] = useState(false);
  const [editing, setEditing] = useState<Member | null>(null);
  const [deactivate, setDeactivate] = useState<Member | null>(null);

  const users = useQuery({
    queryKey: ["team", "all"],
    queryFn: async () => (await ep.team.users({ limit: 200 })).results,
  });
  const invitations = useQuery({
    queryKey: ["team", "invitations"],
    queryFn: async () => (await ep.team.invitations({ limit: 100 })).results,
  });

  const revoke = useMutation({
    mutationFn: (id: string) => stepUp(() => ep.team.revokeInvitation(id)),
    onSuccess: () => {
      toast(toastVerb.revoke);
      void queryClient.invalidateQueries({ queryKey: ["team"] });
    },
    onError: (e) => toast(fail(e, "Could not revoke the invitation.")),
  });
  const deactivateUser = useMutation({
    mutationFn: (id: string) => stepUp(() => ep.team.deactivate(id)),
    onSuccess: () => {
      toast("Person deactivated");
      setDeactivate(null);
      void queryClient.invalidateQueries({ queryKey: ["team"] });
    },
    onError: (e) => {
      setDeactivate(null);
      toast(fail(e, "Could not deactivate this person."));
    },
  });

  const people = (users.data ?? []).filter((u) => u.role !== "PU_AGENT");
  const sentence = (m: Member) =>
    `${ROLE_LABEL[m.role as RoleCode] ?? m.role} · ${geo.data?.describe(m.scope.type, m.scope.ids) ?? "…"}`;

  return (
    <>
      <PageHeader
        title="Team and permissions"
        description="Who can see and do what, and for which part of the state. Every change is written to the audit log."
        actions={
          <Button
            leading={<UserPlus className="h-4 w-4" aria-hidden />}
            onClick={() => setInvite(true)}
          >
            Invite officer
          </Button>
        }
      />

      {users.isLoading ? (
        <Skeleton className="h-72" />
      ) : users.isError ? (
        <QueryError error={users.error} onRetry={() => void users.refetch()} />
      ) : (
        <DataTable<Member>
          caption="Admins and officers"
          rows={people}
          rowKey={(m) => m.user_id}
          initialSort={{ key: "name", dir: "asc" }}
          columns={[
            {
              key: "name",
              header: "Name",
              cell: (m) => (
                <span>
                  <span className="font-semibold">{m.full_name}</span>
                  {m.user_id === me?.user_id ? (
                    <span className="ml-2 text-caption text-subtle-foreground">You</span>
                  ) : null}
                </span>
              ),
              sortValue: (m) => m.full_name,
            },
            { key: "access", header: "Access", cell: (m) => sentence(m) },
            {
              key: "status",
              header: "Status",
              cell: (m) => <StatusChip status={userStatus(m.status)} />,
            },
            {
              key: "mfa",
              header: "Second factor",
              cell: (m) =>
                m.mfa_enabled ? "On" : <span className="text-signal-amber-text">Not set up</span>,
              hideOnNarrow: true,
            },
            {
              key: "actions",
              header: "",
              cell: (m) =>
                m.user_id !== me?.user_id && m.status === "ACTIVE" ? (
                  <span className="flex justify-end gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      leading={<Pencil className="h-4 w-4" aria-hidden />}
                      onClick={() => setEditing(m)}
                    >
                      Change access
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
              icon={<Users className="h-8 w-8" aria-hidden />}
              title="Just you so far"
              description="Invite ward and LGA officers so each part of the state has someone watching it."
              action={<Button onClick={() => setInvite(true)}>Invite officer</Button>}
            />
          }
        />
      )}

      {(invitations.data ?? []).filter((i) => i.role !== "PU_AGENT").length > 0 ? (
        <section className="mt-8">
          <h2 className="mb-3 text-h2">Waiting to accept</h2>
          <DataTable
            caption="Officer invitations not yet accepted"
            dense
            rows={(invitations.data ?? []).filter((i) => i.role !== "PU_AGENT")}
            rowKey={(i) => i.id}
            columns={[
              {
                key: "name",
                header: "Name",
                cell: (i) => <span className="font-semibold">{i.full_name}</span>,
              },
              {
                key: "access",
                header: "Access",
                cell: (i) =>
                  `${ROLE_LABEL[i.role as RoleCode] ?? i.role} · ${geo.data?.describe(i.scope_type, i.scope_ids ?? []) ?? "…"}`,
              },
              { key: "expires", header: "Expires", cell: (i) => formatDate(i.expires_at) },
              {
                key: "revoke",
                header: "",
                cell: (i) => (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-signal-red-text"
                    loading={revoke.isPending && revoke.variables === i.id}
                    onClick={() => revoke.mutate(i.id)}
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

      <InvitePanel open={invite} onClose={() => setInvite(false)} />
      <ChangeAccessPanel member={editing} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={!!deactivate}
        onOpenChange={(open) => !open && setDeactivate(null)}
        title={`Deactivate ${deactivate?.full_name ?? "this person"}?`}
        description="They are signed out everywhere and lose all access. Their past actions stay in the audit log."
        confirmLabel="Deactivate"
        danger
        loading={deactivateUser.isPending}
        onConfirm={() => deactivate && deactivateUser.mutate(deactivate.user_id)}
      />
    </>
  );
}

/** Role plus scope. A ward officer needs wards, an LGA officer needs LGAs, an admin needs neither. */
function AccessFields({
  role,
  setRole,
  lgaIds,
  setLgaIds,
  wardIds,
  setWardIds,
  roles = OFFICER_ROLES,
}: {
  role: RoleCode;
  setRole: (r: RoleCode) => void;
  lgaIds: string[];
  setLgaIds: (v: string[]) => void;
  wardIds: string[];
  setWardIds: (v: string[]) => void;
  roles?: RoleCode[];
}) {
  const geo = useGeoNames();
  const [lgaForWards, setLgaForWards] = useState("");
  const { lgas } = useElectionLgas();
  const wards = [...(geo.data?.wards.values() ?? [])]
    .filter((w) => w.lga_id === lgaForWards)
    .sort((a, b) => a.name.localeCompare(b.name));
  const toggle = (list: string[], id: string) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

  return (
    <div className="flex flex-col gap-4">
      <Field label="Role">
        {(p) => (
          <Select {...p} value={role} onChange={(e) => setRole(e.target.value as RoleCode)}>
            {roles.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {role === "LGA_OFFICER" ? (
        <fieldset className="max-h-60 overflow-y-auto rounded-md border border-border p-3">
          <legend className="px-1 text-label text-strong-foreground">LGAs they cover</legend>
          {lgas.map((l) => (
            <label key={l.id} className="flex min-h-9 items-center gap-3 text-body-sm">
              <input
                type="checkbox"
                className="h-5 w-5 accent-[rgb(var(--primary))]"
                checked={lgaIds.includes(l.id)}
                onChange={() => setLgaIds(toggle(lgaIds, l.id))}
              />
              {l.name}
            </label>
          ))}
        </fieldset>
      ) : null}
      {role === "WARD_OFFICER" ? (
        <>
          <Field label="LGA">
            {(p) => (
              <Select {...p} value={lgaForWards} onChange={(e) => setLgaForWards(e.target.value)}>
                <option value="">Choose an LGA…</option>
                {lgas.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          {lgaForWards ? (
            <fieldset className="max-h-60 overflow-y-auto rounded-md border border-border p-3">
              <legend className="px-1 text-label text-strong-foreground">Wards they cover</legend>
              {wards.map((w) => (
                <label key={w.id} className="flex min-h-9 items-center gap-3 text-body-sm">
                  <input
                    type="checkbox"
                    className="h-5 w-5 accent-[rgb(var(--primary))]"
                    checked={wardIds.includes(w.id)}
                    onChange={() => setWardIds(toggle(wardIds, w.id))}
                  />
                  {w.name}
                </label>
              ))}
            </fieldset>
          ) : null}
          {wardIds.length > 0 ? (
            <p className="text-body-sm text-subtle-foreground">
              {wardIds.length} {wardIds.length === 1 ? "ward" : "wards"} selected.
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function scopeIds(role: RoleCode, lgaIds: string[], wardIds: string[]): string[] | null {
  if (role === "PARTY_ADMIN") return [];
  if (role === "LGA_OFFICER") return lgaIds.length ? lgaIds : null;
  if (role === "WARD_OFFICER") return wardIds.length ? wardIds : null;
  return null;
}

function InvitePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<RoleCode>("WARD_OFFICER");
  const [lgaIds, setLgaIds] = useState<string[]>([]);
  const [wardIds, setWardIds] = useState<string[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const send = useMutation({
    mutationFn: () =>
      stepUp(() =>
        ep.team.invite({
          role,
          full_name: name.trim(),
          phone: normalizePhone(phone) ?? phone,
          email: email.trim().toLowerCase(),
          scope_ids: scopeIds(role, lgaIds, wardIds) ?? [],
        }),
      ),
    onSuccess: () => {
      toast(toastVerb.invite);
      void queryClient.invalidateQueries({ queryKey: ["team"] });
      setName("");
      setPhone("");
      setEmail("");
      setLgaIds([]);
      setWardIds([]);
      setErrors({});
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError) setErrors({ ...e.fieldErrors(), _: describeError(e) });
    },
  });

  function submit() {
    const next: Record<string, string> = {};
    if (name.trim().length < 2) next.full_name = "Enter their full name.";
    if (!normalizePhone(phone)) next.phone = "Enter a Nigerian phone number, like 0803 123 4567.";
    if (!EMAIL.test(email.trim())) next.email = "Enter a valid email address.";
    if (scopeIds(role, lgaIds, wardIds) === null) next.scope = "Choose the area they will cover.";
    setErrors(next);
    if (Object.keys(next).length === 0) send.mutate();
  }

  return (
    <SidePanel
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title="Invite officer"
      description="They accept the invitation, set a password and a second factor."
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
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label="Phone number" error={errors.phone}>
          {(p) => (
            <Input
              {...p}
              inputMode="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          )}
        </Field>
        <Field label="Email" error={errors.email}>
          {(p) => (
            <Input {...p} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          )}
        </Field>
        <AccessFields
          role={role}
          setRole={setRole}
          lgaIds={lgaIds}
          setLgaIds={setLgaIds}
          wardIds={wardIds}
          setWardIds={setWardIds}
        />
        {errors.scope ? <p className="text-caption text-signal-red-text">{errors.scope}</p> : null}
      </div>
    </SidePanel>
  );
}

function ChangeAccessPanel({ member, onClose }: { member: Member | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const [role, setRole] = useState<RoleCode>("WARD_OFFICER");
  const [lgaIds, setLgaIds] = useState<string[]>([]);
  const [wardIds, setWardIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [seeded, setSeeded] = useState<string | null>(null);

  if (member && seeded !== member.user_id) {
    setSeeded(member.user_id);
    setRole(member.role as RoleCode);
    setLgaIds(member.scope.type === "LGA" ? member.scope.ids : []);
    setWardIds(member.scope.type === "WARD" ? member.scope.ids : []);
    setError(null);
  }

  const save = useMutation({
    mutationFn: () =>
      stepUp(() =>
        ep.team.updateMembership(member!.user_id, {
          role,
          scope_ids: scopeIds(role, lgaIds, wardIds) ?? [],
        }),
      ),
    onSuccess: () => {
      toast("Access updated");
      void queryClient.invalidateQueries({ queryKey: ["team"] });
      onClose();
    },
    onError: (e) => setError(fail(e, "Could not change access.")),
  });

  return (
    <SidePanel
      open={!!member}
      onOpenChange={(next) => !next && onClose()}
      title={member ? `Change access for ${member.full_name}` : "Change access"}
      description="This takes effect immediately, is written to the audit log, and needs your authenticator code."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            disabled={scopeIds(role, lgaIds, wardIds) === null}
            onClick={() => save.mutate()}
          >
            Save access
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <InlineAlert tone="danger" title="Not saved">
            {error}
          </InlineAlert>
        ) : null}
        <AccessFields
          role={role}
          setRole={setRole}
          lgaIds={lgaIds}
          setLgaIds={setLgaIds}
          wardIds={wardIds}
          setWardIds={setWardIds}
        />
      </div>
    </SidePanel>
  );
}
