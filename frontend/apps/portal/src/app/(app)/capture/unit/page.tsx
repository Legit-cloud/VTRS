"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  blockingProblem,
  buildSubmission,
  checkTotals,
  completeFor,
  copy,
  formatBytes,
  mismatchAccredited,
  mismatchTotalCast,
  reviewState,
  ruleTitle,
  shortfallTotalCast,
  SHEET_FIELD_ORDER,
  type ResultForm,
  type SheetField,
  type SubmissionOutcome,
} from "@vtrs/core";
import { ArrowLeft, Camera, CheckCircle2, FileUp, Flag, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Button, buttonStyles } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { Dialog } from "@/components/ui/dialog";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Textarea } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { PartyMark } from "@/components/vtrs/contestant-bar";
import { ep } from "@/lib/api";
import {
  clearDraft,
  loadDraft,
  newDraft,
  parseCount,
  saveDraft,
  type Draft,
} from "@/lib/capture/draft";
import { withRetry } from "@/lib/capture/retry";
import { prepareSheet, uploadSheet, type PreparedSheet } from "@/lib/capture/sheet";
import { cn } from "@/lib/cn";
import { errorLines } from "@/lib/errors";

const TOTAL_LABEL: Record<SheetField, { label: string; hint: string }> = {
  accredited: { label: "Accredited voters", hint: "People checked in to vote." },
  total_cast: { label: "Total votes cast", hint: "As written on the sheet." },
  rejected: { label: "Rejected votes", hint: "Spoiled or invalid ballots." },
};

function UnitInner() {
  const params = useSearchParams();
  const electionId = params.get("election") ?? "";
  const pollingUnitId = params.get("pu") ?? "";
  const form = useQuery({
    queryKey: ["form", electionId, pollingUnitId],
    enabled: !!electionId && !!pollingUnitId,
    queryFn: () => ep.agent.form(electionId, pollingUnitId),
    staleTime: 30_000,
  });

  const [sheetFor, setSheetFor] = useState<string | null>(
    params.get("step") === "sheet" ? params.get("version") : null,
  );
  const [done, setDone] = useState(false);

  return (
    <div className="flex flex-col gap-5">
      <Link
        href="/capture"
        className="inline-flex items-center gap-1 self-start text-label font-semibold text-primary-soft-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden /> My polling units
      </Link>
      {form.isLoading ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-64" />
        </div>
      ) : form.isError ? (
        <QueryError error={form.error} onRetry={() => void form.refetch()} />
      ) : form.data ? (
        <>
          <UnitHeader form={form.data} />
          {done ? (
            <Done form={form.data} />
          ) : sheetFor ? (
            <SheetStep versionId={sheetFor} onDone={() => setDone(true)} />
          ) : !form.data.capture_open ? (
            <InlineAlert tone="info" title="Result capture is not open">
              {form.data.election_status === "CLOSED" || form.data.election_status === "RECONCILED"
                ? "This election has closed. No more results can be sent."
                : "You can enter the result once capture opens for this election."}
            </InlineAlert>
          ) : form.data.parties.length === 0 ? (
            <NoForm form={form.data} />
          ) : form.data.current && params.get("correct") !== "1" ? (
            <AlreadySent form={form.data} onAttach={(v) => setSheetFor(v)} />
          ) : (
            <NumbersStep
              key={`${form.data.config_version}-${form.data.current?.version_id ?? "new"}-${params.get("correct") ?? ""}`}
              form={form.data}
              correcting={params.get("correct") === "1"}
              onSent={(versionId) => setSheetFor(versionId)}
            />
          )}
        </>
      ) : null}
    </div>
  );
}

function UnitHeader({ form }: { form: ResultForm }) {
  return (
    <div className="flex flex-col gap-0.5">
      <p className="text-caption font-semibold uppercase tracking-wide text-subtle-foreground">
        {form.election_name}
        {form.constituency ? ` · ${form.constituency.name}` : ""}
      </p>
      <h1 className="text-h2">{form.polling_unit.name}</h1>
      <p className="text-body-sm text-subtle-foreground">
        <span className="mono">{form.polling_unit.inec_code}</span> · {form.polling_unit.ward},{" "}
        {form.polling_unit.lga}
      </p>
    </div>
  );
}

// ---- step 1: the numbers --------------------------------------------------------------------

function NumbersStep({
  form,
  correcting,
  onSent,
}: {
  form: ResultForm;
  correcting: boolean;
  onSent: (versionId: string) => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const electionId = form.election_id;
  const pollingUnitId = form.polling_unit.id;
  // Open the draft kept on this phone, or start one (prefilled from the current version when
  // correcting it). The version id is fixed here, once, for every send of these numbers. This
  // screen only renders in the browser, after the form has loaded, so storage is readable.
  const [draft, setDraft] = useState<Draft | null>(() => openDraft(form, correcting));
  const [tried, setTried] = useState(false);
  const [sending, setSending] = useState<{ attempt: number; waitS: number } | null>(null);
  const [refusal, setRefusal] = useState<string[] | null>(null);
  const [outcome, setOutcome] = useState<SubmissionOutcome | null>(null);

  const update = (change: (d: Draft) => Draft) =>
    setDraft((d) => {
      if (!d) return d;
      const next = change(d);
      saveDraft(next);
      return next;
    });

  const parsed = useMemo(() => {
    if (!draft) return null;
    const votes = form.parties.map((p) => ({
      party: p,
      value: parseCount(draft.votes[p.candidate_id] ?? ""),
    }));
    const totals = Object.fromEntries(
      SHEET_FIELD_ORDER.map((f) => [f, parseCount(draft.totals[f] ?? "")]),
    ) as Record<SheetField, number | null | "invalid">;
    return { votes, totals };
  }, [draft, form.parties]);

  const numbers = (v: number | null | "invalid") => (typeof v === "number" ? v : null);
  const partyVotes = parsed?.votes.map((v) => numbers(v.value)) ?? [];
  const allParties = partyVotes.every((v) => v !== null);
  const totalsNow = parsed
    ? {
        accredited: numbers(parsed.totals.accredited),
        total_cast: numbers(parsed.totals.total_cast),
        rejected: numbers(parsed.totals.rejected),
      }
    : {};
  const checks = allParties ? checkTotals(partyVotes as number[], totalsNow) : [];
  const blocking = blockingProblem(checks);
  const sum = (partyVotes as number[]).reduce((a, b) => a + (b ?? 0), 0);
  const complete =
    !!parsed &&
    allParties &&
    SHEET_FIELD_ORDER.every((f) => typeof parsed.totals[f] === "number");

  const send = async () => {
    setTried(true);
    setRefusal(null);
    if (!draft || !complete || blocking) return;
    setSending({ attempt: 1, waitS: 0 });
    const gps = await position();
    const item = buildSubmission({
      versionId: draft.versionId,
      electionId,
      pollingUnitId,
      configVersion: draft.configVersion,
      parentVersionId: draft.parentVersionId,
      totals: totalsNow,
      votes: form.parties.map((p) => ({
        candidateId: p.candidate_id,
        votes: numbers(parseCount(draft.votes[p.candidate_id] ?? "")),
      })),
      capturedAt: new Date(draft.startedAt),
      gps,
    });
    try {
      const result = await withRetry(() => ep.agent.submit(item), {
        onRetry: (attempt, waitMs) =>
          setSending({ attempt: attempt + 1, waitS: Math.round(waitMs / 1000) }),
      });
      setSending(null);
      if (result.status === "FAILED") {
        setRefusal([result.detail ?? "The numbers were refused.", ...errorTexts(result.errors)]);
        return;
      }
      clearDraft(electionId, pollingUnitId);
      setOutcome(result);
      toast(copy.received.toast);
      // The form is not refetched here: its "current" would replace this screen.
      void queryClient.invalidateQueries({ queryKey: ["me", "assignments"] });
      if (result.status === "ACCEPTED") onSent(result.version_id!);
    } catch (e) {
      setSending(null);
      setRefusal(errorLines(e, "The numbers could not be sent."));
    }
  };

  if (!draft || !parsed) return <Skeleton className="h-64" />;

  if (outcome?.status === "REQUIRES_REVIEW") {
    return (
      <Card className="flex flex-col gap-4 p-5">
        <h2 className="text-h3">{copy.needsReview.headline}</h2>
        <p className="text-body text-strong-foreground">
          Your numbers count, and a coordinator will look at them. Now attach the result sheet.
        </p>
        {(outcome.flags ?? []).length > 0 ? (
          <ul className="list-disc pl-5 text-body-sm text-subtle-foreground">
            {outcome.flags!.map((f) => (
              <li key={f}>{ruleTitle(f)}</li>
            ))}
          </ul>
        ) : null}
        <Button onClick={() => onSent(outcome.version_id!)}>Attach the result sheet</Button>
      </Card>
    );
  }

  const blankError = (abbreviation: string, value: number | null | "invalid") =>
    value === "invalid"
      ? "Use a whole number, such as 0 or 125."
      : tried && value === null
        ? copy.blankParty(abbreviation)
        : null;

  return (
    <form
      className="flex flex-col gap-5"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      {correcting ? (
        <InlineAlert tone="info" title="Correcting your result">
          This sends a new version. The one you sent before is kept, not overwritten.
        </InlineAlert>
      ) : null}

      <Card className="flex flex-col p-0">
        <div className="border-b border-border px-5 py-3">
          <h2 className="text-h3">Votes for each party</h2>
          <p className="text-body-sm text-subtle-foreground">
            Copy every row from the result sheet, your own party too. Use 0 if a party got none.
          </p>
        </div>
        <ul className="divide-y divide-border">
          {parsed.votes.map(({ party, value }) => {
            const error = blankError(party.party_abbreviation, value);
            const id = `v-${party.candidate_id}`;
            return (
              <li key={party.candidate_id} className="flex items-center gap-3 px-5 py-3">
                <PartyMark
                  abbreviation={party.party_abbreviation}
                  logoUrl={party.party_logo_url}
                  size={32}
                />
                <label htmlFor={id} className="min-w-0 flex-1">
                  <span className="block text-body font-bold">{party.party_abbreviation}</span>
                  <span className="block truncate text-body-sm text-subtle-foreground">
                    {party.candidate_name}
                  </span>
                  {error ? (
                    <span id={`${id}-e`} className="block text-caption text-signal-red-text">
                      {error}
                    </span>
                  ) : null}
                </label>
                <CountInput
                  id={id}
                  value={draft.votes[party.candidate_id] ?? ""}
                  invalid={!!error}
                  describedBy={error ? `${id}-e` : undefined}
                  onChange={(text) =>
                    update((d) => ({ ...d, votes: { ...d.votes, [party.candidate_id]: text } }))
                  }
                />
              </li>
            );
          })}
        </ul>
        <div className="flex items-center justify-between border-t border-border bg-muted px-5 py-3">
          <span className="text-body-sm font-semibold">Valid votes (sum of the parties)</span>
          <span className="tabular-nums text-h3 font-bold">{allParties ? sum : "–"}</span>
        </div>
      </Card>

      <Card className="flex flex-col p-0">
        <div className="border-b border-border px-5 py-3">
          <h2 className="text-h3">Totals on the sheet</h2>
        </div>
        <ul className="divide-y divide-border">
          {SHEET_FIELD_ORDER.map((field) => {
            const value = parsed.totals[field];
            const id = `t-${field}`;
            const error =
              value === "invalid"
                ? "Use a whole number."
                : tried && value === null
                  ? `Enter ${TOTAL_LABEL[field].label.toLowerCase()}. Use 0 if there were none.`
                  : null;
            return (
              <li key={field} className="flex items-center gap-3 px-5 py-3">
                <label htmlFor={id} className="min-w-0 flex-1">
                  <span className="block text-body font-semibold">{TOTAL_LABEL[field].label}</span>
                  <span className="block text-caption text-subtle-foreground">
                    {TOTAL_LABEL[field].hint}
                  </span>
                  {error ? (
                    <span id={`${id}-e`} className="block text-caption text-signal-red-text">
                      {error}
                    </span>
                  ) : null}
                </label>
                <CountInput
                  id={id}
                  value={draft.totals[field] ?? ""}
                  invalid={!!error}
                  describedBy={error ? `${id}-e` : undefined}
                  onChange={(text) =>
                    update((d) => ({ ...d, totals: { ...d.totals, [field]: text } }))
                  }
                />
              </li>
            );
          })}
        </ul>
      </Card>

      <LiveChecks checks={checks} />

      {refusal ? (
        <InlineAlert tone="danger" title={copy.notSent.headline}>
          <ul className="list-disc pl-5">
            {refusal.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </InlineAlert>
      ) : null}
      {sending && sending.attempt > 1 ? (
        <InlineAlert tone="warning" title="Still sending">
          Attempt {sending.attempt}
          {sending.waitS > 0 ? `, trying again in ${sending.waitS} s` : ""}. Your numbers stay on
          this phone; keep this page open.
        </InlineAlert>
      ) : null}

      <Button
        type="submit"
        className="h-12 w-full text-body"
        loading={!!sending}
        disabled={!!sending || (tried && (!complete || !!blocking))}
      >
        {sending ? "Sending…" : correcting ? "Send the corrected numbers" : "Send the numbers"}
      </Button>
      <p className="text-center text-caption text-subtle-foreground">
        Your location is recorded once, when you send. You attach the result sheet next.
      </p>

      <MissingPartyLink form={form} />
    </form>
  );
}

function openDraft(form: ResultForm, correcting: boolean): Draft {
  const electionId = form.election_id;
  const pollingUnitId = form.polling_unit.id;
  const current = form.current;
  const parent = correcting && current ? current.version_id : null;
  const kept = loadDraft(electionId, pollingUnitId);
  if (kept && kept.parentVersionId === parent) {
    return { ...kept, configVersion: form.config_version };
  }
  const prefill =
    correcting && current
      ? {
          votes: Object.fromEntries(
            Object.entries(current.votes as Record<string, number>).map(([k, v]) => [k, String(v)]),
          ),
          totals: Object.fromEntries(
            SHEET_FIELD_ORDER.map((f) => [
              f,
              String((current.totals as Record<string, number | null>)[f] ?? ""),
            ]),
          ),
        }
      : {};
  const fresh = newDraft({
    electionId,
    pollingUnitId,
    configVersion: form.config_version,
    parentVersionId: parent,
    ...prefill,
  });
  saveDraft(fresh);
  return fresh;
}

function CountInput({
  id,
  value,
  invalid,
  describedBy,
  onChange,
}: {
  id: string;
  value: string;
  invalid: boolean;
  describedBy?: string;
  onChange: (text: string) => void;
}) {
  return (
    <input
      id={id}
      inputMode="numeric"
      pattern="[0-9]*"
      autoComplete="off"
      enterKeyHint="next"
      maxLength={7}
      value={value}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => onChange(e.target.value.replace(/[^\d]/g, ""))}
      className={cn(
        "h-12 w-28 shrink-0 rounded-md border-[1.5px] bg-input-fill px-3 text-right text-h3 font-bold tabular-nums text-foreground focus-visible:border-primary focus-visible:shadow-focus focus-visible:outline-none",
        invalid ? "border-destructive" : "border-input",
      )}
    />
  );
}

function LiveChecks({ checks }: { checks: ReturnType<typeof checkTotals> }) {
  if (checks.length === 0) return null;
  const lines = checks
    .filter((c) => !c.ok)
    .map((c) => {
      if (c.id === "votes_plus_rejected_vs_cast") {
        return { blocking: true, text: mismatchTotalCast(c.left, 0, c.right) };
      }
      if (c.id === "cast_vs_accredited") {
        return { blocking: true, text: mismatchAccredited(c.left, c.right) };
      }
      return { blocking: false, text: shortfallTotalCast(c.left, 0, c.right) };
    });
  if (lines.length === 0) {
    return (
      <p className="flex items-center gap-2 text-body-sm font-medium text-signal-teal-text">
        <CheckCircle2 className="h-4 w-4" aria-hidden /> The numbers add up.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      {lines.map((l) => (
        <InlineAlert
          key={l.text}
          tone={l.blocking ? "danger" : "warning"}
          title={l.blocking ? "Check the sheet" : "Worth a second look"}
        >
          {l.text}
        </InlineAlert>
      ))}
    </div>
  );
}

async function position(): Promise<{ lat: number; lng: number; accuracyM: number } | null> {
  if (typeof navigator === "undefined" || !navigator.geolocation) return null;
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (p) =>
        resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracyM: p.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    );
  });
}

function errorTexts(errors: unknown): string[] {
  if (!errors || typeof errors !== "object") return [];
  return Object.values(errors as Record<string, unknown>)
    .flat()
    .filter((v): v is string => typeof v === "string");
}

// ---- "party or candidate missing?" ----------------------------------------------------------

function MissingPartyLink({ form }: { form: ResultForm }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"PARTY_MISSING" | "CONTESTANT_MISSING">("PARTY_MISSING");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string[]>([]);
  const report = useMutation({
    mutationFn: () =>
      ep.agent.reportIssue(form.election_id, {
        polling_unit_id: form.polling_unit.id,
        kind,
        note: note.trim(),
      }),
    onSuccess: () => {
      toast("Sent to an admin");
      setOpen(false);
      setNote("");
      setError([]);
    },
    onError: (e) => setError(errorLines(e, "Could not send the report.")),
  });
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mx-auto flex items-center gap-1.5 text-label font-semibold text-primary-soft-foreground"
      >
        <Flag className="h-4 w-4" aria-hidden /> Party or candidate missing?
      </button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Party or candidate missing?"
        description={copy.missingParty}
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={report.isPending}
              disabled={note.trim().length < 3}
              onClick={() => report.mutate()}
            >
              Send to an admin
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {error.length > 0 ? (
            <InlineAlert tone="danger" title="Not sent">
              {error.join(" ")}
            </InlineAlert>
          ) : null}
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-label text-strong-foreground">What is wrong?</legend>
            {(
              [
                ["PARTY_MISSING", "A party on the sheet is not on this form"],
                ["CONTESTANT_MISSING", "A party's candidate is missing or wrong"],
              ] as const
            ).map(([value, label]) => (
              <label
                key={value}
                className={cn(
                  "flex min-h-11 cursor-pointer items-center gap-3 rounded-md border px-3",
                  kind === value ? "border-primary bg-primary-soft" : "border-border",
                )}
              >
                <input
                  type="radio"
                  name="kind"
                  className="h-4 w-4 accent-[rgb(var(--primary))]"
                  checked={kind === value}
                  onChange={() => setKind(value)}
                />
                <span className="text-body-sm">{label}</span>
              </label>
            ))}
          </fieldset>
          <Field label="Which one? What does the sheet say?">
            {(p) => (
              <Textarea
                {...p}
                value={note}
                maxLength={500}
                onChange={(e) => setNote(e.target.value)}
              />
            )}
          </Field>
        </div>
      </Dialog>
    </>
  );
}

function NoForm({ form }: { form: ResultForm }) {
  return (
    <div className="flex flex-col gap-4">
      <InlineAlert tone="warning" title="This unit has no result form yet">
        The parties or contestants for {form.constituency?.name ?? "this unit's constituency"} have
        not been set up. Tell an admin, and check again later.
      </InlineAlert>
      <MissingPartyLink form={form} />
    </div>
  );
}

function AlreadySent({ form, onAttach }: { form: ResultForm; onAttach: (v: string) => void }) {
  const router = useRouter();
  const current = form.current!;
  const complete = current.completion === "COMPLETE";
  return (
    <Card className="flex flex-col gap-4 p-5">
      <h2 className="text-h3">A result has already been sent for this unit</h2>
      <div className="flex flex-wrap gap-2">
        <StatusChip status={reviewState(current.state)} />
      </div>
      {!complete ? (
        <>
          <p className="text-body">It is not complete until the result sheet is attached.</p>
          <Button onClick={() => onAttach(current.version_id)}>Attach the result sheet</Button>
        </>
      ) : (
        <p className="text-body">Its result sheet is in. Nothing else is needed.</p>
      )}
      <Button
        variant="outline"
        onClick={() =>
          router.push(
            `/capture/unit?election=${form.election_id}&pu=${form.polling_unit.id}&correct=1`,
          )
        }
      >
        Correct the numbers
      </Button>
    </Card>
  );
}

// ---- step 2: the result sheet ---------------------------------------------------------------

type UploadState =
  | { kind: "idle" }
  | { kind: "preparing" }
  | { kind: "ready"; sheet: PreparedSheet; preview: string | null; name: string }
  | { kind: "uploading"; sheet: PreparedSheet; preview: string | null; name: string; note: string }
  | { kind: "failed"; sheet: PreparedSheet | null; preview: string | null; name: string; error: string[] };

function SheetStep({ versionId, onDone }: { versionId: string; onDone: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const camera = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>({ kind: "idle" });
  // The preview is a local object URL: release it when replaced, and when leaving the step.
  const previewUrl = useRef<string | null>(null);
  const setPreview = (url: string | null) => {
    if (previewUrl.current && previewUrl.current !== url) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = url;
  };
  useEffect(() => () => setPreview(null), []);

  const choose = async (file: File | undefined) => {
    if (!file) return;
    setState({ kind: "preparing" });
    try {
      const sheet = await prepareSheet(file);
      const preview = sheet.mime.startsWith("image/") ? URL.createObjectURL(sheet.blob) : null;
      setPreview(preview);
      const next = { kind: "ready" as const, sheet, preview, name: file.name };
      setState(next);
      void upload(next);
    } catch (e) {
      setState({ kind: "failed", sheet: null, preview: null, name: file.name, error: errorLines(e, "That file cannot be used.") });
    }
  };

  const upload = async (from: { sheet: PreparedSheet; preview: string | null; name: string }) => {
    const base = { sheet: from.sheet, preview: from.preview, name: from.name };
    setState({ kind: "uploading", ...base, note: "Uploading…" });
    try {
      await uploadSheet(versionId, from.sheet, {
        onStage: (stage) =>
          setState({
            kind: "uploading",
            ...base,
            note:
              stage === "requesting"
                ? "Preparing the upload…"
                : stage === "uploading"
                  ? "Uploading…"
                  : "Confirming…",
          }),
        onRetry: (attempt, waitMs) =>
          setState({
            kind: "uploading",
            ...base,
            note: `Attempt ${attempt} failed. Trying again in ${Math.round(waitMs / 1000)} s…`,
          }),
      });
      toast(copy.complete.toast);
      void queryClient.invalidateQueries({ queryKey: ["me", "assignments"] });
      void queryClient.invalidateQueries({ queryKey: ["form"] });
      onDone();
    } catch (e) {
      setState({
        kind: "failed",
        ...base,
        error: errorLines(e, "The sheet could not be uploaded."),
      });
    }
  };

  const busy = state.kind === "preparing" || state.kind === "uploading";

  return (
    <div className="flex flex-col gap-5">
      <InlineAlert tone="success" title={copy.received.headline}>
        {copy.received.body}
      </InlineAlert>

      <Card className="flex flex-col gap-4 p-5">
        <h2 className="text-h3">Attach the result sheet</h2>
        <p className="text-body-sm text-subtle-foreground">
          A clear photo of the whole sheet (EC8A), flat and in good light, or a PDF.
        </p>

        {"preview" in state && state.preview ? (
          // eslint-disable-next-line @next/next/no-img-element -- local object URL
          <img
            src={state.preview}
            alt="The result sheet you chose"
            className="max-h-80 w-full rounded-md border border-border object-contain"
          />
        ) : "name" in state && state.name ? (
          <p className="rounded-md bg-muted p-3 text-body-sm">{state.name}</p>
        ) : null}
        {"sheet" in state && state.sheet ? (
          <p className="text-caption text-subtle-foreground">
            {formatBytes(state.sheet.blob.size)}
            {state.sheet.blob.size < state.sheet.originalBytes
              ? `, compressed from ${formatBytes(state.sheet.originalBytes)}`
              : ""}
          </p>
        ) : null}

        {state.kind === "uploading" ? (
          <p role="status" className="flex items-center gap-2 text-body-sm font-medium">
            <RefreshCw className="h-4 w-4 animate-spin" aria-hidden /> {state.note}
          </p>
        ) : null}
        {state.kind === "preparing" ? (
          <p role="status" className="text-body-sm font-medium">
            Preparing the photo…
          </p>
        ) : null}
        {state.kind === "failed" ? (
          <InlineAlert tone="danger" title="Not uploaded yet">
            {state.error.join(" ")}
          </InlineAlert>
        ) : null}

        <input
          ref={camera}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            void choose(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <input
          ref={picker}
          type="file"
          accept="image/*,application/pdf"
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            void choose(e.target.files?.[0]);
            e.target.value = "";
          }}
        />

        {state.kind === "failed" && state.sheet ? (
          <Button className="h-12 w-full" onClick={() => void upload({ sheet: state.sheet!, preview: state.preview, name: state.name })}>
            Try the upload again
          </Button>
        ) : null}
        <Button
          className="h-12 w-full"
          variant={state.kind === "failed" && state.sheet ? "outline" : "primary"}
          leading={<Camera className="h-5 w-5" aria-hidden />}
          disabled={busy}
          onClick={() => camera.current?.click()}
        >
          {state.kind === "idle" ? "Take a photo of the sheet" : "Take another photo"}
        </Button>
        <button
          type="button"
          disabled={busy}
          onClick={() => picker.current?.click()}
          className={cn(
            buttonStyles({ variant: "outline" }),
            "inline-flex h-12 w-full items-center justify-center gap-2 rounded-md font-semibold",
          )}
        >
          <FileUp className="h-5 w-5" aria-hidden /> Choose a photo or PDF
        </button>
      </Card>
    </div>
  );
}

function Done({ form }: { form: ResultForm }) {
  return (
    <Card className="flex flex-col items-center gap-3 p-6 text-center">
      <CheckCircle2 className="h-12 w-12 text-primary" aria-hidden />
      <h2 className="text-h2">{copy.complete.headline}</h2>
      <p className="text-body text-strong-foreground">
        {completeFor(form.polling_unit.ward, form.polling_unit.name)}
      </p>
      <Link
        href="/capture"
        className={cn(
          buttonStyles({ variant: "primary" }),
          "mt-2 inline-flex w-full items-center justify-center rounded-md font-semibold",
        )}
      >
        Back to my polling units
      </Link>
    </Card>
  );
}

export default function UnitPage() {
  return (
    <Suspense>
      <UnitInner />
    </Suspense>
  );
}
