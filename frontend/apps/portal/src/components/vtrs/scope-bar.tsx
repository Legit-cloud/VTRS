"use client";

import { ChevronRight, Lock, MapPin } from "lucide-react";
import { Fragment, useMemo } from "react";
import { useAuth } from "@/lib/auth";
import { useElectionLgas, useGeoNames } from "@/lib/geo-names";

// ISO 3166-2:NG short codes, which is what the master-data directories use.
const STATE_NAMES: Record<string, string> = {
  AB: "Abia",
  AD: "Adamawa",
  AK: "Akwa Ibom",
  AN: "Anambra",
  BA: "Bauchi",
  BY: "Bayelsa",
  BE: "Benue",
  BO: "Borno",
  CR: "Cross River",
  DE: "Delta",
  EB: "Ebonyi",
  ED: "Edo",
  EK: "Ekiti",
  EN: "Enugu",
  FC: "FCT",
  GO: "Gombe",
  IM: "Imo",
  JI: "Jigawa",
  KD: "Kaduna",
  KN: "Kano",
  KT: "Katsina",
  KE: "Kebbi",
  KO: "Kogi",
  KW: "Kwara",
  LA: "Lagos",
  NA: "Nasarawa",
  NI: "Niger",
  OG: "Ogun",
  ON: "Ondo",
  OS: "Osun",
  OY: "Oyo",
  PL: "Plateau",
  RI: "Rivers",
  SO: "Sokoto",
  TA: "Taraba",
  YO: "Yobe",
  ZA: "Zamfara",
};

export function stateName(code: string | undefined): string {
  if (!code) return "State";
  // Directory imports prefix the short code (DIR-OY); the synthetic test set is SYN.
  const short = code.toUpperCase().replace(/^DIR-/, "");
  if (short === "SYN") return "Test state";
  const name = STATE_NAMES[short];
  return name ? (name === "FCT" ? "FCT" : `${name} State`) : code;
}

export interface Crumb {
  label: string;
}

/** The geographic limit the server enforces, as a breadcrumb the user can read. */
export function useScopeCrumbs(): { crumbs: Crumb[]; locked: boolean } {
  const { me } = useAuth();
  const scope = me?.scope;
  const { lgas: list, stateCode } = useElectionLgas();
  const names = useGeoNames(!!me);

  return useMemo(() => {
    const state = stateName(stateCode);
    const crumbs: Crumb[] = [{ label: state }];
    const type = scope?.type ?? "ORG";
    if (type === "LGA") {
      const names = list.filter((l) => scope!.ids.includes(l.id)).map((l) => l.name);
      const suffixed = names.map((n) => (/\bLGA$/i.test(n) ? n : `${n} LGA`));
      crumbs.push({ label: suffixed.length ? suffixed.join(", ") : "Your LGA" });
    } else if (type === "WARD") {
      const ward = [...(names.data?.wards.values() ?? [])].filter((w) => scope!.ids.includes(w.id));
      const lga = list.find((l) => ward.some((w) => w.lga_id === l.id));
      if (lga) crumbs.push({ label: /\bLGA$/i.test(lga.name) ? lga.name : `${lga.name} LGA` });
      crumbs.push({ label: ward.length ? ward.map((w) => w.name).join(", ") : "Your ward" });
    } else if (type === "PU") {
      crumbs.push({ label: "Your polling units" });
    }
    return { crumbs, locked: type !== "ORG" };
  }, [list, stateCode, names.data, scope]);
}

export function ScopeBar() {
  const { crumbs, locked } = useScopeCrumbs();
  return (
    <nav
      aria-label="Your geographic scope"
      className="flex min-w-0 items-center gap-1.5 text-body-sm"
    >
      <span className="text-subtle-foreground">Scope:</span>
      {locked ? (
        <Lock
          className="h-4 w-4 shrink-0 text-subtle-foreground"
          aria-label="Limited to this area"
        />
      ) : (
        <MapPin className="h-4 w-4 shrink-0 text-subtle-foreground" aria-hidden />
      )}
      <ol className="flex min-w-0 items-center gap-1">
        {crumbs.map((crumb, index) => (
          <Fragment key={`${crumb.label}-${index}`}>
            {index > 0 ? (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            ) : null}
            <li
              className={
                index === crumbs.length - 1
                  ? "truncate font-semibold text-foreground"
                  : "truncate text-strong-foreground"
              }
            >
              {crumb.label}
            </li>
          </Fragment>
        ))}
      </ol>
    </nav>
  );
}
