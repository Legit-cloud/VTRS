# VTRS frontend

The party portal (Next.js) and the agent app (Expo), built on one design system and one typed
API package. The API is the Django service in the repository root; its contract is
`docs/openapi.yaml`.

```
frontend/
  design-system/   tokens.json -> CSS variables, Tailwind preset, React Native theme
  packages/core/   typed API client, offline-safe hashing, copy, status vocabulary, formatting
  apps/portal/     Next.js 16: War Room, results, anomalies, agents, elections, evidence,
                   reports, team, audit, settings
  apps/mobile/     Expo: agent app (offline capture and sync)
  e2e/             Playwright browser tests for the portal, with axe accessibility scans
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

## Browser tests

They run against a real API with real data, not mocks.

```sh
# 1. dev stack up, migrated, with a located directory imported (docker compose up -d)
# 2. a simulated election day, so there are results, flags and agents:
VTRS_ALLOW_SIMULATION=1 python manage.py simulate_election_day --agents 60 --state SYN
# 3. workers must be running so rollups complete (celery worker and beat), then:
python manage.py prepare_demo_logins
# 4. portal built and started, then:
cd frontend/e2e && npx playwright install chromium && npm test
```

Sign-in is throttled per address; run the API with relaxed throttle rates for a test run (the
throttles themselves are covered by the backend suite). Each run enrols the admin's
authenticator from scratch, so re-run `prepare_demo_logins` between runs.

## Decisions worth knowing

- **Tokens.** Access token in memory, refresh token in an httpOnly, SameSite=Strict cookie
  scoped to `/session`. A refused refresh clears the cookie; a throttled one does not.
- **Second factor.** Roles that need one are held on Settings until they enrol; the API would
  refuse everything else. Actions that need a fresh code ask for it in place and retry.
- **No map.** The directories carry names and counts, not boundaries, and there is no Mapbox
  token, so coverage is a tile grid (the design's sequential scale) rather than an inaccurate
  map. Add a map when boundary data exists.
- **Evidence.** The API has no flat list of photos; evidence belongs to a result version. The
  Evidence page works the way a reviewer does: ward, then polling unit, then its photos.
- **Idempotency.** Every write carries an `Idempotency-Key`. Retries reuse it.
- **Provisional.** Every leader and margin carries the Provisional badge; the words "winner",
  "won" and "declared" never appear.

## Not built yet

- Platform admin app (organisations, verification queue, master-data import, providers). It
  needs a platform-admin role and cross-organisation endpoints on the API first.
- Bot challenge widget on public forms (vendor not chosen, PB-07).
- Yoruba and Pidgin strings (copy is centralised in `packages/core/src/copy.ts`).
