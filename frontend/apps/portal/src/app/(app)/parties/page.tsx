"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toastVerb, type Party } from "@vtrs/core";
import { ImagePlus, Pencil, Plus, Trash2, Vote } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/chip";
import { ConfirmDialog, SidePanel } from "@/components/ui/dialog";
import { EmptyState, InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { PartyMark } from "@/components/vtrs/contestant-bar";
import { PageHeader } from "@/components/vtrs/page-header";
import { ep } from "@/lib/api";
import { sha256 } from "@/lib/capture/sheet";
import { cn } from "@/lib/cn";
import { errorLines } from "@/lib/errors";

const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];
const LOGO_MAX_BYTES = 256 * 1024;

/**
 * The organisation's party master list (FR-6.3.4). Elections pick their contesting parties from
 * it, and every result references a party by id, so agents never type a party name.
 */
export default function PartiesPage() {
  const parties = useQuery({ queryKey: ["parties"], queryFn: () => ep.parties.list() });
  const [editing, setEditing] = useState<Party | "new" | null>(null);
  const [removing, setRemoving] = useState<Party | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  const remove = useMutation({
    mutationFn: (p: Party) => ep.parties.remove(p.id),
    onSuccess: () => {
      toast("Party removed");
      setRemoving(null);
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
    },
    onError: (e) => {
      setRemoving(null);
      toast(errorLines(e, "Could not remove the party.").join(" "));
    },
  });

  const list = [...(parties.data ?? [])].sort((a, b) =>
    a.is_own === b.is_own ? a.abbreviation.localeCompare(b.abbreviation) : a.is_own ? -1 : 1,
  );

  return (
    <>
      <PageHeader
        title="Parties"
        description="Your list of parties, with their abbreviation as printed on the result sheet. Each election picks its contesting parties from here."
        actions={
          <Button leading={<Plus className="h-4 w-4" aria-hidden />} onClick={() => setEditing("new")}>
            Add a party
          </Button>
        }
      />
      {parties.isLoading ? (
        <Skeleton className="h-48" />
      ) : parties.isError ? (
        <QueryError error={parties.error} onRetry={() => void parties.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState
          icon={<Vote className="h-8 w-8" aria-hidden />}
          title="No parties yet"
          description="Add your own party first, then the others you expect on the result sheet, such as APC, PDP, LP, ADC and NNPP."
          action={<Button onClick={() => setEditing("new")}>Add a party</Button>}
        />
      ) : (
        <Card className="p-0">
          <ul className="divide-y divide-border">
            {list.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <PartyMark abbreviation={p.abbreviation} logoUrl={p.logo_url} size={36} />
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-bold">{p.abbreviation}</span>
                  <span className="block text-body-sm text-subtle-foreground">{p.full_name}</span>
                </span>
                {p.is_own ? (
                  <StatusChip status={{ label: "Your party", tone: "teal", icon: "star" }} />
                ) : null}
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Edit ${p.abbreviation}`}
                  onClick={() => setEditing(p)}
                >
                  <Pencil className="h-4 w-4" aria-hidden />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Remove ${p.abbreviation}`}
                  onClick={() => setRemoving(p)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <PartyPanel
        party={editing}
        ownTaken={list.some((p) => p.is_own && (editing === "new" || p.id !== editing?.id))}
        onClose={() => setEditing(null)}
      />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.abbreviation ?? "this party"}?`}
        description="A party that contests an election, or has contestants, cannot be removed; take it out of those elections first."
        confirmLabel="Remove party"
        danger
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </>
  );
}

function PartyPanel({
  party,
  ownTaken,
  onClose,
}: {
  party: Party | "new" | null;
  ownTaken: boolean;
  onClose: () => void;
}) {
  const isNew = party === "new";
  const existing = party && party !== "new" ? party : null;
  return (
    <SidePanel
      open={!!party}
      onOpenChange={(next) => !next && onClose()}
      title={isNew ? "Add a party" : `Edit ${existing?.abbreviation ?? ""}`}
      description="Agents see the abbreviation and logo on their result form."
    >
      {party ? (
        <PartyForm key={existing?.id ?? "new"} party={existing} ownTaken={ownTaken} onDone={onClose} />
      ) : null}
    </SidePanel>
  );
}

function PartyForm({
  party,
  ownTaken,
  onDone,
}: {
  party: Party | null;
  ownTaken: boolean;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [fullName, setFullName] = useState(party?.full_name ?? "");
  const [abbreviation, setAbbreviation] = useState(party?.abbreviation ?? "");
  const [own, setOwn] = useState(!!party?.is_own);
  const [logo, setLogo] = useState<File | null>(null);
  const [error, setError] = useState<string[]>([]);

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        full_name: fullName.trim(),
        abbreviation: abbreviation.trim().toUpperCase(),
        is_own: own,
      };
      let saved: Party;
      if (party) {
        const current = await ep.parties.get(party.id);
        saved = await ep.parties.update(party.id, body, current.etag ?? "");
      } else {
        saved = await ep.parties.create(body);
      }
      if (logo) await uploadLogo(saved.id, logo);
      return saved;
    },
    onSuccess: () => {
      toast(toastVerb.partySaved);
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
      void queryClient.invalidateQueries({ queryKey: ["election-parties"] });
      onDone();
    },
    onError: (e) => setError(errorLines(e, "Could not save the party.")),
  });

  const removeLogo = useMutation({
    mutationFn: () => ep.parties.removeLogo(party!.id),
    onSuccess: () => {
      toast("Logo removed");
      void queryClient.invalidateQueries({ queryKey: ["parties"] });
      onDone();
    },
    onError: (e) => setError(errorLines(e, "Could not remove the logo.")),
  });

  const logoProblem =
    logo && !LOGO_TYPES.includes(logo.type)
      ? "Use a PNG, JPEG or WebP image."
      : logo && logo.size > LOGO_MAX_BYTES
        ? "The logo must be 256 KB or smaller."
        : null;
  const preview = logo && !logoProblem ? URL.createObjectURL(logo) : null;

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {error.length > 0 ? (
        <InlineAlert tone="danger" title="Not saved">
          {error.join(" ")}
        </InlineAlert>
      ) : null}
      <Field label="Abbreviation" hint="As printed on the result sheet, for example APC.">
        {(p) => (
          <Input
            {...p}
            value={abbreviation}
            maxLength={20}
            onChange={(e) => setAbbreviation(e.target.value.toUpperCase())}
          />
        )}
      </Field>
      <Field label="Full name">
        {(p) => <Input {...p} value={fullName} onChange={(e) => setFullName(e.target.value)} />}
      </Field>
      <label
        className={cn(
          "flex items-start gap-3 rounded-md border p-3",
          ownTaken && !own ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:bg-muted",
        )}
      >
        <input
          type="checkbox"
          className="mt-0.5 h-5 w-5 accent-[rgb(var(--primary))]"
          checked={own}
          disabled={ownTaken && !own}
          onChange={(e) => setOwn(e.target.checked)}
        />
        <span>
          <span className="block text-body-sm font-semibold">This is our party</span>
          <span className="block text-caption text-subtle-foreground">
            {ownTaken && !own
              ? "Another party is already marked as yours."
              : "The War Room shows your margin and gives your party the first colour."}
          </span>
        </span>
      </label>

      <div className="flex flex-col gap-2">
        <span className="text-label text-strong-foreground">Logo (optional)</span>
        <div className="flex items-center gap-3">
          {preview ? (
            // eslint-disable-next-line @next/next/no-img-element -- local preview
            <img src={preview} alt="" className="h-12 w-12 rounded-sm object-contain" />
          ) : (
            <PartyMark
              abbreviation={abbreviation || "?"}
              logoUrl={party?.logo_url}
              size={48}
            />
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            leading={<ImagePlus className="h-4 w-4" aria-hidden />}
            onClick={() => file.current?.click()}
          >
            {party?.logo_url || logo ? "Choose another" : "Choose a logo"}
          </Button>
          {party?.logo_url && !logo ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              loading={removeLogo.isPending}
              onClick={() => removeLogo.mutate()}
            >
              Remove
            </Button>
          ) : null}
        </div>
        <input
          ref={file}
          type="file"
          accept={LOGO_TYPES.join(",")}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => setLogo(e.target.files?.[0] ?? null)}
        />
        {logoProblem ? (
          <p className="text-caption text-signal-red-text">{logoProblem}</p>
        ) : (
          <p className="text-caption text-subtle-foreground">PNG, JPEG or WebP, up to 256 KB.</p>
        )}
      </div>

      <div className="flex gap-3">
        <Button
          type="submit"
          loading={save.isPending}
          disabled={!fullName.trim() || !abbreviation.trim() || !!logoProblem}
        >
          {party ? "Save changes" : "Add party"}
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Presigned upload for a logo; it becomes the party's logo only once the server checks it. */
async function uploadLogo(partyId: string, logo: File): Promise<void> {
  const hash = await sha256(logo);
  const entry = await ep.parties.requestLogo(partyId, {
    mime: logo.type,
    size: logo.size,
    sha256: hash,
  });
  const headers = { ...(entry.upload.headers as Record<string, string>) };
  delete headers["Content-Length"];
  const put = await fetch(entry.upload.url, {
    method: entry.upload.method || "PUT",
    headers,
    body: logo,
  });
  if (!put.ok) throw new Error(`The logo upload was refused (${put.status}).`);
  await ep.parties.completeLogo(partyId, { mime: logo.type, sha256: hash });
}
