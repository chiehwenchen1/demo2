#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - DB Status Viewer
"""

import sqlite3, json, os
from pathlib import Path

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')

STORE_FOLDERS = [
    "Taipei Zhongxiao_台北忠孝店_台北忠孝店",
    "Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店",
]

def show_edge_db(folder):
    store_path = PROJECT / 'EDGE' / folder
    db_path = store_path / 'EDGE_DB.db'

    # Extract short ID for display
    parts = folder.split("_")
    short_id = parts[0]

    print(f"\n{'='*70}")
    print(f"  EDGE: {short_id}  —  {folder}")
    print(f"{'='*70}")

    if not db_path.exists():
        print("  [MISS] EDGE_DB.db not found")
        return

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print(f"  Tables: {', '.join(tables)}")

    if 'store_info' in tables:
        cur.execute("SELECT store_id, name_zh, name_en, name_ja, region FROM store_info")
        r = cur.fetchone()
        if r:
            print(f"  Store ID: {r[0]}")
            print(f"  Name: {r[1]} / {r[2]} / {r[3]}  |  Region: {r[4]}")

    if 'enhanced_inventory' in tables:
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT product_id), SUM(stock_quantity), SUM(stock_quantity*retail_price) FROM enhanced_inventory")
        cnt, prod, stock, val = cur.fetchone()
        stock = stock or 0; val = val or 0
        print(f"  [enhanced_inventory] {cnt} rows, {prod} unique products")
        print(f"    Stock: {stock:,} units  |  Value: NT${val:,.0f}")

        cur.execute("""
            SELECT CASE WHEN stock_quantity <= 0 THEN 'OUT_OF_STOCK'
                        WHEN stock_quantity <= reorder_level THEN 'LOW_STOCK'
                        ELSE 'IN_STOCK' END, COUNT(*)
            FROM enhanced_inventory GROUP BY 1 ORDER BY 1
        """)
        for s, c in cur.fetchall():
            print(f"    {s:15s}: {c:4d} items")

        cur.execute("""
            SELECT product_id, product_name, stock_quantity, retail_price,
                   stock_quantity*retail_price
            FROM enhanced_inventory WHERE stock_quantity>0
            ORDER BY stock_quantity*retail_price DESC LIMIT 3
        """)
        print(f"    Top 3:")
        for pid, pname, stk, price, val in cur.fetchall():
            print(f"      {pid:35s} {pname:20s} {stk:3d} x NT${price:>6.0f} = NT${val:>8,.0f}")

    if 'price_history' in tables:
        cur.execute("SELECT COUNT(*) FROM price_history")
        print(f"  [price_history] {cur.fetchone()[0]} products")

    if 'edge_inventory' in tables:
        cur.execute("SELECT COUNT(*), SUM(current_stock) FROM edge_inventory")
        cnt, stk = cur.fetchone()
        print(f"  [edge_inventory] {cnt} items, {stk or 0} units")

    if 'product_catalog' in tables:
        cur.execute("SELECT COUNT(*) FROM product_catalog")
        print(f"  [product_catalog] {cur.fetchone()[0]} products")

    if 'transaction_log' in tables:
        cur.execute("SELECT COUNT(*) FROM transaction_log")
        cnt = cur.fetchone()[0]
        if cnt:
            cur.execute("SELECT SUM(total_price) FROM transaction_log")
            total = cur.fetchone()[0] or 0
            print(f"  [transaction_log] {cnt} txns, NT${total:,}")
        else:
            print(f"  [transaction_log] empty")

    conn.close()

def show_cloud():
    print(f"\n{'='*70}")
    print("  CLOUD REPORTS")
    print(f"{'='*70}")

    reports_dir = PROJECT / 'CLOUD' / 'reports'
    if reports_dir.exists():
        for f in sorted(os.listdir(reports_dir)):
            fp = reports_dir / f
            print(f"  {f:45s} {fp.stat().st_size:>8,} bytes")

    sum_file = reports_dir / 'inventory_summary.json'
    if sum_file.exists():
        with open(sum_file, 'r', encoding='utf-8') as f:
            summary = json.load(f)
        s = summary['summary']
        print(f"\n  Total: {s['total_products']:,} products, NT${s['total_inventory_value']:,.0f}")
        print(f"  IN_STOCK: {s['in_stock_count']}  LOW_STOCK: {s['low_stock_count']}  OUT_OF_STOCK: {s['out_of_stock_count']}")

    inv_dir = PROJECT / 'CLOUD' / 'inventory'
    print(f"\n  Store CSVs:")
    for sd in sorted(os.listdir(inv_dir)):
        inv_path = inv_dir / sd
        if not inv_path.is_dir():
            continue
        for f in os.listdir(inv_path):
            if f.endswith('.csv'):
                fp = inv_path / f
                with open(fp, 'r', encoding='utf-8-sig') as fh:
                    lines = sum(1 for _ in fh) - 1
                print(f"    {sd:35s} {lines:>5,} rows ({fp.stat().st_size:>8,} bytes)")

def main():
    print("=" * 70)
    print("  USI SMART RETAIL OS — DATABASE STATUS")
    print()

    for folder in STORE_FOLDERS:
        show_edge_db(folder)

    show_cloud()

    print(f"\n{'='*70}")
    print("  REGENERATE: python EDGE/services/init_stores.py")
    print("  REPORTS:    python CLOUD/inventory/generate_cloud_reports.py")
    print(f"{'='*70}")

if __name__ == '__main__':
    main()
