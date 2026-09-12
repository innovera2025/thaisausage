# Phase 03: Durable queue, idempotency and delivery recovery

Date: 12-09-26
Complexity: Complex — one phase of ERP SQL Server program
Status: ⏳ PLANNED

## Overview

Objective: Durable queue, idempotency and delivery recovery.
Dependencies: 02 extraction and mapping fixtures.
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

- [ ] Add versioned migrations, local outbox of immutable payload bytes+hash+source revision and attempt history; back up and migrate existing submissions/order_claims without deleting history.
- [ ] Persist extracted page to outbox/quarantine and advance the extraction cursor in one local transaction; only advance after every candidate is durably represented. SQL Server and local store are not a distributed transaction.
- [ ] Keep delivery completion separate from extraction progress. Crash before local commit re-reads page; after commit worker resumes without losing items.
- [ ] Freeze request_id, payload bytes, order membership and order sequence for each outbound attempt lineage. Retry identical bytes/id only; a changed payload requires a new version and explicit resolution.
- [ ] Start with one SO/request to isolate failures; future batches honor local 100 orders/1 MiB AND remote 500 orders/10 MB/2000 lines. Never split one SO across independent requests.
- [ ] Preserve existing API behavior and conservative order claims until migration/recovery semantics are tested. Imported old claims with no payload remain legacy_review; never invent payload for replay.
- [ ] Classify validation rejection as rejected, known pre-send transient failures as retry_wait, 401/config failures as suspended, and post-send/timeout/crash outcomes as needs_review.
- [ ] Current service short-circuits repeated request_id: implement an internal attempt operation that reuses stored bytes without going through the normal duplicate-return path. Operator-authorized replay must not delete order claims.
- [ ] Existing eVRP guide supports identical idempotent replay; unknown outcomes still require operator review until retention/replay availability is confirmed. No unattended blind POST retries.
- [ ] For already sent SO modified/cancelled in ERP, record amendment_required; do not auto-create a replacement SO. No update/cancel endpoint is documented.
- [ ] Add bounded backoff+jitter (initial proposal 30s, 2m, 10m, 30m, 2h; max 5 retries) only for retry-safe classified outcomes, dead-letter/review state and audited operator resolution.
- [ ] Validate success shape/summary against order identities and persist VRP batch/running identifiers and redacted diagnostic codes.

### Test Stage / Test Procedure

Planned test files: tests/test_delivery.py, tests/test_migrations.py, tests/test_recovery.py.
Run command after implementation: `python3 -m unittest discover -s tests -v`.
Pass criteria: Fault injection before/after queue commit, before/after remote acceptance, checkpoint commit failure, duplicated workers, restart, malformed 200, HTTP 401/422/500 and identical replay. Upstream mock records bytes and call counts.
Manual Test: Kill/restart a test worker after mocked remote acceptance, inspect needs_review, then execute reviewed exact replay; test restore of a copy of an existing SQLite database.
Verification Queries / Data Verification: SELECT state,COUNT(*) FROM outbox GROUP BY state; SELECT * FROM source_checkpoints; SELECT request_id,attempt_no,outcome FROM delivery_attempts; compare against mock call ledger.
Do not execute proposed queries until the schema exists; SQL integration suites must fail clearly on unsupported setup and report absent setup as skipped.

## Acceptance Criteria

- All implementation tasks above have evidence, not just source files.
- Local durability and tested recovery semantics, not distributed exactly-once guarantees.
- Automated tests, manual flow, state checks and failure handling pass.
- User Confirmation recorded before VERIFIED.
- Blocker rule: No automatic replay of ambiguous live outcomes until eVRP idempotency retention is known. Order amendments/cancellations wait for vendor contract.

## Public Contracts

Follow umbrella API/data/state/config contracts. Existing endpoints retain behavior unless a documented versioned migration is approved.
No actual SQL table names, accounting write APIs or remote cancellation APIs are assumed.

## Touchpoints

Planned files: thaisausage/store.py, thaisausage/worker.py, thaisausage/service.py, thaisausage/connectors.py, migrations/*.sql, tests/test_delivery.py.
Source documents are read-only references. Persistent report: ../reports/phase-03.md.

## Blast Radius

Local code, tests, config templates and local migrations during implementation. SQL source is SELECT-only;
real VRP imports, external callbacks and production deployment happen only in their explicitly scoped release gates.
Dry-run cannot advance production checkpoints or trigger live sending.

## Verification Evidence

Not executed: this is a plan. Baseline foundation previously passed 15 tests; that is not evidence for this phase.
Store exact commands/results, fixture sizes, query outputs (redacted), observed errors, manual checks and user confirmation in ../reports/phase-03.md.
What green proves: Local durability and tested recovery semantics, not distributed exactly-once guarantees.

## Resume and Execution Handoff

Read umbrella, this phase and dependency reports; inspect worktree and migrations before resuming.
Resume first unchecked task, keep legacy submission history, and never rerun a live import just to reproduce proof.
Next Step (Cursor Plan / RIPER-5): RESEARCH this phase when its dependencies are evidenced, then EXECUTE on implementation instruction, VERIFY and REVIEW.

