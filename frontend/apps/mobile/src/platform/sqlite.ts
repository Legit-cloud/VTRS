import * as SQLite from "expo-sqlite";
import type { Db } from "../core/db";

/** expo-sqlite behind the app's small Db interface. */
export async function openDb(name = "vtrs.db"): Promise<Db> {
  const native = await SQLite.openDatabaseAsync(name);
  await native.execAsync("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;");
  let depth = 0;
  return {
    exec: (sql) => native.execAsync(sql),
    async run(sql, params) {
      const result = await native.runAsync(sql, [...(params ?? [])] as SQLite.SQLiteBindValue[]);
      return { changes: result.changes };
    },
    all: <T>(sql: string, params?: readonly unknown[]) =>
      native.getAllAsync<T>(sql, [...(params ?? [])] as SQLite.SQLiteBindValue[]),
    first: <T>(sql: string, params?: readonly unknown[]) =>
      native.getFirstAsync<T>(sql, [...(params ?? [])] as SQLite.SQLiteBindValue[]),
    async transaction(work) {
      // Nested calls join the outer transaction (the engine composes small steps).
      if (depth > 0) return work();
      depth += 1;
      try {
        let result!: Awaited<ReturnType<typeof work>>;
        await native.withTransactionAsync(async () => {
          result = await work();
        });
        return result;
      } finally {
        depth -= 1;
      }
    },
  };
}
