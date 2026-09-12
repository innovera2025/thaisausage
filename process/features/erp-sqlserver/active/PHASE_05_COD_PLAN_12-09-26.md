# Phase 05: COD callback receiver and accounting handoff

Date: 12-09-26
Complexity: Complex — one phase of ERP SQL Server program
Status: ⏳ PLANNED

## Overview

Objective: COD callback receiver and accounting handoff.
Dependencies: 03 durable storage; source SO identity mapping from 01/02; VRP callback agreement.
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

- [ ] Plan POST /api/v1/cod/payment-received for VRP data[]; validate all required fields, dates/times, decimal amount and payment_status=accounting_payment_sent before batch commit.
- [ ] Current guide sends NO authentication header. Agree gateway IP allowlist/mTLS or vendor-supported signature/auth separately; do not silently require internal API Bearer and break callbacks.
- [ ] Keep callback disabled/external route unexposed until ingress authenticity is agreed. Do not treat an unguessable path as sufficient authentication.
- [ ] Store inbox events durably and ack HTTP 2xx + success=true only after the agreed receiver responsibility is met. Default responsibility is durable receipt, not accounting posting; confirm this interpretation with VRP.
- [ ] Atomic malformed-batch rejection with success=false; identical valid duplicate returns success with no duplicate side effect. Storage failure returns 5xx/success=false.
- [ ] No provider event_id exists in documented contract. Agree a business identity; provisional fingerprint excludes payment_send_api because retries may alter send time. Ambiguous same-payment/correction cases enter review rather than being silently discarded.
- [ ] do_no may contain combined DO references; preserve raw value and do not split on guessed delimiters. Handle partial payments, repeated amounts, overpayment, unknown SO and multi-company collisions through explicit reconciliation rules.
- [ ] Proposed identity dimensions: source/company, so_no, raw do_no, status, payment_date/time, amount; this is a proposal, not a guarantee of uniqueness. Record all deliveries and linking decisions.
- [ ] COD inbox has received/unmatched/review/ready_for_export/exported states. Provide an audited export/report for accounting; no direct writes into ERP accounting tables.
- [ ] Optional future automatic ERP posting requires vendor-supported API/stored procedure and a separate approved write credential plus posting idempotency/reversal contract. Remains deferred with SELECT-only access.

### Test Stage / Test Procedure

Planned test files: tests/test_cod.py, tests/test_cod_reconciliation.py.
Run command after implementation: `python3 -m unittest discover -s tests -v`.
Pass criteria: Single/batch/duplicate callbacks, altered send timestamp, same amount twice, combined DO text, unknown SO, correction, invalid ingress, DB failure and crash-before-ack; prove zero ERP writes.
Manual Test: Use mock VRP/Postman against protected test receiver; retry the same event and inspect one business effect with multiple recorded deliveries; reconcile totals with accounting.
Verification Queries / Data Verification: SELECT state,COUNT(*) FROM cod_events GROUP BY state; SELECT event_id,COUNT(*) FROM cod_deliveries GROUP BY event_id; SELECT * FROM cod_reconciliations; amount comparisons use Decimal.
Do not execute proposed queries until the schema exists; SQL integration suites must fail clearly on unsupported setup and report absent setup as skipped.

## Acceptance Criteria

- All implementation tasks above have evidence, not just source files.
- Durable authenticated receipt/reconciliation and accounting handoff, not funds settlement or automatic ERP posting.
- Automated tests, manual flow, state checks and failure handling pass.
- User Confirmation recorded before VERIFIED.
- Blocker rule: Ingress authenticity, event identity and ack responsibility require vendor confirmation. Direct accounting write is out of current read-only scope.

## Public Contracts

Follow umbrella API/data/state/config contracts. Existing endpoints retain behavior unless a documented versioned migration is approved.
No actual SQL table names, accounting write APIs or remote cancellation APIs are assumed.

## Touchpoints

Planned files: thaisausage/cod.py, thaisausage/api.py, migrations/*_cod.sql, docs/cod-contract.md, tests/test_cod.py.
Source documents are read-only references. Persistent report: ../reports/phase-05.md.

## Blast Radius

Local code, tests, config templates and local migrations during implementation. SQL source is SELECT-only;
real VRP imports, external callbacks and production deployment happen only in their explicitly scoped release gates.
Dry-run cannot advance production checkpoints or trigger live sending.

## Verification Evidence

Not executed: this is a plan. Baseline foundation previously passed 15 tests; that is not evidence for this phase.
Store exact commands/results, fixture sizes, query outputs (redacted), observed errors, manual checks and user confirmation in ../reports/phase-05.md.
What green proves: Durable authenticated receipt/reconciliation and accounting handoff, not funds settlement or automatic ERP posting.

## Resume and Execution Handoff

Read umbrella, this phase and dependency reports; inspect worktree and migrations before resuming.
Resume first unchecked task, keep legacy submission history, and never rerun a live import just to reproduce proof.
Next Step (Cursor Plan / RIPER-5): RESEARCH this phase when its dependencies are evidenced, then EXECUTE on implementation instruction, VERIFY and REVIEW.

