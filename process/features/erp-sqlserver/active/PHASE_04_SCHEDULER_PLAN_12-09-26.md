# Phase 04: Scheduled synchronization and operational API

Date: 12-09-26
Complexity: Complex — one phase of ERP SQL Server program
Status: ⏳ PLANNED

## Overview

Objective: Scheduled synchronization and operational API.
Dependencies: 03 durable store/worker; selected tracking strategy from 01.
Umbrella: [ERP SQL Server program](ERP_SQLSERVER_PLAN_12-09-26.md).
Quick Links: [Execution Brief](#execution-brief) · [Verification Evidence](#verification-evidence) · [Resume and Execution Handoff](#resume-and-execution-handoff).
process/context/all-context.md and process/context/tests/all-tests.md are absent; use README, current code and baseline plan.

## Phase Completion Rules

⏳ PLANNED = not started; 🔨 CODE DONE = code only; 🧪 TESTING = verification underway;
✅ VERIFIED requires integration tests, Manual Test, Data Verification, error handling and User Confirmation.
Never infer live proof from mocked tests or a skipped SQL suite. Record failures, fixes and exact evidence.

## Execution Brief

### Pre-Phase Research

Read current code, previous phase report and vendor source contract before editing. Verify assumptions against the target environment.
This turn authorizes planning only. On a later implementation request, execute the selected phase within authorized scope;
request missing authority only for external writes/schema changes/live records, not routine local implementation choices.

### Implementation Checklist

- [ ] Default poll interval 60 seconds, configurable and disabled until source config is valid; read only SOs where the reviewed query enforces `IsApprSo = 1`. Run one scheduled job at a time per source with durable lease, owner token and expiry.
- [ ] Lease renewal/ownership checks prevent stale workers from committing progress after losing ownership; outbound sends rely additionally on durable per-request guards.
- [ ] Timestamp strategy uses stable keyset (changed_at, source_pk), fixed scan boundary, configurable overlap and periodic full in-scope reconciliation. Header-only timestamps cannot prove line change coverage.
- [ ] If using existing Change Tracking: track all contributing tables, verify minimum valid version before every cycle, capture consistent version boundary and reseed if retention expires; map changed detail keys back to SO.
- [ ] Do not advance to MAX(rowversion) or @@DBTS naively; if rowversion is selected, document active-transaction boundary and prove late-commit coverage in SQL tests.
- [ ] Initial rollout reconciliation proposal: every hour for the approved active-order scope plus operator backfill over a bounded range. Measure cost; no assertion that a finite overlap covers arbitrary late commits/deletes.
- [ ] Pause/resume/manual-run/status commands operate on named configured sources only; enqueue a run and return run_id for async operations. Overlapping manual/scheduled runs return existing active run/conflict.
- [ ] Add bounded backfill with dry-run, preview counts, fixed scope, resumable checkpoints and separate backfill cursor.
- [ ] Keep current /api/v1/erp/pull REST semantics intact. Add /api/v1/sync/runs and /api/v1/sync/status for SQL jobs; GET is read-only.
- [ ] Expose queue age, last successful extraction, last delivery, rejected/review counts, lease owner and source health without secrets/PII. Separate process liveness from dependency readiness.
- [ ] Logs carry run_id/request_id/state/duration/error code; metrics alert on lag and failures without full payloads.

### Test Stage / Test Procedure

Planned test files: tests/test_scheduler.py, tests/test_ops_api.py, tests/sqlserver/test_incremental.py.
Run command after implementation: `python3 -m unittest discover -s tests -v; SQLSERVER_TEST_DSN=<disposable-test-dsn> python3 -m unittest discover -s tests/sqlserver -v`.
Pass criteria: Fake-clock tests cover overlap, outage/catch-up, two schedulers, expired leases, timestamp ties, CT expiry if selected, backfill isolation, protected endpoints and restart.
Manual Test: Approve a test SO, observe scheduled enqueue/delivery; disconnect SQL, reconnect and confirm catch-up; pause and verify no new scheduled extraction.
Verification Queries / Data Verification: SELECT source_id,cursor_json,updated_at FROM source_checkpoints; SELECT run_id,state FROM sync_runs; SELECT source_id,owner,expires_at FROM sync_leases; compare source-to-outbox counts.
Do not execute proposed queries until the schema exists; SQL integration suites must fail clearly on unsupported setup and report absent setup as skipped.

## Acceptance Criteria

- All implementation tasks above have evidence, not just source files.
- Measured scheduled flow under test load with no observed missed candidates; target SLA still needs live sizing.
- Automated tests, manual flow, state checks and failure handling pass.
- User Confirmation recorded before VERIFIED.
- Blocker rule: If source metadata cannot prove change coverage, use agreed complete ready-order scans/reconciliation and disclose the remaining delete/history limitation.

## Public Contracts

Follow umbrella API/data/state/config contracts. Existing endpoints retain behavior unless a documented versioned migration is approved.
No actual SQL table names, accounting write APIs or remote cancellation APIs are assumed.

## Touchpoints

Planned files: thaisausage/scheduler.py, thaisausage/api.py, thaisausage/__main__.py, docs/openapi.yaml, tests/test_scheduler.py, tests/test_ops_api.py.
Source documents are read-only references. Persistent report: ../reports/phase-04.md.

## Blast Radius

Local code, tests, config templates and local migrations during implementation. SQL source is SELECT-only;
real VRP imports, external callbacks and production deployment happen only in their explicitly scoped release gates.
Dry-run cannot advance production checkpoints or trigger live sending.

## Verification Evidence

Not executed: this is a plan. Baseline foundation previously passed 15 tests; that is not evidence for this phase.
Store exact commands/results, fixture sizes, query outputs (redacted), observed errors, manual checks and user confirmation in ../reports/phase-04.md.
What green proves: Measured scheduled flow under test load with no observed missed candidates; target SLA still needs live sizing.

## Resume and Execution Handoff

Read umbrella, this phase and dependency reports; inspect worktree and migrations before resuming.
Resume first unchecked task, keep legacy submission history, and never rerun a live import just to reproduce proof.
Next Step (Cursor Plan / RIPER-5): RESEARCH this phase when its dependencies are evidenced, then EXECUTE on implementation instruction, VERIFY and REVIEW.
