#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_edge_slide_html.py - EDGE Inventory Server
Provides:
  - Web report (editable stock table + order/receive + daily sales)
  - REST API for EDGE_DB.db
Usage:python generate_edge_slide_html.py
      Open browser at http://localhost:5000
Press Ctrl+C to stop
"""
import os, sys, sqlite3, json, io, csv
from datetime import datetime, date, timedelta
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, render_template_string
import urllib.request
import json as stdjson

if sys.stdout.encoding and sys.stdout.encoding.upper() in ('CP950', 'BIG5', 'BIG5-HKSCS'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
CLOUD_DB = os.path.join(PROJECT_DIR, "CLOUD", "database", "cloud_inventory.db")
EDGE_DB = os.path.join(SCRIPT_DIR, "EDGE_DB.db")
CSV_PATH = os.path.join(SCRIPT_DIR, "sku_v3.csv")

if not os.path.exists(EDGE_DB):
    print(f"[ERROR] EDGE_DB.db not found: {EDGE_DB}")
    sys.exit(1)

STORE_ID = os.path.basename(SCRIPT_DIR).split("_")[0]
REGION = "Central" if "南投" in os.path.basename(SCRIPT_DIR) else "Osaka"
store_zh = "Nantou Nangang" if "南投" in SCRIPT_DIR else "Osaka Shinsaibashi"
report_dir = os.path.join(SCRIPT_DIR, "reports")
os.makedirs(report_dir, exist_ok=True)

HANDHELD_API = "http://localhost:8520"

app = Flask(__name__)
# Custom jsonify that outputs raw Chinese (no \\u escapes)
app.json.ensure_ascii = False

# Server-side purchase state
_purchase_state = {}
# Server-side suggested purchase qty (Cross-device Order Sync)
_suggested_purchase_qty = {}

# ─── CSV Category Mapping (比照 handheld_api_server.py) ───

def load_category_map():
    cat_map = {}
    if not os.path.exists(CSV_PATH):
        return cat_map
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 4:
                name = row[0].strip()
                cat = row[3].strip()
                if name and cat:
                    cat_map[name] = cat
    return cat_map

CSV_CAT_MAP = load_category_map()
print(f"  [CSV] loaded {len(CSV_CAT_MAP)} category mappings")


def _resolve_category(row):
    """比照 handheld_api_server.py：DB category 優先，空值則從 CSV 補 short_name"""
    db_cat = (row.get("category") or "").strip()
    if db_cat:
        return db_cat
    return CSV_CAT_MAP.get(row.get("product_name", "") or "", "")

# ─── API ───

@app.route("/api/suggested_qty")
def api_suggested_qty():
    return jsonify(_suggested_purchase_qty)

@app.route("/api/set_suggested_qty", methods=["POST"])
def api_set_suggested_qty():
    data = request.get_json()
    pid = data.get("product_id")
    qty = data.get("quantity")
    if pid and qty is not None:
        _suggested_purchase_qty[str(pid)] = int(qty)
    return jsonify({"ok": True})

@app.route("/api/products")
def api_products():
    conn = sqlite3.connect(EDGE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT product_id, product_name, category, store_stock, retail_price, max_capacity, reorder_level FROM enhanced_inventory ORDER BY category, product_name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    # 比照 handheld_api_server.py：DB 有 category 就用 DB 的，否則從 CSV 補 short_name
    for r in rows:
        if not r.get("category") or not r["category"].strip():
            csv_cat = CSV_CAT_MAP.get(r.get("product_name", ""), "")
            if csv_cat:
                r["category"] = csv_cat
    return jsonify(rows)

@app.route("/api/update_reorder", methods=["POST"])
def api_update_reorder():
    data = request.get_json()
    pid = data.get("product_id")
    new_val = data.get("reorder_level")
    if pid is None or new_val is None:
        return jsonify({"error": "product_id and reorder_level required"}), 400
    conn = sqlite3.connect(EDGE_DB)
    conn.execute("UPDATE enhanced_inventory SET reorder_level = ? WHERE product_id = ?",
                 (int(new_val), str(pid)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/update_stock", methods=["POST"])
def api_update_stock():
    data = request.get_json()
    pid = data.get("product_id")
    new_stock = data.get("store_stock")
    if pid is None or new_stock is None:
        return jsonify({"error": "product_id and store_stock required"}), 400
    conn = sqlite3.connect(EDGE_DB)
    conn.execute("UPDATE enhanced_inventory SET store_stock = ?, last_restock_date = ? WHERE product_id = ?",
                 (int(new_stock), datetime.now().strftime("%Y-%m-%d %H:%M"), str(pid)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "new_stock": int(new_stock)})

@app.route("/api/update_capacity", methods=["POST"])
def api_update_capacity():
    data = request.get_json()
    pid = data.get("product_id")
    new_cap = data.get("max_capacity")
    if pid is None or new_cap is None:
        return jsonify({"error": "product_id and max_capacity required"}), 400
    conn = sqlite3.connect(EDGE_DB)
    conn.execute("UPDATE enhanced_inventory SET max_capacity = ? WHERE product_id = ?",
                 (int(new_cap), str(pid)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

    conn.close()
    return jsonify({"ok": True})

@app.route("/api/receive", methods=["POST"])
def api_receive():
    data = request.get_json()
    pid = data.get("product_id")
    qty = data.get("quantity", 0)
    if pid is None or qty <= 0:
        return jsonify({"error": "invalid"}), 400
    conn = sqlite3.connect(EDGE_DB)
    conn.execute("UPDATE enhanced_inventory SET store_stock = store_stock + ?, last_restock_date = ? WHERE product_id = ?",
                 (int(qty), datetime.now().strftime("%Y-%m-%d %H:%M"), str(pid)))
    conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT store_stock FROM enhanced_inventory WHERE product_id = ?", (str(pid),))
    new_stock = cur.fetchone()[0]
    conn.close()
    return jsonify({"ok": True, "new_stock": new_stock})

@app.route("/api/purchase", methods=["POST"])
def api_purchase():
    data = request.get_json()
    pid = data.get("product_id")
    qty = data.get("quantity", 0)
    if not pid or qty <= 0:
        return jsonify({"error": "invalid"}), 400
    _purchase_state[pid] = {
        "qty_ordered": qty,
        "start_time": datetime.now().timestamp(),
        "duration": qty,
        "is_ready": False
    }
    return jsonify({"ok": True, "product_id": pid, "quantity": qty})

@app.route("/api/purchase_state")
def api_purchase_state():
    now = datetime.now().timestamp()
    result = {}
    for pid, state in list(_purchase_state.items()):
        elapsed = now - state["start_time"]
        remaining = max(0, state["duration"] - int(elapsed))
        ready = remaining <= 0
        if ready:
            state["is_ready"] = True
        result[pid] = {
            "qty": state["qty_ordered"],
            "remaining": remaining,
            "is_ready": ready
        }
    return jsonify(result)

@app.route("/api/purchase_clear", methods=["POST"])
def api_purchase_clear():
    data = request.get_json()
    pid = data.get("product_id")
    if pid and pid in _purchase_state:
        del _purchase_state[pid]
    return jsonify({"ok": True})

@app.route("/api/product_options")
def api_product_options():
    conn = sqlite3.connect(EDGE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT product_id, product_name, category FROM enhanced_inventory ORDER BY category, product_name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    # 比照 handheld_api_server.py：DB 有 category 就用 DB 的，否則從 CSV 補 short_name
    for r in rows:
        if not r.get("category") or not r["category"].strip():
            csv_cat = CSV_CAT_MAP.get(r.get("product_name", ""), "")
            if csv_cat:
                r["category"] = csv_cat
    return jsonify(rows)

@app.route("/api/daily_sales")
def api_daily_sales():
    if not os.path.exists(CLOUD_DB):
        return jsonify([])
    conn = sqlite3.connect(CLOUD_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT date, category, product_id, units_sold FROM inventory_raw WHERE store_id = ? ORDER BY date DESC, category", (STORE_ID,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/transactions")
@app.route("/api/transactions/<txn_type>")
def api_transactions(txn_type=None):
    """Return today's transactions, optionally filtered by type."""
    txn_type = request.args.get("type", txn_type)
    conn = sqlite3.connect(EDGE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    if txn_type:
        cur.execute("SELECT * FROM inventory_transactions WHERE transaction_type = ? AND transaction_time >= ? ORDER BY transaction_time DESC", (txn_type, today))
    else:
        cur.execute("SELECT * FROM inventory_transactions WHERE transaction_time >= ? ORDER BY transaction_time DESC", (today,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route("/api/refresh_chart")
def api_refresh_chart():
    _generate_chart()
    return jsonify({"ok": True, "path": f"/reports/edge_slide_{STORE_ID}.png"})

@app.route("/reports/<path:filename>")
def serve_report(filename):
    return send_from_directory(report_dir, filename)

# ─── Restock / Checkout Static Routes ───

RESTOCK_DIR = os.path.join(SCRIPT_DIR, "restock")
CHECKOUT_DIR = os.path.join(SCRIPT_DIR, "checkout")

@app.route("/restock/")
@app.route("/restock/<path:filename>")
def serve_restock(filename="restock.html"):
    return send_from_directory(RESTOCK_DIR, filename)

@app.route("/checkout/")
@app.route("/checkout/<path:filename>")
def serve_checkout(filename="checkout.html"):
    return send_from_directory(CHECKOUT_DIR, filename)

# ─── Handheld API Proxy ───

def _proxy_request(method, path, body=None):
    """Proxy a request to the handheld API server."""
    url = HANDHELD_API + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return jsonify(json.loads(raw))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            return jsonify(json.loads(err_body)), e.code
        except:
            return jsonify({"error": err_body}), e.code
    except urllib.error.URLError as e:
        return jsonify({"error": f"Handheld API unreachable: {e.reason}"}), 503

@app.route("/api/handheld/products")
def proxy_products():
    return _proxy_request("GET", "/products")

@app.route("/api/handheld/restock", methods=["POST"])
def proxy_restock():
    body = request.get_json(silent=True) or {}
    return _proxy_request("POST", "/restock", body)

@app.route("/api/handheld/sell", methods=["POST"])
def proxy_sell():
    body = request.get_json(silent=True) or {}
    return _proxy_request("POST", "/sell", body)

# ─── 圖表產生 ───

def _generate_chart():
    import numpy as np
    import pandas as pd
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager, rcParams
        has_mpl = True
        for name in ["Microsoft JhengHei", "Noto Sans CJK TC", "SimHei", "Arial Unicode MS"]:
            if name in {f.name for f in font_manager.fontManager.ttflist}:
                rcParams["font.family"] = name
                rcParams["axes.unicode_minus"] = False
                break
    except ImportError:
        has_mpl = False

    conn = sqlite3.connect(EDGE_DB)
    products = pd.read_sql("SELECT * FROM enhanced_inventory ORDER BY product_name", conn)
    conn.close()
    # category fallback：比照 handheld_api_server.py
    has_cat_col = "category" in products.columns
    if has_cat_col:
        for idx, r in products.iterrows():
            resolved = _resolve_category(r)
            if resolved:
                products.at[idx, "category"] = resolved
    products = products.sort_values(["category", "product_name"])
    total_sku = len(products)
    total_stock = int(products["store_stock"].sum())
    oos = int((products["store_stock"].fillna(0) <= 0).sum())
    low_stock = int(((products["store_stock"].fillna(0) < products["reorder_level"].fillna(20)) & (products["store_stock"].fillna(0) > 0)).sum())

    daily = None
    if os.path.exists(CLOUD_DB):
        try:
            cloud_df = pd.read_sql("SELECT * FROM inventory_raw", sqlite3.connect(CLOUD_DB))
            cloud_df["date"] = pd.to_datetime(cloud_df["date"])
            store_mask = cloud_df["store_id"].str.contains(STORE_ID, case=False, na=False)
            local = cloud_df[store_mask].copy()
            daily = local.groupby("date")["units_sold"].sum().reset_index()
        except:
            pass

    if has_mpl and daily is not None and not daily.empty:
        fig = plt.figure(figsize=(18, 16))
        fig.suptitle(f"EDGE Inventory Dashboard - {store_zh}", fontsize=20, weight="bold", y=0.98)
        gs = fig.add_gridspec(3, 3, hspace=0.30, wspace=0.20, left=0.08, right=0.97, top=0.94, bottom=0.04)
        ax1 = fig.add_subplot(gs[0, :])
        sorted_df = products.sort_values("store_stock", ascending=True)
        stocks = sorted_df["store_stock"].fillna(0).tolist()
        colors = ["#ef4444" if s <= 0 else "#f59e0b" if s < (sorted_df.iloc[i]["reorder_level"] or 20) else "#10b981" for i, s in enumerate(stocks)]
        ax1.barh(sorted_df["product_name"].tolist(), stocks, color=colors, height=0.7)
        ax1.set_title(f"Current Stock Levels ({total_sku}items)", fontsize=16, weight="bold")
        ax1.set_xlabel("units", fontsize=13)
        ax1.grid(True, axis="x", alpha=0.3)
        ax1.tick_params(axis="y", labelsize=11)
        ax1.margins(y=0.01)
        ax2 = fig.add_subplot(gs[1, 0])
        products["value"] = products["store_stock"].fillna(0) * products["retail_price"].fillna(0)
        top10 = products.nlargest(10, "value")
        ax2.barh(top10["product_name"], top10["value"] / 10000, color="#3b82f6", height=0.7)
        ax2.set_title("Top 10 Stock Value (NT$10K)", fontsize=16, weight="bold")
        ax2.set_xlabel("NT$10K", fontsize=13)
        ax2.grid(True, axis="x", alpha=0.3)
        ax2.margins(y=0.08)
        ax3 = fig.add_subplot(gs[1, 1])
        ok_count = total_sku - low_stock - oos
        labels, sizes, pie_colors = [], [], []
        if ok_count > 0:
            labels.append(f"OK ({ok_count})"); sizes.append(ok_count); pie_colors.append("#10b981")
        if low_stock > 0:
            labels.append(f"Low Stock ({low_stock})"); sizes.append(low_stock); pie_colors.append("#f59e0b")
        if oos > 0:
            labels.append(f"Out of Stock ({oos})"); sizes.append(oos); pie_colors.append("#ef4444")
        if sizes:
            ax3.pie(sizes, labels=labels, colors=pie_colors, autopct="%1.0f%%", startangle=90, textprops={"fontsize": 15, "weight": "bold"})
        ax3.set_title("Stock Health", fontsize=16, weight="bold")
        ax4 = fig.add_subplot(gs[2, :])
        y_vals = daily["units_sold"].values
        if len(y_vals) > 0:
            cap = np.percentile(y_vals, 99.5) if len(y_vals) > 2 else max(y_vals)
            y_capped = np.minimum(y_vals, cap)
            ax4.plot(daily["date"], y_capped, color="#3b82f6", linewidth=2.5)
            ax4.fill_between(daily["date"], y_capped, alpha=0.15, color="#3b82f6")
        ax4.set_title("Daily Sales Trend", fontsize=16, weight="bold")
        ax4.set_ylabel("Units Sold", fontsize=13)
        ax4.grid(True, alpha=0.3)
        ax4.tick_params(axis="x", rotation=20, labelsize=11)
        png_path = os.path.join(report_dir, f"edge_slide_{STORE_ID}.png")
        fig.savefig(png_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

# ─── 首頁路由 ───
_HTML_CACHE = None

@app.route("/")
def index():
    global _HTML_CACHE
    _generate_chart()
    _HTML_CACHE = _build_page()
    return _HTML_CACHE

def _build_page():
    import pandas as pd
    conn = sqlite3.connect(EDGE_DB)
    products = pd.read_sql("SELECT * FROM enhanced_inventory ORDER BY product_name", conn)
    conn.close()

    # category fallback：比照 handheld_api_server.py
    has_cat_col = "category" in products.columns
    if has_cat_col:
        for idx, r in products.iterrows():
            resolved = _resolve_category(r)
            if resolved:
                products.at[idx, "category"] = resolved
    products = products.sort_values(["category", "product_name"])

    total_sku = len(products)
    total_stock = int(products["store_stock"].sum())
    total_value = float((products["store_stock"].fillna(0) * products["retail_price"].fillna(0)).sum())
    oos = int((products["store_stock"].fillna(0) <= 0).sum())
    low_stock = int(((products["store_stock"].fillna(0) < products["reorder_level"].fillna(20)) & (products["store_stock"].fillna(0) > 0)).sum())
    sell_pct = round((total_sku - low_stock - oos) / total_sku * 100)
    low_pct = round(low_stock / total_sku * 100)
    oos_pct = round(oos / total_sku * 100)

    cloud_sales_qty = 0
    cloud_sales_amt = 0
    if os.path.exists(CLOUD_DB):
        try:
            cdf = pd.read_sql("SELECT * FROM inventory_raw", sqlite3.connect(CLOUD_DB))
            cdf["date"] = pd.to_datetime(cdf["date"])
            cdf["revenue"] = cdf["units_sold"] * cdf["price"] * (1 - cdf.get("discount", 0).fillna(0) / 100)
            mask = cdf["store_id"].str.contains(STORE_ID, case=False, na=False)
            loc = cdf[mask]
            if not loc.empty:
                lat = loc["date"].max()
                r30 = loc[loc["date"] >= lat - pd.Timedelta(days=30)]
                cloud_sales_qty = int(r30["units_sold"].sum())
                cloud_sales_amt = float(r30["revenue"].sum())
        except:
            pass

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    trs = ""
    for _, r in products.iterrows():
        pid = r["product_id"]
        pn = r["product_name"]
        ct = r["category"]
        sk = int(r["store_stock"] or 0)
        rp = float(r["retail_price"] or 0)
        mc = int(r["max_capacity"] or 200)
        ro = int(r["reorder_level"] or 20)
        rt = round(sk / mc * 100) if mc > 0 else 0
        if sk <= 0:
            badge_cls = "bo bo-oos"; badge_txt = "OOS"
        elif sk < ro:
            badge_cls = "bo bo-re"; badge_txt = "LOS"
        else:
            badge_cls = "bo bo-ok"; badge_txt = "\u6b63\u5e38"
        trs += f"""<tr data-pid="{pid}" data-stock="{sk}" data-reorder="{ro}"><td>{pn}</td><td>{ct}</td><td style="text-align:right">${rp:,.0f}</td><td style="text-align:right" class="ed-stock" contenteditable="true">{sk:,}</td><td style="text-align:right" class="ed-capacity" contenteditable="true">{mc:,}</td><td style="text-align:right" class="ed-reorder" contenteditable="true">{ro:,}</td><td style="text-align:right" class="col-rate">{rt}%</td><td><span class="{badge_cls} col-badge">{badge_txt}</span></td><td style="text-align:center"><input type="number" min="0" value="0" class="rq" data-pid="{pid}" style="width:60px;text-align:center;border:2px solid #d1d5db;border-radius:4px;padding:4px"></td><td style="text-align:center"><button class="btn-purchase" data-pid="{pid}" style="padding:4px 10px;margin:2px;background:#4CAF50;color:white;border:none;border-radius:4px;cursor:pointer;font-size:13px">🔁Order</button></td><td style="text-align:center;width:64px"><span class="pt-col">--:--:--</span></td><td style="text-align:center;width:64px" class="hidden-col"><span class="rt-col">--:--:--</span></td><td style="text-align:center" class="hidden-col"><button class="btn-rec" disabled data-pid="{pid}">📥 Receive</button></td></tr>"""

    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{store_zh} - EDGE Inventory</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:"Microsoft JhengHei","Segoe UI",Arial,sans-serif;background:#f4f6f8;color:#1f2937}}
.header{{background:linear-gradient(120deg,#0f172a,#1e3a8a);color:#fff;padding:24px 42px}}
.header h1{{margin:0;font-size:28px}}
.header p{{margin:6px 0 0;font-size:14px;color:#dbeafe}}
.container{{padding:24px 42px 42px}}
.st{{font-size:18px;font-weight:700;margin:24px 0 12px}}
.kg{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}
.card{{background:#fff;border-radius:14px;padding:16px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.card .l{{color:#64748b;font-size:13px;margin-bottom:6px}}
.card .v{{font-size:22px;font-weight:800}}
.cr .v{{color:#dc2626}} .cg .v{{color:#059669}} .cb .v{{color:#2563eb}} .co .v{{color:#ea580c}}
table{{width:100%;border-collapse:collapse;background:#fff;border:2px solid #000;font-size:13px}}
th{{background:#0f172a;color:#fff;padding:8px 10px;text-align:left;border:2px solid #000;white-space:nowrap}}
td{{padding:6px 8px;border:2px solid #000;vertical-align:middle}}
tr:nth-child(even) td{{background:#f8fafc}}
.bo{{display:inline-block;padding:2px 8px;border-radius:20px;font-size:12px;font-weight:700}}
.bo-oos{{background:#fee2e2;color:#b91c1c}}
.bo-re{{background:#fef3c7;color:#92400e;border:2px solid #d97706}}
.bo-ok{{background:#dcfce7;color:#166534}}
.insight{{background:#ecfeff;border-left:6px solid #0891b2;padding:14px 18px;border-radius:10px;line-height:1.7;font-size:14px}}
.footer{{color:#64748b;font-size:12px;margin-top:28px;text-align:center}}
.stbl{{max-height:500px;overflow-y:auto;border:2px solid #000;border-radius:8px}}
.stbl thead th{{position:sticky;top:0;z-index:1}}
.hd{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:16px}}
.hc{{background:#fff;border-radius:14px;padding:20px;text-align:center;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.hc .nm{{font-size:36px;font-weight:800}}
.hc .lb{{font-size:13px;color:#64748b;margin-top:4px}}
.cht{{background:#fff;border-radius:14px;padding:14px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.cht img{{width:100%;display:block}}
.btn{{background:#059669;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-weight:700;font-size:13px}}
.btn:hover{{background:#047857}}
.btn:disabled{{background:#9ca3af;cursor:not-allowed}}
.toast{{position:fixed;top:20px;right:20px;color:#fff;padding:12px 20px;border-radius:8px;z-index:9999;font-weight:700;display:none}}
.toast.ok{{background:#059669}}
.toast.er{{background:#dc2626}}
.rc-cd{{font-size:13px;font-weight:700;color:#b91c1c;animation:pulse 0.5s ease-in-out infinite alternate}}
@keyframes pulse{{from{{opacity:1;transform:scale(1)}}to{{opacity:0.5;transform:scale(1.15)}}}}
</style>
</head>
<body>
<div id="t" class="toast"></div>
<div class="header">
  <h1>🏪 EDGE Inventory - {store_zh}</h1>
  <p>{STORE_ID} | Region: {REGION} | Updated: {now_str}</p>

</div>
<div class="container">
<div class="st">📊 KPI Summary</div>
<div class="kg">
  <div class="card cb"><div class="l">Products (SKU)</div><div class="v">{total_sku}</div></div>
  <div class="card cg"><div class="l">Total Stock</div><div class="v">{total_stock:,}</div></div>
  <div class="card"><div class="l">Total Value</div><div class="v">${total_value:,.0f}</div></div>
  <div class="card co"><div class="l">30-Day Sales Revenue</div><div class="v">${cloud_sales_amt:,.0f}</div></div>
</div>
<div class="hd">
  <div class="hc" style="border-top:4px solid #059669"><div class="nm" style="color:#059669">{sell_pct}%</div><div class="nm" style="font-size:24px">{total_sku - low_stock - oos}</div><div class="lb">OK (SKU)</div></div>
  <div class="hc" style="border-top:4px solid #f59e0b"><div class="nm" style="color:#f59e0b">{low_pct}%</div><div class="nm" style="font-size:24px">{low_stock}</div><div class="lb">LOS (SKU)</div></div>
  <div class="hc" style="border-top:4px solid #dc2626"><div class="nm" style="color:#dc2626">{oos_pct}%</div><div class="nm" style="font-size:24px">{oos}</div><div class="lb">OOS (SKU)</div></div>
</div>
<div style="margin:12px 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
  <button onclick="location.reload()" style="background:#2563eb;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-weight:700">↻ Refresh Page</button>
  <button id="btn-refresh-chart" style="background:#0891b2;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-weight:700">📊 Regenerate Chart</button>
  <span style="color:#64748b;font-size:13px">💡 Press Enter or click away to save stock edit</span>
  <button onclick="toggleRecv()" class="rec-toggle" id="rec-toggle-btn">👁 Show Receive</button>
</div>
<div class="st">📋 📋 Inventory by Category</div>
<div class="stbl">
<table>
<thead><tr><th>Product</th><th>Category</th><th>Price</th><th>Stock(edit)</th><th>Max Cap</th><th>Reorder</th><th>Rate</th><th>Status</th><th>Order</th><th>Order</th><th colspan="2">Arrival</th><th class="hidden-col">Receive Time</th></tr></thead>
<tbody id="tb">{trs}</tbody>
</table>
</div>
<div class="st">📈 📈 Stock Dashboard</div>
<div class="cht"><img id="ci" src="/reports/edge_slide_{STORE_ID}.png" alt="Dashboard" onerror="this.style.display='none'"></div>
<div class="st">📦 📦 Daily Sales by Item</div>
<div style="margin-bottom:10px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
  <label style="font-weight:700;font-size:14px">Item:</label>
  <select id="sales-product-select" style="padding:6px 10px;font-size:14px;border:2px solid #000;border-radius:6px;min-width:250px">
    <option value="__all__">All items (total)</option>
  </select>
</div>
<div class="cht" id="stc-chart-container" style="background:#fff;border:2px solid #000;border-radius:8px;padding:16px;min-height:320px">
  <canvas id="stc-chart" height="280"></canvas>
  <p id="stc-empty" style="color:#64748b;text-align:center;display:none">No sales data</p>
</div>
<div class="st">💡 💡 Stock Insights</div>
<div class="insight">{"Priority: restock low-stock items." if low_stock > 0 else "Stock status is healthy."} 30-day sales {cloud_sales_qty} units, revenue ${cloud_sales_amt:,.0f}。</div>
<div class="footer">USI Smart Retail OS · EDGE Report · {now_str}</div>
</div>
<script>
/* f-string safe - all braces doubled */
var productMap = {{}};
var allSalesData = null;
var salesChart = null;  // canvas 2d bar chart placeholder

function toast(m,e){{
  var t=document.getElementById("t");t.textContent=m;t.className="toast "+(e?"er":"ok");t.style.display="block";setTimeout(function(){{t.style.display="none"}},2500);
}}

function updateRowBadge(tr,stockVal,reorderVal){{
  var bs=tr.querySelector(".col-badge"),rc=tr.querySelector(".col-rate");
  var mc=parseInt(tr.querySelectorAll("td")[4].textContent.replace(/,/g,""));
  var rate=mc>0?Math.round(stockVal/mc*100):0;
  rc.textContent=rate+"%";
  if(stockVal<=0){{bs.className="bo bo-oos col-badge";bs.textContent="OOS"}}
  else if(stockVal<reorderVal){{bs.className="bo bo-re col-badge";bs.textContent="LOS"}}
  else{{bs.className="bo bo-ok col-badge";bs.textContent="OK"}}
}}

function updateSummary(){{
  var trs=document.querySelectorAll("#tb tr"),los=0,oos=0,total=trs.length;
  trs.forEach(function(tr){{
    var b=tr.querySelector(".col-badge");
    if(b&&b.textContent==="OOS")oos++;
    else if(b&&b.textContent==="LOS")los++;
  }});
  var ok=total-oos-los;
  var rate=total>0?Math.round(ok/total*100):0;
  var lr=total>0?Math.round(oos/total*100):0;
  var lr2=total>0?Math.round(los/total*100):0;
  var hcs=document.querySelectorAll(".hc");
  if(hcs[0])hcs[0].innerHTML='<div class="nm" style="font-size:28px;color:#10b981">'+rate+'%</div><div class="nm" style="font-size:24px">'+ok+'</div><div class="lb">OK (SKU)</div>';
  if(hcs[1])hcs[1].innerHTML='<div class="nm" style="font-size:28px;color:#f59e0b">'+lr2+'%</div><div class="nm" style="font-size:24px">'+los+'</div><div class="lb">LOS (SKU)</div>';
  if(hcs[2])hcs[2].innerHTML='<div class="nm" style="font-size:28px;color:#dc2626">'+lr+'%</div><div class="nm" style="font-size:24px">'+oos+'</div><div class="lb">OOS (SKU)</div>';
}}

document.addEventListener("DOMContentLoaded",function(){{  // OOS/LOS auto-fill Order
  document.querySelectorAll("#tb tr").forEach(function(tr){{
    var badge=tr.querySelector(".col-badge");
    if(badge&&(badge.textContent==="OOS"||badge.textContent==="LOS")){{
      var stock=parseInt(tr.dataset.stock);
      var maxCap=parseInt(tr.querySelectorAll("td")[4].textContent.replace(/,/g,""));
      var inp=tr.querySelector(".rq");
      if(inp&&maxCap>stock){{
        var fillQty=Math.max(0, maxCap-stock);
        if(fillQty>0){{ inp.value=fillQty; }}
      }}
    }}
  }});

  document.querySelectorAll(".ed-stock").forEach(function(c){{
    c.addEventListener("blur",function(){{
      var tr=this.closest("tr"),pid=tr.dataset.pid,val=parseInt(this.textContent.replace(/,/g,""));
      if(isNaN(val)||val<0){{toast("Enter a valid number",1);return;}}
      var ro=parseInt(tr.dataset.reorder);
      fetch("/api/update_stock",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{product_id:pid,store_stock:val}})}})
      .then(function(r){{return r.json()}}).then(function(d){{
        if(d.ok){{toast("✅ Updated");tr.dataset.stock=val;updateRowBadge(tr,val,ro);}}
      }}).catch(function(e){{toast("Save failed: "+e,1)}});
    }});
    c.addEventListener("keydown",function(e){{if(e.key==="Enter"){{e.preventDefault();this.blur()}}}});
  }});
  document.querySelectorAll(".ed-reorder").forEach(function(c){{
    c.addEventListener("blur",function(){{
      var tr=this.closest("tr"),pid=tr.dataset.pid,val=parseInt(this.textContent.replace(/,/g,""));
      if(isNaN(val)||val<0){{toast("Enter a valid number",1);return;}}
      fetch("/api/update_reorder",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{product_id:pid,reorder_level:val}})}})
      .then(function(r){{return r.json()}}).then(function(d){{
        if(d.ok){{toast("✅ Reorder point updated");tr.dataset.reorder=val;var sk=parseInt(tr.dataset.stock);updateRowBadge(tr,sk,val);}}
      }}).catch(function(e){{toast("Save failed: "+e,1)}});
    }});
    c.addEventListener("keydown",function(e){{if(e.key==="Enter"){{e.preventDefault();this.blur()}}}});
  }});
  document.querySelectorAll(".ed-capacity").forEach(function(c){{
    c.addEventListener("blur",function(){{
      var tr=this.closest("tr"),pid=tr.dataset.pid,val=parseInt(this.textContent.replace(/,/g,""));
      if(isNaN(val)||val<0){{toast("Enter a valid number",1);return;}}
      fetch("/api/update_capacity",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{product_id:pid,max_capacity:val}})}})
      .then(function(r){{return r.json()}}).then(function(d){{
        if(d.ok){{toast("✅ Max capacity updated");var sk=parseInt(tr.dataset.stock),ro=parseInt(tr.dataset.reorder);updateRowBadge(tr,sk,ro);}}
      }}).catch(function(e){{toast("Save failed: "+e,1)}});
    }});
    c.addEventListener("keydown",function(e){{if(e.key==="Enter"){{e.preventDefault();this.blur()}}}});
  }});
  // fill product select & load sales data
  loadProductOptions();

      // Poll server purchase state every 1 second
  function pollPurchase() {{
    fetch("/api/purchase_state").then(function(r){{return r.json()}}).then(function(state){{
      document.querySelectorAll("#tb tr").forEach(function(tr){{
        var pid=tr.dataset.pid;
        var pc=tr.querySelector(".pt-col");
        var rbtn=tr.querySelector(".btn-rec");
        var pbtn=tr.querySelector(".btn-purchase");
        if(state[pid]){{
          var s=state[pid];
          if(s.is_ready){{
            if(pc)pc.textContent="Ready";
            if(pbtn)pbtn.textContent="Arrived";
            if(rbtn)rbtn.disabled=false;
          }}else{{
            if(pc)pc.textContent="⏱"+s.remaining+"s";
            if(pbtn)pbtn.textContent="⏱"+s.remaining+"s";
            if(rbtn)rbtn.disabled=true;
          }}
        }}else{{
          if(pc&&pc.textContent!=="--:--:--")pc.textContent="--:--:--";
          if(rbtn)rbtn.disabled=true;
          if(pbtn)pbtn.disabled=false;
          if(pbtn)pbtn.textContent="🔁Order";
        }}
      }});
      setTimeout(pollPurchase, 1000);
    }}).catch(function(){{setTimeout(pollPurchase, 2000);}});
  }}
  pollPurchase();

  // Called-goods button: POST to server
  document.querySelectorAll(".btn-purchase").forEach(function(b){{
    b.addEventListener("click",function(){{
      var pid=this.dataset.pid,inp=document.querySelector(".rq[data-pid='"+pid+"']");
      if(!inp)return;
      var qty=parseInt(inp.value);
      if(!qty||qty<=0){{toast("Enter order qty first",1);return;}}
      this.disabled=true;
      this.textContent="Ordering...";
      fetch("/api/purchase",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{product_id:pid,quantity:qty}})}})
      .then(function(r){{return r.json()}}).then(function(d){{
        if(d.ok){{toast("✅ Ordered "+qty+" pcs");}}
        else{{toast("Order failed: "+(d.error||""),1);b.disabled=false;b.textContent="🔁Order";}}
      }}).catch(function(e){{toast("Order failed: "+e,1);b.disabled=false;b.textContent="🔁Order";}});
    }});
  }});

  // Receive button: receive + clear server state
  document.querySelectorAll(".btn-rec").forEach(function(b){{
    b.addEventListener("click",function(){{
      var pid=this.dataset.pid,inp=document.querySelector(".rq[data-pid='"+pid+"']"),qty=parseInt(inp.value);
      if(!qty||qty<=0){{toast("Order qty must be >0",1);return;}}
      var row=this.closest("tr");
      var rc=row.querySelector(".rt-col");
      var pcc=row.querySelector(".pt-col");
      this.disabled=true;this.textContent="Processing...";
      fetch("/api/receive",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{product_id:pid,quantity:qty}})}})
      .then(function(r){{return r.json()}}).then(function(d){{
        if(d.ok){{
          var now=new Date();
          var h=String(now.getHours()).padStart(2,"0");
          var m=String(now.getMinutes()).padStart(2,"0");
          var s=String(now.getSeconds()).padStart(2,"0");
          if(rc)rc.textContent=h+":"+m+":"+s;
          var sc=row.querySelector(".ed-stock");if(sc)sc.textContent=d.new_stock.toLocaleString();
          toast("✅ Receive done. New stock: "+d.new_stock);
          if(pcc)pcc.textContent="done";
          inp.value=0;
          fetch("/api/purchase_clear",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{product_id:pid}})}});
          updateSummary();
          var ci=document.getElementById("ci");if(ci){{ci.src=ci.src.split("?")[0]+"?t="+Date.now();}}
          var ro=parseInt(row.dataset.reorder);updateRowBadge(row,d.new_stock,ro);
        }}else{{toast("Receive failed: "+(d.error||""),1);b.disabled=false;b.textContent="📥 Receive";}}
      }}).catch(function(e){{toast("Receive failed: "+e,1);b.disabled=false;b.textContent="📥 Receive";}});
    }});
  }});

window.doReceive = function(pid,qty,inp,btn){{
  btn.disabled=true;btn.textContent="Processing...";
  fetch("/api/receive",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{product_id:pid,quantity:qty}})}})
  .then(function(r){{return r.json()}}).then(function(d){{
    if(d.ok){{
      var tr=document.querySelector("tr[data-pid='"+pid+"']"),sc=tr.querySelector(".ed-stock");
      sc.textContent=d.new_stock.toLocaleString();toast("✅ Receive done. New stock: "+d.new_stock);updateSummary();var ci=document.getElementById("ci");if(ci){{ci.src=ci.src.split("?")[0]+"?t="+Date.now();}}var n2=new Date();var h2=String(n2.getHours()).padStart(2,"0");var m2=String(n2.getMinutes()).padStart(2,"0");var s2=String(n2.getSeconds()).padStart(2,"0");var pc2=tr.querySelector(".pt-col");if(pc2)pc2.textContent=h2+":"+m2+":"+s2;
      var ro=parseInt(tr.dataset.reorder);updateRowBadge(tr,d.new_stock,ro);
      inp.value='';
    }}
  }}).catch(function(e){{toast("Receive failed: "+e,1)}}).finally(function(){{btn.disabled=false;if(btn.classList.contains("btn-rec")){{btn.textContent="📥 Receive"}}else{{btn.textContent="🔁Order"}}}});
}}
  loadProductOptions();
  document.getElementById("btn-refresh-chart").addEventListener("click",function(){{
    fetch("/api/refresh_chart").then(function(r){{return r.json()}}).then(function(d){{
      if(d.ok){{document.getElementById("ci").src=d.path+"?t="+Date.now();toast("✅ Chart updated")}}
    }}).catch(function(e){{toast("Chart update failed: "+e,1)}});
  }});
}});

function loadProductOptions(){{
  fetch("/api/product_options").then(function(r){{return r.json()}}).then(function(opts){{
    var sel=document.getElementById("sales-product-select");
    sel.innerHTML="<option value='__all__'>All items (total)</option>";
    productMap={{}};
    // build category-to-name map for cloud data matching
    window.catToProduct={{}};
    opts.forEach(function(p){{
      productMap[p.product_id]=p.product_name;
      var o=document.createElement("option");
      o.value=p.product_id;
      o.textContent=p.product_name+" ("+p.category+")";
      sel.appendChild(o);
      // map category -> first product name
      if(p.category && !catToProduct[p.category]) catToProduct[p.category]=p.product_name;
    }});
    sel.onchange=function(){{renderSales(this.value)}};
    fetch("/api/daily_sales").then(function(r){{return r.json()}}).then(function(rows){{
      allSalesData=rows;
      renderSales("__all__");
    }});
  }});
}}

function renderSales(productId){{
  document.getElementById("stc-empty").style.display="none";
  if(!allSalesData||!allSalesData.length){{document.getElementById("stc-empty").style.display="block";return;}}
  var filtered=allSalesData;
  if(productId!=="__all__"){{
    // Filter by category (CLOUD category = EDGE category)
    var catToMatch = null;
    // Reverse lookup: find category for product_id from productMap
    var sel=document.getElementById("sales-product-select");
    for(var i=0;i<sel.options.length;i++){{
      if(sel.options[i].value===productId){{
        var txt=sel.options[i].textContent;
        var m=txt.match(/\((.+)\)$/);
        if(m) catToMatch=m[1];
        break;
      }}
    }}
    if(catToMatch) filtered=allSalesData.filter(function(r){{return r.category===catToMatch}});
  }}
  if(!filtered.length){{document.getElementById("stc-empty").style.display="block";return;}}
  var dateMap = {{}};
  filtered.forEach(function(r){{
    var d=r.date;
    if(!dateMap[d]){{dateMap[d]=0;}}
    dateMap[d]+=r.units_sold;
  }});
  var keys=Object.keys(dateMap).sort();
  var labels=keys,values=keys.map(function(k){{return dateMap[k]}});
  var titleTxt="";
  if(productId==="__all__"){{titleTxt="\u5168\u90e8\u54c1\u9805 \u2014 \u6bcf\u65e5\u92b7\u552e\u7e3d\u91cf";}}
  else{{var nm=productMap[productId]||productId;titleTxt=nm+" \u2014 \u6bcf\u65e5\u92b7\u552e\u8da8\u52e2";}}
  var canvas=document.getElementById("stc-chart");
  var dpr=window.devicePixelRatio||1;
  var rect=canvas.parentElement.getBoundingClientRect();
  canvas.width=Math.max(rect.width-32,300)*dpr;
  canvas.height=300*dpr;
  canvas.style.width=Math.max(rect.width-32,300)+'px';
  canvas.style.height='300px';
  var ctx=canvas.getContext("2d");
  ctx.scale(dpr,dpr);
  var w=canvas.width/dpr,h=canvas.height/dpr;
  ctx.clearRect(0,0,w,h);
  var pad={{top:50,bottom:50,left:60,right:30}};
  var cw=w-pad.left-pad.right,ch=h-pad.top-pad.bottom;
  if(!values.length||values.every(function(v){{return v===0}})){{
    ctx.fillStyle="#64748b";ctx.font="16px Microsoft JhengHei,sans-serif";ctx.textAlign="center";ctx.fillText("\u7121\u92b7\u552e\u6578\u64da",w/2,h/2);return;
  }}
  var maxVal=Math.max.apply(null,values);
  // draw title
  ctx.fillStyle="#1f2937";ctx.font="bold 16px Microsoft JhengHei,sans-serif";ctx.textAlign="center";ctx.fillText(titleTxt,w/2,28);
  // draw grid
  var steps=5;
  for(var i=0;i<=steps;i++){{
    var y=pad.top+ch-ch*i/steps;
    ctx.strokeStyle="#e2e8f0";ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(w-pad.right,y);ctx.stroke();
    ctx.fillStyle="#64748b";ctx.font="12px Microsoft JhengHei,sans-serif";ctx.textAlign="right";ctx.fillText(Math.round(maxVal*i/steps),pad.left-6,y+4);
  }}
  // draw bars
  var barW=Math.min(40,cw/labels.length*0.7);
  var gap=(cw-barW*labels.length)/(labels.length+1);
  for(var i=0;i<values.length;i++){{
    var x=pad.left+gap+(barW+gap)*i;
    var barH=values[i]/maxVal*ch;
    var y=pad.top+ch-barH;
    // bar
    ctx.fillStyle="rgba(37,99,235,0.8)";
    ctx.beginPath();ctx.rect(x,y,barW,barH);ctx.fill();
    ctx.strokeStyle="#1e3a8a";ctx.lineWidth=1.5;ctx.stroke();
    // value on top
    ctx.fillStyle="#1f2937";ctx.font="11px Microsoft JhengHei,sans-serif";ctx.textAlign="center";
    ctx.fillText(values[i],x+barW/2,y-4);
    // date label
    ctx.save();
    ctx.translate(x+barW/2,pad.top+ch+14);
    ctx.rotate(-Math.PI/4);
    ctx.fillStyle="#475569";ctx.font="10px Microsoft JhengHei,sans-serif";ctx.textAlign="right";
    ctx.fillText(labels[i],0,0);
    ctx.restore();
  }}
}}

document.addEventListener("change",function(e){{
  if(e.target&&e.target.id==="sales-product-select"){{
    renderSales(e.target.value);
  }}
}});

function harvestRestock(pid){{
  var inp=document.querySelector(".rq[data-pid='"+pid+"']");
  var btn=document.querySelector(".btn-rec[data-pid='"+pid+"']");
  if(!inp) return;
  var qty=parseInt(inp.value);
  if(qty>0) doReceive(pid,qty,inp,btn);  // original qty added to stock
}}

function toggleRecv(){{
  var els=document.querySelectorAll(".hidden-col"),btn=document.getElementById("rec-toggle-btn");
  var hidden=els.length>0&&els[0].style.display!=="table-cell";
  els.forEach(function(el){{el.style.display=hidden?"table-cell":"none"}});
  btn.textContent=hidden?"👁 👁 Hide Receive":"👁 Show Receive";
  btn.classList.toggle("active",hidden);
}}
// ========== Cross-device Order Sync ==========
var _syncingQty = false;
function syncSuggestedQty(el) {{
  var pid=el.dataset.pid, qty=parseInt(el.value)||0;
  fetch("/api/set_suggested_qty",{{
    method:"POST",
    headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{product_id:pid, quantity:qty}})
  }}).then(function(r){{return r.json()}}).then(function(d){{
    if(!d.ok) console.error("sync fail",d);
  }}).catch(function(e){{console.error("sync fail",e)}});
}}
// Poll suggested qty from server and update inputs (without triggering onchange)
function pollSuggestedQty() {{
  fetch("/api/suggested_qty").then(function(r){{return r.json()}}).then(function(map){{
    _syncingQty = true;
    document.querySelectorAll(".rq").forEach(function(inp){{
      var pid=inp.dataset.pid, val=map[pid];
      if(val!==undefined && parseInt(inp.value)!==val) inp.value=val;
    }});
    _syncingQty = false;
  }}).catch(function(){{}});
  setTimeout(pollSuggestedQty, 3000);
}}
pollSuggestedQty();

// Replace onchange with a version that respects _syncingQty flag
document.addEventListener("change",function(e){{if(!_syncingQty && e.target&&e.target.classList.contains("rq")) syncSuggestedQty(e.target);}});

// run on load to hide by default
window.addEventListener("load",function(){{toggleRecv()}});
</script>

</body></html>"""
    return html

# ─── 啟動 ───
if __name__ == "__main__":
    _generate_chart()
    print(f"🚀 EDGE Server started: http://localhost:5000")
    print(f"   Store: {store_zh} ({STORE_ID})")
    print(f"   EDGE_DB: {EDGE_DB}")
    print(f"   CLOUD_DB: {CLOUD_DB}")
    print(f"   Press Ctrl+C to stop")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
