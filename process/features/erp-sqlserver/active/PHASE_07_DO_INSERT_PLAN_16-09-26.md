# Phase 07: ERP DO Insert Contract and Controlled Rollout Plan

Date: 16-09-26  
Complexity: Complex — database write, transaction and UAT gate  
Status: 🔨 CODE DONE (writer ปิดอยู่) + 🚧 BLOCKED — โครงสร้าง writer และ test เสร็จ 16-09-26
แต่ mapping จริง, การทดสอบกับ SQL Server และการเปิดใช้งานยังรอ ERP DBA และ sign-off  
Report: [phase-07](../reports/phase-07.md) · Mapping: `docs/do-insert-contract.md`  
Feature: ERP SQL Server integration  
Dependencies: Phase 01 SQL discovery, approved DO schema/mapping, ERP owner approval and eVRP/ERP UAT window
Repository context: `process/context/all-context.md` and `process/context/tests/all-tests.md` are not present; use the existing phase reports, code and unittest conventions.

## Overview

จัดทำแผนรองรับการรับ DO จาก thaisausage แล้ว Insert เข้า ERP SQL Server ตามสัญญา
`tbl_DOhdr` และ `tbl_Dodtl` ที่ได้รับ โดยเริ่มจาก staging และ mock ก่อนเสมอ
ระบบจะยังไม่เขียน ERP จริงในช่วงแผนนี้จนกว่าจะผ่าน read-only discovery, mapping review,
transaction test, duplicate test, UAT และผู้มีอำนาจอนุมัติเป็นลายลักษณ์อักษร

Quick Links: [Goals](#goals-and-success-metrics) · [Execution Brief](#execution-brief) · [Public Contracts](#public-contracts) · [Verification Evidence](#verification-evidence) · [Resume](#resume-and-execution-handoff)

## Phase Completion Rules

Phase จะไม่ถือว่าเสร็จจนกว่าจะผ่าน Integration Test, Manual Test, Data Verification,
Error Handling และ User Confirmation

- ⏳ PLANNED — ยังไม่เริ่ม
- 🔨 CODE DONE — เขียนโค้ดแล้ว แต่ยังไม่พิสูจน์ end-to-end
- 🧪 TESTING — อยู่ระหว่างทดสอบ
- ✅ VERIFIED — ทดสอบครบและผู้ใช้ยืนยันผล
- 🚧 BLOCKED — มีเงื่อนไขขวางการทำงาน

ห้ามใช้ ✅ VERIFIED จากการที่ build ผ่านหรือ mock test ผ่านเพียงอย่างเดียว

## Goals and Success Metrics

- รับ DO จาก endpoint staging และตรวจสอบก่อนเขียน ERP
- map Header ไป `tbl_DOhdr` และ Detail ไป `tbl_Dodtl` อย่างถูกต้อง
- ใช้ `TransactionNo` เดียวกันเชื่อม Header/Detail
- กำหนด `IsAcc=0`, `IsAccBy=NULL`, `IsAccDate=NULL`, `DocuNw=NULL` ตาม contract
- Insert สำเร็จทั้งหมดหรือ rollback ทั้ง transaction
- DO เดิม replay ได้โดยไม่สร้างข้อมูลซ้ำ
- ข้อมูลไม่ครบ/ผิดชนิด/foreign key ไม่ผ่านต้องหยุดก่อนเขียน
- มี audit correlation ID โดยไม่ log ข้อมูลลูกค้าเต็มหรือ secrets
- Production write เปิดได้เฉพาะหลัง sign-off จาก ERP และ Thai Sausage

## Non-goals and constraints

- ไม่เปิด ERP INSERT ในรอบ staging, dry-run หรือ mock
- ไม่แก้ไข/ลบ/ปิด/อนุมัติ SO หรือ DO เดิมเพื่อทดสอบ
- ไม่เดาชนิดข้อมูล ความยาว หรือ business rule ที่ยังไม่ยืนยันจาก ERP DBA
- ไม่ใช้ SQL text จาก HTTP request; SQL ต้องเป็น reviewed statement หรือ stored procedure ที่อนุมัติ
- ไม่ส่ง DO จริงเข้า ERP จนกว่าจะมี write credential แยกจาก read-only SQL credential
- ไม่เพิ่ม ERP write-back status หากยังไม่มี callback/ack contract
- หากมี duplicate หรือ transaction ambiguity ต้องเข้า review ไม่ retry แบบ blind

## Source SQL contract received

Header target: `tbl_DOhdr`  
Detail target: `tbl_Dodtl`

Fixed values:

| Field | Value |
|---|---|
| `IsAcc` | 0 |
| `IsAccBy` | NULL |
| `IsAccDate` | NULL |
| `DocuNw` | NULL |
| `EntryDate` | SQL Server `GETDATE()` or agreed server timestamp |

The received SQL uses placeholders such as `?xTransNum` and `?cRun`; these are source-template
names, not directly executable parameter names. Implementation must replace them with parameterized
SQL/procedure arguments after the ERP DBA confirms SQL Server types and constraints.

## Execution Brief

### Phase 1 — Contract discovery and safety review (🚧 BLOCKED)

ตรวจโค้ดและ contract ปัจจุบันแล้วเมื่อ 16-09-26; ไม่มีการเชื่อมต่อหรือเขียน ERP
รายการข้อมูลที่ยังขาด (schema, SQL ต้นฉบับ, กฎเลขที่เอกสาร, แหล่ง payload, กติกาธุรกิจรายฟิลด์,
write credential/test database, กติกาความซ้ำ) บันทึกไว้ใน [รายงาน phase-07](../reports/phase-07.md)

What happens: confirm every column type, nullable rule, length, default, identity/trigger,
foreign key and unique key for both tables. Confirm whether one transaction may insert both tables.

Integration points: ERP DBA, SQL Server metadata, DO staging payload and source DO/SO references.

Test: run metadata-only queries; inspect approved mock DO; do not query or mutate business rows unless
the user explicitly approves a specific read-only sample.

Verify: capture redacted schema evidence, primary/unique keys, trigger list, transaction isolation
requirements and the exact rule for generating `TransactionNo`/running `DoNo`.

Done when: ERP DBA signs the column mapping and write boundary.

### Phase 2 — Mapping and validation design (🚧 BLOCKED)

สร้างแบบฟอร์ม mapping matrix ครบทั้ง 45 ฟิลด์ Header และ 24 ฟิลด์ Detail ไว้ใน
`docs/do-insert-contract.md` พร้อมรูปแบบ config ที่ระบบรองรับแล้ว ช่องชนิดข้อมูล/nullable/
constraint เว้นไว้ให้ DBA เติม ระบบไม่เดาค่าเหล่านี้

What happens: define JSON-to-header/detail mapping, type conversion, required fields,
date/timezone rules, numeric precision, null handling and fixed accounting fields.

Integration points: `POST /api/v1/erp/do-received`, staging database and ERP write adapter.

Test: mock valid DOs for one/multiple details, free/zero values if allowed, Thai text, decimal
weights, missing optional values, duplicate DO and changed replay payload.

Verify: compare generated parameter object to the approved mapping table; no SQL is executed.

Done when: all fields are classified as required, optional, derived, fixed or rejected.

### Phase 3 — Safe writer implementation (🔨 CODE DONE)

`thaisausage/do_writer.py` และ `IntegrationService.write_do` เสร็จแล้ว ปิดด้วย flag เป็นค่าเริ่มต้น
ทดสอบด้วย fake driver 31 เคส (parameter binding, transaction, rollback, duplicate, dry-run, flag off)
ยังไม่เคยเชื่อมต่อหรือเขียน SQL Server จริง

What happens: add an explicit DO writer behind a feature flag and separate write credential.
Use parameter binding, one transaction, duplicate pre-check and post-insert verification.

Integration points: staging record → writer → ERP SQL Server → audit result.

Test: SQL fixture/mock verifies exact parameters, transaction begin/commit/rollback, no string
concatenation, no writes when validation fails and no second insert on replay.

Verify: query only the test transaction/DO identity after an approved test write; verify Header count,
Detail count and shared `TransactionNo`.

Done when: writer is covered by tests and remains disabled by default.

### Phase 4 — Controlled ERP UAT and rollout (⏳ PLANNED)

What happens: use an ERP-approved test database or one explicitly approved DO record. Run one
small batch, reconcile, then test duplicate and failure recovery before any expansion.

Integration points: ERP screen/database, Thai Sausage API, operator runbook and business owner.

Test: valid insert, invalid FK, timeout after commit, rollback, duplicate replay and operator pause.

Verify: source DO count = inserted Header count = expected Detail relationship; accounting fields
match approved values; no unrelated ERP rows changed.

Done when: ERP owner, Thai Sausage IT and business/data owner sign off. eVRP status is separate and
must not be inferred from ERP insert success.

Expected outcome:

- Safe, versioned DO Insert Contract
- Mock/staging tests and read-only discovery evidence
- Disabled-by-default ERP writer
- Transactional Header/Detail insert with duplicate protection
- Rollback and reconciliation runbook
- Explicit production approval gate

## Public Contracts

### Existing inbound staging API

`POST /api/v1/erp/do-received` remains staging-only until a new write feature is approved.
It must continue returning `erp_write=false` in staging mode.

### Proposed internal writer contract

Not public until approved. Proposed internal input:

| Input | Rule |
|---|---|
| `receipt_id` | stable unique identity; same payload replay is safe |
| `do_no` | ERP DO identity; required for production write |
| `transaction_no` | generated/validated by agreed ERP rule |
| `header` | approved `tbl_DOhdr` field mapping |
| `details[]` | one or more approved `tbl_Dodtl` mappings |

The writer response must distinguish `inserted`, `duplicate`, `rejected` and `needs_review`.
A timeout after the database may have committed is `needs_review`, not an automatic retry.

## Proposed mapping checklist

### Header: tbl_DOhdr

- [ ] `TransactionNo` generation and maximum length
- [ ] `DoNo`, `Dodate`, `DeliveryDate`, `DoType`
- [ ] approval/check/close/complete/accounting flags and nullable actor/date fields
- [ ] customer and address fields: `CustCode`, `CustName`, `BillingAddress`, `ShippingAddress`, `DlvCode`
- [ ] logistics: `CarNumber`, `LocationCode`, `LocationName`, `Driver`, `RemarkCode`
- [ ] sales/company fields and `EntryBy`/server `EntryDate`
- [ ] amount, discount, advance, VAT and actual total precision/rounding
- [ ] fixed `IsAcc=0`, `IsAccBy=NULL`, `IsAccDate=NULL`, `DocuNw=NULL`

### Detail: tbl_Dodtl

- [ ] shared `TransactionNo` and unique/sequential `Slno`
- [ ] item/customer/SO/PO references
- [ ] due date, quantity, net weight, total net weight
- [ ] sale price, unit, VAT, warehouse
- [ ] discount percentage/amount and line amount
- [ ] detail count and all numeric precision/scale

## Security and transaction decisions

1. Use a separate least-privilege write account; do not reuse ERP read-only account.
2. Restrict the writer to the two approved tables/procedure and test database first.
3. Use parameterized SQL; never interpolate DO values into SQL.
4. Use a transaction covering Header and all Details.
5. On any validation, FK, constraint or connection error before commit: rollback and mark rejected/review.
6. On ambiguous timeout after commit: query by stable transaction/DO identity before deciding.
7. Redact SQL credentials, addresses, phone numbers, amounts and full payloads from logs.
8. Keep staging payload and write audit retention according to the data owner’s policy.

## Acceptance Criteria

- [ ] No writer is reachable while feature flag is disabled.
- [ ] Existing staging endpoint still has no ERP side effect.
- [ ] All mandatory columns and fixed values are validated before SQL execution.
- [ ] Header and Detail use the same `TransactionNo`.
- [ ] Parameter binding is proven by a SQL mock/driver inspection.
- [ ] One failure rolls back all inserts.
- [ ] Same `receipt_id` + same payload is idempotent.
- [ ] Same identity + changed payload returns conflict/review.
- [ ] Duplicate DO/TransactionNo is handled without an uncontrolled retry.
- [ ] Read-only and controlled-write UAT show no unrelated row changes.
- [ ] ERP and Thai Sausage owners sign off before production enablement.

## Implementation Checklist

- [ ] Obtain DBA schema metadata and constraints for both tables.
- [ ] Confirm approved test database/DO scope and write credential owner.
- [ ] Create a field mapping matrix with source, target, type, nullable and transform.
- [ ] Define TransactionNo/DoNo/Slno uniqueness and concurrency rule.
- [ ] Define feature flag and safe default off.
- [ ] Implement JSON/domain validation before SQL connection.
- [ ] Implement type normalization, decimal rounding and timezone conversion.
- [ ] Implement parameterized Header/Detail writer with one transaction.
- [ ] Implement duplicate lookup and payload hash/reconciliation state.
- [ ] Add redacted reason/audit logging and operator status.
- [ ] Add unit tests for mapping, nulls, Decimal/date, duplicate and invalid input.
- [ ] Add SQL-driver fixture tests for parameters, commit and rollback.
- [ ] Add integration test against approved non-production SQL database.
- [ ] Run mock/staging tests; prove no ERP writes in dry-run.
- [ ] Run controlled UAT with one approved DO and reconcile database counts.
- [ ] Obtain written sign-off, then enable production flag in a scheduled window.
- [ ] Add pause/recovery procedure and monitor first business cycle.

## Test Stage

Test files to add/update:

- `tests/test_do_writer.py` — mapping, validation, fixed values, duplicate and error states
- `tests/test_sqlserver_do.py` — parameter binding, transaction commit/rollback and type conversion
- `tests/test_integration.py` — staging remains `erp_write=false`

Run command:

`python3 -m unittest discover -s tests -v`

Pass criteria: all tests green; SQL writer tests prove no execution on invalid input and rollback
on simulated failure; staging tests prove no ERP mutation. Real SQL UAT is a separate gate and must
record approved DO identity and before/after counts.
Post-phase testing: after each phase, run the relevant automated tests, manual test, state/database
verification and error-handling check before moving to the next phase.

## Touchpoints

Planned code: `thaisausage/service.py`, `thaisausage/sqlserver.py`, a dedicated DO writer module,
`thaisausage/api.py`, `config/example.json`, `tests/`, OpenAPI and operations documentation.

Planned data: staging SQLite schema may gain writer state/audit fields; ERP target tables are
`tbl_DOhdr` and `tbl_Dodtl`. No migration or ERP write is authorized by this plan alone.

## Blast Radius

Potentially affected: DO staging, SQL Server permissions, ERP Header/Detail rows, operator monitoring
and recovery procedures. SO extraction and eVRP submission must remain unchanged. Before production
write, validate that the writer cannot touch other tables and that feature-off behavior is identical
to the current staging behavior.

## Verification Evidence

This artifact is a plan; status is ⏳ PLANNED. No ERP INSERT has been executed by this plan.

Required evidence before ✅ VERIFIED:

- schema metadata and DBA approval (redacted)
- mapping matrix and sample payloads
- automated test output
- SQL fixture transaction trace
- staging no-write proof
- approved UAT DO identity and before/after row counts
- duplicate/rollback/timeout reconciliation result
- user confirmation and sign-off record

What green proves: the approved DO scope can be inserted transactionally and reconciled without
uncontrolled duplicates or unrelated ERP changes. It does not prove all ERP DO variants are supported.

## Resume and Execution Handoff

On resume, first re-check the working tree and this plan. Do not implement before Phase 1
schema/constraint discovery is accepted. Execute one phase at a time and stop at each gate.
Never use the production read-only SQL credential for writes. Keep `dry_run=true` and the writer
feature disabled until written approval.

Next instruction for Cursor/RIPER-5: RESEARCH Phase 1 only, present schema/mapping findings,
then pause for approval before EXECUTE. After each phase, record the report and request user
confirmation before proceeding.

## Cursor + RIPER-5 Guidance

Cursor Plan mode should import only the current phase checklist after DBA inputs are attached.
RIPER-5 sequence: RESEARCH → INNOVATE/resolve mapping ambiguities → PLAN approval → EXECUTE one phase
→ REVIEW with automated/manual/database/error evidence. Do not bundle research and ERP writes.
