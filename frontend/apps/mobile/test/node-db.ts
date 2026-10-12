import { DatabaseSync } from "node:sqlite";
import type { Db } from "../src/core/db";

/** The app's Db interface over Node's built-in SQLite: the same SQL the phone runs. */
export function nodeDb(): Db {
  const sqlite = new DatabaseSync(":memory:");
  let depth = 0;
  const bind = (params?: readonly unknown[]) =>
    (params ?? []) as (string | number | null | bigint | Uint8Array)[];
  return {
    async exec(sql) {
      sqlite.exec(sql);
    },
    async run(sql, params) {
      const result = sqlite.prepare(sql).run(...bind(params));
      return { changes: Number(result.changes) };
    },
    async all<T>(sql: string, params?: readonly unknown[]) {
      return sqlite.prepare(sql).all(...bind(params)) as T[];
    },
    async first<T>(sql: string, params?: readonly unknown[]) {
      return (sqlite.prepare(sql).get(...bind(params)) as T | undefined) ?? null;
    },
    async transaction(work) {
      const nested = depth > 0;
      depth += 1;
      if (!nested) sqlite.exec("BEGIN");
      try {
        const result = await work();
        if (!nested) sqlite.exec("COMMIT");
        return result;
      } catch (error) {
        if (!nested) sqlite.exec("ROLLBACK");
        throw error;
      } finally {
        depth -= 1;
      }
    },
  };
}
