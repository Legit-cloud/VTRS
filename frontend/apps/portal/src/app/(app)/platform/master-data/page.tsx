"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  formatNumber,
  formatPercent,
  type ImportReport,
  type MasterDataState,
  type PlatformUnit,
} from "@vtrs/core";
import { Database, FileUp, Search } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Skeleton } from "@/components/ui/card";
import { InlineAlert, QueryError } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { DataTable } from "@/components/vtrs/data-table";
import { PageHeader } from "@/components/vtrs/page-header";
import { TypedConfirm } from "@/components/vtrs/typed-confirm";
import { ep } from "@/lib/api";
import { useStepUp } from "@/lib/step-up";

const KIND_LABEL: Record<string, string> = {
  states: "States",
  lgas: "LGAs",
  wards: "Wards",
  polling_units: "Polling units",
};

export default function MasterData() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const stepUp = useStepUp();
  const picker = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportReport | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");

  const summary = useQuery({
    queryKey: ["platform", "master-data"],
    queryFn: () => ep.platform.masterData(),
  });
  const found = useQuery({
    queryKey: ["platform", "units", search],
    enabled: search.length >= 2,
    queryFn: () => ep.platform.searchUnits(search),
  });

  const previewing = useMutation({
    mutationFn: (f: File) => ep.platform.previewImport(f, f.name),
    onSuccess: setPreview,
    onError: (e) => {
      setPreview(null);
      setError(e instanceof ApiError ? e.detail : "Could not read that file.");
    },
  });

  const importing = useMutation({
    mutationFn: () => stepUp(() => ep.platform.importMasterData(file!, file!.name)),
    onSuccess: (report) => {
      setConfirm(false);
      setError(null);
      setPreview(null);
      setFile(null);
      toast(
        `Imported ${formatNumber(report.changes.polling_units?.created ?? 0)} new polling units`,
      );
      void queryClient.invalidateQueries({ queryKey: ["platform", "master-data"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.detail : "The import did not go through."),
  });

  const choose = (f: File | null) => {
    setFile(f);
    setPreview(null);
    setError(null);
    if (f) previewing.mutate(f);
  };

  const blocked = !!preview && !preview.ok;
  const changeCount = preview
    ? Object.values(preview.changes).reduce((n, c) => n + c.created + c.updated, 0)
    : 0;

  return (
    <>
      <PageHeader
        title="Master data"
        description="Is the polling unit directory correct? Check it, then import a new file with a preview of exactly what would change."
      />

      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader
            title="By state"
            description="How complete the directory is. Units without coordinates cannot be checked against the geofence."
          />
          <div className="p-5 pt-2">
            {summary.isLoading ? (
              <Skeleton className="h-32" />
            ) : summary.isError ? (
              <QueryError error={summary.error} onRetry={() => void summary.refetch()} />
            ) : (
              <DataTable<MasterDataState>
                caption="Master data by state"
                dense
                rows={summary.data!.states}
                rowKey={(s) => s.state_id}
                columns={[
                  {
                    key: "name",
                    header: "State",
                    cell: (s) => <span className="font-semibold">{s.name}</span>,
                  },
                  {
                    key: "code",
                    header: "Code",
                    cell: (s) => <span className="mono">{s.code}</span>,
                  },
                  { key: "lgas", header: "LGAs", numeric: true, cell: (s) => formatNumber(s.lgas) },
                  {
                    key: "wards",
                    header: "Wards",
                    numeric: true,
                    cell: (s) => formatNumber(s.wards),
                  },
                  {
                    key: "pus",
                    header: "Polling units",
                    numeric: true,
                    cell: (s) => formatNumber(s.polling_units),
                  },
                  {
                    key: "loc",
                    header: "With coordinates",
                    numeric: true,
                    cell: (s) => formatPercent(s.located_pct),
                  },
                  {
                    key: "vot",
                    header: "With voter counts",
                    numeric: true,
                    cell: (s) => formatPercent(s.voters_pct),
                  },
                ]}
                empty={
                  <p className="py-6 text-body text-subtle-foreground">
                    No master data has been imported.
                  </p>
                }
              />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Import a directory"
            description="CSV with one row per polling unit: state_code, state_name, lga_code, lga_name, ward_code, ward_name, pu_code, pu_name, and optionally latitude, longitude, registered_voters."
          />
          <div className="flex flex-col gap-4 p-5 pt-2">
            <input
              ref={picker}
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              aria-label="Choose a CSV file"
              onChange={(e) => choose(e.target.files?.[0] ?? null)}
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                leading={<FileUp className="h-4 w-4" aria-hidden />}
                loading={previewing.isPending}
                onClick={() => picker.current?.click()}
              >
                Choose a file
              </Button>
              {file ? (
                <span className="text-body-sm text-subtle-foreground">{file.name}</span>
              ) : null}
            </div>

            {error && !confirm ? (
              <InlineAlert tone="danger" title="Not imported">
                {error}
              </InlineAlert>
            ) : null}

            {preview ? (
              <div className="flex flex-col gap-4">
                {blocked ? (
                  <InlineAlert
                    tone="danger"
                    title={`${formatNumber(preview.errors?.length ?? 0)} problems stop this import`}
                  >
                    <ul className="mt-1 list-disc pl-5">
                      {(preview.errors ?? []).slice(0, 8).map((m, i) => (
                        <li key={i}>
                          {typeof m === "string" ? m : (m.message ?? JSON.stringify(m))}
                        </li>
                      ))}
                    </ul>
                  </InlineAlert>
                ) : (
                  <>
                    <div>
                      <h3 className="mb-2 text-h3">What would change</h3>
                      <DataTable<[string, { created: number; updated: number }]>
                        caption="Changes the import would make"
                        dense
                        rows={Object.entries(preview.changes)}
                        rowKey={(r) => r[0]}
                        columns={[
                          { key: "kind", header: "Records", cell: (r) => KIND_LABEL[r[0]] ?? r[0] },
                          {
                            key: "created",
                            header: "Added",
                            numeric: true,
                            cell: (r) => formatNumber(r[1].created),
                          },
                          {
                            key: "updated",
                            header: "Changed",
                            numeric: true,
                            cell: (r) => formatNumber(r[1].updated),
                          },
                        ]}
                        empty={null}
                      />
                    </div>
                    {(preview.warnings ?? []).map((w) => (
                      <InlineAlert key={w} tone="warning" title="Worth a look">
                        {w}
                      </InlineAlert>
                    ))}
                    {changeCount === 0 ? (
                      <InlineAlert tone="info" title="Nothing to change">
                        This file matches what is already loaded.
                      </InlineAlert>
                    ) : (
                      <div>
                        <Button onClick={() => setConfirm(true)}>Import this file</Button>
                      </div>
                    )}
                  </>
                )}
              </div>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title="Find a polling unit" />
          <div className="flex flex-col gap-4 p-5 pt-2">
            <form
              className="flex flex-wrap items-end gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                setSearch(query.trim());
              }}
            >
              <Field label="Name or code" className="w-72">
                {(p) => <Input {...p} value={query} onChange={(e) => setQuery(e.target.value)} />}
              </Field>
              <Button
                type="submit"
                variant="secondary"
                leading={<Search className="h-4 w-4" aria-hidden />}
              >
                Search
              </Button>
            </form>
            {search.length >= 2 ? (
              <DataTable<PlatformUnit>
                caption="Matching polling units"
                dense
                rows={found.data?.results ?? []}
                rowKey={(u) => u.id}
                columns={[
                  {
                    key: "code",
                    header: "Code",
                    cell: (u) => <span className="mono">{u.code}</span>,
                  },
                  {
                    key: "name",
                    header: "Polling unit",
                    cell: (u) => <span className="font-semibold">{u.name}</span>,
                  },
                  { key: "area", header: "Ward · LGA", cell: (u) => `${u.ward} · ${u.lga}` },
                  {
                    key: "coords",
                    header: "Coordinates",
                    cell: (u) =>
                      u.latitude && u.longitude ? `${u.latitude}, ${u.longitude}` : "None",
                  },
                  {
                    key: "voters",
                    header: "Voters",
                    numeric: true,
                    cell: (u) => formatNumber(u.registered_voters),
                  },
                ]}
                empty={
                  <p className="flex items-center gap-2 py-4 text-body text-subtle-foreground">
                    <Database className="h-5 w-5" aria-hidden /> No polling unit matches “{search}”.
                  </p>
                }
              />
            ) : null}
          </div>
        </Card>
      </div>

      <TypedConfirm
        open={confirm}
        onOpenChange={(open) => {
          setConfirm(open);
          if (!open) setError(null);
        }}
        title="Import this master data?"
        description={`${formatNumber(changeCount)} records will be added or changed. Units missing from the file are kept, because results may refer to them. You will be asked for your authenticator code.`}
        phrase="import"
        confirmLabel="Import now"
        loading={importing.isPending}
        error={error}
        onConfirm={() => importing.mutate()}
      />
    </>
  );
}
