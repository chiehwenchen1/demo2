#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - EDGE Inventory Database Creator
Creates a simulated inventory database inside EDGE with:
  - Product names matching shelf_history.db categories
  - Random initial stock quantities (NOT from OCC_RATE)
  - Unit prices (buy/retail)
  - Ready for checkout APK to deduct stock later

Tables:
  - edge_inventory     : current stock per product
  - product_catalog    : product info + pricing
  - transaction_log    : records from checkout APK (future use)

Run: python create_edge_inventory.py
"""

import sqlite3
import random
import json
from pathlib import Path
from datetime import datetime

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')
EDGE_DB_DIR = PROJECT / 'EDGE/store_001/local_db'
EDGE_DB_PATH = EDGE_DB_DIR / 'edge_inventory.db'

# ============================================================
# Product definitions matching shelf_history.db items
# Each product has: name, category, unit_price, max_capacity
# Prices in TWD (realistic convenience store pricing)
# ============================================================
PRODUCT_CATALOG = [
    # Beverages - Cola
    {'name': 'big_cola',     'category': 'Beverages', 'unit_price': 35, 'retail_price': 45},
    {'name': 'cola',         'category': 'Beverages', 'unit_price': 25, 'retail_price': 35},
    {'name': 'pepsi',        'category': 'Beverages', 'unit_price': 22, 'retail_price': 30},
    {'name': 'sprite',       'category': 'Beverages', 'unit_price': 22, 'retail_price': 30},
    {'name': 'sprite_can1',  'category': 'Beverages', 'unit_price': 18, 'retail_price': 25},
    {'name': 'sprite_can2',  'category': 'Beverages', 'unit_price': 18, 'retail_price': 25},
    {'name': 'cola_can1',    'category': 'Beverages', 'unit_price': 18, 'retail_price': 25},
    {'name': 'cola_can2',    'category': 'Beverages', 'unit_price': 18, 'retail_price': 25},
    # Beverages - Beer
    {'name': 'beer1',        'category': 'Beverages', 'unit_price': 38, 'retail_price': 55},
    {'name': 'beer2',        'category': 'Beverages', 'unit_price': 42, 'retail_price': 60},
    {'name': 'beer3',        'category': 'Beverages', 'unit_price': 45, 'retail_price': 65},
    {'name': 'beer4',        'category': 'Beverages', 'unit_price': 48, 'retail_price': 69},
    {'name': 'beer5',        'category': 'Beverages', 'unit_price': 50, 'retail_price': 72},
    {'name': 'beer6',        'category': 'Beverages', 'unit_price': 55, 'retail_price': 79},
    # Beverages - Others
    {'name': 'coffee',       'category': 'Beverages', 'unit_price': 30, 'retail_price': 45},
    {'name': 'imei',         'category': 'Beverages', 'unit_price': 20, 'retail_price': 30},
    {'name': 'soup',         'category': 'Beverages', 'unit_price': 25, 'retail_price': 35},
    {'name': 'tomato',       'category': 'Beverages', 'unit_price': 15, 'retail_price': 22},
    # Snacks
    {'name': 'cookie1',      'category': 'Snacks',    'unit_price': 20, 'retail_price': 30},
    {'name': 'cookie2',      'category': 'Snacks',    'unit_price': 22, 'retail_price': 32},
    {'name': 'cookie3',      'category': 'Snacks',    'unit_price': 25, 'retail_price': 38},
    {'name': 'cookie4',      'category': 'Snacks',    'unit_price': 28, 'retail_price': 42},
    {'name': 'cookie5',      'category': 'Snacks',    'unit_price': 30, 'retail_price': 45},
    {'name': 'cookie6',      'category': 'Snacks',    'unit_price': 35, 'retail_price': 50},
    {'name': 'cookie7',      'category': 'Snacks',    'unit_price': 40, 'retail_price': 58},
    # Groceries
    {'name': 'noodle1',      'category': 'Groceries',  'unit_price': 15, 'retail_price': 22},
    {'name': 'noodle2',      'category': 'Groceries',  'unit_price': 18, 'retail_price': 25},
    {'name': 'noodle3',      'category': 'Groceries',  'unit_price': 20, 'retail_price': 28},
    {'name': 'noodle4',      'category': 'Groceries',  'unit_price': 22, 'retail_price': 30},
    {'name': 'croc',         'category': 'Groceries',  'unit_price': 30, 'retail_price': 42},
    # Household
    {'name': 'dalli',        'category': 'Household',  'unit_price': 45, 'retail_price': 65},
    {'name': 'raid',         'category': 'Household',  'unit_price': 80, 'retail_price': 120},
    {'name': 'combat',       'category': 'Household',  'unit_price': 75, 'retail_price': 110},
    {'name': 'paper',        'category': 'Household',  'unit_price': 35, 'retail_price': 55},
]


def create_database():
    """Create edge_inventory.db with product_catalog and edge_inventory tables"""
    EDGE_DB_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(EDGE_DB_PATH)
    c = conn.cursor()

    # --- Product catalog (pricing reference) ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS product_catalog (
            product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT UNIQUE NOT NULL,
            category      TEXT NOT NULL,
            unit_price    INTEGER NOT NULL,
            retail_price  INTEGER NOT NULL,
            max_capacity  INTEGER DEFAULT 200,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # --- Edge inventory (current stock - will be deducted by checkout APK) ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS edge_inventory (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id    INTEGER NOT NULL REFERENCES product_catalog(product_id),
            slot_id       INTEGER,
            name          TEXT NOT NULL,
            category      TEXT NOT NULL,
            current_stock INTEGER NOT NULL,
            max_capacity  INTEGER DEFAULT 200,
            status        TEXT CHECK(status IN ('IN_STOCK','LOW_STOCK','OUT_OF_STOCK','OOS','LOS')),
            unit_price    INTEGER NOT NULL,
            retail_price  INTEGER NOT NULL,
            last_updated  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # --- Transaction log (for future checkout APK) ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS transaction_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id  TEXT NOT NULL,
            product_name    TEXT NOT NULL,
            quantity        INTEGER NOT NULL,
            total_price     INTEGER NOT NULL,
            payment_method  TEXT DEFAULT 'CASH',
            customer_id     TEXT,
            checkout_time   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print(f"[DB] Created tables at {EDGE_DB_PATH}")


def populate_products():
    """Insert product catalog and generate random initial stock"""
    conn = sqlite3.connect(EDGE_DB_PATH)
    c = conn.cursor()

    # Clear existing data
    c.execute('DELETE FROM edge_inventory')
    c.execute('DELETE FROM product_catalog')
    conn.commit()

    # Insert product catalog
    for p in PRODUCT_CATALOG:
        c.execute('''
            INSERT OR IGNORE INTO product_catalog (name, category, unit_price, retail_price, max_capacity)
            VALUES (?, ?, ?, ?, ?)
        ''', (p['name'], p['category'], p['unit_price'], p['retail_price'], 200))
    conn.commit()

    print(f"[Products] Inserted {len(PRODUCT_CATALOG)} products into catalog")

    # Generate random stock per product
    # Each product may have 1-3 slots on shelf
    stock_entries = []
    for p in PRODUCT_CATALOG:
        c.execute('SELECT product_id FROM product_catalog WHERE name = ?', (p['name'],))
        pid = c.fetchone()[0]

        num_slots = 1  # 1-3 slots per product
        base_stock = random.randint(80, 200)

        for slot in range(1, num_slots + 1):
            slot_stock = base_stock // num_slots
            if slot_stock < 10:
                slot_stock = base_stock

            if slot_stock <= 10:
                status = 'OUT_OF_STOCK'
            elif slot_stock <= 50:
                status = 'LOW_STOCK'
            else:
                status = 'IN_STOCK'

            stock_entries.append((
                pid, slot, p['name'], p['category'],
                slot_stock, 200, status, p['unit_price'], p['retail_price']
            ))

    c.executemany('''
        INSERT INTO edge_inventory
        (product_id, slot_id, name, category, current_stock, max_capacity, status, unit_price, retail_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', stock_entries)
    conn.commit()

    total_stock = sum(e[4] for e in stock_entries)
    total_value = sum(e[4] * e[7] for e in stock_entries)
    print(f"[Stock] Created {len(stock_entries)} entries, {total_stock} units, NT${total_value:,} total cost")
    conn.close()


def print_inventory_report():
    """Show a pretty report of current inventory"""
    conn = sqlite3.connect(EDGE_DB_PATH)
    c = conn.cursor()

    print()
    print("=" * 70)
    print("EDGE STORE 001 - INVENTORY REPORT")
    print("=" * 70)
    print(f"{'Product':15s} {'Category':12s} {'Stock':6s} {'Cost':6s} {'Retail':6s} {'Value':10s} {'Status':12s}")
    print("-" * 70)

    c.execute('''
        SELECT e.name, e.category, e.current_stock,
               e.unit_price, e.retail_price,
               (e.current_stock * e.unit_price) as total_cost,
               e.status
        FROM edge_inventory e
        ORDER BY e.category, e.name
    ''')

    grand_total = 0
    total_items = 0
    for row in c.fetchall():
        name, cat, stock, cost, retail, val, status = row
        grand_total += val
        total_items += stock
        print(f"{name:15s} {cat:12s} {stock:6d} NT${cost:4d} NT${retail:4d} NT${val:8,d} {status:12s}")

    print("-" * 70)
    print(f"{'TOTAL':15s} {'':12s} {total_items:6d} {'':8s} {'':8s} NT${grand_total:>8,d}")
    print(f"{'(34 shelf items)':15s}")
    print("=" * 70)

    # Summary counts
    c.execute('''
        SELECT status, COUNT(*), SUM(current_stock)
        FROM edge_inventory GROUP BY status
    ''')
    print()
    print("Status Summary:")
    for s, cnt, stock_sum in c.fetchall():
        print(f"  {s:15s}: {cnt:2d} entries, {stock_sum or 0:5d} units")

    conn.close()


def to_json():
    """Export current inventory as JSON (ready for Cloud upload)"""
    conn = sqlite3.connect(EDGE_DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT e.name, e.category, e.current_stock, e.unit_price,
               e.retail_price, e.status, e.last_updated
        FROM edge_inventory e
        ORDER BY e.category, e.name
    ''')
    rows = []
    for r in c.fetchall():
        rows.append({
            'product': r[0], 'category': r[1], 'stock': r[2],
            'unit_price': r[3], 'retail_price': r[4],
            'status': r[5], 'updated': r[6]
        })
    conn.close()

    j = {
        'store': 'USI_NK',
        'store_id': 'store_001',
        'generated_at': datetime.now().isoformat(),
        'products': rows,
        'total_products': len(rows),
        'total_stock': sum(r['stock'] for r in rows),
        'total_value': sum(r['stock'] * r['unit_price'] for r in rows),
    }
    json_path = EDGE_DB_DIR / 'edge_inventory_export.json'
    with open(json_path, 'w') as f:
        json.dump(j, f, indent=2, ensure_ascii=False)
    print(f"\n[JSON] Exported {len(rows)} products to {json_path}")
    return j


if __name__ == '__main__':
    print("=" * 70)
    print("USI SMART RETAIL OS - EDGE Inventory DB Creator")
    print("=" * 70)
    print()

    create_database()
    populate_products()
    print_inventory_report()
    to_json()

    print()
    print("[DONE] Edge database ready:")
    print(f"  DB:   {EDGE_DB_PATH}")
    print(f"  JSON: {EDGE_DB_DIR / 'edge_inventory_export.json'}")
    print()
    print("[NOTE] Checkout APK will subtract stock via:")
    print("  UPDATE edge_inventory SET current_stock = current_stock - ?")
    print("  WHERE name = ? AND current_stock >= ?")
