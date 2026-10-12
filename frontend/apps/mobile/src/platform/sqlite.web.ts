import type { Db } from "../core/db";

/**
 * The browser build exists to preview screens, not to capture results: SQLite on the web needs
 * a WASM worker this app does not ship. Opening the database fails, and the app falls back to
 * its signed-out screens.
 */
export async function openDb(): Promise<Db> {
  throw new Error("Local storage is not available in the browser preview.");
}
