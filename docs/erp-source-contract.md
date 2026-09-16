# ERP SQL Server source contract

สถานะ: รอ Phase 01 discovery จาก SQL Server จริง

ไฟล์นี้จะบันทึกเฉพาะ schema และข้อมูลที่ได้รับอนุมัติให้ใช้เชื่อมต่อ โดยไม่เก็บ password,
token หรือข้อมูลลูกค้าเต็มชุด การทดสอบใช้ SELECT-only และดึงเฉพาะ SO ที่ผู้ใช้ระบุเท่านั้น

## ต้องเติมจาก ERP/DBA

- SQL Server version, instance/port, database, company/branch และ timezone
- auth mode, ODBC driver, certificate chain และ service identity
- view/table ที่อนุมัติสำหรับ SO header, SO lines, customer, ship-to, hub/warehouse
- primary key และ composite identity ของบริษัท/สาขา + SO
- สถานะที่หมายถึง approved/ready, cancelled และ amended
- ยืนยันแล้ว: สถานะ SO ที่ Approve คือ `IsApprSo = 1`; ยังต้องระบุตาราง/View ที่มี field นี้
- ฟิลด์ที่บอกการแก้ไขของ header, lines, customer และ ship-to
- วิธี tracking ที่พิสูจน์ได้: Change Tracking, change timestamp หรือ bounded ready-order scan
- นโยบายราคา/ภาษี/ส่วนลด/หน่วย และ master code ที่ตรงกับ eVRP
- SO ตัวอย่างที่ผู้ใช้เลือกและอนุมัติสำหรับ SELECT test

## ข้อห้ามระหว่าง discovery/test

- ห้าม INSERT, UPDATE, DELETE, DDL, trigger, stored procedure ที่มี side effect หรือเปลี่ยนสถานะ ERP
- ห้ามใช้ `NOLOCK` เพื่อแก้ปัญหา consistency
- ห้ามอ่านประวัติทั้งหมดหรือทำ full export โดยไม่มี scope
- ห้ามส่ง SO จริงไป eVRP; ใช้ mock/staging สำหรับ delivery tests

## Query evidence

บันทึก query แบบ parameterized, scope, เวลา, จำนวนแถว, execution duration และผลที่ redacted
ลงใน `process/features/erp-sqlserver/reports/phase-01.md` หลังผู้ใช้อนุมัติ SO sample
