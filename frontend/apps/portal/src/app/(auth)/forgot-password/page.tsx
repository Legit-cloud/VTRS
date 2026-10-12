"use client";

import { ApiError, loginIdentifier } from "@vtrs/core";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { InlineAlert } from "@/components/ui/feedback";
import { ep } from "@/lib/api";

type Step = "identify" | "code" | "password" | "done";

export default function ForgotPasswordPage() {
  const [step, setStep] = useState<Step>("identify");
  const [identifier, setIdentifier] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [code, setCode] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      if (step === "identify") {
        const normalised = loginIdentifier(identifier);
        if (!normalised)
          throw new ApiError({
            status: 400,
            code: "bad",
            detail: "Enter a valid phone number or email.",
          });
        const challenge = await ep.auth.forgotPassword({ identifier: normalised });
        setChallengeId(challenge.challenge_id);
        setStep("code");
      } else if (step === "code") {
        const verified = await ep.auth.verifyOtp({ challenge_id: challengeId, code: code.trim() });
        if (!verified.reset_token)
          throw new ApiError({ status: 400, code: "bad", detail: "That code was not accepted." });
        setResetToken(verified.reset_token);
        setStep("password");
      } else if (step === "password") {
        await ep.auth.resetPassword({ reset_token: resetToken, new_password: password });
        setStep("done");
      }
    });
  };

  if (step === "done") {
    return (
      <div className="flex flex-col gap-5">
        <h1 className="text-h1">Password changed</h1>
        <p className="text-body text-subtle-foreground">Sign in with your new password.</p>
        <Link href="/login" className="text-body font-semibold text-primary">
          Go to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <div>
        <h1 className="text-h1">Reset your password</h1>
        <p className="mt-1 text-body text-subtle-foreground">
          {step === "identify" &&
            "Enter the phone number or email on your account. We'll send a code."}
          {step === "code" && "Enter the code we sent you."}
          {step === "password" && "Choose a new password."}
        </p>
      </div>
      {error ? (
        <InlineAlert tone="danger" title="That didn't work">
          {error}
        </InlineAlert>
      ) : null}
      {step === "identify" ? (
        <Field label="Phone number or email">
          {(props) => (
            <Input
              {...props}
              autoFocus
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
            />
          )}
        </Field>
      ) : null}
      {step === "code" ? (
        <Field label="Code">
          {(props) => (
            <Input
              {...props}
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="tabular-nums tracking-widest"
            />
          )}
        </Field>
      ) : null}
      {step === "password" ? (
        <Field label="New password" hint="At least 12 characters.">
          {(props) => (
            <Input
              {...props}
              type="password"
              autoComplete="new-password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
      ) : null}
      <Button type="submit" loading={busy}>
        {step === "identify" ? "Send code" : step === "code" ? "Verify code" : "Change password"}
      </Button>
      <Link href="/login" className="text-center text-body-sm font-semibold text-primary">
        Back to sign in
      </Link>
    </form>
  );
}
