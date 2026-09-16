# ERP DO Insert Contract — Mapping Matrix

Date: 16 September 2026  
Status: 🚧 รอ ERP DBA เติมชนิดข้อมูลและยืนยันแหล่งข้อมูล  
Target tables: `tbl_DOhdr` (Header) และ `tbl_Dodtl` (Detail)  
Plan: `process/features/erp-sqlserver/active/PHASE_07_DO_INSERT_PLAN_16-09-26.md`

เอกสารนี้คือแบบฟอร์มสำหรับให้ ERP DBA และเจ้าของระบบเติมให้ครบ ช่องที่เขียนว่า "รอ DBA"
คือข้อมูลที่ระบบจะไม่เดาเด็ดขาด writer จะไม่ทำงานจนกว่า mapping จะครบและมีการเปิด flag

## 1. ค่าที่ยืนยันแล้วจาก contract

| ฟิลด์ | ค่า | วิธี implement |
|---|---|---|
| `IsAcc` | 0 | `{"source": "fixed", "value": 0}` |
| `IsAccBy` | NULL | `{"source": "fixed", "value": null}` |
| `IsAccDate` | NULL | `{"source": "fixed", "value": null}` |
| `DocuNw` | NULL | `{"source": "fixed", "value": null}` |
| `EntryDate` | เวลาของ SQL Server | `{"source": "server_time"}` ใส่ `GETDATE()` ลงใน statement ไม่ใช่ค่าจากเรา |
| `TransactionNo` | ค่าเดียวกันทั้ง Header และ Detail | `{"source": "transaction_no"}` |

## 2. วิธีเขียน mapping ใน config

ทุกคอลัมน์ระบุแหล่งที่มาได้ 5 แบบ และค่าทุกค่าถูกส่งเป็น SQL parameter เสมอ

| source | ความหมาย |
|---|---|
| `payload` | อ่านจาก JSON ตาม `path` เช่น `"customer.name"` ใส่ `"required": true` เมื่อห้ามเป็น null |
| `fixed` | ค่าคงที่จาก contract เช่น `IsAcc` |
| `transaction_no` | เลข TransactionNo ที่ผูก Header กับ Detail |
| `line_no` | ลำดับบรรทัดของ Detail เริ่มที่ `detail_line_start` |
| `server_time` | ใช้ `GETDATE()` ของ SQL Server |

```json
"do_write": {
  "enabled": false,
  "header_table": "dbo.tbl_DOhdr",
  "detail_table": "dbo.tbl_Dodtl",
  "header_columns": {
    "TransactionNo": {"source": "transaction_no"},
    "DoNo": {"source": "payload", "path": "do_no", "required": true},
    "IsAcc": {"source": "fixed", "value": 0},
    "EntryDate": {"source": "server_time"}
  },
  "detail_columns": {
    "TransactionNo": {"source": "transaction_no"},
    "Slno": {"source": "line_no"},
    "Itemcode": {"source": "payload", "path": "item_code", "required": true}
  }
}
```

## 3. Header — `tbl_DOhdr`

สถานะ: ✅ ยืนยันแล้ว · 🟡 เสนอไว้รอยืนยัน · 🔴 ยังไม่มีคำตอบ

| ERP field | ชนิด/ความยาว | Null | แหล่งที่เสนอ | การแปลง / กติกา | สถานะ |
|---|---|---|---|---|---|
| `TransactionNo` | รอ DBA | รอ DBA | ระบบสร้างหรือ ERP สร้าง | ต้องตกลงรูปแบบและการกันชนกัน | 🔴 |
| `DoNo` | รอ DBA | รอ DBA | running number `?cRun` | ใครเป็นผู้ออกเลข | 🔴 |
| `Dodate` | รอ DBA | รอ DBA | วันที่ออก DO | timezone และรูปแบบ | 🟡 |
| `DeliveryDate` | รอ DBA | รอ DBA | วันที่จัดส่งจาก SO หรือ eVRP | ต้องมีค่าเสมอหรือไม่ | 🟡 |
| `DoType` | รอ DBA | รอ DBA | รอกำหนด | ค่าที่อนุญาตและความหมาย | 🔴 |
| `IsApproved` | รอ DBA | รอ DBA | ค่าเริ่มต้นตอน Insert | ใครเปลี่ยนภายหลัง | 🔴 |
| `IsClosed` | รอ DBA | รอ DBA | ค่าเริ่มต้นตอน Insert | — | 🔴 |
| `IsComplete` | รอ DBA | รอ DBA | ค่าเริ่มต้นตอน Insert | — | 🔴 |
| `IsCheck` | รอ DBA | รอ DBA | ค่าเริ่มต้นตอน Insert | — | 🔴 |
| `Revised` | รอ DBA | รอ DBA | ค่าเริ่มต้นตอน Insert | นับรอบแก้ไขอย่างไร | 🔴 |
| `IsAcc` | รอ DBA | ไม่ | ค่าคงที่ `0` | — | ✅ |
| `CustCode` | รอ DBA | รอ DBA | จาก SO | FK ไปตารางลูกค้าหรือไม่ | 🟡 |
| `CustName` | รอ DBA | รอ DBA | จาก SO หรือ master | ตัดความยาวอย่างไรถ้าเกิน | 🟡 |
| `BillingAddress` | รอ DBA | รอ DBA | จาก SO หรือ master | — | 🟡 |
| `ShippingAddress` | รอ DBA | รอ DBA | จาก SO | — | 🟡 |
| `DlvCode` | รอ DBA | รอ DBA | จุดส่งของ SO | ตรงกับ delivery point ของ eVRP หรือไม่ | 🟡 |
| `CarNumber` | รอ DBA | รอ DBA | จากผลจัดส่ง eVRP | ถ้าไม่มีค่าให้ใส่อะไร | 🟡 |
| `Driver` | รอ DBA | รอ DBA | จากผลจัดส่ง eVRP | เก็บชื่อหรือรหัส | 🟡 |
| `LocationCode` | รอ DBA | รอ DBA | คลัง/สาขาต้นทาง | FK หรือไม่ | 🟡 |
| `LocationName` | รอ DBA | รอ DBA | ชื่อของ LocationCode | ต้องตรงกับ master | 🟡 |
| `RemarkS` | รอ DBA | รอ DBA | หมายเหตุ | ความยาวสูงสุด | 🟡 |
| `RemarkCode` | รอ DBA | รอ DBA | รอกำหนด | ค่าที่อนุญาต | 🔴 |
| `AttachPict` | รอ DBA | รอ DBA | รอกำหนด | เก็บ path, ไบนารี หรือ NULL | 🔴 |
| `DocuNw` | รอ DBA | ใช่ | ค่าคงที่ NULL | — | ✅ |
| `VatType` | รอ DBA | รอ DBA | จาก SO | ค่าที่อนุญาตและความหมาย | 🔴 |
| `VAT` | รอ DBA | รอ DBA | อัตราภาษี | เราคำนวณหรือ ERP คำนวณ | 🔴 |
| `VATAmount` | รอ DBA | รอ DBA | ยอดภาษี | สูตรและการปัดเศษ | 🔴 |
| `TotalAmount` | รอ DBA | รอ DBA | ยอดรวมก่อนส่วนลด | precision/scale | 🔴 |
| `Discount` | รอ DBA | รอ DBA | ส่วนลด | เป็นเปอร์เซ็นต์หรือจำนวนเงิน | 🔴 |
| `DiscountAmount` | รอ DBA | รอ DBA | ยอดส่วนลด | ต่างจาก `TotalDiscountAmount` อย่างไร | 🔴 |
| `TotalDiscountAmount` | รอ DBA | รอ DBA | ยอดส่วนลดรวม | — | 🔴 |
| `AdvancePay` | รอ DBA | รอ DBA | เงินมัดจำ | มาจากไหน | 🔴 |
| `TotalActualAmount` | รอ DBA | รอ DBA | ยอดสุทธิ | สูตรและการปัดเศษ | 🔴 |
| `Paymentinday` | รอ DBA | รอ DBA | เครดิตจาก SO | ตรงกับ `payment_in_day` ของ SO หรือไม่ | 🟡 |
| `EntryBy` | รอ DBA | รอ DBA | บัญชีผู้บันทึก | ใช้ user ใดสำหรับ integration | 🔴 |
| `EntryDate` | รอ DBA | รอ DBA | `GETDATE()` | ยืนยัน timezone ของ server | ✅ |
| `Company` | รอ DBA | รอ DBA | รหัสบริษัท | ค่าคงที่ต่อ environment หรือจาก SO | 🟡 |
| `Comname` | รอ DBA | รอ DBA | ชื่อบริษัท | — | 🟡 |
| `SalesPerson` | รอ DBA | รอ DBA | จาก SO | FK หรือไม่ | 🟡 |
| `SalesName` | รอ DBA | รอ DBA | จาก SO | — | 🟡 |
| `Market` | รอ DBA | รอ DBA | รอกำหนด | ความหมายและค่าที่อนุญาต | 🔴 |
| `Promotion` | รอ DBA | รอ DBA | รอกำหนด | — | 🔴 |
| `Stock` | รอ DBA | รอ DBA | รอกำหนด | — | 🔴 |
| `Scarp` | รอ DBA | รอ DBA | รอกำหนด | สะกดตามตารางจริงหรือไม่ | 🔴 |
| `Time` | รอ DBA | รอ DBA | เวลาออกเอกสาร | ชนิดเป็น time หรือ varchar | 🔴 |

## 4. Detail — `tbl_Dodtl`

| ERP field | ชนิด/ความยาว | Null | แหล่งที่เสนอ | การแปลง / กติกา | สถานะ |
|---|---|---|---|---|---|
| `TransactionNo` | รอ DBA | ไม่ | เท่ากับ Header | — | ✅ |
| `Slno` | รอ DBA | รอ DBA | ลำดับบรรทัด | เริ่มที่ 0 หรือ 1 และ unique ระดับใด | 🔴 |
| `Itemcode` | รอ DBA | รอ DBA | รหัสสินค้าจาก SO | FK ไป master สินค้า | 🟡 |
| `Description` | รอ DBA | รอ DBA | ชื่อสินค้า | — | 🟡 |
| `ItemModel` | รอ DBA | รอ DBA | รอกำหนด | — | 🔴 |
| `PartNoCust` | รอ DBA | รอ DBA | รหัสสินค้าฝั่งลูกค้า | บังคับหรือไม่ | 🔴 |
| `PartNameCust` | รอ DBA | รอ DBA | ชื่อสินค้าฝั่งลูกค้า | — | 🔴 |
| `DescCust` | รอ DBA | รอ DBA | คำอธิบายฝั่งลูกค้า | — | 🔴 |
| `SoNo` | รอ DBA | รอ DBA | เลข SO ต้นทาง | ผูกกับ SO อย่างไร | 🟡 |
| `SOtrNo` | รอ DBA | รอ DBA | TransactionNo ของ SO | ต้องดึงจากตาราง SO | 🔴 |
| `SOline` | รอ DBA | รอ DBA | บรรทัดของ SO | — | 🔴 |
| `SOstock` | รอ DBA | รอ DBA | รอกำหนด | — | 🔴 |
| `PoCust` | รอ DBA | รอ DBA | เลข PO ของลูกค้า | — | 🟡 |
| `DeliveryDueDate` | รอ DBA | รอ DBA | กำหนดส่ง | timezone/รูปแบบ | 🟡 |
| `Qty` | รอ DBA | รอ DBA | จำนวนที่ส่งจริง | precision/scale และหน่วย | 🟡 |
| `Nw` | รอ DBA | รอ DBA | น้ำหนักสุทธิต่อหน่วย | หน่วยน้ำหนัก | 🟡 |
| `TotalNw` | รอ DBA | รอ DBA | น้ำหนักรวม | เราคำนวณ `Nw * Qty` หรือ ERP คำนวณ | 🔴 |
| `Saleprice` | รอ DBA | รอ DBA | ราคาต่อหน่วยจาก SO | precision/scale | 🟡 |
| `Units` | รอ DBA | รอ DBA | หน่วยขาย | FK ไป master หน่วย | 🟡 |
| `IncludeVat` | รอ DBA | รอ DBA | ราคารวมภาษีหรือไม่ | ค่าที่อนุญาต | 🔴 |
| `Warehouse` | รอ DBA | รอ DBA | คลังที่ตัดของ | FK หรือไม่ | 🟡 |
| `DiscountPercent` | รอ DBA | รอ DBA | ส่วนลดรายบรรทัด | — | 🔴 |
| `DiscountAmount` | รอ DBA | รอ DBA | ยอดส่วนลดรายบรรทัด | — | 🔴 |
| `Amount` | รอ DBA | รอ DBA | ยอดรวมบรรทัด | สูตรและการปัดเศษ | 🔴 |

## 5. คำถามที่ต้องตอบก่อนเปิดใช้งาน

1. schema จริงของทั้งสองตาราง: ชนิด ความยาว precision nullable default identity computed trigger FK และ collation
2. SQL ต้นฉบับฉบับเต็มที่ใช้ `?xTransNum` และ `?cRun`
3. กฎการออก `TransactionNo`, `DoNo`, `Slno` และการกันเลขชนกันเมื่อมีหลาย process
4. DO ที่จะ Insert มาจากเหตุการณ์ใด และ payload ตัวอย่างที่อนุมัติอย่างน้อย 1 ชุด
5. ฟิลด์ใดดึงจาก SO ใน ERP ได้ (ต้องระบุ view/table ที่อนุมัติ) และฟิลด์ใดให้ ERP เติมเอง
6. คีย์ที่ใช้ตัดสินว่า DO ซ้ำในฝั่ง ERP และวิธี query ยืนยันผลเมื่อ timeout หลัง commit
7. write credential แยก ผู้ถือสิทธิ์ และ test database ที่อนุญาตให้ทดสอบเขียน

## 6. สถานะการ implement

| ส่วน | สถานะ |
|---|---|
| Writer module `thaisausage/do_writer.py` | 🔨 CODE DONE — flag ปิดเป็นค่าเริ่มต้น |
| Service `write_do` + ตาราง `do_writes` | 🔨 CODE DONE |
| Mapping จริงของ 45+24 ฟิลด์ | 🚧 BLOCKED — รอข้อ 1–5 |
| ทดสอบกับ SQL Server จริง | 🚧 BLOCKED — ไม่มี test database และ write credential |
| เปิดใช้งาน production | 🚧 BLOCKED — รอ UAT และ sign-off |
