#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
以 sku_v3.csv 為準，重建 EDGE_DB.db 的 enhanced_inventory 表格。
保留 transaction 記錄，但 product 清單完全照 CSV 重新建立。

用法: python migrate_to_sku_v3.py
"""

import csv, sqlite3, os, sys
from pathlib import Path

STORE_DIR = Path(__file__).parent.resolve()
DB_PATH = STORE_DIR / "EDGE_DB.db"
CSV_PATH = STORE_DIR / "sku_v3.csv"

# Category 對應表 (舊 DB category -> CSV category)
# 這些是 DB 裡用了不同名字但實際上是同一產品的
CAT_MERGE = {
    "beer1": "heineken",     # 海尼根
    "beer2": "budweiser",    # 百威啤酒
    "soup": "miso_soup",     # 丸米味噌湯
    "tomato": "heinz_ketchup", # HEINZ 番茄醬
    "paper": "toilet_paper", # 舒潔衛生紙
}

def main():
    print("=" * 60)
    print("  EDGE DB Migration: sync to sku_v3.csv")
    print("  Store: " + STORE_DIR.name)
    print("=" * 60)

    # 1. 讀 CSV
    csv_data = []
    with open(str(CSV_PATH), encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 4:
                csv_data.append({
                    "name": row[0].strip(),
                    "barcode": row[1].strip(),
                    "price": float(row[2].strip() or 0),
                    "category": row[3].strip(),
                })
    print(f"\n  CSV: {len(csv_data)} 項產品")

    # 2. 備份 DB
    backup_path = str(DB_PATH) + ".bak"
    if not os.path.exists(backup_path):
        os.rename(str(DB_PATH), backup_path)
        print(f"  備份: {backup_path}")

    # 3. 開新 DB
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # 4. 從備份讀取 category 庫存總和
    backup_conn = sqlite3.connect(backup_path)
    backup_conn.row_factory = sqlite3.Row
    bcur = backup_conn.cursor()
    bcur.execute("SELECT name FROM sqlite_master WHERE type='table'")

    # 讀所有舊資料
    bcur.execute("SELECT * FROM enhanced_inventory")
    old_cols = [desc[0] for desc in bcur.description]
    print(f"  DB old columns: {old_cols}")

    # 收集庫存: 舊 category -> stock sum
    old_stock = {}  # category -> sum
    old_first = {}  # category -> first row
    for row in bcur.fetchall():
        cat = row["category"]
        stock = row["stock_quantity"] or 0
        old_stock[cat] = old_stock.get(cat, 0) + stock
        if cat not in old_first:
            old_first[cat] = dict(row)

    print(f"  DB: {len(old_stock)} 個 category")

    # 5. 重建 enhanced_inventory
    cur.execute("DROP TABLE IF EXISTS enhanced_inventory")
    cur.execute("""
        CREATE TABLE enhanced_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT,
            product_name TEXT,
            category TEXT,
            stock_quantity INTEGER DEFAULT 0,
            retail_price REAL DEFAULT 0.0,
            max_capacity INTEGER DEFAULT 200,
            reorder_level INTEGER DEFAULT 20,
            last_restock_date TEXT,
            last_sold_date TEXT
        )
    """)

    inserted = 0
    merged = 0
    for csv_item in csv_data:
        cat = csv_item["category"]
        name = csv_item["name"]
        price = csv_item["price"]

        # 找庫存: 先直接對 category, 再試 merge
        stock = old_stock.get(cat, 0)
        if stock == 0 and cat in CAT_MERGE.values():
            # 可能是 merge 目標: 檢查對應的舊 category
            for old_cat, new_cat in CAT_MERGE.items():
                if new_cat == cat and old_cat in old_stock:
                    stock = old_stock.get(old_cat, 0)
                    merged += 1
                    break

        if stock > 0:
            merged += 1

        product_id = f"{STORE_DIR.name}_{cat}"
        cur.execute(
            "INSERT INTO enhanced_inventory (product_id, product_name, category, stock_quantity, retail_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (product_id, name, cat, stock, price)
        )
        inserted += 1

    print(f"\n  重建 enhanced_inventory: {inserted} 筆")
    print(f"  其中 {merged} 筆有獲得庫存 (其餘為 0)")

    # 6. 保留其他 table 不變
    backup_conn.close()

    # 7. Commit + 統計
    conn.commit()

    # 列出所有產品
    cur.execute("SELECT id, category, product_name, stock_quantity, retail_price FROM enhanced_inventory ORDER BY id")
    print(f"\n=== 重建後的產品清單 ===")
    for r in cur.fetchall():
        stock_str = f"stock={r[3]}" if r[3] and int(r[3]) > 0 else "stock=0"
        print(f"  [{r[0]:2d}] {r[2]:25s} cat={r[1]:20s} {stock_str:12s} ${r[4]:.0f}")

    conn.close()
    print(f"\n✅ 完成! 備份保留在: {backup_path}")
    print(f"   要還原請關閉後執行: copy /Y \"{backup_path}\" \"{DB_PATH}\"")

if __name__ == "__main__":
    main()
