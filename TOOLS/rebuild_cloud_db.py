#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - CLOUD Database Builder
Merges CSV stores + EDGE stores into cloud_inventory.db
"""

import sqlite3, csv, sys
from pathlib import Path
from datetime import datetime

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')

# Japanese CSV stores
CSV_STORES = {
    "Ginza":     {"en":"Ginza Store","zh":"銀座店","ja":"銀座店","region":"Tokyo"},
    "Ikebukuro": {"en":"Ikebukuro Store","zh":"池袋店","ja":"池袋店","region":"Tokyo"},
    "Shibuya":   {"en":"Shibuya Store","zh":"澀谷店","ja":"渋谷店","region":"Tokyo"},
    "Shinjuku":  {"en":"Shinjuku Store","zh":"新宿店","ja":"新宿店","region":"Tokyo"},
    "Ueno":      {"en":"Ueno Store","zh":"上野店","ja":"上野店","region":"Tokyo"},
}

# EDGE stores
EDGE_STORES = [
    ("Taipei Zhongxiao", PROJECT / 'EDGE/Taipei Zhongxiao_台北忠孝店_台北忠孝店/EDGE_DB.db',
     {"en":"Taipei Zhongxiao Store","zh":"台北忠孝店","ja":"台北忠孝店","region":"Taipei"}),
    ("Osaka Shinsaibashi", PROJECT / 'EDGE/Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店/EDGE_DB.db',
     {"en":"Osaka Shinsaibashi Store","zh":"大阪心齋橋店","ja":"大阪心斎橋店","region":"Osaka"}),
]

DB_PATH = PROJECT / 'CLOUD/database/cloud_inventory.db'
CSV_OUT = PROJECT / 'CLOUD/inventory/cloud_consolidated.csv'

def build():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"  Removed old {DB_PATH.name}")

    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE inventory_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT, date TEXT, product_id TEXT, category TEXT, region TEXT,
            inventory_level INTEGER, units_sold INTEGER, units_ordered INTEGER,
            demand_forecast REAL, price REAL, discount REAL,
            weather TEXT, holiday TEXT, competitor_pricing REAL, seasonality TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE store_info (
            store_id TEXT PRIMARY KEY,
            name_zh TEXT, name_en TEXT, name_ja TEXT, region TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE sales_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT, date TEXT, product_id TEXT, category TEXT,
            units_sold INTEGER, revenue REAL
        )
    """)

    total_rows = 0

    # ── 1. CSV stores ──
    csv_path = PROJECT.parent / 'inventory/retail_store_inventory.csv'
    if csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            store_map = {"S001":"Ginza","S002":"Ikebukuro","S003":"Shibuya","S004":"Shinjuku","S005":"Ueno"}
            for row in reader:
                sid = store_map.get(row['Store ID'], row['Store ID'])
                cur.execute("""
                    INSERT INTO inventory_raw
                    (store_id, date, product_id, category, region,
                     inventory_level, units_sold, units_ordered, demand_forecast,
                     price, discount, weather, holiday, competitor_pricing, seasonality)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    sid, row['Date'], row['Product ID'], row['Category'], row['Region'],
                    int(row['Inventory Level']), int(row['Units Sold']), int(row['Units Ordered']),
                    float(row['Demand Forecast']), float(row['Price']), float(row['Discount']),
                    row.get('Weather Condition',''), row.get('Holiday/Promotion',''),
                    float(row.get('Competitor Pricing',0)), row.get('Seasonality','')
                ))
                revenue = int(row['Units Sold']) * float(row['Price']) * (1 - float(row['Discount'])/100)
                cur.execute("""
                    INSERT INTO sales_summary (store_id, date, product_id, category, units_sold, revenue)
                    VALUES (?,?,?,?,?,?)
                """, (sid, row['Date'], row['Product ID'], row['Category'], int(row['Units Sold']), round(revenue,2)))
                total_rows += 1

        for sid, info in CSV_STORES.items():
            cur.execute("INSERT OR REPLACE INTO store_info VALUES (?,?,?,?,?)",
                       (sid, info['zh'], info['en'], info['ja'], info['region']))
        print(f"  CSV stores: {total_rows:,} rows")

    # ── 2. EDGE stores ──
    for sid, db_path, info in EDGE_STORES:
        if not db_path.exists():
            print(f"  [SKIP] {sid} — EDGE_DB.db not found")
            continue

        try:
            econn = sqlite3.connect(str(db_path))
            ec = econn.cursor()
            ec.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enhanced_inventory'")
            if not ec.fetchone():
                econn.close()
                print(f"  [SKIP] {sid} — no enhanced_inventory")
                continue

            ec.execute("SELECT product_id, product_name, category, stock_quantity, unit_price, retail_price FROM enhanced_inventory")
            records = ec.fetchall()
            for pid, pname, cat, stock, up, rp in records:
                cur.execute("""
                    INSERT INTO inventory_raw
                    (store_id, date, product_id, category, region, inventory_level, units_sold, units_ordered,
                     demand_forecast, price, discount, weather, holiday, competitor_pricing, seasonality)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (sid, datetime.now().strftime('%Y-%m-%d'), pid, cat, info['region'],
                      stock, 0, 0, 0.0, rp, 0.0, '', '', 0.0, ''))
                cur.execute("""
                    INSERT INTO sales_summary (store_id, date, product_id, category, units_sold, revenue)
                    VALUES (?,?,?,?,?,?)
                """, (sid, datetime.now().strftime('%Y-%m-%d'), pid, cat, 0, 0))
                total_rows += 1

            cur.execute("INSERT OR REPLACE INTO store_info VALUES (?,?,?,?,?)",
                       (sid, info['zh'], info['en'], info['ja'], info['region']))
            econn.close()
            print(f"  EDGE {sid}: {len(records)} items")
        except Exception as e:
            print(f"  [ERROR] {sid}: {e}")

    conn.commit()
    conn.close()
    print(f"\n  Total rows: {total_rows:,}")
    print(f"  DB: {DB_PATH}")
    print(f"  DB size: {DB_PATH.stat().st_size:,} bytes")

    # ── Export CSV ──
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventory_raw")
    headers = [d[0] for d in cur.description]
    with open(CSV_OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(cur.fetchall())
    conn.close()
    print(f"  CSV: {CSV_OUT}")

    # Show store count
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM store_info")
    print(f"  Stores in DB: {cur.fetchone()[0]}")
    conn.close()

if __name__ == '__main__':
    build()
