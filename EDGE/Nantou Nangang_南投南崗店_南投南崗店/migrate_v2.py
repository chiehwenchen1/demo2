#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二次 Migration: 精準對應 sku_v3.csv -> EDGE_DB.db

問題分析:
1. CSV 有 4 組重複條碼的產品 (cola_can1/2, sprite_can1/2, kirin_beer1/2, 重複的 330ML 可樂雪碧)
2. DB 舊資料的 category 跟 CSV category 不一致 (e.g. beer1=heineken)
3. 部分 CSV category 在 DB 根本沒有 (budweiser, kirin_beer2, etc.)

解法:
- 重複條碼的產品: 只保留一個 category, 庫存合併
- DB 舊 category -> CSV category: 明確 mapping
- 其他: stock=0 (但用戶可透過 App 進貨)
"""

import csv, sqlite3
from pathlib import Path

STORE_DIR = Path(__file__).parent.resolve()
DB_PATH = STORE_DIR / "EDGE_DB.db"
CSV_PATH = STORE_DIR / "sku_v3.csv"

# ========== 精準對應表 ==========

# 重複條碼的合併: 舊的 cola_can1 + cola_can2 都歸到 cola_can1
CAT_MERGE_CSV = {
    "cola_can2": ("cola_can1", "可樂 330ML"),    # 同條碼, 合併庫存到 cola_can1
    "sprite_can2": ("sprite_can1", "雪碧 330ML"),  # 同上
    "kirin_beer1": ("kirin_beer2", "新KIRIN BEER一番搾"),  # 同上
}

# DB 舊 category -> CSV category 對應 (名稱不同但同一產品的)
CAT_MAP_OLD_TO_NEW = {
    "beer1": "heineken",        # DB beer1 (海尼根) -> CSV heineken
    "beer2": "budweiser",       # DB beer2 (百威) -> CSV budweiser
    "soup": "miso_soup",        # DB soup -> CSV miso_soup
    "tomato": "heinz_ketchup",  # DB tomato -> CSV heinz_ketchup
    "paper": "toilet_paper",    # DB paper -> CSV toilet_paper
    # DB 的 cookie1~7 沒有對應到 CSV 任何產品, 捨棄
    # DB 的 beer3~6 沒有對應到 CSV 任何產品, 捨棄
}

def main():
    print("=" * 60)
    print("  EDGE DB Migration v2 - 精準對應")
    print("  Store:", STORE_DIR.name)
    print("=" * 60)

    # 1. 讀 CSV
    csv_entries = []  # [(name, bar, price, cat), ...]
    with open(str(CSV_PATH), encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 4:
                csv_entries.append((row[0].strip(), row[1].strip(), float(row[2].strip() or 0), row[3].strip()))

    # 去重: 保留每個條碼的第一個 entry, 第二個存捨棄
    seen_bar = {}
    keep = []  # (name, bar, price, cat, is_primary)
    merge_map = {}  # 要被合併的 cat -> 目標 cat
    for entry in csv_entries:
        name, bar, price, cat = entry
        if bar in seen_bar:
            target = seen_bar[bar]
            merge_map[cat] = target
            print(f"  [MERGE] {cat} -> {target} (同條碼 {bar})")
        else:
            seen_bar[bar] = cat
            keep.append(entry)

    print(f"\n  CSV 原始: {len(csv_entries)} 項, 去重後: {len(keep)} 項")

    # 2. 備份 DB (如果還沒有)
    backup_path = DB_PATH.with_suffix(".db.bak")
    if not backup_path.exists():
        import shutil
        shutil.copy2(str(DB_PATH), str(backup_path))
        print(f"  備份: {backup_path}")

    # 3. 從備份讀取舊庫存
    bak = sqlite3.connect(str(backup_path))
    bak.row_factory = sqlite3.Row
    bcur = bak.cursor()
    bcur.execute("SELECT category, SUM(stock_quantity) as total FROM enhanced_inventory GROUP BY category")
    old_stock = {}
    for r in bcur.fetchall():
        cat = r["category"]
        total = r["total"] or 0
        old_stock[cat] = total
    bak.close()
    print(f"  舊 DB: {len(old_stock)} 個 category")

    # 4. 建立新庫存對照 (CSV category -> stock)
    new_stock = {}
    for entry in keep:
        name, bar, price, cat = entry
        stock = 0

        # 先直接對 category
        if cat in old_stock:
            stock = old_stock[cat]
            print(f"  [DIRECT] {cat:20s} -> stock={stock} (直接 match)")
        
        # 檢查是否是 merge 目標 (例如 cola_can1 要加上 cola_can2)
        merged_qty = 0
        for merge_cat, target in merge_map.items():
            if target == cat and merge_cat in old_stock:
                merged_qty += old_stock[merge_cat]
                print(f"  [MERGE]  {merge_cat:20s} stock={old_stock[merge_cat]} -> {cat} (合併)")

        if merged_qty > 0:
            if stock == 0:
                stock = merged_qty
            else:
                # 不應該同時有 direct + merge
                pass

        # 再試舊 category map
        if stock == 0:
            for old_cat, new_cat in CAT_MAP_OLD_TO_NEW.items():
                if new_cat == cat and old_cat in old_stock:
                    stock = old_stock[old_cat]
                    print(f"  [MAP]   {old_cat:20s} stock={old_stock[old_cat]} -> {cat} (對應)")
                    break

        new_stock[cat] = stock

    print(f"\n  新庫存: {len(new_stock)} 個 category")
    stock_total = sum(new_stock.values())
    stock_total = stock_total

    # 5. 重建 enhanced_inventory
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS enhanced_inventory")
    cur.execute("""
        CREATE TABLE enhanced_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT, product_name TEXT, category TEXT,
            stock_quantity INTEGER DEFAULT 0, retail_price REAL DEFAULT 0.0,
            max_capacity INTEGER DEFAULT 200, reorder_level INTEGER DEFAULT 20,
            last_restock_date TEXT, last_sold_date TEXT
        )
    """)

    for i, entry in enumerate(keep, 1):
        name, bar, price, cat = entry
        stock = new_stock.get(cat, 0)
        product_id = f"{STORE_DIR.name}_{cat}"
        cur.execute(
            "INSERT INTO enhanced_inventory (id, product_id, product_name, category, stock_quantity, retail_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (i, product_id, name, cat, stock, price)
        )

    conn.commit()

    # 6. 列出最終結果
    cur.execute("SELECT id, category, product_name, stock_quantity, retail_price FROM enhanced_inventory ORDER BY id")
    print(f"\n=== 最終產品清單 ({len(keep)} 項) ===")
    for r in cur.fetchall():
        s = f"stock={r[3]}" if r[3] and int(r[3]) > 0 else "stock=0"
        print(f"  [{r[0]:2d}] {r[2]:25s} cat={r[1]:20s} {s:12s} ${r[4]:.0f}")

    conn.close()
    print(f"\nDone! Backup: {backup_path}")

if __name__ == "__main__":
    main()
