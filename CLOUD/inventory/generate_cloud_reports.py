#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - Cloud Inventory Report Generator
"""

import sqlite3, json, csv, os
from pathlib import Path
from datetime import datetime

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')

STORE_FOLDERS = [
    "Taipei Zhongxiao_台北忠孝店_台北忠孝店",
    "Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店",
    "Nantou Nangang_南投南崗店_南投南崗店",
]

def ext(folder):
    """Extract short store id from folder name"""
    return folder.split("_")[0]

def load_store_inventory(folder):
    db_path = PROJECT / 'EDGE' / folder / 'EDGE_DB.db'
    sid = ext(folder)

    if not db_path.exists():
        print(f"  [WARN] {sid} no DB")
        return sid, []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enhanced_inventory'")
    if not cur.fetchone():
        conn.close(); return sid, []

    cur.execute("SELECT product_id,product_name,category,stock_quantity,unit_price,retail_price,max_capacity,shelf_position FROM enhanced_inventory ORDER BY category,product_name")
    rows = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT store_id,name_zh,name_en FROM store_info LIMIT 1")
    info = cur.fetchone()
    label = info['name_en'] if info else sid
    conn.close()
    print(f"  [OK] {sid} ({label}): {len(rows)} items")
    return sid, rows

def run():
    print("="*60)
    print("USI Smart Retail OS - Cloud Report Generator")
    print("="*60)

    all_data = {}
    for folder in STORE_FOLDERS:
        print(f"\nLoading {ext(folder)}...")
        sid, inv = load_store_inventory(folder)
        if inv:
            all_data[sid] = inv

    if not all_data:
        print("\n[FAIL] No data")
        return

    # Summary
    rpt = {'generated_at': datetime.now().isoformat(), 'total_stores': len(all_data),
           'summary': {'total_products': 0, 'total_inventory_value': 0.0,
                       'out_of_stock_count': 0, 'low_stock_count': 0, 'in_stock_count': 0},
           'stores': {}}
    for sid, inv in all_data.items():
        s = {'product_count': len(inv), 'total_value': 0.0,
             'out_of_stock': 0, 'low_stock': 0, 'in_stock': 0}
        for item in inv:
            s['total_value'] += item['stock_quantity'] * item['retail_price']
            if item['stock_quantity'] <= 0: s['out_of_stock'] += 1
            elif item['stock_quantity'] <= int(item['max_capacity'] * 0.2): s['low_stock'] += 1
            else: s['in_stock'] += 1
        rpt['stores'][sid] = s
        rpt['summary']['total_products'] += s['product_count']
        rpt['summary']['total_inventory_value'] += s['total_value']
        rpt['summary']['out_of_stock_count'] += s['out_of_stock']
        rpt['summary']['low_stock_count'] += s['low_stock']
        rpt['summary']['in_stock_count'] += s['in_stock']

    # Save
    rdir = PROJECT / 'CLOUD/reports'
    rdir.mkdir(parents=True, exist_ok=True)
    with open(rdir / 'inventory_summary.json', 'w', encoding='utf-8') as f:
        json.dump(rpt, f, indent=2, ensure_ascii=False)
    print(f"\n  [JSON] inventory_summary.json")

    # CSVs
    for sid, inv in all_data.items():
        sdir = PROJECT / 'CLOUD/inventory' / sid
        sdir.mkdir(parents=True, exist_ok=True)
        fp = sdir / f'inventory_{sid}.csv'
        with open(fp, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['ProductID','ProductName','Category','Stock','UnitPrice','RetailPrice'])
            for item in inv:
                w.writerow([item['product_id'], item['product_name'], item['category'],
                           item['stock_quantity'], item['unit_price'], item['retail_price']])
        print(f"  [CSV] {sid}/inventory_{sid}.csv ({len(inv)} rows)")

    # Consolidated CSV
    cp = rdir / 'inventory_consolidated.csv'
    with open(cp, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['StoreID','ProductID','ProductName','Category','Stock','UnitPrice','RetailPrice','Status'])
        for sid, inv in all_data.items():
            for item in inv:
                st = 'OUT_OF_STOCK' if item['stock_quantity']<=0 else 'LOW_STOCK' if item['stock_quantity']<=int(item['max_capacity']*0.2) else 'IN_STOCK'
                w.writerow([sid,item['product_id'],item['product_name'],item['category'],
                           item['stock_quantity'],item['unit_price'],item['retail_price'],st])
    print(f"  [CSV] inventory_consolidated.csv")

    s = rpt['summary']
    print(f"\n=== SUMMARY ===")
    print(f"  Stores: {rpt['total_stores']}")
    print(f"  Products: {s['total_products']:,}")
    print(f"  Value: NT${s['total_inventory_value']:,.0f}")
    print(f"  IN_STOCK: {s['in_stock_count']}  LOW_STOCK: {s['low_stock_count']}  OUT_OF_STOCK: {s['out_of_stock_count']}")

if __name__ == '__main__':
    run()
