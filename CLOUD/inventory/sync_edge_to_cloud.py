#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 3: sync_edge_to_cloud.py
將 EDGE 門市資料同步至 CLOUD 資料庫
- 讀取兩個 EDGE_DB.db 中的庫存資料
- 產生 90+ 天的每日快照（含合理的銷售模擬）
- 寫入 cloud_inventory.db 中的 inventory_raw 表格
- 匯出 CSV 供報表產生器使用

用法:
  python sync_edge_to_cloud.py                  # 預設 90 天
  python sync_edge_to_cloud.py --days 120       # 指定天數
  python sync_edge_to_cloud.py --export-csv     # 同時匯出 CSV
"""
import argparse
import csv
import io
import os
import random
import sqlite3
import sys
from datetime import datetime, date, timedelta

# 修正 Windows console cp950 無法輸出 Unicode emoji 的問題
if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.upper() in ('CP950', 'BIG5', 'BIG5-HKSCS'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 專案根目錄
PROJECT = "D:/bible/USI_SMART_RETAIL_OS"

# ===== 從 sku_v3.csv 載入完整產品清單 =====
SKU_V3_PATH = os.path.join(PROJECT, "EDGE", "Nantou Nangang_南投南崗店_南投南崗店", "sku_v3.csv")

# short_name → { ch_name, product_id, price }
SKU_V3_DATA = {}
if os.path.exists(SKU_V3_PATH):
    with open(SKU_V3_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            short = row.get("short_name", "").strip()
            if short:
                SKU_V3_DATA[short] = {
                    "ch_name": row.get("ch_name", "").strip(),
                    "product_id": row.get("product_id", "").strip(),
                    "price": float(row.get("price", 0) or 0),
                }
    print(f"  [OK] 載入 {len(SKU_V3_DATA)} 項產品 (sku_v3)")
else:
    print(f"  [WARN] sku_v3.csv 不存在: {SKU_V3_PATH}")

# category (short_name) → 映射（直接使用 sku_v3 short_name）
CATEGORY_LIST = list(SKU_V3_DATA.keys())

# 兼容舊版 v2 映射（fallback）
CATEGORY_MAP_V2 = {
    "coke": "cola",
    "sprite": "sprite",
    "pepsi": "pepsi",
    "coke_large": "big_cola",
    "heineken": "beer1",
    "budweiser": "beer2",
    "jagarico": "cookie1",
    "cadina": "cookie2",
    "miso_soup": "soup",
    "heinz_ketchup": "tomato",
}
REVERSE_MAP = {v: k for k, v in CATEGORY_MAP_V2.items()}

# 門市設定
STORE_CONFIG = {
    "Taipei Zhongxiao": {
        "db_dir": "Taipei Zhongxiao_台北忠孝店_台北忠孝店",
        "region": "Taipei",
    },
    "Osaka Shinsaibashi": {
        "db_dir": "Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店",
        "region": "Osaka",
    },
    "Nantou Nangang": {
        "db_dir": "Nantou Nangang_南投南崗店_南投南崗店",
        "region": "Central",
    },
}

# CLOUD 資料庫路徑
CLOUD_DB = os.path.join(PROJECT, "CLOUD", "database", "cloud_inventory.db")

def load_sku_prices():
    """載入 sku_v3.csv 價格"""
    prices = {}
    for short, data in SKU_V3_DATA.items():
        prices[short] = data["price"]
    print(f"   價格已載入 ({len(prices)} 項)")
    return prices

def get_edge_products(store_id, db_dir):
    """從 EDGE DB 取得產品資料（使用 sku_v3.csv 完整清單）"""
    db_path = os.path.join(PROJECT, "EDGE", db_dir, "EDGE_DB.db")
    if not os.path.exists(db_path):
        print(f"  [SKIP] 資料庫不存在: {db_path}")
        return []
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    products = []
    
    # 取得 enhanced_inventory 實際欄位
    cur.execute('PRAGMA table_info(enhanced_inventory)')
    avail_cols = [c[1] for c in cur.fetchall()]
    base_fields = "id, product_id, product_name, category, stock_quantity, retail_price"
    extra_fields = []
    for cf in ['unit_price', 'cost_price', 'max_capacity', 'reorder_level']:
        if cf in avail_cols:
            extra_fields.append(cf)
    if extra_fields:
        select_fields = base_fields + ", " + ", ".join(extra_fields)
    else:
        select_fields = base_fields
    
    # 特殊 category 映射：sku_v3 短名稱 → EDGE_DB 可能的分支
    CATEGORY_SHORT_MAP = {
        'sprite_can': ['sprite_can1', 'sprite_can2'],
        'cola_can': ['cola_can1', 'cola_can2'],
        'kirin_beer': ['kirin_beer1', 'kirin_beer2'],
    }
    
    # 優先從 sku_v3 的 short_name 逐項查詢 EDGE_DB
    for short, data in SKU_V3_DATA.items():
        found = False
        if short in CATEGORY_SHORT_MAP:
            # 合併多個分支的庫存
            total_products = []
            for sub_cat in CATEGORY_SHORT_MAP[short]:
                cur.execute(
                    f"SELECT {select_fields} FROM enhanced_inventory WHERE category = ?",
                    (sub_cat,)
                )
                sub_rows = cur.fetchall()
                for row in sub_rows:
                    p = {
                        "id": row[0],
                        "product_id": row[1],
                        "product_name": row[2],
                        "category": short,
                        "sku_category": short,
                        "stock_quantity": (row[4] or 0) + 0,
                        "retail_price": float(row[5] or 0),
                    }
                    col_idx = 6
                    for cf in ['unit_price', 'cost_price', 'max_capacity', 'reorder_level']:
                        if cf in extra_fields:
                            p[cf] = row[col_idx] if row[col_idx] is not None else 0
                            col_idx += 1
                        else:
                            p[cf] = 0
                    total_products.append(p)
            if total_products:
                # 合併：庫存相加，價格取第一個
                merged = total_products[0].copy()
                merged["stock_quantity"] = sum(p["stock_quantity"] for p in total_products)
                products.append(merged)
                found = True
        
        if not found:
            # 先用 product_id 精確匹配
            cur.execute(
                f"SELECT {select_fields} FROM enhanced_inventory WHERE product_id = ?",
                (data["product_id"],)
            )
            rows = cur.fetchall()
            if not rows:
                # 用短名稱 category 匹配
                cur.execute(
                    f"SELECT {select_fields} FROM enhanced_inventory WHERE category = ?",
                    (short,)
                )
                rows = cur.fetchall()
            for row in rows:
                p = {
                    "id": row[0],
                    "product_id": row[1],
                    "product_name": row[2],
                    "category": short,
                    "sku_category": short,
                    "stock_quantity": row[4] or 0,
                    "retail_price": float(row[5] or 0),
                }
                # 補 optional 欄位
                col_idx = 6
                for cf in ['unit_price', 'cost_price', 'max_capacity', 'reorder_level']:
                    if cf in extra_fields:
                        p[cf] = row[col_idx] if row[col_idx] is not None else 0
                        col_idx += 1
                    else:
                        p[cf] = 0
                products.append(p)
                break  # short_name 只取一筆
    
    conn.close()
    return products

def read_existing_transactions(store_id, db_dir):
    """從 EDGE DB 讀取已有的交易記錄來做每日快照"""
    db_path = os.path.join(PROJECT, "EDGE", db_dir, "EDGE_DB.db")
    if not os.path.exists(db_path):
        return {}
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # 讀取 inventory_transactions
    try:
        cur.execute("SELECT product_id, transaction_type, quantity, transaction_time, total_amount FROM inventory_transactions")
        txn_rows = cur.fetchall()
    except Exception:
        txn_rows = []
    
    conn.close()
    return txn_rows

def get_real_shelf_stock(store_id, db_dir, products):
    """從 shelf_history.db 讀取最新真實庫存"""
    history_paths = [
        os.path.join(PROJECT, "EDGE", db_dir, "smartshelf", "original", "smart_shelf_demoV31", "smart_shelf_demo", "history", "shelf_history.db"),
        os.path.join(PROJECT, "EDGE", db_dir, "smartshelf", "original", "smart_shelf_demo_v29", "smart_shelf_demo", "history", "shelf_history.db"),
    ]
    real_stock = {}
    for hpath in history_paths:
        if os.path.exists(hpath):
            try:
                conn = sqlite3.connect(hpath)
                cur = conn.cursor()
                # get latest timestamp
                cur.execute("SELECT DISTINCT timestamp FROM inventory_history ORDER BY timestamp DESC LIMIT 1")
                ts = cur.fetchone()
                if ts:
                    ts = ts[0]
                    # 讀欄位
                    cur.execute("PRAGMA table_info(inventory_history)")
                    cols = [c[1] for c in cur.fetchall()]
                    if 'base_area' in cols:
                        cur.execute("SELECT item_name, occ_rate, base_area FROM inventory_history WHERE timestamp=?", (ts,))
                        for r in cur.fetchall():
                            stock = round(r[2] * r[1]) if r[2] else round(100 * r[1])
                            real_stock[r[0].strip()] = stock
                    elif 'zone_qty' in cols and 'occ_rate' in cols:
                        cur.execute("SELECT zone_name, zone_qty, occ_rate FROM inventory_history WHERE timestamp=?", (ts,))
                        for r in cur.fetchall():
                            stock = round(r[1] * r[2]) if r[1] else round(100 * r[2])
                            real_stock[r[0].strip()] = stock
                conn.close()
            except Exception as e:
                print(f"  [WARN] 讀取歷史庫存失敗: {e}")
            break
    
    # 特殊映射：shelf_history.db 中區分 can1/can2，但 sku_v3 只有一個 can
    # 合併 can1 + can2 = total
    SPECIAL_MERGE = {
        'sprite_can': ['sprite_can1', 'sprite_can2'],
        'cola_can': ['cola_can1', 'cola_can2'],
        'kirin_beer': ['kirin_beer1', 'kirin_beer2'],
    }
    
    # map to products
    result = {}
    for p in products:
        cat = p["sku_category"]
        # exact match
        if cat in real_stock:
            result[cat] = real_stock[cat]
        elif cat in SPECIAL_MERGE:
            # 合併 can1 + can2
            total = 0
            for sub in SPECIAL_MERGE[cat]:
                if sub in real_stock:
                    total += real_stock[sub]
            if total > 0:
                result[cat] = total
            else:
                result[cat] = p["stock_quantity"]
        else:
            # fuzzy: match ch_name or search
            for sh_name, sh_stock in real_stock.items():
                if cat.lower() in sh_name.lower() or sh_name.lower() in cat.lower():
                    result[cat] = sh_stock
                    break
            if cat not in result:
                result[cat] = p["stock_quantity"]  # fallback to EDGE_DB
    return result


def generate_daily_snapshots(store_id, region, products, days, sku_prices, real_stock=None):
    """
    為每個產品產生 days 天的每日快照資料
    回傳: list of dict (符合 inventory_raw 表格欄位)
    """
    snapshots = []
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    
    print(f"\n  🏪 {store_id} ({region}) — 產生 {days} 天每日快照")
    print(f"     產品數: {len(products)}")
    
    for product in products:
        sku_cat = product["sku_category"]
        price = sku_prices.get(sku_cat, product["retail_price"])
        
        # 從真實庫存資料作為最新日庫存
        if real_stock and sku_cat in real_stock:
            # 最新日 = end_date 的庫存是真實的
            end_stock = real_stock[sku_cat]
            # 從 end_stock 反推 90 天的模擬每日需求
            max_cap = product.get("max_capacity", 200)
            reorder = product.get("reorder_level", 20)
            
            # 建立 2D array: [(date, actual_stock, units_sold, units_ordered)]
            # 從最新日開始，逐步反推
            daily_demand = random.uniform(2, 10)
            
            # 從最舊天開始生成，確保最新天的庫存 = real_stock
            # 方式：先推算一個初始 stock，然後一路往前模擬，最後校正
            raw_days = []
            current_stock = end_stock
            for day_offset_rev in range(days):
                actual_offset = days - 1 - day_offset_rev  # 從最新往最舊
                sim_date = start_date + timedelta(days=actual_offset)
                date_str = sim_date.isoformat()
                
                is_weekend = sim_date.weekday() >= 5
                base_sold = daily_demand * (1.3 if is_weekend else 1.0)
                units_sold = max(0, int(random.gauss(base_sold, base_sold * 0.4)))
                if units_sold > current_stock:
                    units_sold = max(0, current_stock)
                
                prev_stock = current_stock
                current_stock -= units_sold
                
                units_ordered = 0
                if current_stock < reorder:
                    units_ordered = random.randint(30, 80)
                    current_stock += units_ordered
                
                # 最新一天用真實庫存
                if day_offset_rev == 0:
                    current_stock = end_stock
                
                raw_days.append({
                    "date": date_str,
                    "stock": max(0, current_stock),
                    "sold": units_sold,
                    "ordered": units_ordered,
                    "weekend": is_weekend,
                })
                
                if day_offset_rev == 0:
                    # 最新日已設定
                    pass
                else:
                    # 之後 days 都延續前一日的庫存
                    pass

            raw_days.reverse()  # 從最舊到最新
            
            for day_data in raw_days:
                discount = 0
                if random.random() < 0.05:
                    discount = random.choice([5, 10, 15, 20])
                demand_forecast = round(daily_demand * (1 + random.uniform(-0.3, 0.3)), 1)
                
                snapshot = {
                    "store_id": store_id,
                    "date": day_data["date"],
                    "product_id": product["product_id"],
                    "category": sku_cat,
                    "region": region,
                    "inventory_level": day_data["stock"],
                    "units_sold": day_data["sold"],
                    "units_ordered": day_data["ordered"],
                    "demand_forecast": demand_forecast,
                    "price": price,
                    "discount": float(discount),
                    "weather": "sunny" if random.random() > 0.3 else "rainy",
                    "holiday": "1" if day_data["weekend"] else "0",
                    "competitor_pricing": round(price * random.uniform(0.9, 1.1), 2),
                    "seasonality": "normal",
                }
                snapshots.append(snapshot)
        else:
            # 無真實資料，隨機（相容舊版）
            current_stock = random.randint(100, 200)
            daily_demand = random.uniform(3, 12)
            
            for day_offset in range(days):
                sim_date = start_date + timedelta(days=day_offset)
                date_str = sim_date.isoformat()
                
                # 決定今日銷售量
                is_weekend = sim_date.weekday() >= 5
                base_sold = daily_demand * (1.3 if is_weekend else 1.0)
                units_sold = max(0, int(random.gauss(base_sold, base_sold * 0.4)))
                
                # 庫存不能為負數
                if units_sold > current_stock:
                    units_sold = max(0, current_stock)
                
                # 更新庫存
                prev_stock = current_stock
                current_stock -= units_sold
                
                # 如果庫存過低則自動補貨
                units_ordered = 0
                if current_stock < product["reorder_level"]:
                    units_ordered = random.randint(30, 80)
                    current_stock += units_ordered
                
                # 折扣（隨機，大部分無折扣）
                discount = 0
                if random.random() < 0.05:  # 5% 機率打折
                    discount = random.choice([5, 10, 15, 20])
                
                # 需求預測 = 過去趨勢 + 隨機波動
                demand_forecast = round(daily_demand * (1 + random.uniform(-0.3, 0.3)), 1)
                
                snapshot = {
                    "store_id": store_id,
                    "date": date_str,
                    "product_id": product["product_id"],
                    "category": sku_cat,
                    "region": region,
                    "inventory_level": max(0, current_stock),
                    "units_sold": units_sold,
                    "units_ordered": units_ordered,
                    "demand_forecast": demand_forecast,
                    "price": price,
                    "discount": float(discount),
                    "weather": "sunny" if random.random() > 0.3 else "rainy",
                    "holiday": "1" if is_weekend else "0",
                    "competitor_pricing": round(price * random.uniform(0.9, 1.1), 2),
                    "seasonality": "normal",
                }
                snapshots.append(snapshot)
    
    return snapshots

def write_to_cloud_db(snapshots):
    """寫入 cloud_inventory.db 的 inventory_raw 表格"""
    if not snapshots:
        print("  [SKIP] 無資料寫入")
        return
    
    conn = sqlite3.connect(CLOUD_DB)
    cur = conn.cursor()
    
    # 確保 inventory_raw 表格存在
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT,
            date TEXT,
            product_id TEXT,
            category TEXT,
            region TEXT,
            inventory_level INTEGER,
            units_sold INTEGER,
            units_ordered INTEGER,
            demand_forecast REAL,
            price REAL,
            discount REAL,
            weather TEXT,
            holiday TEXT,
            competitor_pricing REAL,
            seasonality TEXT
        )
    """)
    
    # 清空舊資料（選擇性：可改為僅清除當前門市資料）
    store_ids = set(s["store_id"] for s in snapshots)
    for sid in store_ids:
        cur.execute("DELETE FROM inventory_raw WHERE store_id = ?", (sid,))
    
    print(f"     寫入 {len(snapshots)} 筆記錄到 cloud_inventory.db ...")
    
    # 批次寫入
    batch_size = 500
    for i in range(0, len(snapshots), batch_size):
        batch = snapshots[i:i + batch_size]
        for s in batch:
            cur.execute(
                "INSERT INTO inventory_raw (store_id, date, product_id, category, region, "
                "inventory_level, units_sold, units_ordered, demand_forecast, price, discount, "
                "weather, holiday, competitor_pricing, seasonality) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s["store_id"], s["date"], s["product_id"], s["category"], s["region"],
                 s["inventory_level"], s["units_sold"], s["units_ordered"], s["demand_forecast"],
                 s["price"], s["discount"], s["weather"], s["holiday"], 
                 s["competitor_pricing"], s["seasonality"])
            )
        conn.commit()
    
    conn.close()
    print(f"  ✅ 已寫入 {len(snapshots)} 筆至 cloud_inventory.db")

def export_csv(snapshots, csv_path):
    """匯出 CSV 供 inventory_sales_report_zh.py 使用"""
    if not snapshots:
        print("  [SKIP] 無資料可匯出")
        return
    
    fieldnames = [
        "Store ID", "Product ID", "Category", "Region", "Date",
        "Inventory Level", "Units Sold", "Units Ordered", "Demand Forecast",
        "Price", "Discount"
    ]
    
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for s in snapshots:
            writer.writerow({
                "Store ID": s["store_id"],
                "Product ID": s["product_id"],
                "Category": s["category"],
                "Region": s["region"],
                "Date": s["date"],
                "Inventory Level": s["inventory_level"],
                "Units Sold": s["units_sold"],
                "Units Ordered": s["units_ordered"],
                "Demand Forecast": s["demand_forecast"],
                "Price": s["price"],
                "Discount": s["discount"],
            })
    
    print(f"  ✅ 已匯出 CSV: {csv_path}")
    print(f"     共 {len(snapshots)} 筆記錄")

def main():
    parser = argparse.ArgumentParser(description="EDGE → CLOUD 資料同步工具")
    parser.add_argument("--days", type=int, default=90, help="歷史天數 (預設: 90)")
    parser.add_argument("--export-csv", action="store_true", help="同時匯出 CSV")
    parser.add_argument("--csv-path", default=None, help="CSV 匯出路徑")
    args = parser.parse_args()
    
    print("=" * 60)
    print("USI Smart Retail OS — EDGE → CLOUD 資料同步")
    print("=" * 60)
    
    # 載入 sku_v2 價格
    sku_prices = load_sku_prices()
    print(f"\n[OK] 價格已載入 ({len(sku_prices)} 項)")
    
    all_snapshots = []
    
    for store_id, config in STORE_CONFIG.items():
        products = get_edge_products(store_id, config["db_dir"])
        if not products:
            print(f"  [WARN] {store_id} 無產品資料")
            continue
        
        print(f"\n  📦 {store_id}: 找到 {len(products)} 項產品")
        for p in products:
            print(f"      {p['sku_category']:15s} | {p['product_id']:40s} | 零售價: ${p['retail_price']}")
        
        # 讀取真實庫存資料作為最新日
        real_stock = get_real_shelf_stock(store_id, config["db_dir"], products)
        print(f"     真實庫存: {len(real_stock)} 項")
        snapshots = generate_daily_snapshots(store_id, config["region"], products, args.days, sku_prices, real_stock)
        all_snapshots.extend(snapshots)
    
    if not all_snapshots:
        print("\n❌ 無資料可同步")
        return
    
    # 寫入 CLOUD DB
    write_to_cloud_db(all_snapshots)
    
    # 匯出 CSV
    csv_path = args.csv_path or os.path.join(PROJECT, "CLOUD", "inventory", "retail_store_inventory.csv")
    if args.export_csv:
        export_csv(all_snapshots, csv_path)
    
    # 更新 store_info
    conn = sqlite3.connect(CLOUD_DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS store_info (
            store_id TEXT PRIMARY KEY,
            name_zh TEXT,
            name_en TEXT,
            name_ja TEXT,
            region TEXT
        )
    """)
    for store_id, config in STORE_CONFIG.items():
        name_zh = "台北忠孝店" if store_id == "Taipei Zhongxiao" else "大阪心齋橋店"
        name_en = f"{store_id} Store"
        name_ja = "台北忠孝店" if store_id == "Taipei Zhongxiao" else "大阪心斎橋店"
        cur.execute(
            "INSERT OR REPLACE INTO store_info (store_id, name_zh, name_en, name_ja, region) VALUES (?, ?, ?, ?, ?)",
            (store_id, name_zh, name_en, name_ja, config["region"])
        )
    conn.commit()
    conn.close()
    
    print(f"\n{'='*60}")
    print(f"✅ 同步完成！")
    print(f"   門市數: {len(STORE_CONFIG)}")
    print(f"   天數: {args.days}")
    print(f"   總記錄數: {len(all_snapshots):,}")
    print(f"   CLOUD DB: {CLOUD_DB}")
    if args.export_csv:
        print(f"   CSV: {csv_path}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
