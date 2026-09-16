# ERP ↔ Thaisausage Integration Test Plan

**Document version:** 1.0.0  
**Date:** 12 September 2026  
**Audience:** ERP team, Thaisausage IT/Operations and eVRP test coordinator  
**System under test:** https://thaisausage.krs.co.th

## 1. Test objective

ยืนยันการรับ–ส่งข้อมูลระหว่าง ERP และ thaisausage ตั้งแต่การแจ้งเหตุการณ์ SO การอ่าน SO จาก SQL Server แบบ SELECT-only การส่ง standard JSON ไปยัง eVRP การรับ DO เข้าพื้นที่ staging และการตอบกลับสถานะให้ผู้เรียก โดยไม่เปลี่ยนข้อมูลจริงใน ERP และไม่ส่งข้อมูลจริงไป eVRP จนกว่าจะผ่าน UAT และได้รับอนุมัติ

## 2. Scope and direction

| Direction | Flow | Current scope | Expected side effect |
|---|---|---|---|
| ERP → Thaisausage | direct SO / DO receipt; legacy webhook retained | Yes | SQLite submission/staging only |
| Thaisausage → ERP | HTTP response to ERP caller | Yes | response only; no ERP write-back |
| ERP SQL → Thaisausage | approved SO SELECT | Yes | SELECT-only |
| Thaisausage → eVRP | mapped SO submission | scheduled worker/mock first | no real eVRP request in dry-run |
| eVRP → Thaisausage | DO callback to `/api/v1/vrp/do-received` | Yes | SQLite staging only; never writes ERP |
| eVRP → Thaisausage | response/status | mock/UAT | submission state and reference |
| Thaisausage → ERP | asynchronous callback | Not available | separate future contract |

## 3. Safety rules

1. Local tests use temporary SQLite and mocked ERP/eVRP connectors.
2. Deployed smoke uses `dry_run=true` and `sync.enabled=false`.
3. Real ERP SQL Server may be queried only for SO numbers explicitly approved by the user.
4. SQL must be the reviewed SELECT query with a read-only account. No INSERT, UPDATE, DELETE, MERGE, EXEC, DDL or ERP status update.
5. DO tests use mock payloads and must prove `erp_write=false`.
6. No real eVRP submission before the UAT window, test token and sign-off are approved.
7. Never log API keys, SQL passwords, full customer data or unredacted payloads.

## 4. Entry criteria

- [ ] HTTPS, `/health`, `/docs` and `/openapi.json` return successfully.
- [ ] ERP has received the OpenAPI contract and has a test sender.
- [ ] Test API key is configured through secret storage.
- [ ] `dry_run=true` and `sync.enabled=false` are confirmed.
- [ ] Approved SQL query, field mapping and approved SO list are recorded.
- [ ] Test owner, observer and rollback contact are available.
- [ ] eVRP test URL/token and test master data are available before eVRP UAT.
- [ ] Scheduled worker is the only SO trigger; `sync.interval_seconds` is agreed for the test window.
- [ ] `sqlserver.approved_orders_query` is reviewed and filters `IsApprSo = 1`; the app refuses a query without that predicate.
- [ ] `do_write.enabled=false` is confirmed on the environment under test.

## 5. ERP → Thaisausage test cases

| ID | Scenario | Action | Expected result | Evidence |
|---|---|---|---|---|
| ERP-01 | Health/contract | GET `/health`, `/docs`, `/openapi.json` | HTTP 200; no secret exposed | redacted response |
| ERP-02 | Valid SO hook | POST `/api/v1/erp/hooks/order-ready` with unique `event_id` | 202, `state=received`, `sweep=queued` | event_id/status |
| ERP-03 | Hook replay | resend identical body | idempotent; one logical event | hook count/status |
| ERP-04 | Hook conflict | same event_id, changed order data | 409 or safe conflict; no second action | response |
| ERP-05 | Invalid hook | missing ID/unknown event type | 422; not processed | response |
| ERP-06 | Valid direct SO | POST `/api/v1/erp/orders` with standard JSON | 200/202; request stored | request_id/status |
| ERP-07 | SO replay | same request_id and identical payload | idempotent; no duplicate send | submission lookup |
| ERP-08 | Changed payload | same request_id with changed line | 409; operator review | response |
| ERP-09 | Validation | bad date, quantity, hub or duplicate order | 422; no outbound attempt | response |
| ERP-10 | DO staging | POST `/api/v1/erp/do-received` mock receipt | 202, `state=staged`, `erp_write=false` | receipt/status |
| ERP-11 | DO replay/conflict | same receipt, then changed payload | replay safe; changed payload 409 | receipt lookup |
| ERP-12 | Authentication | no/wrong/correct Bearer key | 401/401/accepted | status only |
| ERP-13 | Network retry | timeout/disconnect then retry same body | same identity; reconcile review state | IDs/state |

| ERP-14 | Scheduled approved SO | run the schedule with a reviewed query | only approved SOs are selected; no Hook required | timestamps/query result |
| ERP-15 | Unapproved SO excluded | include an SO with `IsApprSo <> 1` in the source data | the SO is never selected and never reaches eVRP | query result/submission list |
| ERP-16 | Query guard | configure a query without the `IsApprSo` predicate | startup/sweep refuses with a contract error; no SQL executed | error message |
| ERP-17 | Sync disabled | set `sync.enabled=false` and wait two intervals | no SQL query runs and no SO is sent | worker log/query trace |
| ERP-18 | Dry-run schedule | `dry_run=true` with an approved SO | result `preview`; no eVRP call and no `order_claims` row | state/database |
| ERP-19 | Duplicate protection | run two cycles over the same approved SO | second cycle reports `skipped`/`already_sent` | submission/claim rows |
| ERP-21 | Unresolved attempt | force `needs_review`, then run another cycle | second cycle reports `needs_review`/`prior_attempt_needs_review` and does not resend | states/upstream calls |
| ERP-22 | Incomplete detail | approved SO whose detail row has no item code | SO becomes `review`/`detail_item_code_missing` and is not sent | per-order result |
| ERP-23 | Unreadable batch | query returns a row without the configured order key | cycle returns one `review` entry, no exception, log shows counts only | worker log |
| ERP-20 | Isolation | include one unmappable SO next to a valid one | bad SO becomes `review`; the valid SO is still sent | per-order results |

## 5.1 eVRP → Thaisausage DO callback test cases

eVRP เรียก `POST /api/v1/vrp/do-received` หลังสร้าง DO เสร็จ ทุกเคสใช้ข้อมูลจำลองเท่านั้น

| ID | Scenario | Action | Expected result | Evidence |
|---|---|---|---|---|
| DO-01 | Valid callback | POST with unique `receipt_id` and `do_no` | 202, `state=staged`, `source=eVRP`, `receipt_key=eVRP:<receipt_id>`, `erp_write=false` | receipt/status |
| DO-02 | Replay | resend the identical payload | 202 with `replayed=true`; one row in `do_receipts` | row count |
| DO-03 | Conflict | same `receipt_id`, changed payload | 409; original staged row unchanged | response/row |
| DO-04 | Unauthorized | omit or corrupt the Bearer key | 401; nothing stored | status only |
| DO-05 | Invalid JSON | malformed body or wrong Content-Type | 422; nothing stored | status only |
| DO-06 | Missing identity | body without `receipt_id` and `do_no` | 422; nothing stored | status only |
| DO-07 | No ERP write | inspect ERP after DO-01 to DO-06 | zero ERP rows created/changed; `do_write.enabled=false` | before/after counts |
| DO-08 | No echo to eVRP | observe outbound traffic during DO tests | Thaisausage sends nothing back to eVRP | redacted network log |
| DO-09 | Concurrent delivery | send the same callback twice at the same moment | one staged row; the other answer is `replayed=true`; never HTTP 500 | row count/status |
| DO-10 | Source isolation | same `receipt_id` from ERP path and eVRP path | two separate staged rows, no conflict | `receipt_key` values |
| DO-11 | Writer disabled | callback while `do_write.enabled=false` | 202, `erp_write=false`, `do_write.state=disabled`, no ERP row | response/ERP counts |
| DO-12 | No transaction_no | callback without `transaction_no` | 202, `do_write.state=skipped`, DO still staged | response/staging row |
| DO-13 | Writer rejects | enabled writer with incomplete mapping | 202, `do_write.state=rejected`, no SQL executed | response/log |
| DO-14 | Duplicate transaction | second DO reusing a written `transaction_no` | 202, `do_write.state=conflict`, one ERP document only | response/ERP counts |

## 6. Thaisausage → ERP SQL Server test cases

| ID | Scenario | Action | Expected result | Evidence |
|---|---|---|---|---|
| SQL-01 | Connection | use connection string plus `ERP_SQL_USER/PASSWORD` | connects; credentials not logged | redacted check |
| SQL-02 | Approved SO | run reviewed query for one approved SO | rows read and grouped correctly | row count/order |
| SQL-03 | Unknown SO | query test/nonexistent key | empty/controlled review; no broad sweep | result count |
| SQL-04 | Mutation guard | try mutation/non-SELECT query | rejected before execution | rejection code |
| SQL-05 | Mapping | COD, credit, free item, Thai text, decimals, multi-line | standard JSON matches contract | redacted JSON |
| SQL-06 | Scheduled sweep | run approved-SO schedule in controlled mode | correct submission preview/state; no ERP write | run/result state |
| SQL-07 | SQL failure | simulate timeout/unavailable server | controlled review; scheduler stays healthy | redacted logs |

| SQL-08 | Approved schedule | run configured approved-orders query with `IsApprSo = 1` | only approved SOs are returned; no Hook required | query and result count |

## 7. Thaisausage → eVRP and response tests

ทดสอบด้วย mock eVRP ก่อนเสมอ และใช้ eVRP UAT เท่านั้นเมื่อได้รับอนุมัติ

| ID | Scenario | Action | Expected result | Evidence |
|---|---|---|---|---|
| VRP-01 | Valid outbound | submit mapped mock SO | token header reaches mock only | redacted request |
| VRP-02 | Accepted | mock HTTP 200 with reference | state `sent`; reference stored | submission |
| VRP-03 | Temporary failure | mock 502/timeout | `needs_review`; no automatic resend; operator reconciliation | redacted response |
| VRP-04 | Ambiguous timeout | accept then close connection | no blind changed-payload resend | review item |
| VRP-05 | Business reject | mock 422 | not marked sent; actionable error | response |
| VRP-06 | Duplicate | repeat identical request | idempotent logical result | ID/reference |
| VRP-07 | Auth failure | mock 401/403 | no uncontrolled loop; alert operator | status |
| VRP-08 | Unknown hub | send a hub code absent from the eVRP master | 422 `PICKUP_HUB_NOT_FOUND`; message stored in `upstream_error` | submission record |
| VRP-09 | Customer without master | send an SO whose customer has no delivery point/route | 422 `CUSTOMER_MASTER_REQUIRED`; no retry | submission record |
| VRP-10 | Identity reuse | resend a corrected order under the previous request_id | 409 `REQUEST_ID_CONFLICT`; the scheduler must generate a new id instead | request_id values |

ERP must treat 202 as accepted for processing, not proof of eVRP completion. ERP may retry transport failures with the same identity. Thaisausage does not run an automatic retry worker or attempt history yet. A 409 stops automation. A 422 requires payload correction. `needs_review` requires operator reconciliation.

## 8. Test execution record

For every case record: test run ID, environment, Bangkok time, tester, endpoint, HTTP status, request/event/receipt ID, expected state, actual state and redacted evidence path.

At the end record:

- ERP rows before = ___; ERP rows after = ___; mutation check = pass/fail
- Real eVRP send = not used / approved UAT
- Passed = ___; failed = ___; blocked = ___
- Defects, owner, corrective action and retest result

## 9. Exit gates and sign-off

### Gate A — technical smoke

- [ ] ERP-01 to ERP-05 pass.
- [ ] HTTPS, authentication and CSP/Swagger are verified.
- [ ] No secret appears in evidence.

### Gate B — controlled data flow

- [ ] ERP-06 to ERP-20 pass with mock/staging data.
- [ ] DO-01 to DO-08 pass with mock callbacks.
- [ ] SQL-01 to SQL-07 pass using only approved SO SELECTs.
- [ ] DO receiver proves `erp_write=false`.
- [ ] ERP row/status counts are unchanged.

### Gate C — eVRP UAT

- [ ] VRP-01 to VRP-07 pass against eVRP test environment.
- [ ] eVRP confirms customer, item, hub and remote reference mapping.
- [ ] Retry, duplicate and recovery behavior is accepted.
- [ ] Production token, live mode and schedule are approved separately.

| Role | Name | Result | Date/signature |
|---|---|---|---|
| ERP owner |  | Pass / Fail |  |
| Thaisausage IT |  | Pass / Fail |  |
| eVRP coordinator |  | Pass / Fail |  |
| Business/data owner |  | Pass / Fail |  |

## 10. Related contracts

- Swagger: https://thaisausage.krs.co.th/docs
- OpenAPI: `docs/openapi.json`
- ERP guide: `docs/ERP_Integration_Guide.md`
- Operations guide: `docs/Thaisausage_Operations_Guide.md`
