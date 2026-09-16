# Phase 07 verification report — ERP DO Insert

Status: 🔨 CODE DONE (writer ปิดอยู่) + 🚧 BLOCKED — Phase 1 discovery, Phase 2 แบบฟอร์ม mapping
และ Phase 3 writer เสร็จแล้ว; mapping จริง, SQL integration test และการเปิดใช้งานยังถูก block
Plan: [Phase 07](../active/PHASE_07_DO_INSERT_PLAN_16-09-26.md)
Date: 16-09-26

## ยืนยันความปลอดภัย

- ไม่มีการ INSERT/UPDATE/DELETE เข้า ERP เกิดขึ้นในรอบนี้ ไม่มีการเชื่อมต่อ SQL Server จริง
- ยังไม่มีโค้ด DO writer ในรีโป โค้ดที่แตะ SQL Server มีเพียง SELECT guard ใน `thaisausage/sqlserver.py`
- `pyodbc` ไม่ได้ติดตั้งในเครื่องพัฒนา (`ModuleNotFoundError: No module named 'pyodbc'`) จึงเชื่อมต่อ ERP ไม่ได้อยู่แล้ว
- ไม่มีการแก้ไขโค้ดใน commit นี้ มีเพียงเอกสาร/รายงาน

## คำสั่งตรวจสอบที่รัน (16-09-26)

| คำสั่ง | ผล |
|---|---|
| `python3 -m unittest discover -s tests -v` | OK — 32 tests |
| `python3 -m json.tool config/example.json` | OK |
| `python3 -m json.tool docs/openapi.json` | OK |
| `git diff --check` | clean |

## สิ่งที่ตรวจในโค้ดปัจจุบัน

| จุด | สถานะปัจจุบัน |
|---|---|
| `POST /api/v1/erp/do-received` (`api.py`) | รับ payload แล้วเรียก `service.receive_do` ตอบ 202 ไม่มีผลข้างเคียงกับ ERP |
| `IntegrationService.receive_do` (`service.py`) | ตรวจ `receipt_id`/`do_no`, คำนวณ hash, เขียนตาราง `do_receipts` ใน SQLite และคืน `erp_write: False` replay payload เดิมได้ payload ต่างได้ 409 |
| ตาราง `do_receipts` | `receipt_id PK, do_no, payload_hash, payload, state, received_at` มีสถานะเดียวคือ `staged` |
| `SQLServerConnector` | SELECT-only; guard ปฏิเสธ INSERT/UPDATE/DELETE/MERGE/EXEC/ALTER/DROP/TRUNCATE/INTO ไม่มี method สำหรับเขียน |
| credential | มีชุดเดียวคือ `ERP_SQL_USER`/`ERP_SQL_PASSWORD` (read-only) ยังไม่มี write credential แยก |
| config | ไม่มี key `erp_do_write_enabled` หรือ section สำหรับ DO writer |
| OpenAPI `DoReceipt` | `{receipt_id (required), do_no, status, data: object (additionalProperties)}` — payload ปลายเปิด ยังไม่มี schema ของ DO จริง |
| test ที่เกี่ยวข้อง | `tests/test_integration.py::test_do_is_staged_without_erp_write` ยืนยัน `erp_write=false` และไม่เกิดแถวซ้ำ |

สรุป: จุดรับ DO ปัจจุบันเป็น staging ล้วน การเพิ่ม writer จะไม่กระทบเส้นทาง SO/eVRP

## ข้อมูลที่ยังขาด (ต้องได้จาก ERP DBA / เจ้าของระบบ ก่อนเริ่ม Phase 2)

### A. Schema ของสองตาราง (ขาดทั้งหมด — ห้ามเดา)

ทั้ง `tbl_DOhdr` และ `tbl_Dodtl` ยังไม่มีข้อมูลใดในรีโป ต้องได้:

- ชนิดข้อมูล ความยาว precision/scale ของทุกคอลัมน์
- nullable และ default constraint ของทุกคอลัมน์
- primary key, unique key/index, identity column, computed column
- foreign key ที่บังคับ เช่น CustCode, Itemcode, Warehouse, LocationCode, SalesPerson
- trigger บนสองตาราง และผลข้างเคียงที่จะเกิดเมื่อ INSERT
- collation ของคอลัมน์ข้อความไทย และชนิด `nvarchar` กับ `varchar`
- คอลัมน์ทั้งหมดที่มีจริงในตาราง (รายการฟิลด์ที่ได้รับอาจไม่ครบทุกคอลัมน์ที่ NOT NULL)

### B. SQL ต้นฉบับที่อ้างถึงในแผน

แผนระบุว่าได้รับ SQL ที่ใช้ placeholder `?xTransNum` และ `?cRun` แต่ไฟล์นี้ไม่มีอยู่ในรีโป
ต้องส่ง SQL/stored procedure ฉบับเต็มมาเก็บไว้ เพื่อใช้เทียบลำดับคอลัมน์และพารามิเตอร์จริง

### C. กฎการสร้างเลขที่เอกสาร

- `TransactionNo`: ใครสร้าง (ERP หรือฝั่งเรา), รูปแบบ, ความยาว, การกันชนกันเมื่อมีหลาย session
- `DoNo`: `?cRun` หมายถึงตาราง/procedure running number ตัวใด และใครถือสิทธิ์เรียก
- `Slno`: เริ่มที่ 0 หรือ 1, unique ภายใน TransactionNo หรือทั้งตาราง
- กติกาเมื่อเลขซ้ำ: ERP จะปฏิเสธด้วย unique constraint หรือรับซ้ำเงียบๆ

### D. แหล่งข้อมูลต้นทางของ DO (ช่องว่างที่ใหญ่ที่สุด)

Header ต้องใช้ประมาณ 45 ฟิลด์ และ Detail อีก 24 ฟิลด์ แต่ payload DO ที่ระบบรับอยู่ตอนนี้เป็น
object ปลายเปิด และ callback ของ eVRP ตามเอกสาร umbrella มีเพียง `do_no`, `so_no`,
`payment_status`, `payment_amt`, `payment_date`, `payment_time`, `payment_send_api`
จึงไม่พอสำหรับ Header/Detail ต้องตกลงว่า:

- DO ที่จะ Insert มาจากเหตุการณ์ใด: COD callback, ผลการจัดส่งจาก eVRP หรือระบบอื่น
- ฟิลด์ที่ไม่ได้มากับ event จะดึงจาก SO ใน ERP ด้วย SELECT หรือให้ ERP เติมเอง
- ถ้าดึงจาก SO ต้องระบุ view/table และ key ที่อนุมัติ (ผูกกับ Phase 01 ที่ยังไม่เสร็จ)
- JSON schema ของ DO ฉบับจริงพร้อมตัวอย่าง payload ที่อนุมัติอย่างน้อย 1 ชุด

### E. กติกาธุรกิจรายฟิลด์ที่ยังไม่มีคำตอบ

| กลุ่ม | ฟิลด์ | ต้องการคำตอบ |
|---|---|---|
| สถานะเอกสาร | `IsApproved`, `IsClosed`, `IsComplete`, `IsCheck`, `Revised` | ค่าเริ่มต้นตอน Insert และใครเป็นผู้เปลี่ยนภายหลัง |
| ประเภทเอกสาร | `DoType`, `VatType`, `IncludeVat` | ค่าที่อนุญาตและความหมายของแต่ละค่า |
| ภาษี/ยอดเงิน | `TotalAmount`, `Discount`, `DiscountAmount`, `TotalDiscountAmount`, `AdvancePay`, `VAT`, `VATAmount`, `TotalActualAmount` | ฝั่งเราคำนวณหรือ ERP คำนวณ, สูตร, การปัดเศษ, จำนวนทศนิยม |
| ลูกค้า/ที่อยู่ | `CustCode`, `CustName`, `BillingAddress`, `ShippingAddress`, `DlvCode` | มาจาก SO หรือ master ลูกค้า และความยาวสูงสุด |
| โลจิสติกส์ | `CarNumber`, `Driver`, `LocationCode`, `LocationName`, `DeliveryDate` | มาจาก eVRP route หรือ ERP และต้องมีค่าเสมอหรือไม่ |
| องค์กร/ขาย | `Company`, `Comname`, `SalesPerson`, `SalesName`, `Market`, `EntryBy` | ค่าคงที่ต่อบริษัท หรือดึงจาก SO และ `EntryBy` ใช้บัญชีใด |
| อื่นๆ | `Promotion`, `Stock`, `Scarp`, `AttachPict`, `RemarkS`, `RemarkCode`, `Paymentinday`, `Time` | ความหมาย ชนิดข้อมูล และค่าที่ยอมรับ (`Time` เป็น time หรือ varchar) |
| Detail อ้างอิง | `SoNo`, `SOtrNo`, `SOline`, `SOstock`, `PoCust`, `PartNoCust`, `PartNameCust`, `DescCust` | ผูกกับ SO อย่างไร และบังคับหรือไม่ |
| Detail สินค้า | `Itemcode`, `Description`, `ItemModel`, `Units`, `Warehouse`, `Qty`, `Nw`, `TotalNw`, `Saleprice`, `DiscountPercent`, `DiscountAmount`, `Amount`, `DeliveryDueDate` | หน่วยและ precision, `TotalNw` คำนวณจาก `Nw * Qty` หรือส่งมา |

### F. สภาพแวดล้อมและสิทธิ์

- ยังไม่มี write credential แยกจากบัญชี read-only และยังไม่ระบุเจ้าของสิทธิ์
- ยังไม่มี test database หรือรายการ DO ที่อนุมัติให้ทดสอบเขียน
- ยังไม่ได้ยืนยันว่า Header และ Detail อยู่ใน transaction เดียวกันได้ (มี trigger หรือ procedure บังคับหรือไม่)
- ยังไม่มีเครื่องที่ติดตั้ง pyodbc + ODBC Driver 18 สำหรับทดสอบจริง
- ยังไม่ได้ตกลง timezone ของ `EntryDate`/`Dodate`/`DeliveryDate` และการใช้ `GETDATE()` กับเวลาของ SQL Server

### G. กติกาความซ้ำและการกู้คืน

- คีย์ใดเป็นตัวตัดสินว่า DO ซ้ำในฝั่ง ERP: `DoNo`, `TransactionNo` หรือทั้งคู่
- ถ้า DO มีอยู่แล้วใน ERP ต้องข้าม, ปฏิเสธ หรือเข้า review
- วิธียืนยันผลเมื่อ timeout หลัง commit: query ด้วย identity ใดจึงจะปลอดภัย (ต้องเป็น SELECT ที่อนุมัติ)

## ผลการ implement รอบ 16-09-26 (หลังผู้ใช้อนุมัติให้เริ่ม)

### ไฟล์ที่เพิ่ม/แก้

| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `thaisausage/do_writer.py` | ใหม่ — `DOWriter`, `build_insert`, `DOWriteDisabled`, `DOWriteAmbiguous` |
| `thaisausage/service.py` | เพิ่มตาราง `do_writes` + unique index และ method `write_do` |
| `config/example.json` | เพิ่ม section `do_write` (enabled=false, write credential env แยก, mapping ว่าง) |
| `tests/test_sqlserver_do.py` | ใหม่ — 18 เคส: statement shape, parameter binding, transaction/rollback/commit |
| `tests/test_do_writer.py` | ใหม่ — 13 เคส: state, duplicate, replay, dry-run, flag off, staging ไม่เปลี่ยน |
| `docs/do-insert-contract.md` (+ PDF) | ใหม่ — mapping matrix 45+24 ฟิลด์สำหรับ DBA |
| `docs/Thaisausage_System_Manual.md` (+ PDF) | เพิ่มหัวข้อ 9.1, ตาราง `do_writes`, config `do_write`, ผลทดสอบใหม่ |
| `docs/Thaisausage_Operations_Guide.md` (+ PDF) | เพิ่มกติกา operator, write credential และ Gate D-DO |
| `docs/README.md` | เพิ่มลิงก์เอกสาร DO contract และลบรายการซ้ำ |

### กติกาที่บังคับไว้ในโค้ด

- flag `do_write.enabled` ปิดเป็นค่าเริ่มต้น เปิดได้จาก config เท่านั้น ไม่มี endpoint สาธารณะเรียก writer
- credential เขียนต้องคนละ env กับ `ERP_SQLSERVER_CONNECTION_STRING`/`ERP_SQL_USER`/`ERP_SQL_PASSWORD`
- validate mapping + payload ก่อนเปิด connection เสมอ (มี test ที่ทำให้ connect ล้มเหลวถ้าถูกเรียกก่อน)
- ชื่อตาราง/คอลัมน์มาจาก config ที่ review แล้ว ค่าทุกค่าผูกเป็น parameter ไม่มีการต่อ string
- Header + Detail อยู่ใน transaction เดียว ล้มเหลวที่ใดก็ rollback ทั้งชุด
- ล้มเหลวระหว่าง commit = `needs_review` ไม่ retry อัตโนมัติ และ replay จะไม่เขียนซ้ำ
- `dry_run=true` ทำได้แค่ validate และนับ statement
- กันซ้ำด้วย `receipt_id` PK + unique `do_no` + unique `transaction_no`

### ผลทดสอบ 16-09-26

| คำสั่ง | ผล |
|---|---|
| `python3 -m unittest discover -s tests -v` | OK — 63 tests (เดิม 32 + ใหม่ 31) |
| `python3 -m json.tool config/example.json` | OK |
| `python3 -m json.tool docs/openapi.json` | OK |
| `git diff --check` | clean |
| smoke test `/health`, `/openapi.json`, `/docs` | 200 ทั้งหมด |
| smoke test `POST /api/v1/erp/do-received` | 202 `{"state": "staged", "erp_write": false}` |

SQL Integration Test: 🚧 BLOCKED / NOT RUN — ไม่มี test database, ไม่มี write credential
และเครื่องพัฒนาไม่มี `pyodbc` ผลทดสอบทั้งหมดมาจาก fake driver จึงไม่ถือเป็นหลักฐานว่าเชื่อมต่อ ERP ได้

## สิ่งที่ทำได้ทันทีเมื่อได้รับข้อมูล

เมื่อได้ A–G ครบ จะดำเนินการตามลำดับ: สร้าง mapping matrix ครบทุกฟิลด์ → เพิ่ม config
`erp_do_write_enabled=false` พร้อม write credential แยก → เขียน DO writer แบบ parameterized
transaction เดียว → เพิ่มชุดทดสอบตามแผน → รันทดสอบและอัปเดตเอกสาร โดยยังไม่เปิด flag บน VPS

## Evidence to record (ยังไม่มี)

- schema metadata และการอนุมัติจาก DBA (redacted)
- mapping matrix และ payload ตัวอย่างที่อนุมัติ
- ผลรันทดสอบอัตโนมัติของ writer
- SQL fixture transaction trace
- ผลยืนยันว่า staging ไม่เขียน ERP
- UAT DO identity พร้อมจำนวนแถวก่อน/หลัง
- ผล duplicate/rollback/timeout reconciliation
- User confirmation และ sign-off
