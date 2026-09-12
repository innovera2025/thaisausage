# Phase 06: UAT, deployment, monitoring and handoff

Date: 12-09-26
Complexity: Complex — one phase of ERP SQL Server program
Status: ⏳ PLANNED

## Overview

Objective: UAT, deployment, monitoring and handoff.
Dependencies: 01–04 for SO go-live; 05 additionally for COD go-live; releases can be independent.
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

- [ ] Select one deployment topology after environment discovery: single internal host close to SQL Server, production HTTP server/service manager, TLS ingress as needed, persistent local state and least-privilege service identity.
- [ ] Current http.server is development scaffolding; replace behind a production-grade API stack while preserving contracts. Runtime/dependency selection and pins belong to implementation, not untested promises.
- [ ] Use a single owner deployment with SQLite initially; if multiple hosts or measured contention require scale, plan migration to shared transactional storage before enabling replicas.
- [ ] Set secrets outside source control, redact logs, lock down outbound VRP and SQL access, encrypt disks/backups containing outbox/COD data, document rotation and retention deletion policy.
- [ ] Preflight SQL SELECT permissions, trusted TLS certificate, VRP token, master customers/ship-to/routes/hubs, decimal rules, connectivity, firewall, DNS and time synchronization.
- [ ] UAT: compare ERP SO to generated JSON to eVRP import result and UI, including COD/free goods, page boundaries, outages, restarts, validation rejection and amended SO review.
- [ ] Proposed acceptance target: 95% of ready SOs durably queued within 2 polling cycles under agreed peak load; delivery lag separately measured during upstream availability. Final volumes/SLA/backup RPO/RTO need business signoff.
- [ ] Start dry-run against approved sample scope; then operator-authorized small live batch; reconcile count/amounts; enable schedule; observe at least one business cycle before expanding scope.
- [ ] Prove backup/restore plus replay reconciliation: restoring old state may forget accepted sends, so freeze sender and reconcile before resuming. Do not reset checkpoints or delete claims as rollback.
- [ ] Rollback pauses extraction/sending and restores compatible binary/schema with backup; remote SOs cannot be undone locally. Manual eVRP cancellation is a separately authorized business action.
- [ ] Alerts proposed: 3 extraction failures, source lag >5 minutes during operating hours, queue oldest >10 minutes, auth failure immediately, any needs_review. Tune based on measured SLA.
- [ ] Write operator procedures for pause, backlog, review/replay, rejected mapping corrections, CT reseed if applicable, COD review, token rotation and escalation owner.
- [ ] Handoff records exact config keys and owners, diagrams/contracts, deployment commands, restore drill, test results and remaining deferred features.

### Test Stage / Test Procedure

Planned test files: tests/test_smoke.py, tests/test_end_to_end.py, docs/uat-checklist.md.
Run command after implementation: `python3 -m unittest discover -s tests -v; run documented staging smoke and SQL integration commands after configuration`.
Pass criteria: Full staging path with SQL fixture and controlled VRP test records; restore drill and incident drills; report skips/untested live cases honestly. Never load-test production ERP/eVRP without scoped authorization.
Manual Test: User verifies representative orders in ERP and eVRP screens, approves SO release, and separately confirms COD release if enabled. Record dates, sample IDs and results without secrets.
Verification Queries / Data Verification: Reconcile source ready counts against outbox sent/rejected/review counts and remote accepted IDs; verify restored checkpoint/attempt history before enabling sender.
Do not execute proposed queries until the schema exists; SQL integration suites must fail clearly on unsupported setup and report absent setup as skipped.

## Acceptance Criteria

- All implementation tasks above have evidence, not just source files.
- Operationally accepted scoped release and tested recovery; deferred ERP posting/amendments remain excluded.
- Automated tests, manual flow, state checks and failure handling pass.
- User Confirmation recorded before VERIFIED.
- Blocker rule: Live deployment requires actual environment, approved live record scope and acceptance owners. Missing COD contract does not block an explicitly SO-only release.

## Public Contracts

Follow umbrella API/data/state/config contracts. Existing endpoints retain behavior unless a documented versioned migration is approved.
No actual SQL table names, accounting write APIs or remote cancellation APIs are assumed.

## Touchpoints

Planned files: deploy/*, docs/runbook.md, docs/uat-checklist.md, docs/recovery.md, tests/test_smoke.py, operational report.
Source documents are read-only references. Persistent report: ../reports/phase-06.md.

## Blast Radius

Local code, tests, config templates and local migrations during implementation. SQL source is SELECT-only;
real VRP imports, external callbacks and production deployment happen only in their explicitly scoped release gates.
Dry-run cannot advance production checkpoints or trigger live sending.

## Verification Evidence

Not executed: this is a plan. Baseline foundation previously passed 15 tests; that is not evidence for this phase.
Store exact commands/results, fixture sizes, query outputs (redacted), observed errors, manual checks and user confirmation in ../reports/phase-06.md.
What green proves: Operationally accepted scoped release and tested recovery; deferred ERP posting/amendments remain excluded.

## Resume and Execution Handoff

Read umbrella, this phase and dependency reports; inspect worktree and migrations before resuming.
Resume first unchecked task, keep legacy submission history, and never rerun a live import just to reproduce proof.
Next Step (Cursor Plan / RIPER-5): RESEARCH this phase when its dependencies are evidenced, then EXECUTE on implementation instruction, VERIFY and REVIEW.

