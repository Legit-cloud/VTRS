"use client";

import { ApiError } from "@vtrs/core";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { InlineAlert } from "@/components/ui/feedback";
import { ep } from "@/lib/api";
import { setAccessToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const MIN_PASSWORD = 12;

function AcceptForm() {
  const router = useRouter();
  const token = useSearchParams().get("token");
  const { reloadMe } = useAuth();
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [hint, setHint] = useState<string>("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  // The link carries the invitation token; accepting it sends a code to the invited contact.
  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    ep.auth
      .acceptInvitation(token)
      .then((challenge) => {
        setChallengeId(challenge.challenge_id);
        setHint(challenge.destination_hint ?? "");
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e : null));
  }, [token]);

  if (!token) {
    return (
      <InlineAlert tone="danger" title="This invitation link is incomplete">
        Open the link from your invitation message again, or ask your admin to send a new one.
      </InlineAlert>
    );
  }

  const mismatch = confirm.length > 0 && confirm !== password;
  const tooShort = password.length > 0 && password.length < MIN_PASSWORD;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!challengeId || mismatch || tooShort) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/session/accept", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, challenge_id: challengeId, code: code.trim(), password }),
      });
      const body = (await response.json()) as Record<string, unknown>;
      if (!response.ok) {
        throw new ApiError({
          status: response.status,
          code: String(body.code ?? "error"),
          detail: String(body.detail ?? "Could not finish setting up your account."),
          errors: body.errors,
        });
      }
      setAccessToken(String(body.access_token), String(body.access_expires_at));
      await reloadMe();
      router.replace("/settings?enrol=1");
    } catch (e) {
      setError(e instanceof ApiError ? e : null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <div>
        <h1 className="text-h1">Set up your account</h1>
        <p className="mt-1 text-body text-subtle-foreground">
          {challengeId
            ? `We sent a code to ${hint || "your phone or email"}. Enter it, then choose a password.`
            : "Checking your invitation…"}
        </p>
      </div>
      {error ? (
        <InlineAlert tone="danger" title="That didn't work">
          {error.detail}
        </InlineAlert>
      ) : null}
      <Field label="Code we sent you">
        {(props) => (
          <Input
            {...props}
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={!challengeId}
            className="tabular-nums tracking-widest"
          />
        )}
      </Field>
      <Field
        label="Choose a password"
        hint={`At least ${MIN_PASSWORD} characters.`}
        error={tooShort ? `Use at least ${MIN_PASSWORD} characters.` : null}
      >
        {(props) => (
          <Input
            {...props}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      <Field label="Type it again" error={mismatch ? "The two passwords are different." : null}>
        {(props) => (
          <Input
            {...props}
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        )}
      </Field>
      <Button
        type="submit"
        loading={busy}
        disabled={
          !challengeId || code.trim().length < 4 || password.length < MIN_PASSWORD || mismatch
        }
      >
        Create account
      </Button>
    </form>
  );
}

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptForm />
    </Suspense>
  );
}
