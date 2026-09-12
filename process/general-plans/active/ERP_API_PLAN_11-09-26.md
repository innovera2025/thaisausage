# Thaisausage ERP API Integration Plan

> Routing update 12-09-26: เก็บแผนนี้เป็น baseline foundation. งานต่อไปใช้
> [SQL Server master plan](../../features/erp-sqlserver/active/ERP_SQLSERVER_PLAN_12-09-26.md)
> พร้อม phase plans 01–06; ขอบเขต SQL/scheduler/COD ที่เคยอยู่นอก scope ถูกวางแผนใหม่แล้ว แต่ยังไม่ได้ implement.

Date: 11-09-26
Complexity: Simple — executable integration foundation; vendor-specific rollout is future scope
Status: 🔨 CODE DONE — 15 automated tests passed; user confirmation and live configuration pending

## Overview

สร้าง API กลาง thaisausage สำหรับส่ง SO จาก ERP ไป eVRP ทั้ง push และ REST pull
ผู้ใช้จะใส่ config ภายหลัง จึงใช้ REST adapter ที่ map ฟิลด์ได้และ dry-run เป็นค่าเริ่มต้น
ขอบเขตครั้งนี้คือโครงที่รันและทดสอบได้ ไม่ใช่การเปิด production หรือเขียนข้อมูลบัญชีจริง
ผู้ใช้อนุญาตให้สร้างโครงและเริ่มแผนแล้ว จึงดำเนินการภายในขอบเขตนี้ต่อเนื่อง

Quick Links: [Execution Brief](#execution-brief) · [Public Contracts](#public-contracts) · [Verification Evidence](#verification-evidence)

## Goals and Success Metrics

- รัน API ได้ด้วย Python standard library และ config ตัวอย่าง
- ERP ส่งข้อมูลเข้าได้ และ REST adapter เปลี่ยน field mapping ได้โดยไม่แก้ service
- dry-run ไม่เรียก VRP; live requests มีสถานะถาวรและกันส่งซ้ำข้าม restart
- มี automated tests สำหรับ HTTP/auth, mapping, validation, concurrent submissions และ ambiguous outcomes

## Phase Completion Rules

Phase ต้องผ่าน Integration Test, Manual Test, Data Verification, Error Handling และ User Confirmation
จึงใช้ ✅ VERIFIED ได้; 🔨 CODE DONE = เขียนแล้ว, 🧪 TESTING = อยู่ระหว่างพิสูจน์,
⏳ PLANNED = ยังไม่ทำ, 🚧 BLOCKED = มีเหตุขัดขวาง
ผลทดสอบจำลองไม่ใช่หลักฐานว่าเชื่อม ERP/eVRP จริงสำเร็จ
บันทึกสิ่งที่ทดสอบ, สถานะฐานข้อมูล, ข้อผิดพลาดและคำยืนยันผู้ใช้หลังจบ phase

## Execution Brief

### Phase 1 — Config, contracts and ERP adapter (🔨 CODE DONE)

What happens: สร้าง config ที่อ้างชื่อ secret ผ่าน environment, generic GET adapter, nested mapping และ validation
Test Procedure: รัน tests/test_integration.py สำหรับ nested mapping, header/query และค่าที่ไม่ถูกต้อง
Manual Test: ใส่ ERP config และเรียก pull ใน dry-run ตรวจ mapped_payload เทียบ SO ต้นทาง
Verification Queries: ตรวจ mapped_payload ว่ารหัส/จำนวน/ราคาและสินค้าฟรียังคงแยกบรรทัด
Done when: mapping ตรง ERP จริงและผู้ใช้ยืนยัน; ยังรอ config/vendor sample

### Phase 2 — API and durable submission guard (🧪 TESTING)

What happens: เพิ่ม push/pull/status API, internal auth และ SQLite transaction จอง request/order ก่อนส่ง
Test Procedure: HTTP integration test บน localhost ใช้ ERP/VRP จำลอง; duplicate/concurrency/restart/timeout tests
Manual Test: ตาม curl ใน README; dry-run ต้องคืน validated; token ผิดต้อง 401
Verification Queries: `SELECT request_id,state FROM submissions;` และ `SELECT order_no,request_id FROM order_claims;`
Dry-run ต้องไม่มีแถว; live mock ต้องมี sent หรือ needs_review ตามผลจำลอง
Done when: tests ผ่านและผู้ใช้ยืนยันผล local flow; ยังไม่เท่ากับ production-ready

### Phase 3 — Handoff and live readiness (⏳ PLANNED for live checks)

What happens: คู่มือ config, ตัวอย่าง SO, แผนและ verification evidence; live readiness รอ ERP config
Test Procedure: รัน test suite และ plan validator; ตรวจ CLI help และ curl local
Manual Test: ผู้ใช้เติม config จริง ตรวจ mapping/rหัสคลัง และเลือก staging หรือ SO ที่อนุญาตให้ส่ง
Verification Queries: เทียบ SO ที่ eVRP กับเลขต้นทางและสถานะ SQLite; ห้ามนับ 202 เป็นส่งสำเร็จ
Done when: ผู้ใช้ยืนยัน controlled live test โดยไม่มี SO ซ้ำและไม่มีผลต่างด้านจำนวน/ยอดเงิน

Expected Outcome: API โครงเริ่มต้นที่รันได้, config เติมภายหลัง, ERP REST adapter,
VRP sender, durable statuses, tests และเอกสารส่งมอบครบ

## Scope

In: Python 3.9+ standard library, SQLite, manual push/pull, nested REST field mapping,
local validation, bearer auth, safe outcome tracking, sample payload และคู่มือ
Out: frontend, SQL/direct ERP database access, OAuth refresh, scheduler, automatic pagination,
automatic retry, SO update/cancel, inventory sync, COD posting, production hosting

## Assumptions and Constraints

- thaisausage คือบริการกลาง และ eVRP คือปลายทาง ตาม package ที่ได้รับ
- ยังไม่ทราบ ERP vendor/version/schema/auth/pagination; generic REST เป็น adapter เริ่มต้น
- REST pull อ่านหนึ่งหน้า; `query` ต้องตรง ERP; ไม่มี watermark หรือ sync completion acknowledgement
- ไม่แปลงภาษี ส่วนลด หน่วยสินค้า หรือ numeric string โดยเดา
- process/context/all-context.md และ process/context/tests/all-tests.md ยังไม่มีใน workspace
- อ่าน README, Postman collection, ตัวอย่าง และคู่มือ PDF v1.1 ครบแล้วผ่าน macOS PDFKit
- คู่มือยืนยัน request_id 1..120 ตัว [A-Za-z0-9._:-], 500 orders/request, 2000 items/order และ body 10 MB
- Optional fields: customer.name, line_no; payment_in_day null = non-COD; รหัสจุดส่งหรือ shipping_address ใช้อย่างใดอย่างหนึ่งได้
- local batch/body limits ไม่ใช่ข้อสรุปว่าเป็น limit ของ eVRP

## Functional Requirements

- รับ request_id + orders ผ่าน API; validate ก่อน outbound
- รับ request_id + query เพื่อดึง ERP, map แล้วเข้า pipeline เดียวกัน
- POST ไป eVRP `/api/v1/orders/import` ด้วย X-Token
- ค่า payment_in_day=0 เป็น COD; unit_price=0 เก็บสินค้าฟรีแยกบรรทัด
- request_id เดิม payload เปลี่ยนต้อง 409; order_no เดิม request_id ใหม่ต้อง 409
- dry-run ไม่จอง id; unknown outcome ต้อง needs_review และไม่ส่งซ้ำอัตโนมัติ

## Non-Functional Requirements

Secret ผ่าน environment, connector ใช้ HTTPS และไม่ follow redirect, ไม่ log payload/token,
SQL parameter binding, transaction สำหรับจอง batch, request/body timeout/limit
Development HTTP server ยังต้องแทนที่หรือ harden ก่อนเปิด internet

## Acceptance Criteria

1. เริ่มระบบจาก config ตัวอย่างได้เมื่อใส่ internal API key
2. API ปฏิเสธ key ผิด; health ไม่ต้อง auth
3. JSON/จำนวน/ราคาไม่ถูกต้องไม่เรียก VRP
4. ERP nested fields map ได้ และตรวจ array shape ก่อนส่ง
5. dry-run ส่งข้อมูลกลับให้ตรวจแต่ไม่มี outbound VRP หรือ rows
6. request ซ้ำและ concurrent request ส่ง upstream ไม่เกินหนึ่งครั้งใน local guard
7. timeout/error/unconfirmed success คงสถานะให้ตรวจและไม่ auto retry
8. restart แล้วอ่านสถานะและกัน duplicate ได้
9. Automated suite ผ่าน; live ERP/eVRP acceptance แยกจาก mock evidence

## Implementation Checklist

- [x] Config example + environment references; dry-run defaults
- [x] Payload example with fictitious identifiers
- [x] Contracts and validation tests
- [x] REST adapter, nested mapping and mock connector tests
- [x] VRP connector with X-Token, HTTPS and timeout
- [x] SQLite request/order guards and restart/concurrency tests
- [x] API push/pull/status/auth and HTTP integration tests
- [x] README startup/config/manual checks
- [x] Run complete automated suite and record evidence (15 tests passed)
- [x] Validate saved plan artifact (strict: 0 failures, 0 warnings)
- [ ] User fills ERP config and confirms mapping
- [ ] Controlled live validation and User Confirmation

## Risks and Mitigations

- Timeout after remote commit: mark needs_review; reconcile against ERP/VRP, no automatic resend
- Crash after reservation: sending remains; inspect remotely before releasing any order claims
- ERP duplicate across pages: persistent order_no guard; pagination not automatic yet
- Vendor updates may allow SO upsert: current conservative guard blocks update; agree version semantics first
- Config cannot express custom joins/calculations: implement vendor-specific ERPConnector subclass with sample tests
- Response success must match guide: unknown shape gets needs_review rather than claiming success
- Full payload not persisted: ERP remains source for reconciliation/recovery; backup SQLite for guards

## Integration Notes

Local middleware auth differs from eVRP X-Token; ERP auth header/prefix configurable.
SQLite submissions(request_id PK, payload_hash, state, result, created_at),
order_claims(order_no PK, request_id). No COD state changes or ERP writes in foundation.

## Touchpoints

`thaisausage/{config,contracts,connectors,service,api,__main__}.py`, `config/example.json`,
`examples/erp-order.json`, `tests/test_integration.py`, README.md, .gitignore and this plan.
Original customer documents remain source references. Runtime data goes into ignored data/.

## Public Contracts

| Endpoint | Contract |
|---|---|
| GET /health | process status, dry_run |
| POST /api/v1/erp/orders | request_id + standard orders; 200 validated/sent, 202 sending/needs_review |
| POST /api/v1/erp/pull | request_id + optional scalar query; empty result = state empty |
| GET /api/v1/submissions/{request_id} | persisted live result or 404 |

401 unauthenticated; 409 duplicate conflict; 422 validation/config; 502 ERP upstream; 500 internal.
Live sender success predicate currently requires JSON success=true. Full upstream response is not exposed.
COD planned contract: VRP POST data[] with do_no/so_no/payment fields; receiver auth and accounting semantics must be agreed before implementation.

## Blast Radius

Foundation creates new local code and SQLite only. Tests use temp databases and mock upstreams.
Live mode POST changes eVRP orders; enable deliberately only after config and mapping checks.
ERP pull is GET only. No ERP accounting/payment mutation, no deploy, no production API calls during development.

## Verification Evidence

Test Stage: `tests/test_integration.py`; command `python3 -m unittest discover -s tests -v`.
Pass criteria: all assertions green for API/auth/mapping/validation/concurrency/restart/unknown outcome;
SQLite row checks executed in tests. Final suite: 15 tests passed in 0.745s; CLI help passed.
Includes PDF contract optional-field/id checks, atomic rollback and persisted VRP references.
HTTP tests exercise authenticated push, pull and status on localhost with mock ERP/VRP; no live remote requests made.
Plan validator: `node /Users/innovera/.claude/skills/vc-generate-plan/scripts/validate-plan-artifact.mjs process/general-plans/active/ERP_API_PLAN_11-09-26.md --strict`.
Manual/live evidence and User Confirmation: pending.

## Resume and Execution Handoff

Read this plan then README.md, config/example.json and customer API documents.
Current execution anchor is this single plan; no separate phase files.
Resume by checking verification evidence, run remaining gates, then use supplied ERP config/sample
to adapt mapping. Do not infer ERP field names, pagination, token refresh or accounting rules.
To handle needs_review/sending, reconcile remote state before proposing an explicit recovery operation.

## Cursor + RIPER-5 Guidance

User already requested foundation implementation: RESEARCH → PLAN → EXECUTE → REVIEW within that scope.
Cursor Plan: use the Implementation Checklist and preserve completed evidence.
Next Step: finish local verification, then use ERP config to run dry-run mapping; live integration and
COD/accounting expansion require vendor contract and concrete acceptance data.
