"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ROLE_LABEL,
  SEVERITY_ORDER,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
  severity,
  type RoleCode,
  type TotpSetup,
} from "@vtrs/core";
import { Bell, Check, ShieldCheck } from "lucide-react";
import QRCode from "qrcode";
import { Suspense, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { useAuth } from "@/lib/auth";
import { useGeoNames } from "@/lib/geo-names";
import { useStepUp } from "@/lib/step-up";

const fail = (e: unknown, fallback: string) => describeError(e, fallback);

function SettingsInner() {
  const { me, can } = useAuth();
  if (!me) return null;
  return (
    <>
      <PageHeader
        title="Settings"
        description="Your account, security and how you are told about anomalies."
      />
      <div className="flex max-w-4xl flex-col gap-6">
        <ProfileCard />
        <SecurityCard />
        <NotificationsCard />
        {can("alerts.configure") ? <AlertPolicyCard /> : null}
        {can("system.view") ? <SystemCard /> : null}
      </div>
    </>
  );
}

function ProfileCard() {
  const { me } = useAuth();
  const geo = useGeoNames();
  if (!me) return null;
  const org = me.organization as { name?: string };
  const rows: [string, string][] = [
    ["Name", me.full_name],
    ["Organisation", org.name ?? ""],
    ["Role", ROLE_LABEL[me.role as RoleCode] ?? me.role],
    ["Covers", geo.data?.describe(me.scope.type, me.scope.ids) ?? "…"],
    ["Phone", me.phone],
    ["Email", me.email],
  ];
  return (
    <Card>
      <CardHeader title="Your account" />
      <dl className="grid grid-cols-1 gap-x-8 gap-y-3 p-5 pt-2 sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-caption text-subtle-foreground">{label}</dt>
            <dd className="text-body font-medium">{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function SecurityCard() {
  const { me, reloadMe, adoptToken } = useAuth();
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!setup) return;
    let alive = true;
    QRCode.toDataURL(setup.otpauth_uri, { margin: 1, width: 192 }).then(
      (url) => alive && setQr(url),
    );
    return () => {
      alive = false;
    };
  }, [setup]);

  const begin = useMutation({
    mutationFn: () => ep.auth.totpSetup(),
    onSuccess: (data) => {
      setSetup(data);
      setError(null);
    },
    onError: (e) => setError(fail(e, "Could not start setup.")),
  });
  const confirm = useMutation({
    mutationFn: () => ep.auth.totpConfirm(code.trim()),
    onSuccess: async (data) => {
      adoptToken(data.access_token, data.access_expires_at);
      setRecovery(data.recovery_codes);
      setSetup(null);
      setCode("");
      await reloadMe();
    },
    onError: (e) => setError(fail(e, "That code did not match. Check the 6 digits and try again.")),
  });

  if (!me) return null;

  return (
    <Card>
      <CardHeader
        title="Sign-in security"
        description={
          me.mfa_required
            ? "Your role needs a second factor on every sign-in."
            : "A second factor protects your account if your password leaks."
        }
        actions={
          me.mfa_enabled ? (
            <StatusChip
              status={{ label: "Authenticator on", tone: "teal", icon: "shield-check" }}
            />
          ) : (
            <StatusChip status={{ label: "Not set up", tone: "amber", icon: "shield-alert" }} />
          )
        }
      />
      <div className="flex flex-col gap-4 p-5 pt-2">
        {!me.mfa_enabled && me.mfa_required && !setup ? (
          <InlineAlert tone="warning" title="Set up your authenticator to continue">
            Until you do, you can only use this page.
          </InlineAlert>
        ) : null}
        {error ? (
          <InlineAlert tone="danger" title="That did not work">
            {error}
          </InlineAlert>
        ) : null}

        {recovery ? (
          <InlineAlert tone="success" title="Save your recovery codes">
            <p>Each code works once if you lose your phone. They are not shown again.</p>
            <ul className="mono mt-2 grid grid-cols-2 gap-1">
              {recovery.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <Button className="mt-3" size="sm" variant="outline" onClick={() => setRecovery(null)}>
              I have saved them
            </Button>
          </InlineAlert>
        ) : null}

        {!me.mfa_enabled && !setup ? (
          <div>
            <Button
              loading={begin.isPending}
              onClick={() => begin.mutate()}
              leading={<ShieldCheck className="h-4 w-4" aria-hidden />}
            >
              Set up authenticator
            </Button>
          </div>
        ) : null}

        {setup ? (
          <div className="flex flex-col gap-4 sm:flex-row">
            <div className="flex flex-col items-center gap-2">
              {setup && qr ? (
                // The QR is a data: URL generated in the browser; next/image adds nothing here.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={qr} alt="QR code for your authenticator app" width={192} height={192} />
              ) : (
                <Skeleton className="h-48 w-48" />
              )}
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-3">
              <p className="text-body">
                Scan the code with an authenticator app, or type this key in by hand:
              </p>
              <code className="mono break-all rounded-md bg-muted p-2 text-body-sm">
                {setup.secret_base32}
              </code>
              <Field label="6-digit code from the app">
                {(p) => (
                  <Input
                    {...p}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className="max-w-48 tabular-nums tracking-widest"
                  />
                )}
              </Field>
              <div>
                <Button
                  loading={confirm.isPending}
                  disabled={code.trim().length < 6}
                  leading={<Check className="h-4 w-4" aria-hidden />}
                  onClick={() => confirm.mutate()}
                >
                  Turn on authenticator
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function NotificationsCard() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["notifications", "list"],
    queryFn: async () => (await ep.me.notifications({ limit: 20 })).results,
  });
  const readAll = useMutation({
    mutationFn: () => ep.me.markAllRead(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
  const read = useMutation({
    mutationFn: (id: string) => ep.me.markRead(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = (list.data ?? []).filter((n) => !n.read_at).length;

  return (
    <Card>
      <div id="notifications" />
      <CardHeader
        title="Notifications"
        actions={
          unread > 0 ? (
            <Button
              size="sm"
              variant="outline"
              loading={readAll.isPending}
              onClick={() => readAll.mutate()}
            >
              Mark all as read
            </Button>
          ) : undefined
        }
      />
      <div className="p-5 pt-2">
        {list.isLoading ? (
          <Skeleton className="h-24" />
        ) : list.isError ? (
          <QueryError error={list.error} onRetry={() => void list.refetch()} />
        ) : (list.data ?? []).length === 0 ? (
          <p className="flex items-center gap-2 text-body text-subtle-foreground">
            <Bell className="h-5 w-5" aria-hidden /> Nothing yet. Alerts about anomalies and reviews
            appear here.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {list.data!.map((n) => (
              <li key={n.id} className="flex items-start gap-3 py-3">
                <StatusChip status={severity(n.severity)} className="mt-0.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className={n.read_at ? "text-body" : "text-body font-semibold"}>{n.title}</p>
                  <p className="text-body-sm text-subtle-foreground">{n.body}</p>
                  <p className="text-caption text-subtle-foreground">
                    {formatRelative(n.created_at)}
                  </p>
                </div>
                {!n.read_at ? (
                  <Button size="sm" variant="ghost" onClick={() => read.mutate(n.id)}>
                    Mark read
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

const LEVELS = [
  ["WARD", "Ward officer"],
  ["LGA", "LGA officer"],
  ["ADMIN", "Party admin"],
] as const;
const CHANNELS = ["IN_APP", "PUSH", "SMS", "EMAIL", "WHATSAPP"] as const;
const CHANNEL_LABEL: Record<string, string> = {
  IN_APP: "In the portal",
  PUSH: "Push",
  SMS: "SMS",
  EMAIL: "Email",
  WHATSAPP: "WhatsApp",
};

interface Rung {
  notify: string[];
  channels: string[];
  ack_minutes: number | null;
  escalation_channels: string[];
}

function AlertPolicyCard() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  // Edits are kept on top of what the server says is in force; nothing is copied into state
  // until the person changes something.
  const [edits, setEdits] = useState<Record<string, Rung> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const policy = useQuery({ queryKey: ["alert-policy"], queryFn: () => ep.admin.alertPolicy() });
  const effective = policy.data?.effective as unknown as Record<string, Rung> | undefined;
  const draft = edits ?? effective ?? null;

  const save = useMutation({
    mutationFn: () => stepUp(() => ep.admin.updateAlertPolicy(draft as never)),
    onSuccess: () => {
      toast("Alert policy saved");
      setError(null);
      setEdits(null);
      void queryClient.invalidateQueries({ queryKey: ["alert-policy"] });
    },
    onError: (e) => setError(fail(e, "Could not save the policy.")),
  });
  const reset = useMutation({
    mutationFn: () => stepUp(() => ep.admin.resetAlertPolicy()),
    onSuccess: () => {
      toast("Defaults restored");
      setEdits(null);
      void queryClient.invalidateQueries({ queryKey: ["alert-policy"] });
    },
    onError: (e) => setError(fail(e, "Could not restore the defaults.")),
  });

  const patch = (sev: string, change: Partial<Rung>) => {
    const base = edits ?? effective;
    if (!base) return;
    setEdits({ ...base, [sev]: { ...base[sev]!, ...change } });
  };
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value];

  return (
    <Card>
      <CardHeader
        title="Who is told, and how fast"
        description="When a flag is raised, the people whose area covers it are told. If nobody acknowledges it in time, it climbs one level."
        actions={
          policy.data?.overridden ? (
            <StatusChip
              status={{ label: "Customised", tone: "blue", icon: "sliders-horizontal" }}
            />
          ) : (
            <StatusChip status={{ label: "Platform defaults", tone: "ink", icon: "settings" }} />
          )
        }
      />
      <div className="flex flex-col gap-6 p-5 pt-2">
        {error ? (
          <InlineAlert tone="danger" title="Not saved">
            {error}
          </InlineAlert>
        ) : null}
        {policy.isLoading || !draft ? (
          <Skeleton className="h-48" />
        ) : (
          SEVERITY_ORDER.map((sev) => {
            const rung = draft[sev];
            if (!rung) return null;
            const view = severity(sev);
            return (
              <fieldset key={sev} className="rounded-md border border-border p-4">
                <legend className="px-1">
                  <StatusChip status={view} />
                </legend>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div>
                    <p className="mb-1 text-label text-strong-foreground">Told straight away</p>
                    {LEVELS.map(([value, label]) => (
                      <label key={value} className="flex min-h-9 items-center gap-2 text-body-sm">
                        <input
                          type="checkbox"
                          className="h-5 w-5 accent-[rgb(var(--primary))]"
                          checked={rung.notify.includes(value)}
                          onChange={() => patch(sev, { notify: toggle(rung.notify, value) })}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                  <div>
                    <p className="mb-1 text-label text-strong-foreground">Through</p>
                    {CHANNELS.map((c) => (
                      <label key={c} className="flex min-h-9 items-center gap-2 text-body-sm">
                        <input
                          type="checkbox"
                          className="h-5 w-5 accent-[rgb(var(--primary))]"
                          checked={rung.channels.includes(c)}
                          onChange={() => patch(sev, { channels: toggle(rung.channels, c) })}
                        />
                        {CHANNEL_LABEL[c]}
                      </label>
                    ))}
                  </div>
                  <div className="flex flex-col gap-3">
                    <Field label="Minutes to acknowledge" hint="Empty means it never escalates.">
                      {(p) => (
                        <Input
                          {...p}
                          type="number"
                          min={1}
                          value={rung.ack_minutes ?? ""}
                          onChange={(e) =>
                            patch(sev, {
                              ack_minutes: e.target.value === "" ? null : Number(e.target.value),
                            })
                          }
                        />
                      )}
                    </Field>
                    <div>
                      <p className="mb-1 text-label text-strong-foreground">
                        Added when it escalates
                      </p>
                      {CHANNELS.map((c) => (
                        <label key={c} className="flex min-h-8 items-center gap-2 text-body-sm">
                          <input
                            type="checkbox"
                            className="h-5 w-5 accent-[rgb(var(--primary))]"
                            checked={rung.escalation_channels.includes(c)}
                            onChange={() =>
                              patch(sev, {
                                escalation_channels: toggle(rung.escalation_channels, c),
                              })
                            }
                          />
                          {CHANNEL_LABEL[c]}
                        </label>
                      ))}
                    </div>
                  </div>
                </div>
              </fieldset>
            );
          })
        )}
        <div className="flex flex-wrap gap-2">
          <Button loading={save.isPending} disabled={!draft} onClick={() => save.mutate()}>
            Save policy
          </Button>
          {policy.data?.overridden ? (
            <Button variant="outline" loading={reset.isPending} onClick={() => reset.mutate()}>
              Restore defaults
            </Button>
          ) : null}
        </div>
        {policy.data?.updated_at ? (
          <p className="text-caption text-subtle-foreground">
            Last changed {formatDateTime(policy.data.updated_at)}. Saving needs your authenticator
            code.
          </p>
        ) : null}
      </div>
    </Card>
  );
}

function SystemCard() {
  const health = useQuery({
    queryKey: ["admin", "health"],
    queryFn: () => ep.admin.health(),
    refetchInterval: 30_000,
  });
  const quality = useQuery({
    queryKey: ["admin", "quality"],
    queryFn: () => ep.admin.dataQuality(),
  });

  return (
    <Card>
      <CardHeader
        title="System and data"
        description="Is the service healthy, and is the master data complete enough to trust the geofence?"
      />
      <div className="grid grid-cols-1 gap-6 p-5 pt-2 md:grid-cols-2">
        <div>
          <h3 className="mb-2 flex items-center gap-2 text-h3">
            Service
            {health.data ? (
              <StatusChip
                status={
                  health.data.status === "ok"
                    ? { label: "Healthy", tone: "teal", icon: "check-circle-2" }
                    : { label: "Needs attention", tone: "amber", icon: "alert-triangle" }
                }
              />
            ) : null}
          </h3>
          {health.isLoading ? (
            <Skeleton className="h-24" />
          ) : health.isError ? (
            <QueryError error={health.error} onRetry={() => void health.refetch()} />
          ) : (
            <dl className="flex flex-col gap-1.5 text-body-sm">
              {Object.entries(health.data!.components ?? {}).map(([name, value]) => (
                <div key={name} className="flex justify-between gap-3">
                  <dt className="text-subtle-foreground">{name.replace(/_/g, " ")}</dt>
                  <dd className="font-medium">
                    {typeof value === "object" && value !== null
                      ? String((value as { status?: unknown }).status ?? JSON.stringify(value))
                      : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-h3">Master data</h3>
          {quality.isLoading ? (
            <Skeleton className="h-24" />
          ) : quality.isError ? (
            <QueryError error={quality.error} onRetry={() => void quality.refetch()} />
          ) : (
            <dl className="flex flex-col gap-1.5 text-body-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-subtle-foreground">Polling units</dt>
                <dd className="tabular-nums font-medium">
                  {formatNumber(quality.data!.polling_units)}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-subtle-foreground">With coordinates</dt>
                <dd className="tabular-nums font-medium">
                  {formatPercent(quality.data!.coordinates_complete_pct)}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-subtle-foreground">Without registered voter count</dt>
                <dd className="tabular-nums font-medium">
                  {formatNumber(quality.data!.without_registered_voters)}
                </dd>
              </div>
            </dl>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <Suspense>
      <SettingsInner />
    </Suspense>
  );
}
