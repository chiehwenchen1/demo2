#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三次 DB Migration: 以 sku_v3.csv 的 B (barcode) 為產品唯一識別碼

規則:
- B (barcode) = DB product_id (唯一 key)
- A (中文名) = UI 顯示名稱
- C (價格)   = DB retail_price (同 B 價格檢查: 已確認一致)
- D (category) = 保持不變 (給 smart_shelf_demo 用)

重複條碼處理: 保留第一筆為主, 其他合併庫存到第一筆
"""

import csv, sqlite3, shutil
from pathlib import Path
from collections import OrderedDict

STORE_DIR = Path(__file__).parent.resolve()
DB_PATH = STORE_DIR / "EDGE_DB.db"
CSV_PATH = STORE_DIR / "sku_v3.csv"

def main():
    print("=" * 60)
    print("  EDGE DB Migration v3 — Barcode 唯一識別")
    print("  Store:", STORE_DIR.name)
    print("=" * 60)

    # ========== 1. 讀 CSV, 依 B 去重 ==========
    csv_data = OrderedDict()  # barcode -> (name, price, cat)
    with open(str(CSV_PATH), encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) < 4: continue
            name, bar, price, cat = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
            if not bar: continue
            if bar in csv_data:
                # 同條碼: 如果已經有了就跳過 (保留第一個), 但庫存後面會合併
                old_name, old_price, old_cat = csv_data[bar]
                print(f"  [DUP] B={bar} -> 保留第1筆, 跳過 {cat}")
            else:
                csv_data[bar] = (name, float(price or 0), cat)

    print(f"  CSV: 34 行 -> {len(csv_data)} 唯一條碼")

    # ========== 2. 備份 DB ==========
    backup_path = DB_PATH.with_suffix(".db.bak3")
    if not backup_path.exists():
        shutil.copy2(str(DB_PATH), str(backup_path))
        print(f"  備份: {backup_path}")

    # ========== 3. 從舊 DB 讀取庫存 ==========
    bak = sqlite3.connect(str(backup_path))
    bak.row_factory = sqlite3.Row
    bcur = bak.cursor()

    # 讀舊 DB: 所有記錄
    bcur.execute("SELECT * FROM enhanced_inventory")
    old_rows = [dict(r) for r in bcur.fetchall()]
    bak.close()
    print(f"  舊 DB: {len(old_rows)} 筆記錄")

    # ========== 4. 建立精準對應 ==========
    # DB 舊 category -> CSV 條碼的對應表
    CAT_BAR_MAP = {
        "beer1": "8712000061821",       # 海尼根
        "beer2": "01801828",             # 百威
        "beer3": None,                   # 無對應
        "beer4": None,
        "beer5": None,
        "beer6": None,
        "cookie1": None,                 # CALBEE JAGARICO -> CSV 沒有這個產品
        "cookie2": None,                 # 卡迪那脆薯條 -> CSV 沒有這個產品名
        "cookie3": None,
        "cookie4": None,
        "cookie5": None,
        "cookie6": None,
        "cookie7": None,
        "paper": "4710114812999",        # 舒潔衛生紙 (toilet_paper)
        "soup": "4902713134040",         # 丸米味噌湯 (miso_soup)
        "tomato": "4718262424019",       # HEINZ 番茄醬 (heinz_ketchup)
        # 以下是 CSV 也有的 category, 直接對應
        "big_cola": "4710018148408",
        "pepsi": "4710110803526",
        "sprite": "4710018028601",
        "cola": "4710018028809",
        "sprite_can1": "4710018000409",
        "cola_can1": "4710018000102",
        "imei": "4710126005181",
        "coffee": "4710179172113",
        "noodle1": "4710088411983",
        "noodle2": "4710088414243",
        "noodle3": "8936048470814",
        "noodle4": "4710088470313",
        "croc": "4710312010036",
        "dalli": "4012400528837",
        "raid": "4710314262426",
        "combat": "4897888000477",
    }

    # 重複條碼合併: 合併到第一筆的 barcode
    DUP_MERGE = {
        "cola_can2": "4710018000102",     # cola_can2 -> cola_can1 的條碼
        "sprite_can2": "4710018000409",    # sprite_can2 -> sprite_can1 的條碼
        "kirin_beer1": "4901411035703",    # kirin_beer1 -> kirin_beer2 的條碼
    }

    # ========== 5. 計算新庫存 (barcode -> stock) ==========
    new_stock = {}  # barcode -> stock
    for r in old_rows:
        cat = r["category"]
        stock = r["stock_quantity"] or 0

        # 先把 category 轉成 barcode
        bar = None

        # 1) 直接查對應表
        if cat in CAT_BAR_MAP:
            bar = CAT_BAR_MAP[cat]

        # 2) 如果是 merge 來源
        if bar is None and cat in DUP_MERGE:
            bar = DUP_MERGE[cat]

        # 3) 如果 CSV 有這個 category 當條碼值 (機率低但保留)
        if bar is None:
            for b, (n, p, c) in csv_data.items():
                if c == cat and b:
                    bar = b
                    break

        if bar and bar in csv_data:
            new_stock[bar] = new_stock.get(bar, 0) + stock
            old_name = r["product_name"]
            csv_name, csv_price, csv_cat = csv_data.get(bar, ("?", 0, "?"))
            if stock > 0:
                print(f"  [MAP]   cat={cat:20s} stock={stock:6d} -> B={bar:20s} ({csv_name})")
        else:
            print(f"  [SKIP]  cat={cat:20s} stock={stock:6d} (無對應, 捨棄)")

    # ========== 6. 重建 DB ==========
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

    inserted = 0
    for bar, (name, price, cat) in csv_data.items():
        stock = new_stock.get(bar, 0)
        cur.execute(
            "INSERT INTO enhanced_inventory (product_id, product_name, category, stock_quantity, retail_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (bar, name, cat, stock, price)
        )
        inserted += 1

    conn.commit()

    # ========== 7. Results ==========
    cur.execute("SELECT id, product_name, stock_quantity, retail_price, category FROM enhanced_inventory ORDER BY id")
    print(f"\n=== 最終 ({inserted} 項) ===")
    for r in cur.fetchall():
        s = f"stock={r[2]}" if r[2] and int(r[2]) > 0 else "stock=0"
        print(f"  [{r[0]:2d}] B={csv_data[r['category']][2] if len(csv_data.get(r['category'],('','','')))>2 else '?':>4s} {r[1]:25s} {s:12s} ${r[3]:.0f} cat={r[4]}")

    conn.close()
    print(f"\nDone! Backup: {backup_path}")

if __name__ == "__main__":
    main()
