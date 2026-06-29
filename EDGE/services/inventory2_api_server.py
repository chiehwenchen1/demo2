#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventory2_api_server.py — Flask API server for inventory2 Android app
直接接南投店的 EDGE_DB.db

Endpoints (match inventory2 app expectations):
  GET  /api/products         - 產品列表
  POST /api/purchase         - 叫貨 (product_id, quantity)
  POST /api/receive          - 收貨入庫 (product_id, quantity)
  GET  /api/purchase_state   - 叫貨中狀態
  POST /api/purchase_clear   - 清除叫貨狀態
  GET  /api/status           - 伺服器狀態

用法: python inventory2_api_server.py [port]
預設 port: 5000
"""

import io, sys, os, json, sqlite3, uuid, time
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

if sys.stdout.encoding and sys.stdout.encoding.upper() in ('CP950', 'BIG5', 'BIG5-HKSCS'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ========== 設定 ==========
THIS_DIR = Path(__file__).parent.resolve()
STORE_DIR = THIS_DIR.parent / "Nantou Nangang_南投南崗店_南投南崗店"
DB_PATH = STORE_DIR / "EDGE_DB.db"

# ========== Purchase State (in-memory, 叫貨到收貨的生命週期) ==========
# 結構: { product_id: {"qty": int, "remaining": int, "is_ready": bool, "started_at": float} }
# remaining: 倒數秒數 (模擬叫貨到貨時間，簡化為固定 30 秒)
PURCHASE_DELAY_SEC = 30
purchase_states = {}

# ========== DB 操作 ==========

def _get_connection():
    if not DB_PATH.exists():
        return None, f"DB not found: {DB_PATH}"
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn, None

def load_products():
    """從 DB 載入產品列表，回傳 list of dict"""
    conn, err = _get_connection()
    if err:
        print(f"  [ERROR] {err}")
        return []
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT product_id, product_name, store_stock, reorder_level, max_capacity, retail_price "
        "FROM enhanced_inventory ORDER BY product_id"
    ).fetchall()
    conn.close()
    products = []
    for r in rows:
        products.append({
            "product_id": str(r["product_id"] or "").strip(),
            "product_name": r["product_name"] or "",
            "stock": r["store_stock"] or 0,
            "max_capacity": r["max_capacity"] or 200,
            "reorder_level": r["reorder_level"] or 0,
            "retail_price": float(r["retail_price"] or 0),
        })
    return products

def update_stock(product_id, delta):
    """更新庫存 (delta 正=入庫，負=銷貨)，回傳 (success, new_stock, error_msg)"""
    conn, err = _get_connection()
    if err:
        return False, 0, err
    cur = conn.cursor()
    cur.execute("SELECT id, store_stock FROM enhanced_inventory WHERE product_id = ?", (product_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, 0, f"product not found: {product_id}"
    stock = row["store_stock"] or 0
    new_stock = stock + delta
    if new_stock < 0:
        conn.close()
        return False, 0, f"insufficient stock: {stock} < {-delta}"
    cur.execute("UPDATE enhanced_inventory SET store_stock = ? WHERE product_id = ?", (new_stock, product_id))
    # 記錄交易
    txn_id = f"INV2-{uuid.uuid4().hex[:12].upper()}"
    txn_type = "restock" if delta > 0 else "sell"
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO inventory_transactions (transaction_id, product_id, transaction_type, quantity, "
        "previous_stock, new_stock, total_amount, transaction_time, device_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (txn_id, product_id, txn_type, abs(delta), stock, new_stock, 0, now, "INVENTORY2_API")
    )
    conn.commit()
    conn.close()
    return True, new_stock, None

# ========== HTTP Handler ==========

class Inventory2Handler(BaseHTTPRequestHandler):
    PRODUCTS_CACHE = []
    CACHE_TIME = 0
    CACHE_TTL = 5  # 秒

    def _products(self):
        now = time.time()
        if now - self.CACHE_TIME > self.CACHE_TTL or not self.PRODUCTS_CACHE:
            self.PRODUCTS_CACHE = load_products()
            self.CACHE_TIME = now
        return self.PRODUCTS_CACHE

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/products":
            self._json({"products": self._products()})
        elif path == "/api/purchase_state":
            # 清理過期的狀態
            now = time.time()
            expired = [pid for pid, s in list(purchase_states.items())
                       if not s["is_ready"] and now - s["started_at"] >= PURCHASE_DELAY_SEC]
            for pid in expired:
                purchase_states[pid]["is_ready"] = True
                purchase_states[pid]["remaining"] = 0
            # 回傳
            result = {}
            for pid, s in purchase_states.items():
                if not s["is_ready"]:
                    s["remaining"] = max(0, int(PURCHASE_DELAY_SEC - (now - s["started_at"])))
                result[pid] = {
                    "qty": s["qty"],
                    "remaining": s["remaining"],
                    "is_ready": s["is_ready"],
                }
            self._json(result)
        elif path == "/api/status":
            self._json({
                "status": "ok",
                "db": str(DB_PATH),
                "db_exists": DB_PATH.exists(),
                "product_count": len(self._products()),
                "purchase_states": len(purchase_states),
            })
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = self._body()
        except Exception:
            self._json({"error": "Invalid JSON"}, 400)
            return

        if path == "/api/purchase":
            pid = body.get("product_id", "").strip()
            qty = int(body.get("quantity", 1))
            if not pid:
                self._json({"error": "product_id required"}, 400)
                return
            # 先確認產品存在
            products = self._products()
            if not any(p["product_id"] == pid for p in products):
                self._json({"error": f"product not found: {pid}"}, 404)
                return
            purchase_states[pid] = {
                "qty": qty,
                "remaining": PURCHASE_DELAY_SEC,
                "is_ready": False,
                "started_at": time.time(),
            }
            self._json({"success": True, "product_id": pid, "quantity": qty,
                        "eta_seconds": PURCHASE_DELAY_SEC})

        elif path == "/api/receive":
            pid = body.get("product_id", "").strip()
            qty = int(body.get("quantity", 1))
            if not pid:
                self._json({"error": "product_id required"}, 400)
                return
            success, new_stock, err = update_stock(pid, qty)
            if not success:
                self._json({"error": err}, 400)
                return
            # 自動清除購買狀態
            purchase_states.pop(pid, None)
            self._json({"success": True, "product_id": pid, "quantity": qty, "new_stock": new_stock})

        elif path == "/api/purchase_clear":
            pid = body.get("product_id", "").strip()
            if pid:
                purchase_states.pop(pid, None)
            self._json({"success": True})

        else:
            self._json({"error": "Not found"}, 404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

    # 先確認 DB 可用
    prods = load_products()
    print(f"  [DB] {DB_PATH}")
    print(f"  [SKU] 載入 {len(prods)} 項產品")
    if len(prods) == 0:
        print("  [WARN] 無產品資料，請確認 DB 路徑")

    server = HTTPServer(("0.0.0.0", port), Inventory2Handler)
    print("=" * 60)
    print("  USI Smart Retail OS - Inventory2 API Server")
    print(f"  DB: {DB_PATH}")
    print(f"  Listening on http://0.0.0.0:{port}")
    print("=" * 60)
    print("  Endpoints:")
    print("    GET  /api/products         - Product list")
    print("    POST /api/purchase          - Purchase order (product_id, quantity)")
    print("    POST /api/receive           - Receive stock (product_id, quantity)")
    print("    GET  /api/purchase_state    - Purchase state polling")
    print("    POST /api/purchase_clear    - Clear purchase state")
    print("    GET  /api/status            - Server status")
    print("  Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped")
        server.server_close()


if __name__ == "__main__":
    main()
