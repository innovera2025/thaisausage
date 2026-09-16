# Review request — SO schedule flow, DO callback and disabled DO writer

Date: 16-09-26  
Requested by: Claude Code session (main developer)  
Reviewer: Codex  
Scope: working tree ที่ยังไม่ commit บน branch `main` (commit ล่าสุด `7ce9101`)

## สิ่งที่ขอให้ตรวจ

ตรวจว่าโค้ดตรงกับ requirement ด้านล่างจริงหรือไม่ และหาจุดที่ยังพลาด
ห้าม commit, push, deploy, แก้ `.env`/`deploy/vps.env` หรือเชื่อมต่อ ERP/eVRP จริง

### SO flow

- Scheduler ดึง SO จาก SQL Server เท่านั้น ไม่ใช้ ERP hook เป็น trigger หลัก
- ใช้เฉพาะ SO ที่ `IsApprSo = 1` และ query ต้องเป็น SELECT-only
- กันส่ง SO ซ้ำ
- `dry_run=true` ต้องไม่ส่งไป eVRP และไม่จอง `order_no`
- `sync.enabled=false` ต้องไม่ query เลย
- log ต้องไม่มีข้อมูลลูกค้า, token, password หรือ connection string

### DO flow

- endpoint หลักคือ `POST /api/v1/vrp/do-received` ใช้ Bearer จาก `THAISAUSAGE_API_KEY`
- 202 เมื่อรับสำเร็จ, replay payload เดิมได้, identity เดิม payload เปลี่ยน = 409, JSON เสีย/ไม่มี identity = 422, ไม่มี key = 401
- บันทึกเข้า staging เท่านั้น ห้ามเขียน ERP ห้ามส่ง DO กลับ eVRP
- `do_write.enabled` ต้องเป็น false และ writer ต้องเปิดเองไม่ได้

### Config

- `.env` เก็บ secret เท่านั้น: `THAISAUSAGE_API_KEY`, `VRP_TOKEN`, `ERP_SQLSERVER_CONNECTION_STRING`, `ERP_SQL_USER`, `ERP_SQL_PASSWORD`
- `config/local.json` ห้ามมี secret และต้องไม่หลุดเข้า Git หรือ Docker image

## การเปลี่ยนแปลงรอบนี้ (ยังไม่ commit)

| ไฟล์ | สาระ |
|---|---|
| `thaisausage/service.py` | แยก error รายรายการใน `sweep_approved_orders`; แถวไม่มี `order_no` เป็น `review`; `receive_do(payload, source)` บันทึกคอลัมน์ `source` และคืน `erp_write:false` ทุกครั้ง; migration เพิ่มคอลัมน์ |
| `thaisausage/sqlserver.py` | `fetch_approved_orders` ปฏิเสธ query ที่ว่างหรือไม่มี `IsApprSo` ก่อนเปิด connection |
| `thaisausage/api.py` | route `/api/v1/vrp/do-received` ส่ง `source` ให้ service แทนการแก้ dict ทีหลัง |
| `thaisausage/__main__.py` | เพิ่ม `run_sweep_cycle()` เพื่อให้ทดสอบเงื่อนไข `sync.enabled` ได้ |
| `deploy/.dockerignore` | เพิ่ม `config/local.json`, `deploy/vps.env` |
| `tests/test_integration.py`, `tests/test_sqlserver_config.py` | เพิ่มเคส DO callback (401/202/replay/409/422), scheduler ปิด/เปิด, isolation, guard ของ query |
| `docs/*` + PDF, `README.md`, `docs/openapi.json` | ปรับให้ตรงโค้ด |

## ผลตรวจที่รันแล้ว

- `python3 -m unittest discover -s tests -v` → OK, 68 tests
- `python3 -m json.tool docs/openapi.json` → OK
- `git diff --check` → clean
- ไม่มีการเชื่อมต่อ SQL Server/eVRP จริง (เครื่องนี้ไม่มี `pyodbc`) ทุก test ใช้ mock/fake driver

## คำถามที่อยากได้คำตอบจาก reviewer

1. มีเส้นทางใดที่ทำให้เกิด ERP write ได้โดยไม่ตั้ง `do_write.enabled=true` ด้วยมือหรือไม่
2. `sweep_approved_orders` ยังมีกรณีที่ทำให้ส่ง SO ซ้ำหรือข้าม SO เงียบๆ หรือไม่
3. การกัน replay/conflict ของ DO ครอบคลุมพอหรือยัง โดยเฉพาะเมื่อ ERP และ eVRP ใช้ `receipt_id` ชนกัน
4. guard ที่บังคับคำว่า `IsApprSo` ในตัว query เข้มงวดเกินไปหรือหลวมเกินไป
5. มี log หรือ error message ใดที่อาจหลุดข้อมูลลูกค้าหรือ secret

## BLOCKER ที่ทราบอยู่แล้ว

- query จริงและ `field_map`/`item_field_map` ยังไม่มีจาก ERP DBA จึงยืนยัน mapping กับ contract ของ eVRP ไม่ได้
- DO mapping 45+24 ฟิลด์ของ `tbl_DOhdr`/`tbl_Dodtl` ยังรอ schema, SQL ต้นฉบับ `?xTransNum`/`?cRun` และกฎออกเลขเอกสาร
- ยังไม่มี test database, write credential และ UAT
