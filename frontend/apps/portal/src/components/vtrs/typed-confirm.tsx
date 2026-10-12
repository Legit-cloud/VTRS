"use client";

import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/field";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  /** The words the operator must type before the button works. */
  phrase: string;
  confirmLabel: string;
  danger?: boolean;
  loading?: boolean;
  /** Ask for a reason that is kept with the decision. */
  reasonLabel?: string;
  error?: string | null;
  onConfirm: (reason: string) => void;
  children?: ReactNode;
}

/**
 * High-impact platform actions (suspending a party, importing master data) name the thing and
 * ask for it to be typed, so a stray click cannot do them.
 */
export function TypedConfirm({
  open,
  onOpenChange,
  title,
  description,
  phrase,
  confirmLabel,
  danger,
  loading,
  reasonLabel,
  error,
  onConfirm,
  children,
}: Props) {
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const matches = typed.trim().toLowerCase() === phrase.trim().toLowerCase();
  const needsReason = !!reasonLabel && reason.trim().length < 3;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setTyped("");
          setReason("");
        }
        onOpenChange(next);
      }}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant={danger ? "danger" : "primary"}
            loading={loading}
            disabled={!matches || needsReason}
            onClick={() => onConfirm(reason.trim())}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {children}
        {reasonLabel ? (
          <Field
            label={reasonLabel}
            hint="This is kept in the audit log and shown to the organisation."
          >
            {(p) => (
              <Textarea
                {...p}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
              />
            )}
          </Field>
        ) : null}
        <Field label={`Type "${phrase}" to confirm`} error={error}>
          {(p) => (
            <Input
              {...p}
              autoComplete="off"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}
