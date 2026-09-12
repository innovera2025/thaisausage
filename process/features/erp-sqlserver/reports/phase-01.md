# Phase 01 verification report

Status: 🧪 TESTING — connector foundation implemented; live SQL discovery blocked by missing driver/setup.
Plan: [Phase 01](../active/PHASE_01_DISCOVERY_PLAN_12-09-26.md).

## Evidence to record

- Source/config decisions and unresolved dependencies
- Commit/files changed and migration version
- Exact automated test commands, passed/failed/skipped counts
- Manual Test and redacted Data Verification outputs
- Fault/recovery checks and fixes
- What green proves and what remains unverified
- User Confirmation and release scope

No execution or live evidence has been recorded for this phase.

## Current evidence — 12-09-26

- Added `thaisausage/sqlserver.py`: lazy `pyodbc` connector, separate SQL credentials,
  credential-safe ODBC string builder, HTTPS/TLS config contract and SELECT-only statement guard.
- Added `docs/erp-source-contract.md`, `requirements.txt` and SQL config fields.
- Automated command: `python3 -m unittest discover -s tests -v` → **23 passed**.
- Tests cover credential separation/escaping, integrated auth config, identifier allowlist and mutation rejection.
- Real SQL connection was not attempted: `pyodbc` and ODBC tooling are absent in this environment.
- No ERP query, INSERT, UPDATE, DELETE, DDL, status change or eVRP request was made.

## Blocker and next evidence

Install the approved `pyodbc` version and Microsoft ODBC Driver 18 on the deployment/test host,
then provide a disposable/read-only connection target and an explicitly approved SO scope.
Run only the metadata check first; run SO SELECT mapping only after the scope is recorded.
