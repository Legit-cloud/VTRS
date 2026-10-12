/** Minimal RFC 4180 reader: quoted fields, doubled quotes, CRLF or LF, BOM tolerated. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  const input = text.replace(/^﻿/, "");
  for (let i = 0; i < input.length; i++) {
    const c = input[i]!;
    if (quoted) {
      if (c === '"' && input[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') {
        quoted = false;
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && input[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.some((cell) => cell.trim() !== "")) rows.push(row);
      row = [];
    } else {
      field += c;
    }
  }
  row.push(field);
  if (row.some((cell) => cell.trim() !== "")) rows.push(row);
  return rows;
}

export interface InviteRow {
  line: number;
  name: string;
  phone: string;
  email: string;
  unitCode: string;
}

export interface InviteCsv {
  rows: InviteRow[];
  /** Set when the header row is missing a column we need. */
  problem: string | null;
}

const ALIASES: Record<string, keyof Omit<InviteRow, "line">> = {
  name: "name",
  full_name: "name",
  fullname: "name",
  phone: "phone",
  mobile: "phone",
  phone_number: "phone",
  email: "email",
  polling_unit_code: "unitCode",
  polling_unit: "unitCode",
  pu_code: "unitCode",
  code: "unitCode",
};

export function readInviteCsv(text: string): InviteCsv {
  const table = parseCsv(text);
  if (table.length === 0) return { rows: [], problem: "The file is empty." };
  const header = table[0]!.map((h) =>
    h
      .trim()
      .toLowerCase()
      .replace(/[\s-]+/g, "_"),
  );
  const index: Partial<Record<keyof Omit<InviteRow, "line">, number>> = {};
  header.forEach((h, i) => {
    const key = ALIASES[h];
    if (key && index[key] === undefined) index[key] = i;
  });
  const missing = (["name", "phone", "email", "unitCode"] as const).filter(
    (k) => index[k] === undefined,
  );
  if (missing.length > 0) {
    const names: Record<string, string> = {
      name: "name",
      phone: "phone",
      email: "email",
      unitCode: "polling_unit_code",
    };
    return {
      rows: [],
      problem: `Add a header row with these columns: name, phone, email, polling_unit_code. Missing: ${missing
        .map((m) => names[m])
        .join(", ")}.`,
    };
  }
  const rows = table.slice(1).map((cells, i) => ({
    line: i + 2,
    name: (cells[index.name!] ?? "").trim(),
    phone: (cells[index.phone!] ?? "").trim(),
    email: (cells[index.email!] ?? "").trim(),
    unitCode: (cells[index.unitCode!] ?? "").trim(),
  }));
  return { rows, problem: null };
}
