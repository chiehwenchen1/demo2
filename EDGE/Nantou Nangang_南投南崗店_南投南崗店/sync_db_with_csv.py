# -*- coding: utf-8 -*-
"""同步 sku_v3.csv → EDGE_DB.db enhanced_inventory

CSV 欄位: ch_name, en_name, product_id, price, zone_name
比對 key: ch_name (CSV) <-> product_name (DB) 因 product_id 格式不同且 zone_name 可能改過

- DB 已有相同 product_name → 更新 product_id, category(zone), price，庫存保留
- CSV 有、DB 沒有 → 新增 (預設庫存 50)
- DB 有、CSV 沒有 → 保留不動
"""
import sqlite3, csv, os

db_path = os.path.join(os.path.dirname(__file__), "EDGE_DB.db")
csv_path = os.path.join(os.path.dirname(__file__), "sku_v3.csv")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# ── 1. 讀 CSV ──
csv_items = {}
with open(csv_path, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        name = row.get("ch_name", "").strip()
        pid = row.get("product_id", "").strip()
        zone = row.get("zone_name", "").strip()
        try:
            price = float(row.get("price", "0").strip())
        except ValueError:
            price = 0.0
        if not name or not pid:
            continue
        csv_items[name] = dict(pid=pid, zone=zone, price=price)

print(f"CSV 讀取 {len(csv_items)} 筆")
for n, v in sorted(csv_items.items()):
    print(f"  {n:25s} pid={v['pid']:15s} cat={v['zone']:30s} price={v['price']:5.1f}")

# ── 2. 讀 DB ──
cur.execute("SELECT id, product_id, product_name, category, stock_quantity, retail_price FROM enhanced_inventory ORDER BY id")
db_rows = cur.fetchall()
db_by_name = {}
for r in db_rows:
    db_by_name[r[2]] = r
print(f"\nDB 原有 {len(db_rows)} 筆")

# ── 3. 比對 ──
to_insert = []
to_update = []

for csv_name, csv_data in csv_items.items():
    if csv_name in db_by_name:
        r = db_by_name[csv_name]
        to_update.append((csv_data["pid"], csv_name, csv_data["zone"], csv_data["price"], r[0], r[4]))
        print(f"  MATCH name={csv_name:25s} -> 更新 id={r[0]:3d}")
    else:
        to_insert.append((csv_name, csv_data))
        print(f"  NEW name={csv_name:25s} pid={csv_data['pid']} cat={csv_data['zone']}")

print(f"\n=== 執行同步 ===")
print(f"  INSERT {len(to_insert)} 筆新品、UPDATE {len(to_update)} 筆更新")

# ── 4. UPDATE：改 product_id, product_name, category, price，庫存不動 ──
for pid, name, zone, price, db_id, old_qty in to_update:
    cur.execute(
        "UPDATE enhanced_inventory SET product_id=?, product_name=?, category=?, retail_price=? WHERE id=?",
        (pid, name, zone, price, db_id)
    )
    print(f"  UPDATE id={db_id:2d} name={name:25s} cat={zone:30s} price={price:5.1f} (庫存={old_qty} 不變)")

# ── 5. INSERT：新品 ──
for name, data in to_insert:
    cur.execute(
        "INSERT INTO enhanced_inventory (product_id, product_name, category, stock_quantity, retail_price, max_capacity, reorder_level) "
        "VALUES (?, ?, ?, 50, ?, 200, 20)",
        (data["pid"], name, data["zone"], data["price"])
    )
    print(f"  INSERT name={name:25s} cat={data['zone']:30s} price={data['price']:5.1f} qty=50")

conn.commit()

# ── 6. 最終確認 ──
print("\n=== 最終庫存 ===")
cur.execute("SELECT id, product_name, category, stock_quantity, retail_price FROM enhanced_inventory ORDER BY id")
for r in cur.fetchall():
    print(f"  id={r[0]:3d} name={r[1]:25s} cat={r[2]:30s} qty={r[3]:3d} price={r[4]:5.1f}")

# 補上未出現在 CSV 的舊品項
if len(db_rows) > len(csv_items):
    print(f"\n⚠ NOTE: DB 原有 {len(db_rows)} 筆，CSV 只有 {len(csv_items)} 筆")
    csv_names = set(csv_items.keys())
    for r in db_rows:
        if r[2] not in csv_names:
            print(f"  ⏸ DB only: id={r[0]:3d} {r[2]:25s} (保留不動)")

print(f"\nOK done!")
conn.close()
