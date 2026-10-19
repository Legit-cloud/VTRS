"use client";

import { ApiError, loginIdentifier } from "@vtrs/core";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { InlineAlert } from "@/components/ui/feedback";
import { useAuth } from "@/lib/auth";

function LoginForm() {
  const { login, verifyMfa, status, me } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const submitting = useRef(false);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  const next = params.get("next");
  const destination = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";

  // Someone who is already signed in has no use for this page. A sign-in in flight decides
  // its own destination below, so it is left alone.
  useEffect(() => {
    if (status !== "authenticated" || submitting.current || !me) return;
    router.replace(me.mfa_required && !me.mfa_enabled ? "/settings?enrol=1" : destination);
  }, [status, me, destination, router]);

  const describe = (e: unknown): ApiError =>
    e instanceof ApiError
      ? e
      : new ApiError({ status: 0, code: "error", detail: "Something went wrong. Try again." });

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setFieldError(null);
    submitting.current = true;
    setBusy(true);
    try {
      if (mfaToken) {
        await verifyMfa(mfaToken, code.trim());
        router.replace(destination);
        return;
      }
      const normalised = loginIdentifier(identifier);
      if (!normalised) {
        setFieldError("Enter the phone number or email you were invited with.");
        return;
      }
      const outcome = await login(normalised, password);
      if (outcome.kind === "mfa") {
        setMfaToken(outcome.mfaToken);
      } else {
        router.replace(outcome.enrolmentRequired ? "/settings?enrol=1" : destination);
      }
    } catch (e) {
      setError(describe(e));
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const locked = error?.status === 429 || error?.code === "account_locked";

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5" noValidate>
      <div>
        <h1 className="text-h1">{mfaToken ? "Enter your code" : "Sign in"}</h1>
        <p className="mt-1 text-body text-subtle-foreground">
          {mfaToken
            ? "Open your authenticator app and enter the 6-digit code. A recovery code works too."
            : "Use the phone number or email address you were invited with."}
        </p>
      </div>

      {params.get("expired") ? (
        <InlineAlert tone="info" title="You were signed out">
          Your session ended. Sign in again to carry on.
        </InlineAlert>
      ) : null}

      {error ? (
        <InlineAlert
          tone={locked ? "warning" : "danger"}
          title={locked ? "Too many attempts" : "Couldn't sign in"}
        >
          {error.isNetwork
            ? "Could not reach the server. Check your connection and try again."
            : error.detail}
          {error.retryAfterSeconds
            ? ` Try again in ${Math.ceil(error.retryAfterSeconds / 60)} min.`
            : ""}
        </InlineAlert>
      ) : null}

      {mfaToken ? (
        <Field label="Authenticator code">
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
      ) : (
        <>
          <Field label="Phone number or email" error={fieldError}>
            {(props) => (
              <Input
                {...props}
                autoComplete="username"
                autoFocus
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
              />
            )}
          </Field>
          <Field label="Password">
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            )}
          </Field>
        </>
      )}

      <Button
        type="submit"
        loading={busy}
        disabled={mfaToken ? code.trim().length < 6 : !identifier || !password}
        trailing={<ArrowRight className="h-5 w-5" aria-hidden />}
        className="w-full"
      >
        {mfaToken ? "Verify" : "Continue"}
      </Button>

      {mfaToken ? (
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            setMfaToken(null);
            setCode("");
            setError(null);
          }}
        >
          Use a different account
        </Button>
      ) : (
        <Link
          href="/forgot-password"
          className="text-center text-body-sm font-semibold text-primary"
        >
          Forgot your password?
        </Link>
      )}
    </form>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
