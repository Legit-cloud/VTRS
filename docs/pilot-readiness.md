# Pilot readiness (Oyo State)

Where the backend stands against the PRD's acceptance criteria (AC), definition of done (DD)
and pre-build requirements (PB). "Evidence" points at tests or commands that show it; "Needs"
says who has to act. Updated at M7.

Status key: **Met** (built and verified here), **Backend met** (the client side is separate
work), **Open** (needs a decision, a provider, or an environment this repository does not
have).

## Acceptance criteria

| ID | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| AC-01 | Register an organization and verify by OTP | Met | `tests/accounts/test_registration_and_mfa.py` |
| AC-02 | Configure an election, its contesting parties and contestants | Met | `tests/elections/test_configuration.py`, browser suite |
| AC-03 | Invite and assign agents to polling units | Met | `tests/accounts/test_invitations.py`, `tests/assignments` |
| AC-04 | An agent sees only authorized assignments | Met | `tests/authz/test_matrix.py` |
| AC-05 | Capture a complete result: the numbers, then the result sheet | Met | `tests/results/test_submission.py`; browser suite (phone width: numbers, sheet compressed and uploaded, complete) |
| AC-06 | GPS and timestamp recorded at submission | Met | The browser asks for location once, when sending; the server stores and checks it: `tests/anomalies/test_pipeline.py` |
| AC-07 | Failed submissions and uploads retry automatically | Met | Backoff with the same version id; replay safety: `tests/results/test_concurrency.py`, portal `test/capture.test.ts` |
| AC-08 | Duplicate retries create no duplicate submissions | Met | 100 parallel replays, one version |
| AC-09 | Results aggregate correctly to ward, LGA, state | Met | `tests/aggregation/test_rollups.py`, `verify_rollups` |
| AC-10 | Expected versus reported units are accurate | Met | `tests/aggregation/test_dashboard.py` |
| AC-11 | Anomalies detected per approved rules, visible only to authorized users | Met (rules are defaults pending PB-10) | `tests/anomalies` |
| AC-12 | Evidence stored privately, hashed, retrievable by admins | Met | `tests/results/test_evidence.py`, `tests/reports/test_pack.py` |
| AC-13 | Audit logs capture material changes | Met | `tests/audit`, audit assertions throughout |
| AC-14 | Role and geographic permissions prevent unauthorized access | Met | `tests/authz/test_matrix.py` (every route, every role, four targets) |
| AC-15 | Dashboard performance and throughput meet pilot targets | Met on a laptop; **repeat on staging** | section "Load" below |

## Definition of done

| ID | Item | Status |
| --- | --- | --- |
| DD-01 | All agreed MVP requirements implemented and tested | Met in the backend and the one web app (October 2026 change: no mobile app) |
| DD-02 | Capture and retry pass end-to-end tests | Met: browser suite against the real API; 100 parallel replays make one version |
| DD-03 | Role and geographic permissions pass authorization tests | Met |
| DD-04 | Evidence integrity and access controls pass security testing | Met in code and tests; independent penetration test is **Open** |
| DD-05 | Aggregation reconciles against known datasets | Met (`verify_rollups`, reconciliation snapshot, simulation) |
| DD-06 | Dashboard meets performance targets under load | Measured here; confirm on staging hardware |
| DD-07 | Critical and high security findings resolved | Dependency audit clean (`pip-audit`), static scan reviewed (`bandit`: only false positives), hardening tests pass; pen test **Open** |
| DD-08 | UAT signed off | **Open**: needs the business owner; the simulator provides the scenario |
| DD-09 | Support, backup, monitoring and incident procedures documented | `docs/runbook.md`; restore drill recorded below |
| DD-10 | Pilot deployment ready for the Oyo test jurisdictions | **Open**: needs the environment (PB-12) |

## Pre-build requirements

| ID | Item | Status | What is still needed |
| --- | --- | --- | --- |
| PB-01 | Scope and role matrix | Met | Sign-off |
| PB-02 | Organization identity and ownership | Open | Business |
| PB-03 | Approved master dataset | Interim directories loaded; INEC export still needed | Supplied community directories are bundled in `data/master/` and import through `convert_directory` then `import_master_data --no-expectations`: Oyo (33 LGAs, 351 wards, 4,731 of about 6,390 units), Ogun (20 / 236 / 3,184) Ekiti (16 / 177 / 2,191), Lagos (20 / 245 / 8,322) and Osun (30 / 332 / 2,984). They are names only: no INEC codes (provisional `DIR-<state>-…` codes are positional), no coordinates, no voter counts, and they omit units added in 2022. GPS and expected-versus-reported figures are therefore partial until the INEC export replaces them |
| PB-04 | Candidate and election configuration rules | Met (rules enforced; lock fingerprints the configuration) | Confirmation |
| PB-05 | Result-sheet fields and validation | Every configured party, plus accredited, total cast and rejected; valid is the sum of the parties. The two arithmetic limits reject (open decision #12) | Confirm the field set, and reject versus flag for the limits |
| PB-06 | Agent deployment model | Decided: up to three agents per polling unit | None |
| PB-07 | OTP, SMS, email providers | Adapters built (Twilio SMS and WhatsApp, Turnstile or hCaptcha or reCAPTCHA, ClamAV) and tested against their protocols | Pick vendors, supply credentials, run each against the real service once |
| PB-08 | Biometric / face verification | Not implemented (feature flag off) | Legal and privacy decision |
| PB-09 | Evidence retention, access and export policy | Defaults implemented and documented (README, `VTRS_RETENTION_YEARS`) | Legal sign-off |
| PB-10 | Anomaly rules and escalation matrix | Industry-standard defaults implemented, all tunable (`VTRS_ANOMALY_THRESHOLDS`, `VTRS_ESCALATION_MATRIX`, per-organization override) | Confirm thresholds and the officer chain |
| PB-11 | Security architecture and threat model | `docs/threat-model.md` | Review and penetration test |
| PB-12 | Hosting, account ownership, data residency | Open | Decision; no residency claim is made until then |
| PB-13 | UAT scenarios and simulation plan | `simulate_election_day` and the runbook's timeline | Run on staging; agree scenarios |

## Load

The simulator (`simulate_election_day`) was run against the real API, database, broker and
workers on one developer laptop. The figures below are a floor, not a promise.

Environment: one developer laptop (8 logical cores), PostgreSQL and Redis in containers, one
worker process with eight threads, the load generator and the workers on the same machine.
Each request carries one result.

| Scenario | Submit rate | Request latency (p50 / p95 / p99) | Dashboard latency (p50 / p95) | Workers caught up |
| --- | --- | --- | --- | --- |
| 300 agents, 12 at a time, 20 dashboard readers | 5.1 per second (18,400 per hour) | 2.2 s / 3.4 s / 6.0 s | 1.0 s / 3.5 s | 4 s after the last submit |
| 300 agents, 3 at a time, 5 dashboard readers | 4.4 per second (15,700 per hour) | 0.6 s / 0.9 s / 1.0 s | 0.25 s / 0.40 s | 4 s after the last submit |

Both runs ended with every polling unit reported, zero rollup differences against an
independent calculation, and an intact audit chain. The target is 10,000 per hour
(2.8 per second): about 1.6 to 1.8 times that was sustained with the generator competing for the
same cores. API alone, with three clients and no dashboard readers, sustained 16.9 results per
second at p95 263 ms. Against a full state (6,390 units) the dashboard answered in about 0.1 s,
a full results export built in about 5 s, and a full rollup rebuild took under 2 s.

What the load work found and fixed (all in this milestone):

- Celery's built-in Django fixup throttled every worker to a few tasks per second on top of a
  prefetch multiplier of 1 that stalled thread pools between polling ticks. Rollups lagged by
  minutes; now they lag by seconds. Both are configuration (`config/celery.py`, settings).
- Rollup refresh now coalesces: events mark a ward, one worker refreshes everything marked,
  once per LGA and state, and other workers return immediately instead of queueing on a lock.
- A periodic self-check rebuilds any live contest whose rollups drift from a fresh calculation
  (a lost message after a broker failure was the cause in testing) and audits the repair.

Not yet measured: prefork workers on Linux, multi-instance API behind a load balancer,
500 concurrent WebSocket dashboards, a 6,390-agent day. These need staging hardware.

## Restore drill

Drill on the development database (about 6.7 MB, 4,700 result versions, 10,800 audit
events): `pg_dump --format=custom` took 1.1 s and `pg_restore` into an empty database 4.7 s.

| Table | Source | Restored |
| --- | --- | --- |
| `result_version` | 4,693 | 4,693 |
| `vote_line` | 14,038 | 14,038 |
| `pu_result` | 4,442 | 4,442 |
| `evidence_file` | 14 | 14 |
| `audit_event` | 10,828 | 10,828 |
| `audit_batch` | 161 | 161 |
| `custody_event` | 50 | 50 |
| `anomaly_flag` | 1,489 | 1,489 |
| `rollup` | 10,010 | 10,010 |

`verify_audit_chain` on the restored copy: intact. `verify_rollups` on the restored copy
matched the source election by election: the elections that were healthy in the source were
healthy in the copy, and the older simulation elections that showed differences in the copy
showed the same differences in the source (they were abandoned mid-run after their broker
messages were deliberately discarded). That is what a restore should do: reproduce the source,
including its faults. Repair is `rebuild_rollups`, and live elections now do it themselves.

This was a logical dump of a small database on one machine. It proves the procedure and the
integrity gates, not recovery time at production size or point-in-time recovery; rehearse
those on the production stack (runbook section 7).

## Before go-live, in order

1. Decide hosting and region (PB-12); stand up staging and production.
2. Provide the INEC master data (PB-03) and import it in place of the interim directory.
3. Choose the SMS, WhatsApp, challenge and scanner vendors (PB-07); run each adapter once
   against the real service.
4. Repeat the load simulation on staging hardware with prefork workers; record the numbers here.
5. Independent penetration test; resolve critical and high findings.
6. Legal review of retention, export and biometrics (PB-08, PB-09).
7. UAT with the business owner using simulated election days; sign off (DD-08).
8. Rehearse restore and key rotation on the production stack (runbook sections 7 and 9).
