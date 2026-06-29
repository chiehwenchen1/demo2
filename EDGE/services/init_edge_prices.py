#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 1: init_edge_prices.py
初始化 EDGE 門市價格與庫存
- 讀取 sku_v2.csv 價格
- 更新 EDGE_DB.db 中的 retail_price、unit_price、cost_price
- 初始化庫存（每項 100~200 件）
- 記錄價格變更至 price_history

用法: python init_edge_prices.py
"""
import csv
import sqlite3
import os
import sys
from datetime import datetime, date
import random

# 專案根目錄
PROJECT = "D:/bible/USI_SMART_RETAIL_OS"

# sku_v2 類別 → EDGE category / 簡短 product_id 名稱
SHORT_PRODUCT_NAMES = {
    "cola": "可樂 330ML",
    "sprite": "雪碧 330ML",
    "pepsi": "百事可樂 500ML",
    "big_cola": "可樂 920ML",
    "beer1": "海尼根啤酒",
    "beer2": "百威啤酒 473ML",
    "cookie1": "CALBEE JAGARICO",
    "cookie2": "卡迪那脆薯條",
    "soup": "丸米減鹽味噌湯",
    "tomato": "HEINZ 番茄醬 3入",
}

SKU_CATEGORY_MAP = {
    "coke":        "cola",
    "sprite":      "sprite",
    "pepsi":       "pepsi",
    "coke_large":  "big_cola",
    "heineken":    "beer1",
    "budweiser":   "beer2",
    "jagarico":    "cookie1",
    "cadina":      "cookie2",
    "miso_soup":   "soup",
    "heinz_ketchup": "tomato",
}

# 各門市 EDGE 資料庫路徑
EDGE_STORES = {
    "Taipei Zhongxiao": os.path.join(PROJECT, "EDGE", "Taipei Zhongxiao_台北忠孝店_台北忠孝店", "EDGE_DB.db"),
    "Osaka Shinsaibashi": os.path.join(PROJECT, "EDGE", "Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店", "EDGE_DB.db"),
}

def load_sku_prices():
    """
    讀取 sku_v2.csv 價格資料
    回傳: { category: { "name": str, "price": float, "barcode": str } }
    """
    sku_path = os.path.join(PROJECT, "EDGE", "Taipei Zhongxiao_台北忠孝店_台北忠孝店", "sku_v2.csv")
    sku_data = {}
    with open(sku_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cat = row["category"].strip()
            sku_data[cat] = {
                "name": row["item_name"].strip(),
                "price": float(row["price"]),
                "barcode": row["barcode"].strip(),
            }
    return sku_data

def init_store_prices(store_id, db_path, sku_data):
    """初始化指定門市的價格與庫存"""
    if not os.path.exists(db_path):
        print(f"  [SKIP] 資料庫不存在: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    today = date.today().isoformat()
    now_ts = datetime.now().isoformat()

    print(f"\n=== 初始化門市: {store_id} ===")
    print(f"  資料庫: {db_path}")

    # 先確認 store_info 是否存在
    cur.execute("SELECT store_id, region FROM store_info WHERE store_id = ?", (store_id,))
    info = cur.fetchone()
    if info:
        print(f"  門市資訊: {info[0]}, 區域: {info[1]}")
    else:
        print(f"  [WARN] store_info 中找不到 {store_id}")

    for sku_cat, edge_cat in SKU_CATEGORY_MAP.items():
        if sku_cat not in sku_data:
            print(f"  [WARN] sku_v2 中無此類別: {sku_cat}")
            continue

        price = sku_data[sku_cat]["price"]
        sku_name = sku_data[sku_cat]["name"]
        barcode = sku_data[sku_cat]["barcode"]

        # 在 enhanced_inventory 中查找匹配的產品（用 category 配對）
        # EDGE 的 category 欄位為英文簡稱，例如 "cola", "sprite", "pepsi"
        cur.execute(
            "SELECT id, product_id, product_name, category, retail_price, unit_price, cost_price, stock_quantity, max_capacity, barcode "
            "FROM enhanced_inventory WHERE product_id LIKE ? AND category = ?",
            (f"{store_id}_%_{edge_cat}", edge_cat)
        )
        rows = cur.fetchall()

        if not rows:
            # 對某些類別，可能 product_id 結尾不同（如 cookie1 → _cookie1）
            # 用 LIKE 更寬鬆匹配
            cur.execute(
                "SELECT id, product_id, product_name, category, retail_price, unit_price, cost_price, stock_quantity, max_capacity, barcode "
                "FROM enhanced_inventory WHERE category = ? AND product_id LIKE ?",
                (edge_cat, f"{store_id}_%_{edge_cat}")
            )
            rows = cur.fetchall()

        if not rows:
            # 最後嘗試：只匹配 category
            cur.execute(
                "SELECT id, product_id, product_name, category, retail_price, unit_price, cost_price, stock_quantity, max_capacity, barcode "
                "FROM enhanced_inventory WHERE category = ?",
                (edge_cat,)
            )
            rows = cur.fetchall()

        if not rows:
            print(f"  [WARN] 找不到 {store_id} 中 category='{edge_cat}' 的產品 (sku_cat={sku_cat}, {sku_name})")
            continue

        for row in rows:
            pid = row[1]
            pname = row[2]
            cat = row[3]
            old_retail = row[4]
            old_unit = row[5]
            old_cost = row[6]
            old_stock = row[7]
            max_cap = row[8] if row[8] else 200

            # 設定成本價 = 零售價的 60%
            cost_price = round(price * 0.6, 2)
            # 設定進貨價（unit_price）= 成本價
            unit_price = cost_price

            # 重新命名 product_id: 門市_類別（例如 "Taipei cola"、"Osaka cola"）
            short_prefix = store_id.replace("Taipei Zhongxiao", "Taipei").replace("Osaka Shinsaibashi", "Osaka")
            short_product_id = f"{short_prefix} {edge_cat}"
            short_product_name = SHORT_PRODUCT_NAMES.get(edge_cat, sku_name)

            # 更新價格 + product_id + product_name
            cur.execute(
                "UPDATE enhanced_inventory SET product_id = ?, product_name = ?, retail_price = ?, unit_price = ?, cost_price = ? WHERE id = ?",
                (short_product_id, short_product_name, price, unit_price, cost_price, row[0])
            )
            print(f"  ✅ {short_product_name} ({cat}): 零售價 ${old_retail} → ${price}, ID={short_product_id}")

            # 如果目前庫存為 0 或不合理，初始化庫存（100~200）
            if old_stock == 0 or old_stock > 5000:
                init_stock = random.randint(100, 200)
                cur.execute(
                    "UPDATE enhanced_inventory SET stock_quantity = ? WHERE id = ?",
                    (init_stock, row[0])
                )
                print(f"     📦 庫存初始化: {old_stock} → {init_stock}")

            # 寫入 price_history
            cur.execute(
                "INSERT INTO price_history (product_id, product_name, unit_price, retail_price, cost_price, effective_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, pname, unit_price, price, cost_price, today)
            )

            # 更新 edge_inventory（如果有此表格）
            try:
                cur.execute(
                    "UPDATE edge_inventory SET retail_price = ?, unit_price = ? WHERE name = ? AND category = ?",
                    (price, unit_price, pname, cat)
                )
            except Exception:
                pass  # edge_inventory 可能為空

            # 更新 product_catalog（如果有此表格）
            try:
                cur.execute(
                    "UPDATE product_catalog SET retail_price = ?, unit_price = ? WHERE name = ? AND category = ?",
                    (price, unit_price, pname, cat)
                )
            except Exception:
                pass

    conn.commit()
    conn.close()
    print(f"\n✅ {store_id} 初始化完成！")

def main():
    print("=" * 60)
    print("USI Smart Retail OS — EDGE 價格初始化工具")
    print("=" * 60)

    # 讀取 sku_v2 價格
    sku_data = load_sku_prices()
    print(f"\n📋 從 sku_v2.csv 讀取 {len(sku_data)} 項產品:")
    for cat, info in sku_data.items():
        print(f"   {info['name']:20s} ({cat:15s}) → ${info['price']:<6.1f}  條碼: {info['barcode']}")

    # 初始化所有門市
    for store_id, db_path in EDGE_STORES.items():
        init_store_prices(store_id, db_path, sku_data)

    print("\n" + "=" * 60)
    print("✅ 所有門市初始化完成！")
    print("=" * 60)

if __name__ == "__main__":
    main()
