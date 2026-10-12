"use client";

import { useQuery } from "@tanstack/react-query";
import { cursorFrom, type PollingUnit } from "@vtrs/core";
import { X } from "lucide-react";
import { useMemo, useState } from "react";
import { Field, Input, Select } from "@/components/ui/field";
import { ep } from "@/lib/api";
import { useElectionLgas } from "@/lib/geo-names";

export interface PickedUnit {
  id: string;
  code: string;
  name: string;
  ward: string;
}

/** LGA, then ward, then polling units with a name filter. Selected units show as removable chips. */
export function PollingUnitPicker({
  value,
  onChange,
  max,
}: {
  value: PickedUnit[];
  onChange: (next: PickedUnit[]) => void;
  max?: number;
}) {
  const [lgaId, setLgaId] = useState("");
  const [wardId, setWardId] = useState("");
  const [filter, setFilter] = useState("");

  const { lgas } = useElectionLgas();
  const wards = useQuery({
    queryKey: ["geo", "wards", lgaId],
    enabled: !!lgaId,
    queryFn: async () => (await ep.geography.wards({ lga: lgaId, limit: 200 })).results,
    staleTime: 10 * 60_000,
  });
  const units = useQuery({
    queryKey: ["geo", "pus", wardId],
    enabled: !!wardId,
    queryFn: async () => {
      const all: PollingUnit[] = [];
      let cursor: string | null = null;
      do {
        const page: Awaited<ReturnType<typeof ep.geography.pollingUnits>> =
          await ep.geography.pollingUnits({ ward: wardId, limit: 200, cursor });
        all.push(...page.results);
        cursor = cursorFrom(page.next);
      } while (cursor);
      return all;
    },
    staleTime: 10 * 60_000,
  });

  const wardName = wards.data?.find((w) => w.id === wardId)?.name ?? "";
  const picked = useMemo(() => new Set(value.map((v) => v.id)), [value]);
  const visible = (units.data ?? []).filter((u) =>
    `${u.name} ${u.inec_code}`.toLowerCase().includes(filter.trim().toLowerCase()),
  );
  const atMax = max !== undefined && value.length >= max;

  return (
    <div className="flex flex-col gap-3">
      {value.length > 0 ? (
        <ul className="flex flex-wrap gap-2" aria-label="Selected polling units">
          {value.map((u) => (
            <li
              key={u.id}
              className="inline-flex items-center gap-1 rounded-full bg-primary-soft py-1 pl-3 pr-1 text-body-sm font-medium text-primary-soft-foreground"
            >
              {u.name}
              <button
                type="button"
                onClick={() => onChange(value.filter((v) => v.id !== u.id))}
                aria-label={`Remove ${u.name}`}
                className="flex h-6 w-6 items-center justify-center rounded-full hover:bg-primary-soft-hover"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="LGA">
          {(props) => (
            <Select
              {...props}
              value={lgaId}
              onChange={(e) => {
                setLgaId(e.target.value);
                setWardId("");
              }}
            >
              <option value="">Choose an LGA…</option>
              {lgas.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Ward">
          {(props) => (
            <Select
              {...props}
              value={wardId}
              disabled={!lgaId}
              onChange={(e) => setWardId(e.target.value)}
            >
              <option value="">Choose a ward…</option>
              {(wards.data ?? []).map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {wardId ? (
        <>
          <Field label="Find a polling unit">
            {(props) => (
              <Input
                {...props}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Name or code"
              />
            )}
          </Field>
          <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-md border border-border">
            {units.isLoading ? (
              <li className="p-3 text-body-sm text-subtle-foreground">Loading…</li>
            ) : null}
            {visible.map((u) => {
              const checked = picked.has(u.id);
              return (
                <li key={u.id}>
                  <label className="flex min-h-12 cursor-pointer items-center gap-3 px-3 py-2 hover:bg-muted">
                    <input
                      type="checkbox"
                      className="h-5 w-5 accent-[rgb(var(--primary))]"
                      checked={checked}
                      disabled={!checked && atMax}
                      onChange={() =>
                        onChange(
                          checked
                            ? value.filter((v) => v.id !== u.id)
                            : [
                                ...value,
                                { id: u.id, code: u.inec_code, name: u.name, ward: wardName },
                              ],
                        )
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-body-sm font-semibold">{u.name}</span>
                      <span className="mono text-caption text-subtle-foreground">
                        {u.inec_code}
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
            {!units.isLoading && visible.length === 0 ? (
              <li className="p-3 text-body-sm text-subtle-foreground">No polling units match.</li>
            ) : null}
          </ul>
        </>
      ) : null}
    </div>
  );
}
