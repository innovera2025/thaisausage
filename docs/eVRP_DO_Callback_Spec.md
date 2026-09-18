# eVRP → Thai Sausage: DO Callback Specification

- Document version: 2.0.0
- Date: 18 September 2026
- ผู้รับ: ทีมพัฒนา eVRP
- Endpoint: `https://thaisausage.krs.co.th/api/v1/vrp/do-received`

เอกสารนี้อธิบายเฉพาะการส่ง DO กลับมาที่ Thai Sausage การส่ง SO เข้า eVRP ใช้ API ของทาง eVRP ตามคู่มือ
VRP Production API Customer Integration Guide v1.1 ซึ่งฝั่ง Thai Sausage เชื่อมต่อเรียบร้อยแล้ว

## 1. ภาพรวม

```text
Thai Sausage  --- POST /v1/orders/import --->  eVRP        (ตามคู่มือของ eVRP)
eVRP          --- POST /api/v1/vrp/do-received --->  Thai Sausage   (เอกสารนี้)
```

เมื่อ eVRP สร้าง DO เสร็จ ให้ยิงกลับมาที่ endpoint ของเรา ส่งเมื่อไหร่ก็ได้ ระบบเปิดรับตลอดเวลา

## 2. การยืนยันตัวตน

```http
POST /api/v1/vrp/do-received HTTP/1.1
Host: thaisausage.krs.co.th
Authorization: Bearer <THAISAUSAGE_API_KEY>
Content-Type: application/json
```

- `THAISAUSAGE_API_KEY` ทีม Thai Sausage เป็นผู้ออกและส่งให้แยกช่องทาง ไม่อยู่ในเอกสารนี้
- ต้องแนบ header ทุกครั้ง ถ้าไม่มีหรือไม่ถูกต้องจะได้ `401`
- ใช้ HTTPS เท่านั้น

## 3. รูปแบบข้อมูล

ส่ง **ครั้งละ 1 DO** (ไม่ใช่ array หลายรายการใน `data[]`)

```json
{
  "receipt_id": "DO2609040001",
  "do_no": "DO2609040001",
  "status": "accounting_payment_sent",
  "data": {
    "so_no": "SO-L2609-1737",
    "payment_amt": 898.0,
    "payment_date": "2026-09-04",
    "payment_time": "10:30:00",
    "payment_send_api": "2026-09-04 10:35:20"
  }
}
```

| Field | บังคับ | กติกา |
|---|---|---|
| `receipt_id` | ใช่ (หรือใช้ `do_no` แทนได้) | ยาวไม่เกิน 120 ตัวอักษร และต้อง **คงที่ต่อ DO หนึ่งใบ** ทุกครั้งที่ส่งซ้ำ |
| `do_no` | ควรส่ง | เลขที่ DO |
| `status` | ไม่บังคับ | สถานะฝั่ง eVRP |
| `data` | ไม่บังคับ | object อิสระ ใส่ฟิลด์ใดก็ได้ ระบบเก็บทั้งก้อน |

ฟิลด์ที่ **ไม่ต้องส่ง** เพราะระบบเราสร้างเองตอนบันทึกเข้า ERP: `TransactionNo`, `Slno`, `EntryDate`,
`IsAcc`, `IsAccBy`, `IsAccDate`, `DocuNw`

## 4. คำตอบที่จะได้รับ

| HTTP | เมื่อไหร่ | ความหมายฝั่ง eVRP |
|---|---|---|
| `202` | รับและบันทึกแล้ว | สำเร็จ ไม่ต้องส่งซ้ำ |
| `202` + `"replayed": true` | ส่งซ้ำด้วย payload เดิม | สำเร็จ ระบบไม่สร้างข้อมูลซ้ำ |
| `409` | `receipt_id` เดิมแต่ข้อมูลเปลี่ยน | หยุดและตรวจสอบ ห้ามส่งต่อด้วย id เดิม ให้ใช้ `receipt_id` ใหม่ |
| `401` | ไม่มีหรือผิด API key | แก้ credential แล้วส่งใหม่ได้ |
| `422` | JSON ผิดรูป, ไม่ใช่ `application/json`, หรือไม่มีทั้ง `receipt_id` และ `do_no` | แก้ payload แล้วส่งใหม่ |
| `500` | ปัญหาฝั่งเรา | ส่งใหม่ได้ และแจ้งทีม Thai Sausage |

ตัวอย่างคำตอบเมื่อสำเร็จ:

```json
{"receipt_id": "DO2609040001", "receipt_key": "eVRP:DO2609040001",
 "source": "eVRP", "state": "staged", "erp_write": false}
```

ส่งซ้ำด้วยข้อมูลเดิมจะได้ก้อนเดิมพร้อม `"replayed": true`

## 5. กติกาที่ควรทราบ

- **ส่งซ้ำได้ปลอดภัย** ระบบใช้ `receipt_id` เป็นตัวระบุ และเทียบเนื้อหาด้วย hash จึงไม่เกิดข้อมูลซ้ำ
- **ยิงพร้อมกันได้** ถ้าส่ง DO ใบเดียวกันสองครั้งพร้อมกัน ระบบจองสิทธิ์ในทรานแซกชันเดียว จะได้ `202` ทั้งคู่ ไม่มี `500`
- **เราไม่ส่งอะไรกลับไป eVRP** หลังรับ DO ไม่มี callback ย้อนกลับ
- **`erp_write: false` ในระยะนี้** DO ถูกเก็บเข้าพื้นที่ตรวจสอบ (staging) ก่อนเสมอ การบันทึกเข้า ERP
  เป็นขั้นตอนที่ทีม Thai Sausage สั่งเองทีละใบหลังตรวจแล้ว

## 6. ทดสอบ

```sh
curl -X POST https://thaisausage.krs.co.th/api/v1/vrp/do-received \
  -H "Authorization: Bearer <THAISAUSAGE_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"receipt_id":"TEST-001","do_no":"TEST-001","status":"test",
       "header":{"do_no":"TEST-001","dodate":"2026-09-18","cust_code":"CT-MS-BKK-2092"},
       "details":[{"item_code":"A20-002","qty":10,"units":"ลัง","amount":5950.00}]}'
```

ตรวจสัญญาเพิ่มเติมได้ที่ `https://thaisausage.krs.co.th/openapi.json`
(หน้า Swagger อยู่ที่ `/docs`)

### 6.1 ชุดทดสอบที่แนะนำ (ทีม eVRP ทดสอบเองได้เลย)

ระบบเปิดรับตลอดเวลา ไม่ต้องนัดหมายล่วงหน้า ทดสอบ 5 เคสนี้ได้ครบในไม่กี่นาที

| # | ทดสอบ | วิธี | ผลที่ควรได้ |
|---|---|---|---|
| 1 | ส่งปกติ | POST ด้วย `receipt_id` ใหม่ | `202` · `state: staged` · `erp_write: false` |
| 2 | ส่งซ้ำ | POST ก้อนเดิมอีกครั้ง | `202` · `replayed: true` · ไม่เกิดข้อมูลซ้ำ |
| 3 | ข้อมูลเปลี่ยน | `receipt_id` เดิม แก้ค่าใน `header` หรือ `details` | `409` |
| 4 | ไม่มี key | ตัด header `Authorization` ออก | `401` |
| 5 | ข้อมูลไม่ครบ | ไม่ส่งทั้ง `receipt_id` และ `do_no` | `422` |

ทดสอบพร้อมกันหลาย request ด้วย `receipt_id` เดียวกันก็ได้ — ระบบจะตอบ `202` ทุกคำขอ
โดยเก็บข้อมูลเพียงชุดเดียว ไม่มี `500`

**ใช้ `receipt_id` ที่ขึ้นต้นด้วย `TEST-` สำหรับการทดสอบ** เพื่อให้เราแยกออกจากของจริงตอนกระทบยอด

**`erp_write: false` เป็นผลที่ถูกต้องในระยะนี้** DO ที่ท่านส่งมาจะถูกเก็บไว้ในพื้นที่ตรวจสอบของเรา
ก่อน แล้วทีม Thai Sausage จึงสั่งบันทึกเข้า ERP ทีละใบหลังตรวจความถูกต้อง การทดสอบของท่านจึงไม่
กระทบข้อมูลใน ERP

ทดสอบเสร็จแจ้งกลับมาได้เลยครับ เราจะตรวจฝั่งเราแล้วยืนยันว่าได้รับครบทุกใบ

## 7. สถานะการเชื่อมต่อ SO (อัปเดต 18 กันยายน 2026)

ส่ง SO เข้า eVRP สำเร็จแล้ว ขอบคุณสำหรับรหัส hub และการตั้ง master ครับ

| เรื่อง | สถานะ |
|---|---|
| `pickup_hub_code` = `TS-h01` | ✅ ใช้งานได้ |
| `delivery_date` = order_date + 1 วัน (ข้ามวันอาทิตย์) | ✅ ส่งตามที่ตกลง |
| Customer master 7 ราย | ✅ ส่งผ่านแล้ว |
| `CT-LR-BKK-2088` ซี.เจ.เอ็กซ์เพรส | ⏳ **ยังไม่มี master** — SO ที่อ้างถึงลูกค้ารายนี้ถูกพักไว้ที่ฝั่งเรา ยังไม่ส่งซ้ำ รบกวนแจ้งเมื่อตั้งเสร็จ |

ผลการส่งจริงวันแรก: 10 ใบสำเร็จ (`running_code` 260916000001–260916000010) และ 2 ใบรอลูกค้ารายข้างต้น

ปริมาณเฟสแรก: หจก. ไทยซอสเทรดดิ้ง ประมาณ 10 SO ต่อวัน จากคลังนครปฐม

## 8. DO ที่ส่งมาแล้วเกิดอะไรขึ้น

1. ระบบตรวจ JSON และจองรหัสอ้างอิง (`eVRP:<receipt_id>`) ในทรานแซกชันเดียว
2. เก็บ payload ทั้งก้อนไว้ในพื้นที่ตรวจสอบของ Thai Sausage
3. ตอบ `202` พร้อม `erp_write: false`

การบันทึกเข้า ERP **ยังไม่เปิดอัตโนมัติ** ในระยะนี้ ทีม Thai Sausage จะเลือกบันทึกทีละใบด้วยมือ
ภายใต้การตรวจสอบ จึงไม่มีผลข้างเคียงกับ ERP จากการที่ท่านทดสอบยิงเข้ามา

## 9. รูปแบบ DO ที่ขอให้ส่งมา (เพื่อบันทึกเข้า ERP)

ERP บันทึก DO ลงสองตาราง ทีม Thai Sausage กำหนดชื่อฟิลด์ใน JSON ให้ตรงกับคอลัมน์ของ ERP แล้ว
ส่งเท่าที่มีได้ก่อนก็ได้ ฟิลด์ที่ไม่ส่งจะถูกบันทึกเป็น NULL ยกเว้นฟิลด์ที่ระบุว่าบังคับ

```json
{
  "receipt_id": "DO2609180001",
  "do_no": "DO2609180001",
  "status": "delivered",
  "header": {
    "do_no": "DO2609180001",
    "dodate": "2026-09-18",
    "delivery_date": "2026-09-19",
    "cust_code": "CT-MS-BKK-2092",
    "cust_name": "บริษัท ไทย ฟู้ดส์ เฟรซ มาร์เก็ต จำกัด",
    "shipping_address": "…",
    "car_number": "70-1234 กรุงเทพมหานคร",
    "driver": "สมชาย ใจดี",
    "location_code": "TS-h01",
    "total_amount": 1070.50,
    "vat_amount": 70.00,
    "total_actual_amount": 1140.50,
    "paymentinday": "30"
  },
  "details": [
    {
      "item_code": "A20-002",
      "description": "ซอสหอยนางรมตราทะเลงามพรีเมี่ยม950ก.1*12",
      "so_no": "SO-L2609-1737",
      "qty": 10,
      "units": "ลัง",
      "saleprice": 595.00,
      "amount": 5950.00,
      "warehouse": "WH01"
    }
  ]
}
```

ฟิลด์ที่ **ไม่ต้องส่ง** เพราะระบบเรากำหนดเอง: `TransactionNo` (ออกเลขอัตโนมัติ), `Slno` (ลำดับบรรทัด),
`EntryDate` (เวลาของ SQL Server), `IsAcc` = 0, `IsAccBy` = NULL, `IsAccDate` = NULL, `DocuNw` = NULL

ฟิลด์ที่ **ส่งก็ได้ ไม่ส่งก็ได้** — ถ้าไม่ส่ง ระบบจะใส่ค่าที่ทีม ERP กำหนดไว้ให้ (ยืนยัน 18 ก.ย. 2026)

| ฟิลด์ใน JSON | ค่าที่ใส่ให้ถ้าไม่ส่ง |
|---|---|
| `is_approved` | `0` |
| `is_closed` | `0` |
| `is_complete` | `0` |
| `is_check` | `0` |
| `revised` | `0` |
| `do_type` | `ขนส่งโดยบริษัท` |

### 9.1 หัวเอกสาร — `header`

| คอลัมน์ใน ERP | ฟิลด์ใน JSON | ที่มา | บังคับ |
|---|---|---|---|
| `TransactionNo` | — | ระบบเราออกเลขเอง |  |
| `DoNo` | `do_no` | eVRP ส่งมา | ใช่ |
| `Dodate` | `dodate` | eVRP ส่งมา |  |
| `IsApproved` | `is_approved` | eVRP ส่งมา |  |
| `IsApprovedBy` | `is_approved_by` | eVRP ส่งมา |  |
| `IsApprovedDate` | `is_approved_date` | eVRP ส่งมา |  |
| `IsClosed` | `is_closed` | eVRP ส่งมา |  |
| `IsClosedBy` | `is_closed_by` | eVRP ส่งมา |  |
| `IsClosedDate` | `is_closed_date` | eVRP ส่งมา |  |
| `IsComplete` | `is_complete` | eVRP ส่งมา |  |
| `IsCompleteBy` | `is_complete_by` | eVRP ส่งมา |  |
| `IsCompleteDate` | `is_complete_date` | eVRP ส่งมา |  |
| `IsCheck` | `is_check` | eVRP ส่งมา |  |
| `IsCheckBy` | `is_check_by` | eVRP ส่งมา |  |
| `IsCheckDate` | `is_check_date` | eVRP ส่งมา |  |
| `IsAcc` | — | ค่าคงที่ |  |
| `IsAccBy` | — | ค่าคงที่ |  |
| `IsAccDate` | — | ค่าคงที่ |  |
| `Revised` | `revised` | eVRP ส่งมา |  |
| `DoType` | `do_type` | eVRP ส่งมา |  |
| `DeliveryDate` | `delivery_date` | eVRP ส่งมา |  |
| `CarNumber` | `car_number` | eVRP ส่งมา |  |
| `CustCode` | `cust_code` | eVRP ส่งมา | ใช่ |
| `CustName` | `cust_name` | eVRP ส่งมา |  |
| `BillingAddress` | `billing_address` | eVRP ส่งมา |  |
| `ShippingAddress` | `shipping_address` | eVRP ส่งมา |  |
| `DlvCode` | `dlv_code` | eVRP ส่งมา |  |
| `RemarkS` | `remark_s` | eVRP ส่งมา |  |
| `AttachPict` | `attach_pict` | eVRP ส่งมา |  |
| `DocuNw` | — | ค่าคงที่ |  |
| `VatType` | `vat_type` | eVRP ส่งมา |  |
| `EntryBy` | `entry_by` | eVRP ส่งมา |  |
| `EntryDate` | — | เวลาของ SQL Server |  |
| `Company` | `company` | eVRP ส่งมา |  |
| `Comname` | `comname` | eVRP ส่งมา |  |
| `SalesPerson` | `sales_person` | eVRP ส่งมา |  |
| `SalesName` | `sales_name` | eVRP ส่งมา |  |
| `Promotion` | `promotion` | eVRP ส่งมา |  |
| `Stock` | `stock` | eVRP ส่งมา |  |
| `Scarp` | `scarp` | eVRP ส่งมา |  |
| `Paymentinday` | `paymentinday` | eVRP ส่งมา |  |
| `Time` | `time` | eVRP ส่งมา |  |
| `Market` | `market` | eVRP ส่งมา |  |
| `TotalAmount` | `total_amount` | eVRP ส่งมา |  |
| `Discount` | `discount` | eVRP ส่งมา |  |
| `DiscountAmount` | `discount_amount` | eVRP ส่งมา |  |
| `TotalDiscountAmount` | `total_discount_amount` | eVRP ส่งมา |  |
| `AdvancePay` | `advance_pay` | eVRP ส่งมา |  |
| `VAT` | `vat` | eVRP ส่งมา |  |
| `VATAmount` | `vat_amount` | eVRP ส่งมา |  |
| `TotalActualAmount` | `total_actual_amount` | eVRP ส่งมา |  |
| `LocationCode` | `location_code` | eVRP ส่งมา |  |
| `LocationName` | `location_name` | eVRP ส่งมา |  |
| `Driver` | `driver` | eVRP ส่งมา |  |
| `RemarkCode` | `remark_code` | eVRP ส่งมา |  |

### 9.2 รายการสินค้า — `details[]`

| คอลัมน์ใน ERP | ฟิลด์ใน JSON | ที่มา | บังคับ |
|---|---|---|---|
| `TransactionNo` | — | ระบบเราออกเลขเอง |  |
| `Slno` | — | ระบบเราใส่ลำดับเอง |  |
| `Itemcode` | `item_code` | eVRP ส่งมา | ใช่ |
| `Description` | `description` | eVRP ส่งมา |  |
| `ItemModel` | `item_model` | eVRP ส่งมา |  |
| `PartNoCust` | `part_no_cust` | eVRP ส่งมา |  |
| `PartNameCust` | `part_name_cust` | eVRP ส่งมา |  |
| `DescCust` | `desc_cust` | eVRP ส่งมา |  |
| `SoNo` | `so_no` | eVRP ส่งมา |  |
| `SOtrNo` | `s_otr_no` | eVRP ส่งมา |  |
| `SOline` | `s_oline` | eVRP ส่งมา |  |
| `SOstock` | `s_ostock` | eVRP ส่งมา |  |
| `PoCust` | `po_cust` | eVRP ส่งมา |  |
| `DeliveryDueDate` | `delivery_due_date` | eVRP ส่งมา |  |
| `Qty` | `qty` | eVRP ส่งมา | ใช่ |
| `Nw` | `nw` | eVRP ส่งมา |  |
| `TotalNw` | `total_nw` | eVRP ส่งมา |  |
| `Saleprice` | `saleprice` | eVRP ส่งมา |  |
| `Units` | `units` | eVRP ส่งมา |  |
| `IncludeVat` | `include_vat` | eVRP ส่งมา |  |
| `Warehouse` | `warehouse` | eVRP ส่งมา |  |
| `DiscountPercent` | `discount_percent` | eVRP ส่งมา |  |
| `DiscountAmount` | `discount_amount` | eVRP ส่งมา |  |
| `Amount` | `amount` | eVRP ส่งมา |  |

ชื่อฟิลด์ใน JSON คือชื่อคอลัมน์ของ ERP แปลงเป็นตัวพิมพ์เล็กคั่นด้วย `_` จึงเทียบกลับได้ตรงตัว
หากฟิลด์ใดระบบท่านไม่มีหรือใช้ชื่ออื่น แจ้งกลับมาได้ เราปรับที่ฝั่งเราโดยไม่ต้องแก้ระบบท่าน
