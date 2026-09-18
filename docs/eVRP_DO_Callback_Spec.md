# eVRP → Thai Sausage: DO Callback Specification

- Document version: 1.2.0
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
- **`erp_write: false` ในระยะนี้** DO ถูกเก็บเข้าพื้นที่ตรวจสอบ (staging) เท่านั้น ยังไม่ถูกบันทึกเข้า ERP
  จนกว่าจะตกลง mapping ครบและผ่าน UAT ร่วมกัน

## 6. ทดสอบ

```sh
curl -X POST https://thaisausage.krs.co.th/api/v1/vrp/do-received \
  -H "Authorization: Bearer <THAISAUSAGE_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"receipt_id":"DO-TEST-001","do_no":"DO-TEST-001","status":"test",
       "data":{"so_no":"SO-TEST-001"}}'
```

ตรวจสัญญาเพิ่มเติมได้ที่ `https://thaisausage.krs.co.th/openapi.json`
(หน้า Swagger อยู่ที่ `/docs`)

### 6.1 ชุดทดสอบที่แนะนำ (ทีม eVRP ทดสอบเองได้เลย)

ระบบเปิดรับตลอดเวลา ไม่ต้องนัดหมายล่วงหน้า ทดสอบ 5 เคสนี้ได้ครบในไม่กี่นาที

| # | ทดสอบ | วิธี | ผลที่ควรได้ |
|---|---|---|---|
| 1 | ส่งปกติ | POST ด้วย `receipt_id` ใหม่ | `202` · `state: staged` · `erp_write: false` |
| 2 | ส่งซ้ำ | POST ก้อนเดิมอีกครั้ง | `202` · `replayed: true` · ไม่เกิดข้อมูลซ้ำ |
| 3 | ข้อมูลเปลี่ยน | `receipt_id` เดิม แก้ค่าใน `data` | `409` |
| 4 | ไม่มี key | ตัด header `Authorization` ออก | `401` |
| 5 | ข้อมูลไม่ครบ | ไม่ส่งทั้ง `receipt_id` และ `do_no` | `422` |

ทดสอบพร้อมกันหลาย request ด้วย `receipt_id` เดียวกันก็ได้ — ระบบจะตอบ `202` ทุกคำขอ
โดยเก็บข้อมูลเพียงชุดเดียว ไม่มี `500`

**ใช้ `receipt_id` ที่ขึ้นต้นด้วย `TEST-` สำหรับการทดสอบ** เพื่อให้เราแยกออกจากของจริงตอนกระทบยอด

**`erp_write: false` เป็นผลที่ถูกต้องในระยะนี้** DO จะถูกเก็บไว้ในพื้นที่ตรวจสอบของเราเท่านั้น
ยังไม่บันทึกเข้า ERP จนกว่าจะตกลง mapping และผ่าน UAT ร่วมกัน

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
ระบบส่งอัตโนมัติตามรอบ ทุก SO ส่งครั้งเดียว และมีระบบกันส่งซ้ำฝั่งเรา
