#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - USI_NK_Store Real-time Integration
Bridges Smart Shelf OOS/LOS detection with inventory sales report.

Item categories are read DIRECTLY from shelf_history.db to match original data.
Reports are generated inside USI_SMART_RETAIL_OS project structure.
"""

import sqlite3
import pandas as pd
import numpy as np
import time
import sys
import os
import shutil
import json
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path('D:/bible')
PROJECT = BASE / 'USI_SMART_RETAIL_OS'

# Edge layer
EDGE_INVENTORY_DIR = PROJECT / 'EDGE/inventory'
EDGE_REPORT_DIR = PROJECT / 'EDGE/inventory/reports'
EDGE_REPORT_SCRIPT = PROJECT / 'EDGE/services/inventory_sales_report_zh.py'

# Source files
INVENTORY_CSV = BASE / 'inventory/retail_store_inventory.csv'
INVENTORY_USI_NK = EDGE_INVENTORY_DIR / 'retail_store_inventory_with_usi_nk.csv'
SHELF_DB = PROJECT / 'EDGE/store_001/smartshelf/original/smart_shelf_demo_v27_phone_formalrelease/history/shelf_history.db'

# Cloud layer
CLOUD_REPORT_DIR = PROJECT / 'CLOUD/reports'

# ============================================================
# Category mapping from shelf_history.db original categories
# Shelf category is the item name itself (e.g. big_cola, beer1)
# We map them to retail-friendly category groups
# ============================================================
SHELF_CATEGORY_MAP = {
    # Beverages - Cola
    'big_cola': 'Beverages', 'cola': 'Beverages', 'pepsi': 'Beverages',
    'sprite': 'Beverages', 'sprite_can1': 'Beverages', 'sprite_can2': 'Beverages',
    'cola_can1': 'Beverages', 'cola_can2': 'Beverages',
    # Beverages - Beer
    'beer1': 'Beverages', 'beer2': 'Beverages', 'beer3': 'Beverages',
    'beer4': 'Beverages', 'beer5': 'Beverages', 'beer6': 'Beverages',
    # Beverages - Others
    'coffee': 'Beverages', 'imei': 'Beverages', 'soup': 'Beverages', 'tomato': 'Beverages',
    # Snacks
    'cookie1': 'Snacks', 'cookie2': 'Snacks', 'cookie3': 'Snacks',
    'cookie4': 'Snacks', 'cookie5': 'Snacks', 'cookie6': 'Snacks', 'cookie7': 'Snacks',
    # Groceries
    'noodle1': 'Groceries', 'noodle2': 'Groceries', 'noodle3': 'Groceries', 'noodle4': 'Groceries',
    'croc': 'Groceries',
    # Household
    'dalli': 'Household', 'raid': 'Household', 'combat': 'Household', 'paper': 'Household',
}

# Shelf base_name -> retail Product ID
SMART_SHELF_PRODUCT_MAP = {
    'big_cola': 'P0001', 'cola': 'P0001', 'pepsi': 'P0001',
    'sprite': 'P0002', 'sprite_can1': 'P0002', 'sprite_can2': 'P0002',
    'coffee': 'P0003', 'imei': 'P0003',
    'soup': 'P0004', 'tomato': 'P0004',
    'beer1': 'P0005', 'beer2': 'P0005', 'beer3': 'P0005',
    'beer4': 'P0005', 'beer5': 'P0005', 'beer6': 'P0005',
    'cookie1': 'P0010', 'cookie2': 'P0010', 'cookie3': 'P0010',
    'cookie4': 'P0010', 'cookie5': 'P0010', 'cookie6': 'P0010', 'cookie7': 'P0010',
    'noodle1': 'P0011', 'noodle2': 'P0011', 'noodle3': 'P0011', 'noodle4': 'P0011',
    'cola_can1': 'P0016', 'cola_can2': 'P0016', 'croc': 'P0016',
    'paper': 'P0020', 'combat': 'P0020', 'raid': 'P0020', 'dalli': 'P0020',
}


def read_shelf_status():
    """Read every slot OCC_RATE + original category from shelf_history.db"""
    if not SHELF_DB.exists():
        print(f"[ERROR] Shelf DB not found: {SHELF_DB}")
        return None

    conn = sqlite3.connect(SHELF_DB)
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(timestamp) FROM inventory_history")
    latest_ts = cursor.fetchone()[0]

    cursor.execute("""
        SELECT item_name, category, occ_rate, status, slot_id, timestamp
        FROM inventory_history
        WHERE timestamp = ?
        ORDER BY item_name
    """, (latest_ts,))

    rows = cursor.fetchall()
    conn.close()

    print(f"[Shelf] Read {len(rows)} records at {latest_ts}")
    return rows, latest_ts


def aggregate_by_retail_product(shelf_rows):
    """
    Aggregate shelf slots by retail Product ID.
    Returns: list of {pid, category, stock, units_sold, demand, …}
    The 'category' comes from SHELF_CATEGORY_MAP, not from retail CSV.
    """
    from collections import defaultdict

    pid_occ = defaultdict(list)
    pid_original_cats = defaultdict(set)

    for item_name, orig_category, occ_rate, status, slot_id, timestamp in shelf_rows:
        base_name = item_name.rsplit('_R', 1)[0] if '_R' in item_name else item_name
        pid = SMART_SHELF_PRODUCT_MAP.get(base_name)
        if pid is None:
            continue
        pid_occ[pid].append(occ_rate)
        # Keep original shelf category
        pid_original_cats[pid].add(orig_category)

    inventory_items = []
    for pid, occ_rates in pid_occ.items():
        avg_occ = np.mean(occ_rates)
        max_capacity = 200
        stock = int(avg_occ * max_capacity)
        units_sold = max(0, int((1 - avg_occ) * max_capacity * 0.3))
        demand = int(max(5, (1 - avg_occ) * 30))

        # Use shelf category (first original category seen for this PID)
        orig_cats = pid_original_cats[pid]
        first_base = next(iter(orig_cats))
        shelf_category = SHELF_CATEGORY_MAP.get(first_base, 'Beverages')

        inventory_items.append({
            'pid': pid,
            'stock': stock,
            'units_sold': units_sold,
            'demand': demand,
            'category': shelf_category,
            'slot_count': len(occ_rates),
        })

    return inventory_items


def generate_usi_nk_csv_data(today=None):
    """Generate USI_NK_Store CSV rows from shelf data + template"""
    if today is None:
        today = datetime.now()

    shelf_data = read_shelf_status()
    if shelf_data is None or shelf_data[0] is None:
        print("[FAIL] Cannot read shelf data")
        return None

    shelf_rows, latest_ts = shelf_data
    inv_items = aggregate_by_retail_product(shelf_rows)
    print(f"[USI_NK] Mapped {len(inv_items)} retail products from shelf")

    # Read original retail CSV as template for prices etc.
    df_template = pd.read_csv(INVENTORY_CSV)
    s001_data = df_template[df_template['Store ID'] == 'S001']
    template_lookup = {}
    for pid in sorted(s001_data['Product ID'].unique()):
        tpl = s001_data[s001_data['Product ID'] == pid].iloc[0]
        template_lookup[pid] = tpl

    today_str = today.strftime('%Y-%m-%d')
    rows = []

    for item in inv_items:
        tpl = template_lookup.get(item['pid'])
        if tpl is None:
            continue

        # Simulate real-time fluctuation
        time_seed = int(time.time()) % 100
        rng = np.random.default_rng(time_seed + int(item['pid'][-2:]))
        stock_delta = rng.integers(-3, 3)
        actual_stock = max(0, item['stock'] + stock_delta)
        actual_sold = max(0, item['units_sold'] + rng.integers(0, 2))

        if actual_stock < item['demand'] * 3:
            units_ordered = max(10, int(item['demand'] * 7))
        else:
            units_ordered = max(0, int(item['demand'] * 14 - actual_stock))

        rows.append({
            'Date': today_str,
            'Store ID': 'USI_NK',
            'Product ID': item['pid'],
            # Category from shelf, not from retail template
            'Category': item['category'],
            'Region': 'North',
            'Inventory Level': actual_stock,
            'Units Sold': actual_sold,
            'Units Ordered': units_ordered,
            'Demand Forecast': item['demand'],
            'Price': tpl['Price'],
            'Discount': tpl['Discount'],
            'Weather Condition': 'Clear',
            'Holiday/Promotion': 0,
            'Competitor Pricing': tpl['Competitor Pricing'],
            'Seasonality': 'Normal',
        })

    # Fill remaining PIDs not on the shelf (use template data + shelf categories)
    existing_pids = {r['Product ID'] for r in rows}
    for pid in sorted(template_lookup.keys()):
        if pid not in existing_pids:
            tpl = template_lookup[pid]
            rows.append({
                'Date': today_str,
                'Store ID': 'USI_NK',
                'Product ID': pid,
                'Category': tpl['Category'],
                'Region': 'North',
                'Inventory Level': int(rng.integers(50, 300)),
                'Units Sold': int(rng.integers(0, 30)),
                'Units Ordered': int(rng.integers(10, 100)),
                'Demand Forecast': int(rng.integers(10, 50)),
                'Price': tpl['Price'],
                'Discount': tpl['Discount'],
                'Weather Condition': 'Clear',
                'Holiday/Promotion': 0,
                'Competitor Pricing': tpl['Competitor Pricing'],
                'Seasonality': 'Normal',
            })

    return pd.DataFrame(rows)


def update_inventory_csv():
    """Replace today's USI_NK data with fresh shelf data"""
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')

    EDGE_INVENTORY_DIR.mkdir(parents=True, exist_ok=True)

    if INVENTORY_USI_NK.exists():
        df_existing = pd.read_csv(INVENTORY_USI_NK)
    else:
        df_existing = pd.read_csv(INVENTORY_CSV)

    df_new = generate_usi_nk_csv_data(now)
    if df_new is None:
        return df_existing

    if 'USI_NK' in df_existing['Store ID'].values:
        old_count = len(df_existing[(df_existing['Store ID'] == 'USI_NK') &
                                     (df_existing['Date'] == today_str)])
        df_existing = df_existing[~((df_existing['Store ID'] == 'USI_NK') &
                                     (df_existing['Date'] == today_str))]
        if old_count > 0:
            print(f"[CSV] Replaced {old_count} old rows for today")

    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined.to_csv(INVENTORY_USI_NK, index=False)

    print(f"[CSV] Wrote {len(df_new)} rows -> {INVENTORY_USI_NK}")
    print(f"[CSV] Total rows: {len(df_combined)}")
    return df_combined


def generate_report():
    """Generate report inside project dirs, copy to Cloud"""
    EDGE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    CLOUD_REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[Report] Generating...")
    csv_path = str(INVENTORY_USI_NK)
    os.system(f'python "{EDGE_REPORT_SCRIPT}" --csv "{csv_path}" --out "{EDGE_REPORT_DIR}"')

    for f in ['inventory_sales_report_zh.html', 'inventory_sales_dashboard_zh.png']:
        src = EDGE_REPORT_DIR / f
        if src.exists():
            shutil.copy2(src, CLOUD_REPORT_DIR / f)
            print(f"[Cloud] Copied {f}")

    print(f"[OK] Edge:  {EDGE_REPORT_DIR}")
    print(f"[OK] Cloud: {CLOUD_REPORT_DIR}")


def run_once():
    print(f"\n{'='*60}")
    print(f"USI_NK Store - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('='*60)
    update_inventory_csv()
    generate_report()
    print(f"\n[OK] Report: {EDGE_REPORT_DIR / 'inventory_sales_report_zh.html'}")


def run_watch(interval=30):
    print(f"\n[Watch] Real-time monitor every {interval}s (Ctrl+C to stop)\n")
    try:
        while True:
            run_once()
            print(f"\n[Watch] Next update in {interval}s...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[Watch] Stopped.")


if __name__ == '__main__':
    if '--watch' in sys.argv:
        interval = 30
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            interval = int(sys.argv[2])
        run_watch(interval)
    else:
        run_once()
