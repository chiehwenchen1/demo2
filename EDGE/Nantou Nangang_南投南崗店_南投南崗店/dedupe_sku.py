# -*- coding: utf-8 -*-
"""
只保留 31 個 unique 貨品碼的品項。
重複條碼的品項刪掉（保留第一筆），剩下庫存調到 50~110。
"""
import sqlite3, csv, os, random
from collections import Counter

db_path = os.path.join(os.path.dirname(__file__), "EDGE_DB.db")
csv_path = os.path.join(os.path.dirname(__file__), "sku_v3.csv")

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 讀 CSV 找出重複條碼
csv_rows = []
with open(csv_path, encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    for row in reader:
        name = row[0].strip()
        barcode = row[1].strip()
        price = float(row[2].strip())
        category = row[3].strip()
        csv_rows.append((name, barcode, price, category))

# 找出哪些條碼重複
barcode_counts = Counter(r[1] for r in csv_rows)
dup_barcodes = {bc for bc, cnt in barcode_counts.items() if cnt > 1}
print(f"重複條碼: {dup_barcodes}")

# 同條碼保留第一個 category，其餘要刪
keep_categories = set()  # (barcode, category) 要保留
for bc in dup_barcodes:
    first_cat = None
    for name, barcode, price, category in csv_rows:
        if barcode == bc:
            if first_cat is None:
                first_cat = category
                keep_categories.add(category)
                break

# 找出要刪的 DB id
cur.execute("SELECT id, product_id, product_name, category, stock_quantity FROM enhanced_inventory")
all_rows = cur.fetchall()

to_delete_ids = []
to_keep_ids = []
for r in all_rows:
    pid, pname, cat, qty = r[1], r[2], r[3], r[4]
    if pid in dup_barcodes:
        # 對重複條碼：保留第一個出現在 CSV 的 category
        first_cat = None
        for name, barcode, price, category in csv_rows:
            if barcode == pid:
                first_cat = category
                break
        if cat != first_cat:
            to_delete_ids.append(r[0])
            print(f"  刪除 id={r[0]:2d} {pname:12s} cat={cat:15s} (同條碼保留 {first_cat})")
        else:
            to_keep_ids.append(r[0])
    else:
        to_keep_ids.append(r[0])

print(f"\n要刪除: {len(to_delete_ids)} 筆")
print(f"要保留並更新庫存: {len(to_keep_ids)} 筆")

# 執行刪除
for did in to_delete_ids:
    cur.execute("DELETE FROM enhanced_inventory WHERE id = ?", (did,))

# 更新保留的庫存到 50~110
cur.execute("SELECT id, product_name, stock_quantity FROM enhanced_inventory ORDER BY id")
remaining = cur.fetchall()
print(f"\n刪除後剩餘: {len(remaining)} 筆")
for r in remaining:
    new_qty = random.randint(50, 110)
    cur.execute("UPDATE enhanced_inventory SET stock_quantity = ?, max_capacity = 200, reorder_level = 20 WHERE id = ?",
                (new_qty, r[0]))
    print(f"  id={r[0]:2d} {r[1]:12s} qty: {r[2]:4d} -> {new_qty}")

conn.commit()

# 驗證
cur.execute("SELECT COUNT(*) FROM enhanced_inventory")
cnt = cur.fetchone()[0]
print(f"\n最終 DB 總記錄數: {cnt}")
cur.execute("SELECT id, product_name, category, stock_quantity FROM enhanced_inventory ORDER BY id")
for r in cur.fetchall():
    print(f"  id={r[0]:2d} {r[1]:12s} cat={r[2]:15s} qty={r[3]:4d}")

conn.close()
print("\n完成！")
