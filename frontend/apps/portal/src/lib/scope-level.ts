import type { Level, Me } from "@vtrs/core";

export interface View {
  level: Level;
  /** Area to list the children of; null at the top of the caller's scope. */
  parent: string | null;
}

export const NEXT_LEVEL: Record<Level, Level | null> = { lga: "ward", ward: "pu", pu: null };

/**
 * Where a person's drill-down starts. The API's top level is the caller's own area (state
 * officers start at LGAs, an LGA officer at their LGA, a ward officer at their ward), and it
 * refuses a level without the parent it needs. With exactly one area in scope we go straight
 * to its children, which is what the person wants to see.
 */
export function startView(scope: Me["scope"] | undefined): View | null {
  const type = scope?.type ?? "ORG";
  const ids = scope?.ids ?? [];
  if (type === "LGA")
    return ids.length === 1 ? { level: "ward", parent: ids[0]! } : { level: "lga", parent: null };
  if (type === "WARD")
    return ids.length === 1 ? { level: "pu", parent: ids[0]! } : { level: "ward", parent: null };
  if (type === "PU") return null;
  return { level: "lga", parent: null };
}

/** The root of the trail, for the breadcrumb: where "up" stops. */
export function isStart(view: View, start: View | null): boolean {
  return !!start && view.level === start.level && (view.parent ?? null) === (start.parent ?? null);
}
