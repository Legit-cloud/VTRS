"use client";

import { ApiError } from "@vtrs/core";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/field";
import { ep } from "./api";
import { useAuth } from "./auth";
import { useCooldown } from "./cooldown";

type Runner = <T>(action: () => Promise<T>) => Promise<T>;

const StepUpContext = createContext<Runner | null>(null);

/**
 * Role and scope changes, locking an election, reconciliation, exports and alert policy need a
 * fresh second factor. Wrap the call: if the server says so, email a code, ask for it once,
 * then retry.
 */
export function StepUpProvider({ children }: { children: ReactNode }) {
  const { adoptToken } = useAuth();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<{ id: string; sentTo: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const resend = useCooldown(60);

  const sendCode = useCallback(async () => {
    setError(null);
    try {
      const sent = await ep.auth.stepUpRequest();
      setChallenge({ id: sent.challenge_id, sentTo: sent.destination_hint });
      resend.start();
    } catch (error_) {
      setError(error_ instanceof ApiError ? error_.detail : "Could not send a code. Try again.");
    }
  }, [resend]);
  const waiter = useRef<{ resolve: () => void; reject: (e: unknown) => void } | null>(null);

  const ask = useCallback(
    () =>
      new Promise<void>((resolve, reject) => {
        waiter.current = { resolve, reject };
        setCode("");
        setChallenge(null);
        setOpen(true);
        void sendCode();
      }),
    [sendCode],
  );

  const run = useCallback<Runner>(
    async (action) => {
      try {
        return await action();
      } catch (error_) {
        if (!(error_ instanceof ApiError) || !error_.needsStepUp) throw error_;
        await ask();
        return action();
      }
    },
    [ask],
  );

  const submit = async () => {
    if (!challenge) return;
    setBusy(true);
    setError(null);
    try {
      const result = await ep.auth.stepUp({ challenge_id: challenge.id, code: code.trim() });
      adoptToken(result.access_token, result.access_expires_at);
      setOpen(false);
      waiter.current?.resolve();
    } catch (error_) {
      setError(error_ instanceof ApiError ? error_.detail : "That code did not work. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    setOpen(false);
    waiter.current?.reject(new ApiError({ status: 0, code: "cancelled", detail: "Cancelled." }));
    waiter.current = null;
  };

  const value = useMemo(() => run, [run]);
  return (
    <StepUpContext.Provider value={value}>
      {children}
      <Dialog
        open={open}
        onOpenChange={(next) => (next ? setOpen(true) : cancel())}
        title="Confirm it's you"
        description={
          challenge
            ? `This change needs a fresh code. We sent 6 digits to ${challenge.sentTo}.`
            : "This change needs a fresh code. Sending one to your email…"
        }
        footer={
          <>
            <Button variant="outline" onClick={cancel} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={submit} loading={busy} disabled={!challenge || code.trim().length < 6}>
              Confirm
            </Button>
          </>
        }
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (code.trim().length >= 6) void submit();
          }}
          className="flex flex-col gap-2"
        >
          <Field label="Code from the email" error={error}>
            {(props) => (
              <Input
                {...props}
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="tabular-nums tracking-widest"
              />
            )}
          </Field>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="self-start"
            disabled={resend.remaining > 0}
            onClick={() => void sendCode()}
          >
            {resend.remaining > 0 ? `Send a new code in ${resend.remaining} s` : "Send a new code"}
          </Button>
        </form>
      </Dialog>
    </StepUpContext.Provider>
  );
}

export function useStepUp(): Runner {
  const value = useContext(StepUpContext);
  if (!value) throw new Error("useStepUp must be used inside StepUpProvider");
  return value;
}
