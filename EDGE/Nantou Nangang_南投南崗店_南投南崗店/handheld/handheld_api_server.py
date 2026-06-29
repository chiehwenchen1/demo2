#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - Handheld API Server (v4)

以 EDGE_DB.db 的 enhanced_inventory 為主要產品來源 (barcode = product_id)。
sku_v3.csv 只提供 short_name (category) 對照。

用法: python handheld_api_server.py (port 8520)
"""

import io, sys, os, json, sqlite3, uuid, subprocess, csv
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.upper() in ('CP950', 'BIG5', 'BIG5-HKSCS'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ========== 設定 ==========
STORE_DIR = Path(__file__).parent.resolve().parent
DB_PATH = STORE_DIR / "EDGE_DB.db"
CSV_PATH = STORE_DIR / "sku_v3.csv"

DIRNAME = STORE_DIR.name
STORE_ID = ("Nantou Nangang" if "南投" in DIRNAME or "Nantou" in DIRNAME else
            "Taipei Zhongxiao" if "台北" in DIRNAME or "Taipei" in DIRNAME else
            "Osaka Shinsaibashi" if "大阪" in DIRNAME or "Osaka" in DIRNAME else "Unknown")
if "Nantou" in STORE_ID:
    REGION = "Central"
elif "Taipei" in STORE_ID:
    REGION = "North"
elif "Osaka" in STORE_ID:
    REGION = "Osaka"
else:
    REGION = "Unknown"

# ========== DB 操作 (要先定義) ==========

def _get_connection():
    if not DB_PATH.exists():
        return None, "DB not found: " + str(DB_PATH)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn, None

# ========== 載入產品 (以 DB 為主, CSV 補 category) ==========

def load_category_map():
    cat_map = {}
    if not CSV_PATH.exists():
        return cat_map
    with open(str(CSV_PATH), encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 4:
                name = row[0].strip()
                cat = row[3].strip()
                if name and cat:
                    cat_map[name] = cat
    return cat_map

CSV_CAT_MAP = load_category_map()

PRODUCTS = []

def load_products():
    global PRODUCTS
    conn, err = _get_connection()
    if err:
        print(f"  [ERROR] {err}")
        return
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT product_id, product_name, store_stock, retail_price, category, reorder_level, max_capacity "
        "FROM enhanced_inventory ORDER BY product_id"
    ).fetchall()
    conn.close()
    products = []
    for i, r in enumerate(rows, 1):
        pid = str(r["product_id"] or "").strip()
        pname = r["product_name"] or ""
        stock = r["store_stock"] or 0
        price = float(r["retail_price"] or 0)
        db_cat = (r["category"] or "").strip()
        category = db_cat if db_cat else CSV_CAT_MAP.get(pname, "")
        products.append({
            "id": i,
            "barcode": pid,
            "name": pname,
            "category": category,
            "stock": stock,
            "price": price,
        })
    PRODUCTS = products
    print(f"  [SKU] 載入 {len(PRODUCTS)} 項產品 (來源: DB)")

load_products()

def get_products():
    return {"products": PRODUCTS, "store_id": STORE_ID, "region": REGION}

def find_product_by_barcode(barcode):
    for p in PRODUCTS:
        if p["barcode"] == barcode:
            return p
    for p in PRODUCTS:
        if p["barcode"].endswith(barcode):
            return p
    return None

def execute_sell(barcode, qty):
    conn, err = _get_connection()
    if err:
        return {"error": err}
    cur = conn.cursor()
    cur.execute("SELECT id, product_id, product_name, store_stock, retail_price FROM enhanced_inventory WHERE product_id = ?", (barcode,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": "product not found: " + barcode}
    stock = row["store_stock"] or 0
    if stock < qty:
        conn.close()
        return {"error": "insufficient stock: " + str(stock) + " < " + str(qty)}
    new_stock = stock - qty
    total_amount = qty * (row["retail_price"] or 0)
    cur.execute("UPDATE enhanced_inventory SET store_stock = ? WHERE product_id = ?", (new_stock, barcode))
    _record_txn(cur, barcode, "sell", qty, stock, new_stock, total_amount)
    conn.commit()
    conn.close()
    _sync_and_report()
    load_products()
    return {"success": True, "product": row["product_name"], "barcode": barcode, "qty": qty,
            "previous_stock": stock, "new_stock": new_stock, "total_amount": total_amount}

def execute_restock(barcode, qty):
    conn, err = _get_connection()
    if err:
        return {"error": err}
    cur = conn.cursor()
    cur.execute("SELECT id, product_id, product_name, store_stock, retail_price FROM enhanced_inventory WHERE product_id = ?", (barcode,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"error": "product not found: " + barcode}
    stock = row["store_stock"] or 0
    new_stock = stock + qty
    total_amount = qty * (row["retail_price"] or 0) * 0.6
    cur.execute("UPDATE enhanced_inventory SET store_stock = ? WHERE product_id = ?", (new_stock, barcode))
    _record_txn(cur, barcode, "restock", qty, stock, new_stock, total_amount)
    conn.commit()
    conn.close()
    _sync_and_report()
    load_products()
    return {"success": True, "product": row["product_name"], "barcode": barcode, "qty": qty,
            "previous_stock": stock, "new_stock": new_stock, "total_amount": total_amount}

def _record_txn(cur, barcode, txn_type, qty, prev_stock, new_stock, total_amount):
    txn_id = "TXN-" + uuid.uuid4().hex.upper()
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO inventory_transactions (transaction_id, product_id, transaction_type, quantity, "
        "previous_stock, new_stock, total_amount, transaction_time, device_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (txn_id, barcode, txn_type, qty, prev_stock, new_stock, total_amount, now, "ANDROID_API")
    )
    try:
        cur.execute(
            "INSERT INTO transaction_log (transaction_id, product_name, quantity, total_price, "
            "payment_method, customer_id, checkout_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (txn_id, barcode, qty, total_amount, "ANDROID", "APP", now)
        )
    except Exception:
        pass

def _sync_and_report():
    try:
        subprocess.run(
            ["python", "store_ops.py", "--action", "report"],
            cwd=str(STORE_DIR), capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace'
        )
    except Exception as e:
        print("  [WARN] report update failed: " + str(e))

# ========== HTTP Server ==========

class Handler(BaseHTTPRequestHandler):

    def _set_headers(self, status=200, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, data, status=200):
        self._set_headers(status)
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        if path in ("", "/"):
            self._json({"service": "USI Smart Retail OS - Handheld API (v4 DB-driven)",
                        "store": STORE_ID, "region": REGION,
                        "endpoints": ["/products", "/status", "/sell", "/restock"],
                        "time": datetime.now().isoformat()})
        elif path == "/products":
            self._json(get_products())
        elif path == "/status":
            self._json({"store": STORE_ID, "region": REGION,
                        "db_exists": DB_PATH.exists(), "product_count": len(PRODUCTS),
                        "time": datetime.now().isoformat()})
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = self._body()
        except Exception:
            self._json({"error": "Invalid JSON"}, 400)
            return
        bar = body.get("barcode") or body.get("product_id") or body.get("id")
        qty = int(body.get("qty", 1))
        if not bar:
            self._json({"error": "barcode required"}, 400)
            return
        if path == "/sell":
            self._json(execute_sell(str(bar), qty))
        elif path == "/restock":
            self._json(execute_restock(str(bar), qty))
        else:
            self._json({"error": "Not found"}, 404)

def main():
    port = 8520
    server = HTTPServer(("0.0.0.0", port), Handler)
    print("=" * 60)
    print("  USI Smart Retail OS - Handheld API Server (v4 DB-driven)")
    print("  Store:", STORE_ID, "(" + REGION + ")")
    print("  DB:", DB_PATH)
    print("  Listening on http://0.0.0.0:" + str(port))
    print("=" * 60)
    print("  Endpoints:")
    print("    GET  /          - This info")
    print("    GET  /products  - Product list (barcode = DB product_id)")
    print("    GET  /status    - Server status")
    print("    POST /sell      - Sell (barcode, qty)")
    print("    POST /restock   - Restock (barcode, qty)")
    print("  Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped")
        server.server_close()

if __name__ == "__main__":
    main()
