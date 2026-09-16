# Thaisausage ERP integration

แผนงานล่าสุด: [SQL Server → JSON → eVRP พร้อม scheduler/COD และ rollout](process/features/erp-sqlserver/active/ERP_SQLSERVER_PLAN_12-09-26.md).
มีแผนย่อย 6 phase; โค้ดปัจจุบันมี API, SQL connector และ scheduled approved-SO worker แล้ว แต่ยังปิด live SQL sweep จนกว่าจะยืนยัน schema/mapping และ UAT.

API กลางรับ Sales Order จาก ERP แล้วส่งไป eVRP ตามเอกสารใน `eVRP_ไทยซอส/`
สมมติฐาน: thaisausage คือบริการกลางของโปรเจกต์นี้ และ eVRP คือปลายทางส่งคำสั่งซื้อ
หาก thaisausage มี API ปลายทางแยกต่างหาก ต้องเพิ่ม destination adapter ตาม contract ของระบบนั้น

```text
ERP ส่ง JSON ── POST /api/v1/erp/orders ──┐
                                       ├─ validate ─ SQLite กันส่งซ้ำ ─ eVRP
ERP REST API ← POST /api/v1/erp/pull ─ map┘                       POST /api/v1/orders/import
```

ใช้ Python 3.9+ และ standard library ไม่ต้องติดตั้ง package เพิ่ม
เป็นโครงเริ่มต้นสำหรับทดสอบและต่อยอด ไม่ใช่ production deployment สำเร็จรูป

## เริ่มรัน

รันจาก root ของโปรเจกต์:

```sh
cp config/example.json config/local.json
# แก้ค่า placeholder ใน .env ให้เป็นค่าจริงก่อนเริ่มระบบ
python3 -m thaisausage --config config/local.json
```

ค่าเริ่มต้น `dry_run: true` ตรวจและคืน payload โดยไม่ส่งไป eVRP และไม่จอง request_id/order_no
API ใช้ `http://127.0.0.1:8080` ค่า environment เป็น secret ของคุณ ใส่ผ่าน shell หรือ secret manager
ระบบอ่าน `.env` แบบ local อัตโนมัติเมื่อเริ่มต้น โดย environment ที่มีอยู่แล้วจะมีสิทธิ์เหนือค่าในไฟล์
ไฟล์ `.env` อยู่ใน `.gitignore`; ห้ามใส่ค่า token/password จริงในเอกสารหรือ commit

## SQL Server connection

เติมค่า `ERP_SQLSERVER_CONNECTION_STRING` ใน [.env](/Users/innovera/Documents/thaisausage/.env)
ตัวอย่างใช้ Microsoft ODBC Driver 18, encryption และตรวจ certificate (`TrustServerCertificate=no`)
ถ้าใช้ SQL Server Authentication ให้ใส่ username/password แยกใน `ERP_SQL_USER` และ `ERP_SQL_PASSWORD`
ไม่ต้องใส่ `UID` หรือ `PWD` ซ้ำใน connection string; SQL connector จะประกอบ credential ตอนเชื่อมต่อ

```text
DRIVER={ODBC Driver 18 for SQL Server};SERVER=erp-db.example,1433;DATABASE=ERP;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=10
```

บัญชีนี้ควรมีสิทธิ์ `SELECT` เฉพาะ view/table ที่อนุมัติเท่านั้น
connection string นี้เป็น config contract สำหรับ SQL connector;
โค้ด SQL connector เริ่มต้นอยู่ใน `thaisausage/sqlserver.py` และจะเปิด connection เฉพาะเมื่อเรียกใช้งาน
ต้องติดตั้ง `pyodbc` และ Microsoft ODBC Driver 18 ใน environment ที่ Deploy
ก่อนมี schema/mapping ยืนยัน ระบบจะทำได้เฉพาะ metadata check และไม่อ่านตารางธุรกิจ

```sh
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/api/v1/erp/orders \
  -H "Authorization: Bearer $THAISAUSAGE_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @examples/erp-order.json
```

## Config ที่ใส่ภายหลัง

| Config | ความหมาย |
|---|---|
| `api_key_env` | ชื่อ environment ที่เก็บ key สำหรับ ERP เรียก API กลาง |
| `dry_run` | `true` ตรวจข้อมูล; `false` ส่งจริง |
| `vrp.base_url` | ค่าเริ่มต้น Production URL ตามเอกสาร |
| `vrp.token_env` | ชื่อ environment สำหรับ `X-Token` เช่น `VRP_TOKEN` |
| `erp.base_url` | HTTPS URL ของ ERP เช่น `https://erp.company.example` |
| `erp.orders_path` | path สำหรับ GET คำสั่งซื้อ |
| `erp.token_env` | ชื่อ environment เก็บ token ของ ERP เช่น `ERP_TOKEN` |
| `erp.auth_header`, `auth_prefix` | ค่าเริ่มต้น `Authorization` และ `Bearer `; เปลี่ยนได้ตาม ERP |
| `erp.orders_list_path` | ตำแหน่ง array ใน JSON เช่น `data.orders`; `""` ใช้ root array |
| `erp.field_map` | key = ฟิลด์มาตรฐานปลายทาง, value = path ในข้อมูล ERP |
| `erp.items_path`, `item_field_map` | ตำแหน่งและ mapping รายการสินค้า |
| `database` | ไฟล์ SQLite เก็บสถานะส่งจริง |

Mapping รองรับ nested path เช่น `"order_no": "document.number"` และ
`"customer.code": "buyer.customer_code"` หาก map ทั้ง `customer` และ `customer.code`
ให้เลือกเพียงรูปแบบเดียวเพื่อไม่ให้ทับกัน ค่าเงินและจำนวนต้องเป็น JSON number;
ยังไม่มีการแปลงหน่วย, ภาษี, ส่วนลด หรือ string เป็น number โดยอัตโนมัติ

## ดึงจาก ERP

ตั้งค่า ERP และ `export ERP_TOKEN='your-token'` แล้วเรียก:

```sh
curl -X POST http://127.0.0.1:8080/api/v1/erp/pull \
  -H "Authorization: Bearer $THAISAUSAGE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"ERP-PULL-0001","query":{"page":1}}'
```

`query` ส่งเป็น query string ให้ ERP ตาม config ดึงหนึ่งหน้า/หนึ่ง request เท่านั้น
ยังไม่มี pagination อัตโนมัติ, watermark, durable outbox/attempt history หรือการเขียนสถานะกลับ ERP
โหมด dry-run ของ pull ยังเรียก GET ไป ERP แต่ไม่ส่งไป eVRP
กรณีไม่มีรายการจะคืน `state: empty` ไม่สร้าง submission

## สัญญา API กลาง

ทุก endpoint ยกเว้น `/health` ใช้ `Authorization: Bearer <THAISAUSAGE_API_KEY>`

| Method / path | ข้อมูลเข้า / ผลลัพธ์ |
|---|---|
| `GET /health` | สถานะ process และ dry_run; ไม่ตรวจการเชื่อมต่อ ERP/eVRP |
| `GET /docs` | Swagger UI สำหรับดูและทดลอง API |
| `GET /openapi.json` | OpenAPI 3.0 specification |
| `POST /api/v1/erp/orders` | `{request_id, orders: [...]}` รูปแบบใน `examples/erp-order.json` |
| `POST /api/v1/erp/pull` | `{request_id, query?: {...}}` ดึง ERP → map → ส่ง |
| `POST /api/v1/erp/hooks/order-ready` | ERP แจ้ง event เพื่อปลุก SQL sweep; ไม่ใช่ข้อมูล SO เต็ม |
| `POST /api/v1/erp/do-received` | รับ DO เข้า staging เพื่อตรวจสอบ; ไม่เขียนกลับ ERP |
| `GET /api/v1/submissions/{request_id}` | สถานะที่บันทึกของการส่งจริง |

ผลลัพธ์หลัก: `{request_id, state, dry_run}` และ `replayed: true` เมื่อเป็น request เดิม
`validated` (HTTP 200) = ผ่าน local validation ใน dry-run, `sent` (200) = upstream ยืนยัน success,
`sending` (202) = จองแล้ว/กำลังส่ง, `needs_review` (202) = ต้องตรวจสอบผล upstream
HTTP 202 **ไม่ได้หมายความว่าส่งสำเร็จ** ระบบส่งต่อด้วย scheduled worker เมื่อเปิด sync และไม่ resend อัตโนมัติเมื่อผลลัพธ์ไม่แน่นอน ต้อง reconcile ก่อน
HTTP 401 = key ไม่ถูกต้อง, 409 = request/order ซ้ำขัดแย้ง, 422 = ข้อมูล/config ไม่ถูกต้อง,
502 = ดึง ERP ไม่สำเร็จ, 500 = internal error
payload สูงสุด 1 MiB และ batch 100 orders เป็นขีดจำกัดของบริการนี้
คู่มือ eVRP v1.1 ระบุสูงสุด 10 MB, 500 orders/request และ 2,000 items/order
`request_id` ต้องเป็น A-Z, a-z, 0-9, จุด, underscore, colon หรือ hyphen ไม่เกิน 120 ตัว
`payment_in_day` เป็น null/ไม่ส่งได้ (ไม่ใช่ COD); ต้องมี `customer.code` และ
`delivery_point_code` หรือ `shipping_address` เพื่อให้ eVRP ระบุจุดส่ง
Local validation ไม่ตรวจ master ลูกค้า/จุดส่ง/route/คลัง; eVRP ตรวจเมื่อส่งจริง
สินค้าใหม่ต้องมี description ตามคู่มือ; adapter ไม่ทราบว่า item_code มีอยู่แล้วหรือไม่

## การส่งจริงและสถานะ

หลังตรวจ mapping และรหัสคลัง/สินค้า/ลูกค้าจริง ให้ตั้ง `VRP_TOKEN` และ `dry_run: false` แล้ว restart
หนึ่ง `request_id` ผูกกับ payload เดียว; ส่งซ้ำจะคืนผลเดิมจาก SQLite
`order_no` เดิมภายใต้ request_id ใหม่จะถูกปฏิเสธเพื่อกันส่งซ้ำจาก ERP
Batch จองรายการพร้อมกันใน transaction; หากชนแม้รายการเดียวจะไม่ส่งทั้ง batch

หาก timeout, upstream error, success response ไม่ตรงรูปแบบ หรือ process หยุดขณะส่ง
ให้ตรวจ eVRP และ SQLite ก่อนดำเนินการต่อ รายการ `sending` ที่ค้างต้องตรวจด้วยมือเช่นกัน
โครงนี้ไม่ resend อัตโนมัติและยังไม่มี API ปลดรายการ/แก้ไข SO
SQLite เก็บ hash, สถานะ และเลขอ้างอิง batch/SO ของ VRP ไม่เก็บ payload เต็ม จึงต้องเก็บต้นฉบับที่ ERP เพื่อใช้ reconcile
ยังไม่อ้างว่าระบบรับประกัน exactly-once ที่ปลายทาง

## ERP webhook trigger

การส่งหลักใช้ Schedule ดึงเฉพาะ SO ที่ Approve แล้วจาก `approved_orders_query` ที่ผ่านการ review:

```sh
curl -X POST http://127.0.0.1:8080/api/v1/erp/hooks/order-ready \
  -H "Authorization: Bearer $THAISAUSAGE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"ERP-EVENT-0001","event_type":"sales_order.ready","source_id":"main-erp","company_id":"THAI","order_no":"SO-0001","changed_at":"2026-09-12T10:00:00+07:00"}'
```

ระบบจะ query ตามรอบ `sync.interval_seconds` และส่งเฉพาะแถวที่ query กรองว่า Approve แล้ว
ไม่ใช้ Hook เป็นตัวเริ่มงานอีกต่อไป; endpoint Hook เดิมเก็บไว้เพื่อ compatibility เท่านั้น

## Deploy บน VPS

กรอกไฟล์ [deploy/vps.env](/Users/innovera/Documents/thaisausage/deploy/vps.env) บนเครื่อง local
หรือ copy จาก [deploy/vps.env.example](/Users/innovera/Documents/thaisausage/deploy/vps.env.example)
ไฟล์นี้ถูก ignore และห้าม commit/publish ค่า SSH, SQL password, API key หรือ VRP token

ค่าที่สำคัญคือ `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY` (แนะนำ SSH key แทน password)
ส่วน `ERP_SQLSERVER_CONNECTION_STRING`, `ERP_SQL_USER`, `ERP_SQL_PASSWORD`, `THAISAUSAGE_API_KEY`
และ `VRP_TOKEN` ให้อยู่ใน `.env` ไฟล์เดียว ไม่ต้องคัดลอกซ้ำมาไว้ใน `deploy/vps.env`

เตรียมไฟล์ config บน VPS ก่อน โดยไม่ copy `.env` เข้า Git:

```sh
cp config/example.json config/local.json
# แก้ source/sqlserver/sync และ SQL query ที่ได้รับการอนุมัติ
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml logs --tail=100 thaisausage
```

Compose bind port ไว้ที่ localhost และใช้ volume สำหรับ SQLite; ให้ reverse proxy ที่มี TLS
เป็นผู้รับ traffic จาก ERP และส่งต่อเข้า container app; ชุด Compose นี้ใช้ Caddy และ
`thaisausage.krs.co.th` เป็นค่าเริ่มต้นสำหรับ HTTPS อัตโนมัติ
ตั้ง `sync.enabled=true` หลัง dry-run และ read-only SO verification ผ่านเท่านั้น
ก่อน `docker compose up` ต้องตรวจ `config/local.json`, `.env` permission และ firewall

## ทดสอบและแผน

```sh
python3 -m unittest discover -s tests -v
```

ทดสอบ HTTP บน localhost ด้วย upstream จำลอง, mapping, validation, SQLite,
การส่งซ้ำพร้อมกัน และ timeout โดยไม่เรียก ERP/eVRP จริง
แผนงาน: `process/general-plans/active/ERP_API_PLAN_11-09-26.md`
COD callback และการลงรับชำระเงิน ERP อยู่ในแผน ยังไม่เปิด endpoint สำหรับใช้งาน
ก่อน deploy ต้องเลือก production server/TLS, backup, monitoring และยืนยัน vendor contracts
