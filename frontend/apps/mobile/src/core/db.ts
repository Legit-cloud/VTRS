/**
 * The little the app needs from a database. The phone implements it with expo-sqlite; the tests
 * implement it with Node's built-in SQLite, so the same SQL runs in both places.
 */
export interface Db {
  exec(sql: string): Promise<void>;
  run(sql: string, params?: readonly unknown[]): Promise<{ changes: number }>;
  all<T>(sql: string, params?: readonly unknown[]): Promise<T[]>;
  first<T>(sql: string, params?: readonly unknown[]): Promise<T | null>;
  transaction<T>(work: () => Promise<T>): Promise<T>;
}

const MIGRATIONS: string[] = [
  `
  CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);

  -- One row per result the agent has finished. item_json is exactly what was signed.
  CREATE TABLE submission (
    version_id      TEXT PRIMARY KEY,
    election_id     TEXT NOT NULL,
    contest_id      TEXT NOT NULL,
    contest_title   TEXT NOT NULL,
    polling_unit_id TEXT NOT NULL,
    pu_name         TEXT NOT NULL,
    pu_code         TEXT NOT NULL,
    ward            TEXT NOT NULL,
    lga             TEXT NOT NULL,
    item_json       TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    server_state    TEXT,
    version_no      INTEGER,
    review_reason   TEXT,
    flags           TEXT,
    created_at      INTEGER NOT NULL,
    sent_at         INTEGER
  );
  CREATE INDEX submission_status ON submission (status, next_attempt_at);

  CREATE TABLE evidence (
    evidence_id     TEXT PRIMARY KEY,
    version_id      TEXT NOT NULL REFERENCES submission (version_id),
    kind            TEXT NOT NULL,
    local_uri       TEXT NOT NULL,
    mime            TEXT NOT NULL,
    size            INTEGER NOT NULL,
    sha256          TEXT NOT NULL,
    status          TEXT NOT NULL,
    upload_url      TEXT,
    upload_headers  TEXT,
    upload_expires  INTEGER,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT
  );
  CREATE INDEX evidence_status ON evidence (status, next_attempt_at);

  -- Autosaved entry in progress, one per contest and polling unit.
  CREATE TABLE draft (
    contest_id      TEXT NOT NULL,
    polling_unit_id TEXT NOT NULL,
    json            TEXT NOT NULL,
    updated_at      INTEGER NOT NULL,
    PRIMARY KEY (contest_id, polling_unit_id)
  );
  `,
];

/** Apply any migrations this database has not seen. Safe to call on every start. */
export async function migrate(db: Db): Promise<void> {
  await db.exec("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)");
  const row = await db.first<{ version: number }>(
    "SELECT MAX(version) AS version FROM schema_version",
  );
  const current = row?.version ?? 0;
  for (let v = current; v < MIGRATIONS.length; v++) {
    await db.transaction(async () => {
      await db.exec(MIGRATIONS[v]!);
      await db.run("INSERT INTO schema_version (version) VALUES (?)", [v + 1]);
    });
  }
}

export async function kvGet(db: Db, key: string): Promise<string | null> {
  const row = await db.first<{ value: string }>("SELECT value FROM kv WHERE key = ?", [key]);
  return row?.value ?? null;
}

export async function kvSet(db: Db, key: string, value: string): Promise<void> {
  await db.run(
    "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    [key, value],
  );
}
