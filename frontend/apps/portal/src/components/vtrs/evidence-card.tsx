"use client";

import { Check, Copy, ExternalLink, FileText, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { ApiError, type StatusView } from "@vtrs/core";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/ui/chip";
import { useToast } from "@/components/ui/toast";
import { ep } from "@/lib/api";

export interface EvidenceItem {
  evidence_id: string;
  kind: string;
  status: string;
  sha256: string;
  /** The sheet is a photo (JPEG, PNG, WebP) or a PDF. */
  mime?: string;
}

const STATUS: Record<string, StatusView> = {
  VERIFIED: { label: "Verified hash", tone: "teal", icon: "shield-check" },
  STORED: { label: "Verified hash", tone: "teal", icon: "shield-check" },
  PENDING: { label: "Waiting for upload", tone: "ink", icon: "clock" },
  PENDING_UPLOAD: { label: "Waiting for upload", tone: "ink", icon: "clock" },
  UPLOADED: { label: "Checking", tone: "blue", icon: "refresh-cw" },
  QUARANTINED: { label: "Hash mismatch", tone: "red", icon: "shield-alert" },
  REJECTED: { label: "Hash mismatch", tone: "red", icon: "shield-alert" },
};

const KIND_LABEL: Record<string, string> = {
  EC8A: "EC8A · Polling unit result",
  EC8B: "EC8B · Ward collation",
  EC8C: "EC8C · LGA collation",
};

/** Title, status chip, SHA-256 in mono with a copy button, and a logged view action. */
export function EvidenceCard({
  item,
  place,
  canView,
  capturedAt,
}: {
  item: EvidenceItem;
  place?: string;
  canView: boolean;
  capturedAt?: string;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const status = STATUS[item.status] ?? {
    label: item.status,
    tone: "ink" as const,
    icon: "circle",
  };
  const bad = status.tone === "red";
  const pdf = item.mime === "application/pdf";
  const noun = pdf ? "PDF" : "photo";

  async function open() {
    setBusy(true);
    try {
      const { url } = await ep.evidence.downloadUrl(item.evidence_id);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast(e instanceof ApiError ? e.detail : `Could not open the ${noun}.`);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(item.sha256);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast("Copy is not available here. Select the hash and copy it.");
    }
  }

  return (
    <div className="flex gap-4 rounded-md border border-border bg-card p-4">
      <div
        className="flex h-24 w-[72px] shrink-0 items-center justify-center rounded-sm bg-muted text-muted-foreground"
        aria-hidden
      >
        {bad ? (
          <ShieldAlert className="h-8 w-8" />
        ) : pdf ? (
          <FileText className="h-8 w-8" />
        ) : (
          <ShieldCheck className="h-8 w-8" />
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-h3 font-semibold">
            {KIND_LABEL[item.kind] ?? item.kind}
            {place ? ` · ${place}` : ""}
          </h4>
          <StatusChip status={status} />
        </div>
        {capturedAt ? (
          <p className="text-caption text-subtle-foreground">Captured {capturedAt}</p>
        ) : null}
        <p className="flex min-w-0 items-center gap-1 text-body-sm">
          <span className="text-subtle-foreground">SHA-256</span>
          <code className="mono truncate" title={item.sha256}>
            {item.sha256.slice(0, 6)}…{item.sha256.slice(-4)}
          </code>
          <Button variant="ghost" size="icon-sm" onClick={copy} aria-label="Copy the SHA-256 hash">
            {copied ? (
              <Check className="h-4 w-4" aria-hidden />
            ) : (
              <Copy className="h-4 w-4" aria-hidden />
            )}
          </Button>
        </p>
        {canView ? (
          <div>
            <Button
              size="sm"
              variant="secondary"
              loading={busy}
              onClick={open}
              leading={<ExternalLink className="h-4 w-4" aria-hidden />}
            >
              View {noun}
            </Button>
            <span className="ml-2 text-caption text-subtle-foreground">Viewing is logged.</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
