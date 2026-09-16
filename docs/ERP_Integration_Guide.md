# Thaisausage ERP Integration Guide

**Document version:** 1.0.0  
**Date:** 12 September 2026  
**Audience:** ERP / IT integration team  
**Production endpoint:** `https://thaisausage.krs.co.th`

## 1. Purpose and scope

เอกสารนี้อธิบายการเชื่อมต่อจาก ERP มายัง API กลางของ thaisausage เพื่อแจ้ง SO ที่พร้อมส่ง,
ส่งข้อมูล SO, รับ DO สำหรับ staging และตรวจสอบสถานะการส่งต่อไป eVRP

ERP เป็นแหล่งข้อมูลหลักของ SO ระบบจะอ่านข้อมูลฉบับเต็มจาก SQL Server ตาม Schedule
Query ต้องกรองเฉพาะ SO ที่ Approve แล้วด้วย `IsApprSo = 1` และผ่านการ review จาก ERP/DBA;
ไม่ใช้ Webhook เป็นช่องทางหลัก

ระหว่างการทดสอบ ระบบจะใช้ dry-run/staging เท่านั้น ไม่มีการเขียนกลับ ERP และไม่ส่ง SO จริงไป eVRP

## 2. Data flow

```text
ERP approves SO
        |
        | scheduled approved_orders_query (SELECT-only)
        v
Thaisausage Scheduler -> maps full SO to JSON -> eVRP Import SO API

ERP DO event/data -> Thaisausage DO staging -> inspection/reconciliation
                                         (no ERP INSERT/UPDATE/DELETE)
```

## 3. Base URL and authentication

ทุก endpoint ยกเว้น `/health`, `/docs` และ `/openapi.json` ต้องใช้ API key ของ thaisausage:

```http
Authorization: Bearer <THAISAUSAGE_API_KEY>
Content-Type: application/json
Accept: application/json
```

`THAISAUSAGE_API_KEY` เป็น key ภายในที่ทีมระบบ thaisausage สร้างและส่งให้ ERP แยกช่องทาง
ห้ามใช้ `VRP_TOKEN` แทน key นี้ และ ERP ไม่ต้องรู้ `VRP_TOKEN`

## 4. Legacy webhook (not used by the scheduled flow)

### Endpoint

```http
POST /api/v1/erp/hooks/order-ready
```

ไม่ต้องเรียกใน Flow ปัจจุบัน ระบบใช้ Schedule ดึง SO ที่ Approve แล้วจาก SQL Server

### Request

```json
{
  "event_id": "ERP-SO-20260912-000001",
  "event_type": "sales_order.ready",
  "source_id": "main-erp",
  "company_id": "THAI",
  "order_no": "SO-0001",
  "changed_at": "2026-09-12T10:00:00+07:00"
}
```

Fields:

| Field | Required | Rule |
|---|---:|---|
| `event_id` | yes | unique, non-empty, max 120 characters |
| `event_type` | yes | `sales_order.ready` or `sales_order.changed` |
| `source_id` | yes | configured ERP source identifier |
| `company_id` | no | company/branch scope |
| `order_no` | optional for legacy hook | not used by the scheduled approved-SO flow |
| `changed_at` | no | source timestamp with timezone preferred |

### Response

```http
HTTP/1.1 202 Accepted
```

```json
{
  "event_id": "ERP-SO-20260912-000001",
  "state": "received",
  "sweep": "queued"
}
```

การตอบ `202` หมายถึงบันทึก legacy trigger เท่านั้น ไม่ได้แปลว่า SO ถูกส่งถึง eVRP แล้ว
ส่ง event เดิมซ้ำได้ ระบบจะตอบ `replayed: true` และไม่สร้างผลซ้ำ

## 5. Send SO directly (available contract)

### Endpoint

```http
POST /api/v1/erp/orders
```

ใช้เมื่อ ERP เป็นผู้สร้าง standard JSON ตาม contract หรือใช้ทดสอบ mapping ก่อน SQL sweep เปิด

```json
{
  "request_id": "ERP-SO-20260912-000001",
  "orders": [
    {
      "order_no": "SO-0001",
      "order_date": "2026-09-12",
      "delivery_date": null,
      "payment_in_day": 30,
      "customer": {
        "code": "CUST-0001",
        "name": "ลูกค้าทดสอบ",
        "billing_address_line1": "ที่อยู่ทดสอบ",
        "district": "เมือง",
        "province": "นครปฐม",
        "country": "ไทย",
        "postcode": "73000",
        "phone": ""
      },
      "delivery_point_code": "CUST-0001",
      "shipping_address": "ที่อยู่จัดส่งทดสอบ นครปฐม 73000",
      "pickup_hub_code": "h01",
      "pickup_hub_name": "นครปฐม",
      "items": [
        {
          "line_no": 1,
          "item_code": "ITEM-0001",
          "description": "สินค้าทดสอบ",
          "quantity": 2,
          "unit_price": 100
        }
      ]
    }
  ]
}
```

Rules used by the local contract:

- `request_id` uses only `A-Z a-z 0-9 . _ : -`, maximum 120 characters.
- `order_no` must be unique within the request and maximum 100 characters.
- `order_date` is `YYYY-MM-DD`; `delivery_date` can be null or empty.
- `payment_in_day = 0` means COD; null or a positive value means non-COD.
- `customer.code` is required. `customer.name` is optional.
- `delivery_point_code` or `shipping_address` must identify the delivery point.
- `pickup_hub_code` is required and must be a hub known to eVRP.
- `quantity > 0`; `unit_price >= 0`. A free item remains a separate line with price `0`.
- Maximum local batch is 100 orders and request body is 1 MiB. eVRP v1.1 supports larger limits,
  but local limits are intentionally stricter until load testing is complete.

## 6. DO staging receiver

### Endpoint

```http
POST /api/v1/erp/do-received
```

ตัวอย่าง:

```json
{
  "receipt_id": "DO-20260912-000001",
  "do_no": "DO-0001",
  "status": "delivered",
  "data": {
    "so_no": "SO-0001",
    "delivered_at": "2026-09-12T12:00:00+07:00"
  }
}
```

ระบบตอบ `202` และ `erp_write: false` เมื่อบันทึก staging สำเร็จ
`receipt_id` เดิมกับ payload เดิม replay ได้; payload ต่างกันจะได้ `409`
รูปแบบ field ภายใน `data` จะยืนยันอีกครั้งหลังสำรวจ DO ของ ERP

## 7. Status and errors

| HTTP | Meaning | ERP action |
|---:|---|---|
| 200 | accepted/validated/sent | record response |
| 202 | queued or outcome requires review | do not mark eVRP success yet |
| 401 | missing/invalid internal API key | fix credential, then retry same event |
| 409 | duplicate identity with different data | stop and reconcile |
| 422 | invalid JSON or business field | fix payload; use a new request identity if payload changed |
| 502 | upstream ERP request failed | retry only according to operator policy |
| 500 | internal failure | contact thaisausage operator |

Submission states are `validated`, `sent`, `sending`, and `needs_review`.
`needs_review` or an interrupted connection can mean the remote system accepted the request;
do not blindly resend a changed payload. Reconcile with the operator first.

## 8. Retry and idempotency

Use a stable unique `request_id` for one immutable payload. The same ID and identical payload is safe
to replay. Reusing an ID with changed data is a conflict. `order_no` also cannot be reused under another
request while its previous claim exists.

For webhook delivery, ERP should retry network failures and non-2xx responses with the same `event_id`.
Recommended delays are 30 seconds, 2 minutes and 10 minutes, with an operator review after the limit.
The receiver is idempotent, but the ERP must keep its event log and not generate a new event ID for every retry.

## 9. ERP implementation checklist

- [ ] Store `THAISAUSAGE_API_KEY` in the ERP secret store.
- [ ] Send webhook only after the agreed SO-ready transition is committed in ERP.
- [ ] Use a stable `event_id`; retry the same body on transport failure.
- [ ] Provide `order_no`, `company_id` and `changed_at` whenever available.
- [ ] Keep ERP as the source of complete SO data; do not put full SO data in the hook.
- [ ] Confirm the SQL Server service account can read only approved views/tables.
- [ ] Provide sample SOs for COD, credit, free item, multiple lines and changed detail.
- [ ] Do not expect DO receiver to update ERP until a separate write contract is approved.
- [ ] Test against the deployed Domain using mock/staging data first.

## 10. Test examples

```sh
curl -X POST https://thaisausage.krs.co.th/api/v1/erp/hooks/order-ready \
  -H 'Authorization: Bearer <THAISAUSAGE_API_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"ERP-SO-TEST-001","event_type":"sales_order.ready","source_id":"main-erp","order_no":"SO-TEST-001"}'
```

Swagger UI: `https://thaisausage.krs.co.th/docs`  
OpenAPI: `https://thaisausage.krs.co.th/openapi.json`

## 11. Current limitations

SQL table/view names, SO-ready status, master mappings, tax/discount rules and pagination are not
assumed in this document. They must be filled after Phase 01 discovery. SQL sweep is disabled until
mapping and an approved SO read test pass. No API for ERP accounting writeback or SO cancellation is defined.
