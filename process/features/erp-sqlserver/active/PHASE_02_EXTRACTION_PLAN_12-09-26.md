# Phase 02: SQL reader and ERP-to-JSON mapping

Date: 12-09-26
Complexity: Complex — one phase of ERP SQL Server program
Status: ⏳ PLANNED

## Overview

Objective: SQL reader and ERP-to-JSON mapping.
Dependencies: 01 discovery source contract.
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

- [ ] Add source.type=sqlserver|rest while retaining existing REST behavior. Keep credentials in environment references; config/schema validation runs before connection.
- [ ] SQL values use parameters; table/view/column identifiers come only from reviewed allowlists. Do not accept arbitrary SQL or connection strings in public request bodies.
- [ ] Fetch candidate order keys in stable pages, then retrieve complete header/detail/customer data in bounded queries; never paginate joined line rows as if they were complete orders.
- [ ] Group lines by immutable company+SO key and preserve line identifiers, free items, same item_code at different prices and exact quantities. Do not silently collapse lines.
- [ ] Map every field in umbrella mapping contract. Use Decimal for SQL decimal/money, agreed rounding/unit conversions, lossless numeric JSON serialization; no blanket conversion to binary float.
- [ ] Capture consistent order snapshots and source revisions/fingerprints. Re-read or quarantine unstable records instead of exporting half-written approval/detail changes.
- [ ] New line-only updates, late approvals of old SOs, customer/ship-to changes and cancellations must enter candidate selection or scheduled reconciliation.
- [ ] Detect missing master mappings/route assumptions, duplicate source keys, unsupported tax/discount rules, >2000 lines or oversized single order; quarantine with a field-level explanation.
- [ ] Dry-run returns redacted preview on operator request, writes no live queue or checkpoint; previews cannot advance production cursors.
- [ ] GET/CLI connectivity check and preview only read SQL. No update of exported flags in ERP.

### Test Stage / Test Procedure

Planned test files: tests/test_sqlserver_reader.py, tests/test_mapping.py, tests/sqlserver/test_extraction.py.
Run command after implementation: `python3 -m unittest discover -s tests -v; SQLSERVER_TEST_DSN=<disposable-test-dsn> python3 -m unittest discover -s tests/sqlserver -v`.
Pass criteria: Golden fixtures match full SO/line counts, Thai text, decimals, dates, COD and gifts. Integration tests include split pages, timestamp ties, detail-only edits, rollback/late commit and invalid masters.
Manual Test: Compare at least 10 representative SO previews with ERP screens/export; include COD, credit, gift, discount/tax and multiple shipping points.
Verification Queries / Data Verification: Record source header count, detail count and decimal totals beside each output; SELECT from approved schema only. No production checkpoint is changed by preview.
Do not execute proposed queries until the schema exists; SQL integration suites must fail clearly on unsupported setup and report absent setup as skipped.

## Acceptance Criteria

- All implementation tasks above have evidence, not just source files.
- Complete and faithful JSON snapshots; remote acceptance remains unproven.
- Automated tests, manual flow, state checks and failure handling pass.
- User Confirmation recorded before VERIFIED.
- Blocker rule: Unresolved pricing/tax/unit or readiness semantics quarantine affected orders; do not infer a formula from sample values.

## Public Contracts

Follow umbrella API/data/state/config contracts. Existing endpoints retain behavior unless a documented versioned migration is approved.
No actual SQL table names, accounting write APIs or remote cancellation APIs are assumed.

## Touchpoints

Planned files: thaisausage/sqlserver.py, thaisausage/mapping.py, thaisausage/contracts.py, sql/erp/*.sql, config/sqlserver.example.json, docs/field-mapping.md, examples/sqlserver/*.json.
Source documents are read-only references. Persistent report: ../reports/phase-02.md.

## Blast Radius

Local code, tests, config templates and local migrations during implementation. SQL source is SELECT-only;
real VRP imports, external callbacks and production deployment happen only in their explicitly scoped release gates.
Dry-run cannot advance production checkpoints or trigger live sending.

## Verification Evidence

Not executed: this is a plan. Baseline foundation previously passed 15 tests; that is not evidence for this phase.
Store exact commands/results, fixture sizes, query outputs (redacted), observed errors, manual checks and user confirmation in ../reports/phase-02.md.
What green proves: Complete and faithful JSON snapshots; remote acceptance remains unproven.

## Resume and Execution Handoff

Read umbrella, this phase and dependency reports; inspect worktree and migrations before resuming.
Resume first unchecked task, keep legacy submission history, and never rerun a live import just to reproduce proof.
Next Step (Cursor Plan / RIPER-5): RESEARCH this phase when its dependencies are evidenced, then EXECUTE on implementation instruction, VERIFY and REVIEW.

