# Thaisausage SQL Server ERP Integration — Master Plan

Date: 12-09-26
Complexity: Complex — phase program with six separately verified phases
Status: 🧪 TESTING — Phase 01 connector foundation implemented; real SQL discovery awaits driver and approved SO scope

## Overview

แผนหลักสำหรับ SQL Server → ตัวเชื่อมต่อ → JSON → API กลาง thaisausage → eVRP
พร้อมกำหนดงานรับ COD callback และส่งต่อข้อมูลให้บัญชี แผนนี้แทนแนวทาง REST-first ของ
[แผนเดิม](../../../general-plans/active/ERP_API_PLAN_11-09-26.md) สำหรับงานต่อจากนี้
เก็บแผนเดิมเป็นหลักฐาน foundation ไม่ถือว่างาน SQL Server ทำแล้ว

ผู้ใช้ยืนยันว่าปัจจุบันเข้าถึง ERP ได้ผ่าน SQL Server และจะใส่ config ภายหลัง
คำขอรอบนี้คือจัดทำแผนทั้งหมด จึงไม่มีการเพิ่ม connector/ตารางจริง/ตั้ง schedule/ส่ง SO จริง
นโยบายทดสอบบังคับ: ห้าม INSERT/UPDATE/DELETE หรือเปลี่ยนสถานะข้อมูลจริงใน ERP และห้ามส่งข้อมูลจริงไป eVRP;
อนุญาตเฉพาะ SELECT เพื่อดึง SO ที่ผู้ใช้ระบุและอนุมัติไว้สำหรับตรวจ mapping/JSON เท่านั้น
ใช้ skill vc:generate-plan จัดแผนหลักและแผนราย phase พร้อมจุดเก็บผลทดสอบ
local complex PRD template, phase-program protocol และ process/context/all-context.md ไม่มีใน workspace;
ใช้ข้อกำหนด skill ที่อ่านแล้ว, current code และเอกสารผู้ให้บริการเป็นฐาน

Quick Links: [Phases](#phased-delivery-plan) · [Config](#configuration-contract) · [Mapping](#data-mapping-contract) · [API](#public-contracts) · [Handoff](#resume-and-execution-handoff)

## Current State and Gap Analysis

| รายการ | สถานะจริง |
|---|---|
| Python API รับ JSON / REST pull / status / auth | มีโค้ดแล้ว |
| ERP webhook trigger / durable hook inbox | เพิ่มแล้ว; ยังไม่มี SQL sweep worker |
| Validation ตาม eVRP v1.1 | มีโค้ดแล้ว; ไม่ตรวจ master ฝั่ง eVRP |
| SQLite submissions/order_claims | มีแล้ว; ยังไม่เก็บ immutable payload/retry attempts |
| dry-run และ duplicate guard | มีแล้ว |
| Automated baseline | เคยผ่าน 15 tests เมื่อ 11-09-26; รอบนี้ไม่ rerun เพราะแก้เอกสาร |
| SQL Server connector / schema mapping | ยังไม่มี |
| Incremental sync / scheduler / backfill / reconciliation | ยังไม่มี |
| Durable outbox / operator replay / migration | ยังไม่มี |
| COD receiver / reconciliation | ยังไม่มี |
| Production server / deployment / live acceptance | ยังไม่มี |
| ERP config, vendor/version, source schema | รอข้อมูลจริง |

## Goals and Non-Goals

เป้าหมายคือส่ง SO ที่อนุมัติและพร้อมจัดส่งอย่างครบถ้วน ตรวจย้อนกลับได้ และกู้ต่อหลังระบบขัดข้องได้
ไม่จำเป็นต้อง real-time แบบ event; เริ่ม polling ทุก 60 วินาที ปรับตามปริมาณงานและภาระ SQL
สรุปความสำเร็จเป็น SO sent/rejected/review แยกจากจำนวนแถวที่อ่าน ไม่ใช้ HTTP 202 เป็นหลักฐานส่งสำเร็จ

Must: SQL read-only connector, mapping, durable extraction/outbox, duplicate protection, scheduled pull,
dry-run, error/recovery handling, operator visibility, UAT and runbook.
Should: bounded backfill, periodic reconciliation, metrics/alerts, protected COD inbox and accounting export.
Deferred: ERP accounting writes, SO update/cancel, inventory sync, frontend, automatic master creation,
HA/multi-host scaling, CT/CDC/triggers enabling and any ERP schema alteration without a separate DBA decision.
COD phase is planned fully but SO go-live can be accepted independently.

## Phase Completion Rules

⏳ PLANNED = ยังไม่ทำ; 🔨 CODE DONE = มีโค้ด; 🧪 TESTING = อยู่ระหว่างพิสูจน์;
✅ VERIFIED ต้องครบ integration test, Manual Test, Data Verification, error handling และ User Confirmation.
โค้ดผ่าน mock ไม่แปลว่า SQL/eVRP จริงผ่าน; skipped SQL tests ต้องแสดงแยกจาก passed.
ทุก phase มี Test Procedure, Verification Queries, Done Criteria และ report ถาวร
ห้ามเริ่ม dependent live rollout จนกว่าหลักฐานของ dependency จะพร้อม

## Architecture Decisions

1. ใช้ service ภายนอกอ่าน SQL Server ด้วย SELECT-only credential; ไม่ให้ฐานข้อมูลเรียก HTTP ผ่าน trigger
และไม่เขียน exported/payment flags กลับ ERP
2. เริ่มติดตั้งตัวอ่านกับ API/worker บน internal host เดียวที่เข้าถึง SQL ได้ ลดปัญหา credential/network
ให้ source adapter เรียก shared ingestion service ภายใน process เพื่อไม่ต้องวน HTTP localhost;
JSON contract เดียวกับ POST API ใช้สำหรับ ERP push หรือแยก host ในอนาคต
3. Candidate reader → complete SO snapshot → mapping → outbox → worker → eVRP.
จุด commit extraction cursor อยู่หลัง persist outbox/quarantine; delivery progress แยกกัน
4. Existing REST adapter และ push API ยังคงอยู่; source.type เลือก SQL Server สำหรับงานนี้
5. Driver proposal: pyodbc + Microsoft ODBC Driver 18; pin versions/เลือก Python ที่ยังรองรับใน phase 01
หลังรู้ deployment OS/SQL auth จริง; ไม่อ้างว่าได้ติดตั้งแล้ว
6. SQLite ใช้สำหรับ single-host foundation; migrations ต้องรักษา submissions/order_claims.
Multi-host workers ต้องเปลี่ยน shared store/locking design ก่อนขยาย ไม่วาง SQLite บน network share โดยเดา
7. ไม่เดาว่า updated_at ของ header ครอบคลุม detail/customer; tracking strategy ต้องพิสูจน์จาก source schema
8. ทุก unknown delivery outcome ตรวจสอบก่อน resend; guide รองรับ replay id เดิม+payloadเดิม
แต่ยังต้องยืนยัน retention และทดสอบ operation ที่ข้าม duplicate short-circuit อย่างถูกต้อง

## Execution Brief

ลำดับ SO: 01 สำรวจ → 02 อ่านและ map → 03 queue/recovery → 04 schedule/ops → 06 UAT/release.
COD: 03 + mapping identity → 05 callback/reconcile → 06 COD release.
Test: แต่ละ phase มี unit, HTTP/SQL integration, crash/recovery และ manual proof ตามขอบเขต.
Verify: เทียบ source IDs/lines/amounts กับ local state และ remote identifiers.
Expected Outcome: config เติมได้, SO ส่งอัตโนมัติเป็นรอบ, operator ดู backlog/review ได้,
COD รับอย่างมีการยืนยันแหล่งที่มาและส่งต่อบัญชีได้ภายใน scope ที่ตกลง พร้อมเอกสาร recovery.

## Phased Delivery Plan

| Phase | Execution anchor | Dependency | Evidence |
|---|---|---|---|
| 01 | [SQL Server discovery and source contract](PHASE_01_DISCOVERY_PLAN_12-09-26.md) | Baseline | [report](../reports/phase-01.md) |
| 02 | [SQL reader and ERP-to-JSON mapping](PHASE_02_EXTRACTION_PLAN_12-09-26.md) | 01 | [report](../reports/phase-02.md) |
| 03 | [Durable queue, idempotency and delivery recovery](PHASE_03_DELIVERY_PLAN_12-09-26.md) | 02 | [report](../reports/phase-03.md) |
| 04 | [Scheduled synchronization and operational API](PHASE_04_SCHEDULER_PLAN_12-09-26.md) | 03 | [report](../reports/phase-04.md) |
| 05 | [COD callback receiver and accounting handoff](PHASE_05_COD_PLAN_12-09-26.md) | 03 + identity mapping | [report](../reports/phase-05.md) |
| 06 | [UAT, deployment, monitoring and handoff](PHASE_06_ROLLOUT_PLAN_12-09-26.md) | 01–04; 05 for COD | [report](../reports/phase-06.md) |

ทุก phase เป็น ⏳ PLANNED. ไม่กำหนดจำนวนวันโดยไม่ทราบ schema, ปริมาณงานและ environment.
RFC-001–006 ตรงกับ phase 01–06; ทำทีละ phase และบันทึกการเปลี่ยน contract ไว้ในรายงาน.

## Configuration Contract

ทั้งหมดต่อไปนี้เป็น planned keys; ยังไม่ได้เปลี่ยน config/example.json หรือ runtime parser.
ห้ามนำ config นี้ไปเปิด live ก่อน implementation และ preflight สำเร็จ

| Key | Proposed default / ผู้เติม |
|---|---|
| source.type / source.id | sqlserver / stable identifier ผู้ดูแลกำหนด |
| source.company_id / branch_scope | ผู้ใช้กำหนดบริษัท/สาขา ป้องกัน SO ชนกัน |
| sqlserver.driver | ODBC Driver 18 for SQL Server; ตรวจรุ่นจริง phase 01 |
| sqlserver.connection_string_env | `ERP_SQLSERVER_CONNECTION_STRING`; ค่าอยู่ใน `.env` local และไม่ commit |
| sqlserver.server / instance / port / database | ผู้ใช้/DBA; ไม่สมมติ port 1433 กับ named instance |
| sqlserver.auth_mode | sql หรือ integrated ตาม host/service account |
| sqlserver.username_env / password_env | `ERP_SQL_USER` / `ERP_SQL_PASSWORD` สำหรับ SQL auth; ไม่ใส่ UID/PWD ซ้ำใน connection string |
| sqlserver.encrypt / trust_server_certificate | true / false; ใช้ trusted certificate |
| sqlserver.connect_timeout_seconds / query_timeout_seconds | 10 / 30 (เสนอ; ปรับตามผล query) |
| sqlserver.query_set / approved_objects | ชื่อชุด query และ allowlist ที่ review แล้ว; ไม่รับ SQL ผ่าน API |
| mapping.version / field_map / master_mappings | กำหนดจาก source contract + ตัวอย่างที่ยืนยัน |
| sync.enabled / interval_seconds | false / 60 |
| sync.page_size / max_orders_per_run | 100 / 1000 เสนอ; วัด load ก่อนใช้ |
| sync.strategy | TBD จาก schema: change_tracking / timestamp / scoped_scan |
| sync.overlap_seconds / reconcile_interval_seconds | 300 / 3600 สำหรับกลยุทธ์ที่เหมาะ; ไม่รับประกัน arbitrary late commits |
| sync.initial_start / backfill_scope | ต้องกำหนดก่อนเปิด; ไม่ default ทั้งประวัติ |
| sync.business_timezone | Asia/Bangkok; ต้องยืนยัน source datetime semantics |
| sync.lease_seconds | 120 เสนอ; มี renewal/ownership checks |
| delivery.max_orders_per_request | 1 เริ่มต้น, เพิ่มได้หลังทดสอบ atomic failure |
| delivery.max_body_bytes | ไม่เกิน local 1 MiB ปัจจุบัน; ไม่เกิน upstream 10 MB |
| delivery.retry_policy / max_retries | classified-safe only / 5; unknown → review |
| api_key_env / vrp.token_env / dry_run | ใช้ existing keys; dry_run=true |
| cod.enabled / cod.ingress_policy | false / TBD รอ VRP contract |
| storage.path / backup / retention | ผู้ดูแลกำหนด; payload/COD มีข้อมูลส่วนบุคคล |
| alerts.destination / owner | ผู้ใช้ระบุช่องทางและผู้รับผิดชอบก่อน deploy |

No secrets in plan or connection logs. ไม่บังคับสร้าง ERP_TOKEN เมื่อ source.type=sqlserver.
Integrated auth ต้องพิสูจน์ใน service identity จริง ไม่ใช้ผลจาก interactive user แทน.

## Data Mapping Contract

ชื่อ source table/field ทุกตัวเป็น TBD; phase 01 บันทึกใน docs/erp-source-contract.md,
phase 02 บันทึก transformation/rounding/ตัวอย่างใน docs/field-mapping.md.

| JSON target | Source meaning | Rule |
|---|---|---|
| request_id | persisted delivery identity | 1..120 ตัว [A-Za-z0-9._:-]; freeze ต่อ payload |
| order_no | external SO identity | <=100; company collision strategy ต้องตกลงกับ VRP |
| order_date / delivery_date | วันที่ SO / ส่ง | YYYY-MM-DD; delivery optional/default order_date ตาม guide |
| payment_in_day | credit term | 0=COD; positive/null=non-COD; อย่าเปลี่ยน null เป็น 0 |
| customer.code / name | customer master | code required <=50, known to VRP; name optional |
| customer.billing_address_line1/2,district,province,country,postcode,phone | billing info | preserve Unicode; postcode/phone เป็น string |
| customer.sale_code,sale_name,google_maps | sales/map refs | optional; map ตามข้อมูลจริง |
| delivery_point_code / shipping_address | ship-to | code หรือ address ต้องระบุจุดส่งได้; route ฝั่ง VRP ต้องมี |
| pickup_hub_code / pickup_hub_name | warehouse mapping | code ต้อง map กับ VRP hub; name อ้างอิง |
| items[].line_no / item_code / description | SO detail | stable ordering; code<=50; description จำเป็นสำหรับสินค้าใหม่ |
| items[].quantity / unit_price | qty/price | qty>0, price>=0; Decimal; gift price=0 แยกบรรทัด |
| items[].cbm / nw | dimensions per unit | optional >=0; ยืนยันหน่วย |
| items[].main_unit / pack_unit | units | optional; conversion ที่ตกลงเท่านั้น |

ราคา/ส่วนลด/ภาษี/ค่าขนส่ง: ต้องตอบว่า unit_price รวมอะไร และ eVRP bill_amount ตรงยอดที่เก็บอย่างไร.
ไม่มี tax/discount field ใน contract ที่อ่าน จึงห้ามย้ายยอดไป field อื่นหรือหารเฉลี่ยโดยไม่มีข้อตกลง.
SO พร้อมส่งต้องมี header+lines ครบและสถานะอนุมัติที่ถูกต้อง;
SO เปลี่ยนหลังส่ง → amendment_required จนมี update/cancel contract.

## Extraction and State Contract

- Source cursor ของแต่ละ source/company เก็บแยก live, dry-run, backfill.
- Query keyset บน source keys; checkpoint แทนชุดข้อมูลที่ persist แล้ว ไม่ใช่ last poll wall clock.
- Enqueue/quarantine ทุก candidate ใน local transaction เดียวกับ cursor update; รายการผิดไม่ขวางทั้ง pipeline
แต่ต้องอยู่ใน review ledger พร้อมเหตุผล ไม่หายเงียบ.
- Consistent read ทั้ง header/detail/customer ตามกลยุทธ์ที่พิสูจน์. ใช้ read transaction สั้นและ bounded query;
NOLOCK ไม่ใช่วิธีแก้ throughput.
- Timestamp overlap + reconciliation เป็น mitigation ไม่ใช่หลักฐานว่าจับ hard deletes/long transactions ทุกกรณี.
ต้องมี source audit/change mechanism หรือ business no-delete/stable-ready contract ถ้าต้องการ coverage เต็ม.
- Outbox states (planned): queued → sending → sent; sending → retry_wait/rejected/needs_review;
changed sent order → amendment_required. Lease หมดอายุระหว่าง POST ต้องตรวจ outcome ไม่ย้อน queued โดยอัตโนมัติ.
- Current submissions API states remain compatible: validated, sent, sending, needs_review.
New outbox state surface อยู่ใน ops API; อย่าเปลี่ยน existing clients โดยเงียบ.
- Freeze bytes/hash ก่อนส่ง; batch error atomic. Corrected rejected payload สร้าง lineage ใหม่หลังตรวจ
และ release/replace claim อย่างมี audit เฉพาะกรณีที่มั่นใจว่ายังไม่ถูก import.

## Planned Local Data Model and Migrations

| Table | Minimum fields / invariant |
|---|---|
| schema_migrations | version, applied_at; backup before migration |
| submissions / order_claims | preserve legacy keys/results; do not discard dedupe history |
| source_checkpoints | source_id, company, stream, cursor_json, version, updated_at |
| sync_runs / sync_leases | run_id, counters, state; owner token, expiry, source identity |
| outbox | id, source identity/PK/revision, mapping_version, request_id, payload_bytes/hash, state, next_attempt_at |
| delivery_attempts | request_id+attempt_no unique, start/end, classified result, redacted remote refs |
| source_quarantine | source identity/revision, issue, observed_at, resolved_by |
| operator_actions | actor, reason, target, previous/new state, immutable timestamp |
| cod_events / cod_deliveries | business identity candidate, immutable raw event, duplicate/review decision; each receipt trace |
| cod_reconciliations | SO match, decimal amount, reconciliation status, export reference |

Persist payload requires access control, encrypted storage/backup and a documented retention period.
Unknown legacy payload cannot be reconstructed for automatic replay.
SQLite schema versioning/rollback compatible binary policy must precede worker deployment.

## Public Contracts

Existing APIs remain available, documented in README:
GET /health; POST /api/v1/erp/orders; POST /api/v1/erp/pull (REST only); GET /api/v1/submissions/{request_id}.
Authorization remains internal Bearer except /health. Do not repurpose REST pull silently.

Planned additions, not callable yet:

| Endpoint | Input / response |
|---|---|
| GET /ready | dependency readiness; internal use, redacted |
| POST /api/v1/sync/runs | configured source_id, dry_run; 202 run_id |
| GET /api/v1/sync/runs/{id} | extraction counts/state/errors |
| GET /api/v1/sync/status | cursors/queue lag/last success |
| POST /api/v1/sync/pause or /resume | operator identity+source_id; audit; no arbitrary query |
| POST /api/v1/sync/backfills | reviewed source/range/limit/dry_run; 202 run_id |
| GET /api/v1/outbox/{id} | redacted state/attempts/remote refs |
| POST /api/v1/outbox/{id}/replay | operator reason+expected state version; exact saved request only |
| POST /api/v1/cod/payment-received | VRP data[] contract; ack after durable responsibility fulfilled |

Ops API separates operator permission from ERP ingestion permission, requires concurrency version on state changes,
limits rate/body and never exposes arbitrary SQL. Full OpenAPI schema/examples/error codes are a phase-04 deliverable.
202=accepted/in-progress, not sent. Bulk operations must be bounded and audited.

eVRP production import: POST https://vrp.oneplatformth.com/api/v1/orders/import, X-Token,
JSON atomic, <=500 orders, <=2000 lines/order, <=10 MB. Existing local limits are stricter.
Reference /v1/cod/payment-received on VRP is a sample receiver, not our production callback destination.
No endpoint for ERP writeback, VRP SO lookup/update/cancel or callback event_id has been supplied.

## COD and Accounting Boundary

Callback requires do_no, so_no, payment_status, payment_amt, payment_date, payment_time, payment_send_api in data[].
Documented status accounting_payment_sent describes VRP accounting's notification; it is not evidence that
our ERP ledger has been posted. Success criterion is HTTP 2xx + success=true.
Current vendor contract sends no auth header. Agree ingress protection and receipt-vs-posting ack responsibility.
Duplicates/corrections/combined DO references/partial payments need explicit identity and accounting rules;
payment_send_api is not a reliable sole idempotency key.
Initial delivery ends at durable inbox + reconciliation/export for accounting.
Automatic posting stays deferred until vendor-supported write mechanism, reversal rules and separate permission exist.

## Acceptance Criteria

- SQL connection proven SELECT-only, correct service identity/certificate, no source writes.
- Representative approved SOs match JSON line counts/decimals/masters with no guessed transformations.
- Pagination/change strategy handles detail-only edits, late approval, ties, restart and outage under verified source assumptions.
- No cursor advance without durable representation; dry-run does not mutate production progress.
- Duplicate/concurrent delivery/restart tests prove local guards and review policy.
- Changed/cancelled sent SOs produce actionable review; no unapproved remote mutation.
- Operators can see status, pause, resume, reconcile and safely replay with audit.
- Mock + real disposable SQL integration tests pass; controlled eVRP UAT separately evidenced.
- COD gate passes only with agreed ingress/auth, deduplication and accounting handoff responsibility.
- Deployment has monitored lag/errors, backup/restore drill and accepted release scope.
- Final User Confirmation recorded; no skipped/live-unrun test labeled VERIFIED.

## Test Data Safety Policy

การทดสอบทุก phase ต้องใช้ mock/staging fixtures สำหรับการส่ง, callback, retry, scheduler, deployment และ error injection
การเชื่อมต่อ ERP จริงใช้บัญชี SELECT-only และดึงได้เฉพาะ SO ที่ผู้ใช้อนุมัติเป็นรายรายการหรือชุดตัวอย่าง
ห้ามทำ DDL, INSERT, UPDATE, DELETE, stored procedure ที่มี side effect, เปลี่ยนสถานะ ERP,
สร้างข้อมูล DO หรือส่งข้อมูลจริงไป eVRP ระหว่าง test. หาก test ต้องพิสูจน์การส่งจริง ให้ใช้ staging/test token และข้อมูลจำลอง
หลักฐานต้องระบุ query แบบ read-only, SO scope, เวลา, จำนวนแถว และยืนยันว่าไม่มี mutation; หาก scope ไม่ชัดให้หยุด phase

## Verification Evidence

Current plan-only turn: read config/code/baseline and verify Microsoft references; no live SQL/VRP calls.
Prior baseline 15 passing tests is historical evidence only.
Future tests and exact commands listed per phase. SQL test environment is isolated; production read samples need
scope/timeouts; no production DDL or fault-injection tests.
Plan validation: validate every *_PLAN_* file with vc:generate-plan validator --strict.
12-09-26 validation result: all 7 new plans and the updated baseline passed strict validation; 0 failures, 0 warnings.
Actual phase evidence lives in ../reports/phase-01.md through phase-06.md (currently not started).
Manual Test/UAT and Data Verification queries are included in each phase.

## Risks, Operations and Release Gates

- Credentials/schema absent: planning complete, real integration evidence waits for config; do not infer field names.
- Read inconsistency/change gaps: source contract gate; fallback scans with explicit limits and reconciliation.
- Remote timeout: review; identical replay only under tested policy, no deletion of claims.
- Accounting duplication: durable inbox, agreed business key, no direct SQL posting.
- Production restore: pause sender and reconcile remote accepted requests before resuming an older backup.
- SO release and COD release are separate; COD dependency does not silently expand SO-only acceptance.
- DBA changes to source permissions/views/indexes/CT/CDC/isolation are separately scoped; this plan does not execute them.

## Implementation Checklist

- [x] Inspect baseline and preserve existing work/evidence
- [x] Define SQL Server architecture, config, mapping, state and API contracts
- [x] Write six phase plans and durable report destinations
- [x] Add local `.env` template and dotenv loader for SQL Server connection config
- [ ] Complete phase 01 discovery on real configured source
- [ ] Complete phase 02 mapping and SQL reader
- [ ] Complete phase 03 durable delivery/recovery
- [ ] Complete phase 04 scheduler/operations
- [ ] Complete phase 05 COD receipt/reconciliation when contract available
- [ ] Complete phase 06 scoped UAT/deployment/handoff
- [ ] Record User Confirmation per phase/release

## Touchpoints

This turn: master/phase plans/reports, baseline routing note and README link only.
Future runtime changes are listed by phase; SQL source queries are reviewed/parameterized;
original customer documents and secrets remain unchanged.

## Blast Radius

Plan edits do not install drivers, open SQL connections, alter ERP, schedule jobs, deploy or send orders.
Future local migrations retain current records; live POST changes eVRP and requires a controlled record scope.
No ERP schema changes or accounting writes are implied by planning.

## Source References

- Customer-owned VRP_API_Integration_Guide.pdf v1.1, Postman and examples under eVRP_ไทยซอส:
  local contract reviewed in prior implementation; do not expose Token_eVRP.pages.
- [Microsoft ODBC connection options](https://learn.microsoft.com/en-us/sql/connect/odbc/dsn-connection-string-attribute?view=sql-server-ver17):
  Encrypt/TrustServerCertificate affect encryption and certificate validation; planned explicit trusted TLS.
- [Microsoft Change Tracking workflow](https://learn.microsoft.com/en-us/sql/relational-databases/track-changes/work-with-change-tracking-sql-server?view=sql-server-ver17):
  validate minimum valid version and use a consistent synchronization boundary.
- [Microsoft rowversion](https://learn.microsoft.com/en-us/sql/t-sql/data-types/rowversion-transact-sql?view=sql-server-ver17)
  and [MIN_ACTIVE_ROWVERSION](https://learn.microsoft.com/en-us/sql/t-sql/functions/min-active-rowversion-transact-sql?view=sql-server-ver17):
  rowversion is not a date/time; active-transaction boundaries matter for extraction.

## Resume and Execution Handoff

Primary execute anchor is PHASE_01_DISCOVERY_PLAN_12-09-26.md, not the whole program.
Read master → phase 01 → baseline README/config and prior reports. source config and approved metadata are
the next inputs needed to verify real SQL behavior; planning does not wait for these inputs.
After a phase, update report/status with evidence and route to the next dependent phase.
If a contract changes, update master, affected phase, tests/OpenAPI and migration notes together.
Never apply the old foundation's REST-only handoff as the SQL implementation direction.

Next Step (Cursor Plan / RIPER-5): attach phase 01, RESEARCH actual source/config on implementation instruction,
then EXECUTE scoped discovery/adapter setup, VERIFY and REVIEW before phase 02.
