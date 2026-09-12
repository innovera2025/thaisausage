# Phase 01: SQL Server discovery and source contract

Date: 12-09-26
Complexity: Complex — one phase of ERP SQL Server program
Status: 🧪 TESTING — read-only connector foundation added; real SQL discovery pending approved SO scope

## Overview

Objective: SQL Server discovery and source contract.
Dependencies: None; use current foundation as baseline.
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

- [ ] Record SQL Server version, ERP vendor/version, host OS, instance/resolved port, database, company/branch and timezone; no guessed production identifiers.
- [ ] Select SQL authentication or integrated authentication from deployment evidence; select supported Python runtime, pyodbc and Microsoft ODBC driver versions and pin only after compatibility testing.
- [ ] Use a dedicated SELECT-only principal over approved tables/views. Test denied writes using permission inspection or disposable test database, never attempted production writes.
- [ ] Inspect metadata and limited anonymized records for SO header, detail, customers, shipping locations, warehouse and approval/cancellation history. Identify immutable source PKs and composite company+SO identity.
- [ ] Document joins/cardinality, ready-for-delivery status, approval transitions, last modification source, hard deletes and whether detail/customer updates change the header timestamp.
- [ ] Choose tracking with evidence: existing Change Tracking if available and suitable; otherwise reliable change timestamp with keyset+overlap+periodic reconciliation. If neither is reliable, bounded/full ready-order scans with fingerprints and explicit throughput limits. rowversion alone is not a datetime or commit-order watermark.
- [ ] Obtain consistent header/detail reads using an existing supported isolation mechanism or vendor-approved stable export/view; do not use NOLOCK. Do not enable snapshot/CT/CDC or create views/triggers/indexes without DBA-authorized change.
- [ ] Define initial cutover boundary and approved backfill range; no automatic export of all historical SOs.
- [ ] Record unknowns as TBD and owners: user/ERP team for schema and rules, DBA for access/isolation, eVRP owner for masters and contract questions.
- [x] Add lazy SQL Server connector, credential separation, read-only statement guard and source-contract template.

### Test Stage / Test Procedure

Planned test files: tests/test_sqlserver_config.py; tests/sqlserver/test_access_and_schema.py.
Run command after implementation: `python3 -m unittest discover -s tests -v; SQLSERVER_TEST_DSN=<disposable-test-dsn> python3 -m unittest discover -s tests/sqlserver -v`.
Pass criteria: Read-only connectivity and anonymized schema sample match ERP. Bad credentials/certificate/timeouts produce redacted errors. SQL-dependent tests must report skipped separately from passed.
Manual Test: DBA/user verifies SELECT permissions and sample SO keys/statuses against ERP screens; inspect execution plans and measured query duration on approved data.
Verification Queries / Data Verification: Approved read-only sys.columns/sys.types/sys.indexes queries and scoped SELECT TOP samples; record actual table/PK/status fields in source contract, not invented SQL.
Do not execute proposed queries until the schema exists; SQL integration suites must fail clearly on unsupported setup and report absent setup as skipped.

## Acceptance Criteria

- All implementation tasks above have evidence, not just source files.
- A proven source contract and compatible connection, not successful eVRP delivery.
- Automated tests, manual flow, state checks and failure handling pass.
- User Confirmation recorded before VERIFIED.
- Blocker rule: Real SQL Server/schema-dependent execution waits for config and approved metadata. Mock scaffolding can proceed but cannot close this phase.

## Public Contracts

Follow umbrella API/data/state/config contracts. Existing endpoints retain behavior unless a documented versioned migration is approved.
No actual SQL table names, accounting write APIs or remote cancellation APIs are assumed.

## Touchpoints

Planned files: docs/erp-source-contract.md, config/sqlserver.example.json (future), requirements.txt (future pinned dependency).
Source documents are read-only references. Persistent report: ../reports/phase-01.md.

## Blast Radius

Local code, tests, config templates and local migrations during implementation. SQL source is SELECT-only;
real VRP imports, external callbacks and production deployment happen only in their explicitly scoped release gates.
Dry-run cannot advance production checkpoints or trigger live sending.

## Verification Evidence

Not executed: this is a plan. Baseline foundation previously passed 15 tests; that is not evidence for this phase.
Store exact commands/results, fixture sizes, query outputs (redacted), observed errors, manual checks and user confirmation in ../reports/phase-01.md.
What green proves: A proven source contract and compatible connection, not successful eVRP delivery.

## Resume and Execution Handoff

Read umbrella, this phase and dependency reports; inspect worktree and migrations before resuming.
Resume first unchecked task, keep legacy submission history, and never rerun a live import just to reproduce proof.
Next Step (Cursor Plan / RIPER-5): RESEARCH this phase when its dependencies are evidenced, then EXECUTE on implementation instruction, VERIFY and REVIEW.
