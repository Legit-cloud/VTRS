"use client";

import { ChevronDown, ChevronRight, ChevronUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface Column<Row> {
  key: string;
  header: string;
  cell: (row: Row) => ReactNode;
  /** Right-align and use tabular figures. */
  numeric?: boolean;
  /** Return a comparable value to make the column sortable. */
  sortValue?: (row: Row) => number | string | null;
  width?: string;
  /** Hidden below the md breakpoint. */
  hideOnNarrow?: boolean;
}

interface Props<Row> {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  dense?: boolean;
  onRowClick?: (row: Row) => void;
  selectedKey?: string | null;
  empty: ReactNode;
  caption: string;
  initialSort?: { key: string; dir: "asc" | "desc" };
  footer?: ReactNode;
}

/** Row 48 (dense 40), sticky header, no zebra, numeric columns right-aligned and tabular. */
export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  dense,
  onRowClick,
  selectedKey,
  empty,
  caption,
  initialSort,
  footer,
}: Props<Row>) {
  const [sort, setSort] = useState(initialSort ?? null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const column = columns.find((c) => c.key === sort.key);
    if (!column?.sortValue) return rows;
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = column.sortValue!(a);
      const y = column.sortValue!(b);
      if (x === y) return 0;
      if (x === null) return 1;
      if (y === null) return -1;
      return (x < y ? -1 : 1) * factor;
    });
  }, [rows, columns, sort]);

  if (rows.length === 0) return <>{empty}</>;

  return (
    <div className="scroll-x rounded-lg border border-border bg-card shadow-card">
      <table className="w-full border-collapse text-left text-body-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 z-10 bg-canvas">
          <tr className="border-b border-border">
            {columns.map((c) => {
              const active = sort?.key === c.key;
              return (
                <th
                  key={c.key}
                  scope="col"
                  style={{ width: c.width }}
                  aria-sort={
                    active ? (sort!.dir === "asc" ? "ascending" : "descending") : undefined
                  }
                  className={cn(
                    "h-10 whitespace-nowrap px-4 text-label font-semibold text-strong-foreground",
                    c.numeric && "text-right",
                    c.hideOnNarrow && "hidden md:table-cell",
                  )}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      className={cn(
                        "inline-flex items-center gap-1 rounded-sm hover:text-foreground",
                        c.numeric && "flex-row-reverse",
                      )}
                      onClick={() =>
                        setSort((cur) =>
                          cur?.key === c.key
                            ? { key: c.key, dir: cur.dir === "asc" ? "desc" : "asc" }
                            : { key: c.key, dir: c.numeric ? "desc" : "asc" },
                        )
                      }
                    >
                      {c.header}
                      {active ? (
                        sort!.dir === "asc" ? (
                          <ChevronUp className="h-4 w-4" aria-hidden />
                        ) : (
                          <ChevronDown className="h-4 w-4" aria-hidden />
                        )
                      ) : null}
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
            {onRowClick ? <th className="w-10" aria-hidden /> : null}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const key = rowKey(row);
            const selected = key === selectedKey;
            return (
              <tr
                key={key}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                tabIndex={onRowClick ? 0 : undefined}
                aria-selected={selected || undefined}
                className={cn(
                  "border-b border-border last:border-b-0",
                  dense ? "h-10" : "h-12",
                  onRowClick && "cursor-pointer hover:bg-muted focus-visible:bg-muted",
                  selected && "bg-primary-soft",
                )}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn(
                      "px-4 align-middle",
                      c.numeric && "text-right tabular-nums",
                      c.hideOnNarrow && "hidden md:table-cell",
                    )}
                  >
                    {c.cell(row)}
                  </td>
                ))}
                {onRowClick ? (
                  <td className="pr-3 text-muted-foreground">
                    <ChevronRight className="h-4 w-4" aria-hidden />
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
      {footer ? <div className="border-t border-border p-3">{footer}</div> : null}
    </div>
  );
}
