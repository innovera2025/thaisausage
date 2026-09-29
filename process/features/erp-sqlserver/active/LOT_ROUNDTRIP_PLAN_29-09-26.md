# แผน: ส่ง Lot ไป eVRP และรับกลับมาใน DO

Date: 29-09-26
Status: 📋 PLAN — ยังไม่เริ่ม รอผลสำรวจและคำตอบจากสองทีม

## สิ่งที่รู้แล้ว

| เรื่อง | สถานะ |
|---|---|
| สัญญา API ของ eVRP (v1.2 §8.2) | **ไม่มีฟิลด์ lot** — มีแค่ line_no, item_code, description, cbm, nw, main_unit, pack_unit, quantity, unit_price |
| การแมป DO ของเรา (24 คอลัมน์รายละเอียด) | **ไม่มีคอลัมน์ lot** — script INSERT ที่ทีม ERP ให้มาไม่มี |
| SQL ที่ดึง SO | **ไม่ได้ดึง lot** |

แปลว่างานนี้ไม่ใช่การต่อท่อที่มีอยู่แล้ว แต่ต้องเพิ่มของใหม่ทั้งสามฝั่ง

## คำถามที่ต้องตอบก่อน — ข้อ 1 สำคัญที่สุด

### 1. ใครเป็นคนกำหนด lot

| ถ้า | แปลว่า | งานที่ต้องทำ |
|---|---|---|
| **ERP กำหนดตอนเปิด SO** | lot ผูกกับออเดอร์ตั้งแต่ต้น | ส่งไป-รับกลับ ตามที่สั่ง |
| **คลังเลือกตอนหยิบของ** | ตอนเปิด SO ยังไม่รู้ lot | **ไม่ต้องส่งไป** — ให้ eVRP/คลังเป็นคนบอกกลับมาทางเดียว |

ถ้าเป็นแบบที่สอง การส่ง lot ไปกับ SO จะส่งค่าว่างไปเปล่าๆ ทุกใบ และงานครึ่งหนึ่งในแผนนี้ตัดทิ้งได้

### 2. หนึ่งบรรทัดใช้ได้กี่ lot

ถ้าสินค้าตัวเดียว 170 ลัง หยิบจาก 3 lot ต้องตัดสินใจว่า

- **หนึ่งบรรทัด = หนึ่ง lot** → eVRP ต้องแตกบรรทัดให้ กระทบ `Slno`, `Qty`, `Amount` และจำนวนบรรทัดจะไม่ตรงกับ SO
- **หนึ่งบรรทัดหลาย lot** → ต้องเก็บเป็นข้อความรวม เช่น `L2609/01,L2609/02` ซึ่ง ERP อาจคำนวณต่อไม่ได้

### 3. eVRP ยอมเพิ่มฟิลด์ไหม

v1.2 ไม่มี `lot` ในสัญญา item การส่งค่าที่เขาไม่รู้จักไปอาจถูกทิ้งเงียบๆ — และต่อให้เขารับไว้ ก็ต้อง **เก็บและส่งกลับ** ซึ่งเป็นงานพัฒนาฝั่งเขา เหมือนที่เขาทำให้กับ `company`/`comname`/`vat_type` ใน v1.2 §7

## สำรวจก่อน — คำสั่งอ่านอย่างเดียว

```sh
cd /opt/thaisausage
docker compose -f deploy/docker-compose.yml exec -T thaisausage python -c "
from thaisausage.config import load_config
from thaisausage.sqlserver import SQLServerConnector
config = load_config('/app/config/local.json')
connector = SQLServerConnector(config['sqlserver'])
connection = connector.connect()
rows = connector.select_approved(connection,
  \"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH AS max_len \"
  \"FROM INFORMATION_SCHEMA.COLUMNS \"
  \"WHERE (COLUMN_NAME LIKE '%Lot%' OR COLUMN_NAME LIKE '%Batch%' OR COLUMN_NAME LIKE '%Expire%' \"
  \"OR COLUMN_NAME LIKE '%MFG%' OR COLUMN_NAME LIKE '%Serial%') \"
  \"ORDER BY TABLE_NAME, COLUMN_NAME\")
for row in rows:
    print('%-22s %-20s %-10s %s' % (row['TABLE_NAME'], row['COLUMN_NAME'], row['DATA_TYPE'], row['max_len']))
connection.close()"
```

ผลลัพธ์จะบอกสามอย่างพร้อมกัน: ERP เก็บ lot ไว้ตารางไหน, `tbl_Dodtl` มีช่องรับหรือยัง, และชื่อคอลัมน์จริงคืออะไร

ถ้า `tbl_Dodtl` ไม่มีคอลัมน์ lot เลย ต้องขอ DBA เพิ่มก่อน ซึ่งเป็นการแก้โครงสร้าง ERP — ต้องอนุมัติแยก

## แผนดำเนินงาน (หลังได้คำตอบ)

### ระยะ 1 — ส่ง lot ไปกับ SO
1. เพิ่มคอลัมน์ lot ใน `approved_orders_query` และ `item_field_map`
2. เพิ่มการตรวจใน `contracts.py` (ความยาว และต้องเป็นข้อความหรือว่าง)
3. เทสว่าค่าเดินทางจาก SQL ถึง payload ครบ
4. **ก่อน deploy: ยืนยันกับ eVRP ว่าเขารับฟิลด์นี้และจะไม่ปฏิเสธทั้ง batch** — โหมด atomic ทำให้ใบเดียวพังทั้งชุด

### ระยะ 2 — รับ lot กลับมาใน DO
5. เพิ่มคอลัมน์ในการแมป `detail_columns` ของ `do-write-template.json`
6. เพิ่มในคู่มือ eVRP §9.2 และ §9.3 พร้อมบอกว่าเป็นค่าที่ขอรับกลับ
7. ตรวจด้วย `fit_do` ว่าความยาวพอดีคอลัมน์

### ระยะ 3 — พิสูจน์
8. ให้ eVRP ส่ง DO ทดสอบที่มี lot
9. `fit_do` → ซ้อมเขียน → เขียนจริง 1 ใบ → `verify_do` ดูว่า lot ลงถูกช่อง

## ประเมิน

| ระยะ | งานฝั่งเรา | ต้องรอใคร |
|---|---|---|
| 1 | เล็ก — แก้ config + เทส | eVRP ยืนยันว่ารับฟิลด์ |
| 2 | เล็ก — แก้ mapping + เอกสาร | DBA ถ้า `tbl_Dodtl` ไม่มีคอลัมน์ |
| 3 | เล็ก | eVRP ส่งทดสอบ |

งานฝั่งเราไม่หนัก ตัวที่กำหนดเวลาจริงคือ **eVRP ต้องพัฒนาให้เก็บและส่งกลับ** และ **คำตอบข้อ 1 ว่าใครกำหนด lot**

## ที่ยังค้างอยู่ก่อนหน้า (ไม่ควรทำ lot ทับซ้อน)

- DO จริงจาก eVRP ยังเขียนเข้า ERP ไม่ได้ — ติด `String or binary data would be truncated` ยังไม่รู้คอลัมน์ (รัน `fit_do` ค้างอยู่)
- `total_amount` ไม่เท่าผลรวมบรรทัดทุกใบ ยังไม่รู้ว่าตั้งใจหรือผิด
- `LocationCode` ที่รับกลับมาเป็นรหัส hub ของ eVRP ไม่ใช่ของ ERP
- ข้อความ COD ที่ไม่มี header/details ยังไม่มีที่ลง
