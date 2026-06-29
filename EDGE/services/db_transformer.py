#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - Database Transformer (v3)
Reads original shelf_history.db (read-only), creates EDGE_DB.db
Product ID format: StoreName_English_Chinese_Japanese_XXXX
"""

import sqlite3, json, random, sys
from pathlib import Path
from datetime import datetime, timedelta

PRICE_RANGES = {
    'Groceries': (30, 500), 'Toys': (100, 2000), 'Electronics': (1000, 50000),
    'Clothing': (200, 5000), 'Home': (200, 8000), 'Default': (50, 1000)
}

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')

STORE_CONFIG = [
    {
        "id": "Taipei Zhongxiao",
        "name_zh": "台北忠孝店",
        "name_en": "Taipei Zhongxiao Store",
        "name_ja": "台北忠孝店",
        "region": "North",
        "folder": "Taipei Zhongxiao_台北忠孝店_台北忠孝店"
    },
    {
        "id": "Osaka Shinsaibashi",
        "name_zh": "大阪心齋橋店",
        "name_en": "Osaka Shinsaibashi Store",
        "name_ja": "大阪心斎橋店",
        "region": "Kansai",
        "folder": "Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店"
    }
]

# Build lookup dicts
STORE_BY_FOLDER = {s["folder"]: s for s in STORE_CONFIG}
STORE_BY_ID = {s["id"]: s for s in STORE_CONFIG}

def get_store_info(store_id):
    """Find store config by either folder name or short ID"""
    if store_id in STORE_BY_FOLDER:
        return STORE_BY_FOLDER[store_id]
    if store_id in STORE_BY_ID:
        return STORE_BY_ID[store_id]
    return {"id": store_id, "name_zh": store_id, "name_en": store_id, "name_ja": store_id,
            "region": "Unknown", "folder": store_id}

def store_folder_to_id(folder):
    """Convert folder name like 'Taipei Zhongxiao_台北忠孝店_台北忠孝店' to 'Taipei Zhongxiao'"""
    if folder in STORE_BY_FOLDER:
        return STORE_BY_FOLDER[folder]["id"]
    return folder.split("_")[0]

def transform_database(store_folder='Taipei Zhongxiao_台北忠孝店_台北忠孝店'):
    store_path = PROJECT / 'EDGE' / store_folder
    original_db = store_path / 'smartshelf/original/smart_shelf_demo_v27_phone_formalrelease/history/shelf_history.db'
    old_tmp_db = store_path / 'smartshelf/processed/shelf_history_tmp.db'
    old_edge_db = store_path / 'local_db/edge_inventory.db'
    mapping_file = store_path / 'smartshelf/processed/product_mapping.json'
    output_db = store_path / 'EDGE_DB.db'

    store_info = get_store_info(store_folder)
    store_id = store_info["id"]

    print(f"[{store_id}] Starting database transform...")
    print(f"     {store_info['name_zh']} / {store_info['name_en']} / {store_info['name_ja']}")

    if not original_db.exists():
        print(f"[{store_id}] ERROR: Original DB not found: {original_db}")
        return False

    try:
        output_db.parent.mkdir(parents=True, exist_ok=True)

        # Read original DB (read-only)
        orig_conn = sqlite3.connect(f"file:{original_db}?mode=ro", uri=True)
        cursor = orig_conn.cursor()
        cursor.execute("""
            SELECT timestamp, slot_id, item_name, category, occ_rate, base_area, live_area
            FROM inventory_history ORDER BY timestamp DESC
        """)
        rows = cursor.fetchall()
        orig_conn.close()
        print(f"[{store_id}] {len(rows)} records from original DB")

        if not rows:
            print(f"[{store_id}] No data to transform")
            return False

        # Clean old DBs
        for f in [output_db, old_tmp_db]:
            if f.exists():
                f.unlink()

        # Create new DB
        conn = sqlite3.connect(str(output_db))
        cur = conn.cursor()

        # Tables
        cur.execute("""
            CREATE TABLE enhanced_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_timestamp TEXT, slot_id INTEGER, category TEXT,
                base_area REAL, live_area REAL,
                product_id TEXT, product_name TEXT,
                unit_price DECIMAL(10,2), retail_price DECIMAL(10,2), cost_price DECIMAL(10,2),
                stock_quantity INTEGER, max_capacity INTEGER, reorder_level INTEGER,
                last_restock TEXT, shelf_position TEXT,
                supplier_id TEXT, barcode TEXT, sku TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE inventory_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT UNIQUE, product_id TEXT,
                transaction_type TEXT, quantity INTEGER,
                previous_stock INTEGER, new_stock INTEGER,
                total_amount DECIMAL(10,2), transaction_time TIMESTAMP, device_id TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT, product_name TEXT,
                unit_price DECIMAL(10,2), retail_price DECIMAL(10,2), cost_price DECIMAL(10,2),
                effective_date TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE product_catalog (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL, category TEXT NOT NULL,
                unit_price INTEGER NOT NULL, retail_price INTEGER NOT NULL,
                max_capacity INTEGER DEFAULT 200,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE edge_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES product_catalog(product_id),
                slot_id INTEGER, name TEXT NOT NULL, category TEXT NOT NULL,
                current_stock INTEGER NOT NULL, max_capacity INTEGER DEFAULT 200,
                status TEXT CHECK(status IN ('IN_STOCK','LOW_STOCK','OUT_OF_STOCK','OOS','LOS')),
                unit_price INTEGER NOT NULL, retail_price INTEGER NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE transaction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL, product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL, total_price INTEGER NOT NULL,
                payment_method TEXT DEFAULT 'CASH', customer_id TEXT,
                checkout_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE store_info (
                store_id TEXT PRIMARY KEY,
                name_zh TEXT, name_en TEXT, name_ja TEXT,
                region TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("INSERT OR REPLACE INTO store_info VALUES (?,?,?,?,?, CURRENT_TIMESTAMP)",
                    (store_id, store_info['name_zh'], store_info['name_en'], store_info['name_ja'], store_info['region']))

        # Load or create mapping
        product_mapping = {}
        if mapping_file.exists():
            with open(mapping_file, 'r', encoding='utf-8') as f:
                product_mapping = json.load(f)
            print(f"[{store_id}] Loaded {len(product_mapping)} existing mappings")

        # Transform — aggregate by product name (de-duplicate)
        now = datetime.now()
        product_agg = {}  # product_name -> { mapping, total_stock, max_cap, last_ts, slots }

        for row in rows:
            ts, slot_id, item_name, cat, occ_rate, base_area, live_area = row
            if item_name not in product_mapping:
                product_mapping[item_name] = create_product_mapping(item_name, cat, store_id)
            mapping = product_mapping[item_name]
            max_cap = mapping.get('max_capacity', 100)
            stock_qty = max(0, int(occ_rate * max_cap))

            short_name = mapping['product_name']
            if short_name not in product_agg:
                product_agg[short_name] = {
                    'mapping': mapping,
                    'total_stock': 0,
                    'max_capacity': max_cap,
                    'reorder_level': int(max_cap * 0.2),
                    'unit_price': mapping['unit_price'],
                    'retail_price': mapping['retail_price'],
                    'category': cat,
                    'product_id': mapping['product_id'],
                }
            product_agg[short_name]['total_stock'] += stock_qty
            if max_cap > product_agg[short_name]['max_capacity']:
                product_agg[short_name]['max_capacity'] = max_cap

        enhanced_rows = []
        for short_name, agg in product_agg.items():
            pid = agg['product_id']
            enhanced_rows.append((
                now.isoformat(), 0, agg['category'], 0, 0,
                f"{store_id}_{pid[-4:]}_{short_name}", short_name,
                agg['unit_price'], agg['retail_price'], agg['mapping']['cost_price'],
                agg['total_stock'], agg['max_capacity'], agg['reorder_level'],
                now.isoformat(), 'AGG',
                agg['mapping']['supplier_id'], agg['mapping']['barcode'], agg['mapping']['sku']
            ))

        cur.executemany("""
            INSERT INTO enhanced_inventory (
                original_timestamp, slot_id, category, base_area, live_area,
                product_id, product_name, unit_price, retail_price, cost_price,
                stock_quantity, max_capacity, reorder_level,
                last_restock, shelf_position, supplier_id, barcode, sku
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, enhanced_rows)

        # Price history (one per unique product name)
        seen_names = set()
        for item_name, mapping in product_mapping.items():
            short_name = mapping['product_name']
            if short_name not in seen_names:
                seen_names.add(short_name)
                prod_id = f"{store_id}_{mapping['product_id'][-4:]}_{short_name}"
                cur.execute("""
                    INSERT INTO price_history (product_id, product_name, unit_price, retail_price, cost_price, effective_date)
                    VALUES (?,?,?,?,?,?)
                """, (prod_id, short_name, mapping['unit_price'], mapping['retail_price'],
                      mapping['cost_price'], now.strftime('%Y-%m-%d')))

        # Merge from old edge_inventory.db
        if old_edge_db.exists() and old_edge_db.stat().st_size > 100:
            print(f"[{store_id}] Merging old edge_inventory.db...")
            try:
                edge_conn = sqlite3.connect(str(old_edge_db))
                edge_cur = edge_conn.cursor()
                for tbl in ['product_catalog', 'edge_inventory', 'transaction_log']:
                    edge_cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}'")
                    if edge_cur.fetchone():
                        edge_cur.execute(f"SELECT * FROM {tbl}")
                        col_count = len([d[0] for d in edge_cur.description])
                        for row_data in edge_cur.fetchall():
                            placeholders = ','.join(['?'] * col_count)
                            cur.execute(f"INSERT INTO {tbl} VALUES ({placeholders})", row_data)
                edge_conn.close()
                print(f"[{store_id}] Merged successfully")
            except Exception as e:
                print(f"[{store_id}] Merge skipped: {e}")

        # Views
        cur.execute("""
            CREATE VIEW IF NOT EXISTS inventory_status_view AS
            SELECT product_id, product_name, category,
                   stock_quantity, max_capacity,
                   ROUND(stock_quantity*100.0/NULLIF(max_capacity,0),1) as stock_pct,
                   shelf_position, unit_price, retail_price, reorder_level,
                   CASE WHEN stock_quantity<=0 THEN 'OUT_OF_STOCK'
                        WHEN stock_quantity<=reorder_level THEN 'LOW_STOCK'
                        ELSE 'IN_STOCK' END as inv_status
            FROM enhanced_inventory
        """)

        conn.commit()
        conn.close()

        # Save mapping
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(product_mapping, f, indent=2, ensure_ascii=False)

        # Clean old files
        for f in [old_tmp_db, old_edge_db]:
            if f.exists():
                f.unlink()
        old_json = store_path / 'local_db/edge_inventory_export.json'
        if old_json.exists():
            old_json.unlink()

        print(f"[{store_id}] [OK] EDGE_DB.db created:")
        print(f"     Location: {output_db}")
        print(f"     Unique products: {len(enhanced_rows)}")
        print(f"     (Aggregated from {len(rows)} slot records to {len(enhanced_rows)} unique products)")
        return True

    except Exception as e:
        print(f"[{store_id}] [FAIL] {e}")
        import traceback; traceback.print_exc()
        return False

def create_product_mapping(item_name, category, store_id):
    price_range = PRICE_RANGES.get(category, PRICE_RANGES['Default'])
    base_price = round(random.uniform(price_range[0], price_range[1]), 2)
    retail_price = round(base_price * random.uniform(1.2, 1.5), 2)
    cost_price = round(base_price * random.uniform(0.6, 0.85), 2)
    short_name = item_name.split('_R')[0] if '_R' in item_name else item_name
    short_name = short_name.split('_slot')[0] if '_slot' in short_name else short_name
    prod_num = abs(hash(item_name)) % 10000
    return {
        'product_id': f"{store_id}_{prod_num:04d}",
        'product_name': short_name,
        'unit_price': base_price,
        'retail_price': retail_price,
        'cost_price': cost_price,
        'max_capacity': random.choice([50, 100, 150, 200, 300]),
        'supplier_id': f"SUP{random.randint(100, 999)}",
        'barcode': f"471{random.randint(1000000000, 9999999999)}",
        'sku': f"SKU-{short_name.upper()[:8]}"
    }

if __name__ == '__main__':
    if len(sys.argv) > 1:
        transform_database(sys.argv[1])
    else:
        for s in STORE_CONFIG:
            transform_database(s["folder"])
