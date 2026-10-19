# VTRS frontend

One role-based web app (Next.js) for everyone: party leadership, LGA and ward coordinators,
polling unit agents (in their phone's browser) and platform operators. What a person sees
depends only on their role and assigned area. It is built on one design system and one typed
API package. The API is the Django service in the repository root; its contract is
`docs/openapi.yaml`. Since the October 2026 product change there is no mobile app and no
offline capture.

```
frontend/
  design-system/   tokens.json -> CSS variables and Tailwind preset; DESIGN_SYSTEM.md is
                   the written system (October 2026 revision)
  packages/core/   typed API client, submission hashing, arithmetic checks, copy, status
                   vocabulary, formatting
  apps/portal/     Next.js 16, the one web app: result capture for agents (/capture); War
                   Room, results and verification, anomalies, agents, elections and
                   contestants, parties, evidence, reports, team, audit, settings; and, for
                   platform operators, the platform admin surface under /platform
  e2e/             Playwright browser tests (desktop and phone width), with axe scans
```

## Setup

Node 22 or newer.

```sh
cd frontend
npm install
npm run tokens      # regenerate design tokens (fails if a contrast pair drops)
npm run gen:api     # regenerate API types from ../docs/openapi.yaml
npm run typecheck && npm run lint && npm test
```

### Run the portal against a local API

```sh
# API on :8000 (see the root README), then:
cp apps/portal/.env.example apps/portal/.env.local
npm run dev:portal                       # http://localhost:3000
```

The browser only talks to the portal's own origin. `/api/v1/*` is proxied to `VTRS_API_URL`
(no CORS to configure) and the refresh token lives in an httpOnly cookie set by `/session/*`
route handlers; the access token is held in memory only. The live dashboard socket connects to
`NEXT_PUBLIC_WS_URL`, so that origin must be allowed by the API's `VTRS_CORS_ALLOWED_ORIGINS`
(or its `ALLOWED_HOSTS` when that is empty).

Agents upload result sheets straight to object storage with a presigned PUT, which is
cross-origin: the bucket must allow PUT from the web app's origin. `python manage.py
ensure_evidence_bucket` writes that rule from `VTRS_CORS_ALLOWED_ORIGINS`.

## Browser tests

They run against a real API with real data, not mocks.

```sh
# 1. dev stack up, migrated, with a located directory imported (docker compose up -d)
# 2. a simulated election day, so there are results, flags and agents:
VTRS_ALLOW_SIMULATION=1 python manage.py simulate_election_day --agents 120
# 3. workers must be running so rollups complete (celery worker and beat), then:
python manage.py prepare_demo_logins
# 4. portal built and started, then:
cd frontend/e2e && npx playwright install chromium && npm test
```

Sign-in is throttled per address; run the API with relaxed throttle rates for a test run (the
throttles themselves are covered by the backend suite), and with the second factor enforced
(`VTRS_ENFORCE_MFA = True`; development turns it off), because the suite walks through
enrolment. Each run enrols the admin's authenticator from scratch, so re-run
`prepare_demo_logins` between runs. The phone-width project signs in as the demo agent
(`agent@demo.example`), sends a result and uploads a generated sheet photo to the object store.

## Platform admin

Platform operators run VTRS across all parties. They sign in to the same portal and get
different chrome (an ink sidebar and a strip across the top naming the surface and the
environment) and different pages: Overview, Organisations, Verification queue, Elections,
Master data, System health, Messaging providers, Audit log.

- **Who they are.** A `PLATFORM_ADMIN` membership in the platform organization. No party admin
  can grant the role and no invitation can carry it: create one on a trusted machine with
  `python manage.py create_platform_admin --email … --name … --password …`. They enrol an
  authenticator on first sign-in, and every decision needs a fresh code.
- **What they see.** Organisations, their admins (contact details masked), elections and their
  lock state, directory completeness, delivery rates, platform-wide audit. Never a party's
  results, evidence or people.
- **Typed confirmation** (the organisation's name) for approve, reject, suspend and
  reinstate; rejecting and suspending also need a reason that is kept and shown to them. A
  suspended organisation is signed out at once, agents included.
- **Master data** is previewed before it is written: the preview applies the import inside a
  savepoint and rolls it back, so the added and changed counts are exactly what the real import
  produces. Units missing from a file are kept, because results may refer to them.
- It shares the portal app and components rather than being a second deployment. The role and
  the API enforce the boundary, and party users who open `/platform` are sent back. If the
  platform must live on its own host, serve the same build there and restrict the routes at
  the proxy.

Not built: real vendor failover for messaging (the page shows delivery rates and sends a test
message through the live provider; choosing and ordering providers is PB-07), and an
"acting as" mode that opens a party's pages (deliberately omitted: operators do not need
results to run the platform).

## Agents, in the browser

Agents get their own phone-first screens in the same app: an agent who signs in lands on
`/capture` and cannot open anything else but Settings.

1. **My polling units** lists each assignment with its state: not started, draft on this phone,
   sheet missing, sheet uploaded, and the review state beside it (unverified, needs review,
   verified, rejected with the coordinator's reason).
2. **The result form** has one row per configured party in the admin's order (abbreviation,
   logo, candidate) and the three totals. Zero is a number; blank is refused, naming the party.
   The same arithmetic the server applies runs as the agent types. "Party or candidate
   missing?" files a report for an admin.
3. **Send.** The version id is made when the form opens and kept with the draft in local
   storage, so a reload keeps the typed numbers and a retry is a replay. Location is asked for
   once, at sending. Network failures, 429 and 5xx retry with backoff (2 s to 60 s, full jitter,
   honouring Retry-After) while the page is open, and say so on screen.
4. **Attach the sheet.** "Take a photo" opens the camera; "Choose a photo or PDF" opens the
   picker. Photos are scaled to about 2,200 px on the long side and re-encoded as JPEG,
   stepping quality down to about 2 MB; PDFs go as they are. The browser hashes the exact bytes,
   gets a presigned PUT, uploads straight to storage, confirms, and shows "Uploaded".
5. **Corrections** open the form prefilled from the current version and send a new version
   that points at it; nothing is overwritten.

Not built: an installable app (PWA, on the spec's cut list). A real low-end Android phone pass
is still worth doing before the pilot (the browser suite runs at Pixel 5 size in Chromium).

## Decisions worth knowing

- **Tokens.** Access token in memory, refresh token in an httpOnly, SameSite=Strict cookie
  scoped to `/session`. A refused refresh clears the cookie; a throttled one does not.
- **Second factor.** Roles that need one are held on Settings until they enrol; the API would
  refuse everything else. Actions that need a fresh code ask for it in place and retry.
- **No map.** The directories carry names and counts, not boundaries, and there is no Mapbox
  token, so coverage is a tile grid (the design's sequential scale) rather than an inaccurate
  map. Add a map when boundary data exists.
- **Evidence.** The API has no flat list of sheets; evidence belongs to a result version. The
  Evidence page works the way a reviewer does: ward, then polling unit, then its sheet.
- **Verification.** Every result is unverified until a coordinator verifies it against its
  sheet, which needs the sheet to be in. The War Room and Results switch between all results
  and verified only; ties and narrow margins are named, never shown as a plain leader.
- **Idempotency.** Every write carries an `Idempotency-Key`. Retries reuse it.
- **Provisional.** Every leader and margin carries the Provisional badge; the words "winner",
  "won" and "declared" never appear.

## Not built yet

- Bot challenge widget on public forms (vendor not chosen, PB-07).
- Strings are English only (copy is centralised in `packages/core/src/copy.ts`). The Yoruba
  translation went with the mobile app; it can be brought back for the capture screens.
- Identity check (PB-08), real messaging-provider failover (PB-07).
