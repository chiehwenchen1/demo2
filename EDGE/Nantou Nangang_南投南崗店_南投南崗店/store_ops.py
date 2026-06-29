#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store_ops.py — 門市進貨 / 存貨 / 銷貨操作
可直接複製到各門市資料夾下使用，自動辨識門市名稱。
支援三種操作：
  --action restock      進貨（增加庫存）
  --action sell         銷貨（減少庫存）
  --action status       庫存狀態一覽
  --action report       產生 EDGE 報表（HTML + PNG）
"""

# 修正 Windows cp950 無法處理 emoji 的問題
import io, sys
if sys.stdout.encoding and sys.stdout.encoding.upper() in ('CP950', 'BIG5', 'BIG5-HKSCS'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import csv
import glob
import os
import sqlite3
import sys
import uuid
from datetime import datetime, date, timedelta
import time

# ========== 自動偵測門市名稱 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "EDGE_DB.db")

# 從目錄名稱推斷 store_id & CLOUD store_id
DIRNAME = os.path.basename(SCRIPT_DIR)
if "南投" in DIRNAME or "Nantou" in DIRNAME:
    STORE_ID = "Nantou Nangang"
    STORE_PREFIX = "Nantou"
    REGION = "Central"
elif "北忠孝" in DIRNAME or "Taipei" in DIRNAME:
    STORE_ID = "Taipei Zhongxiao"
    STORE_PREFIX = "Taipei"
    REGION = "North"
elif "大阪" in DIRNAME or "Osaka" in DIRNAME:
    STORE_ID = "Osaka Shinsaibashi"
    STORE_PREFIX = "Osaka"
    REGION = "Osaka"
else:
    # 從 EDGE_DB.db 的 store_info 讀取
    STORE_ID = "Unknown"
    STORE_PREFIX = "Store"
    REGION = "Unknown"
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT store_id, region FROM store_info LIMIT 1")
            row = cur.fetchone()
            if row:
                STORE_ID = row[0]
                REGION = row[1] or "Unknown"
                if "Nantou" in STORE_ID or "Taipei" in STORE_ID:
                    STORE_PREFIX = "Nantou"
                elif "Osaka" in STORE_ID:
                    STORE_PREFIX = "Osaka"
            conn.close()
        except:
            pass

# CLOUD 資料庫路徑（從專案目錄推算）
PROJECT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
CLOUD_DB = os.path.join(PROJECT_DIR, "CLOUD", "database", "cloud_inventory.db")
CLOUD_CSV_DIR = os.path.join(PROJECT_DIR, "CLOUD", "inventory")

# 類別對照（EDGE category → 中文品名）
CATEGORY_TO_NAME = {
    "cola": "可樂 330ML",
    "sprite": "雪碧 330ML",
    "pepsi": "百事可樂 500ML",
    "big_cola": "可樂 920ML",
    "beer1": "海尼根啤酒",
    "beer2": "百威啤酒 473ML",
    "cookie1": "CALBEE JAGARICO",
    "cookie2": "卡迪那脆薯條",
    "soup": "丸米減鹽味噌湯",
    "tomato": "HEINZ 番茄醬 3入",
}

# EDGE category → sku_v2 category
EDGE_TO_SKU = {
    "cola": "coke",
    "sprite": "sprite",
    "pepsi": "pepsi",
    "big_cola": "coke_large",
    "beer1": "heineken",
    "beer2": "budweiser",
    "cookie1": "jagarico",
    "cookie2": "cadina",
    "soup": "miso_soup",
    "tomato": "heinz_ketchup",
}

PRODUCT_ALIASES = {
    "cola": "cola", "coke": "cola", "可樂": "cola",
    "big_cola": "big_cola", "coke_large": "big_cola", "大瓶可樂": "big_cola",
    "sprite": "sprite", "雪碧": "sprite",
    "pepsi": "pepsi", "百事可樂": "pepsi",
    "heineken": "beer1", "海尼根": "beer1", "beer1": "beer1",
    "budweiser": "beer2", "百威": "beer2", "beer2": "beer2",
    "jagarico": "cookie1", "calbee": "cookie1", "cookie1": "cookie1",
    "cadina": "cookie2", "卡迪那": "cookie2", "cookie2": "cookie2",
    "miso_soup": "soup", "味噌湯": "soup", "soup": "soup",
    "heinz_ketchup": "tomato", "番茄醬": "tomato", "tomato": "tomato",
}


# ========== 工具函數 ==========

def get_conn():
    """取得 EDGE DB 連線"""
    if not os.path.exists(DB_PATH):
        print(f"❌ 找不到 EDGE 資料庫: {DB_PATH}")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def resolve_product(conn, alias):
    """根據別名查詢產品"""
    #edge_cat = PRODUCT_ALIASES.get(alias, alias)
    edge_cat = alias
    cur = conn.cursor()
    # 用簡短 product_id 查詢
    cur.execute(
        "SELECT id, product_id, product_name, category, store_stock, "
        "retail_price, max_capacity, reorder_level "
        "FROM enhanced_inventory WHERE category = ? AND product_id LIKE ?",
        (edge_cat, f"{STORE_PREFIX}%{edge_cat}")
    )
    row = cur.fetchone()
    if row:
        return row
    # 只查 category
    cur.execute(
        "SELECT id, product_id, product_name, category, store_stock, "
        "retail_price, max_capacity, reorder_level "
        "FROM enhanced_inventory WHERE category = ?",
        (edge_cat,)
    )
    return cur.fetchone()


def record_transaction(conn, product_id, txn_type, qty, prev_stock, new_stock, total_amount=0):
    """記錄交易"""
    cur = conn.cursor()
    txn_id = f"TXN-{uuid.uuid4().hex.upper()}"
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO inventory_transactions (transaction_id, product_id, transaction_type, quantity, "
        "previous_stock, new_stock, total_amount, transaction_time, device_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (txn_id, product_id, txn_type, qty, prev_stock, new_stock, total_amount, now, "STORE_OPS")
    )
    try:
        cur.execute(
            "INSERT INTO transaction_log (transaction_id, product_name, quantity, total_price, "
            "payment_method, customer_id, checkout_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (txn_id, product_id, qty, total_amount, "SYSTEM", "OPS", now)
        )
    except:
        pass
    return txn_id


# ========== 操作功能 ==========

def action_status(conn):
    """顯示目前庫存狀態"""
    cur = conn.cursor()
    products = []
    cur.execute(
        "SELECT product_id, product_name, category, stock_quantity, "
        "retail_price, max_capacity, reorder_level "
        "FROM enhanced_inventory ORDER BY category, product_name"
    )
    for row in cur.fetchall():
        products.append(row)

    if not products:
        print("找不到任何產品")
        return

    display_name = CATEGORY_TO_NAME

    print(f"\n{'='*80}")
    print(f"  {STORE_ID} — 目前庫存狀態")
    print(f"{'='*80}")
    print(f"  {'品名':<22s} {'類別':<12s} {'零售價':>8s} {'庫存':>6s} {'最大':>6s} {'補貨點':>6s} {'庫存率':>8s}")
    print(f"  {'-'*70}")

    total_stock = 0
    total_value = 0
    oos_count = 0

    for p in products:
        prod_id, pname, cat, stock, rprice, max_cap, reorder = p[:7]
        max_cap = max_cap or 200
        reorder = reorder or 20
        dname = pname
        rate = (stock / max_cap * 100) if max_cap > 0 else 0
        icon = "🟢" if rate > 50 else "🟡" if rate > 20 else "🔴"
        print(f"  {icon} {dname:<20s} {cat:<12s} ${rprice:>6.1f} {stock:>6d} {max_cap:>6d} {reorder:>6d} {rate:>7.0f}%")
        total_stock += stock
        total_value += stock * rprice
        if stock <= 0:
            oos_count += 1

    print(f"  {'-'*70}")
    print(f"  📊 彙總:")
    print(f"     總庫存數量: {total_stock:,} 件")
    print(f"     總庫存價值: ${total_value:,.2f}")
    print(f"     缺貨商品數: {oos_count}")
    print(f"{'='*80}\n")


def action_restock(conn, alias, qty):
    """進貨：增加庫存"""
    product = resolve_product(conn, alias)
    if not product:
        print(f"❌ 找不到產品: {alias}")
        return

    pid, prod_id, pname, cat, stock, rprice, max_cap, reorder = product
    prev_stock = stock
    new_stock = prev_stock + qty
    total_amount = qty * rprice * 0.6  # 成本價

    cur = conn.cursor()
    cur.execute("UPDATE enhanced_inventory SET store_stock = ? WHERE id = ?", (new_stock, pid))
    record_transaction(conn, prod_id, "restock", qty, prev_stock, new_stock, total_amount)
    conn.commit()

    print(f"✅ 進貨完成: {pname} ({cat}) +{qty} 件")
    print(f"   原庫存: {prev_stock} → 新庫存: {new_stock}")
    print(f"   進貨金額: ${total_amount:.2f}")


def action_sell(conn, alias, qty):
    """銷貨：減少庫存"""
    product = resolve_product(conn, alias)
    if not product:
        print(f"❌ 找不到產品: {alias}")
        return

    pid, prod_id, pname, cat, stock, rprice, max_cap, reorder = product
    if stock < qty:
        print(f"❌ 庫存不足！{pname} 目前庫存: {stock}，需求: {qty}")
        return

    prev_stock = stock
    new_stock = prev_stock - qty
    total_amount = qty * rprice

    cur = conn.cursor()
    cur.execute("UPDATE enhanced_inventory SET store_stock = ? WHERE id = ?", (new_stock, pid))
    record_transaction(conn, prod_id, "sell", qty, prev_stock, new_stock, total_amount)
    conn.commit()

    print(f"✅ 銷貨完成: {pname} ({cat}) -{qty} 件")
    print(f"   原庫存: {prev_stock} → 新庫存: {new_stock}")
    print(f"   銷售金額: ${total_amount:.2f}")


# ========== CLOUD 同步 ==========

def sync_to_cloud():
    """將 EDGE 目前庫存同步到 CLOUD
    - 從 EDGE inventory_transactions 計算今日實際銷售/進貨量
    - 寫入一筆今日快照到 CLOUD inventory_raw（與模擬資料同格式）
    - 確保 EDGE 報表與 CLOUD 報表的銷售 KPI 同源
    """
    if not os.path.exists(CLOUD_DB):
        print(f"  [SKIP] CLOUD 資料庫不存在: {CLOUD_DB}")
        return

    conn = get_conn()
    cur = conn.cursor()
    today_str = date.today().isoformat()

    # 先查詢今日已銷售/進貨量
    cur.execute("""
        SELECT product_id, transaction_type, SUM(quantity)
        FROM inventory_transactions
        WHERE DATE(transaction_time) = ? AND transaction_type IN ('sell','restock')
        GROUP BY product_id, transaction_type
    """, (today_str,))
    today_txns = cur.fetchall()

    # 建立 {product_id: {sell: N, restock: N}} 對照
    today_sold = {}
    today_restocked = {}
    for row in today_txns:
        pid, ttype, qty = row
        qty = qty or 0
        if ttype == "sell":
            today_sold[pid] = qty
        elif ttype == "restock":
            today_restocked[pid] = qty

    # 蒐集所有產品資料
    snapshots = []
    for edge_cat, sku_cat in EDGE_TO_SKU.items():
        cur.execute(
            "SELECT product_id, product_name, category, stock_quantity, retail_price "
            "FROM enhanced_inventory WHERE category = ? AND product_id LIKE ?",
            (edge_cat, f"{STORE_PREFIX}%{edge_cat}")
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "SELECT product_id, product_name, category, stock_quantity, retail_price "
                "FROM enhanced_inventory WHERE category = ?",
                (edge_cat,)
            )
            row = cur.fetchone()
        if not row:
            continue

        prod_id, pname, cat, stock, rprice = row
        stock = stock or 0
        rprice = float(rprice or 0)

        # 從今日交易記錄計算實際銷售/進貨
        sold = today_sold.get(prod_id, 0)
        ordered = today_restocked.get(prod_id, 0)
        # 簡單需求預估（用近7天平均銷售）
        cur.execute("""
            SELECT COALESCE(AVG(quantity),0)
            FROM inventory_transactions
            WHERE product_id = ? AND transaction_type = 'sell'
              AND DATE(transaction_time) >= ? AND DATE(transaction_time) < ?
        """, (prod_id, (date.today() - timedelta(days=7)).isoformat(), today_str))
        avg_sold = cur.fetchone()[0] or 0
        demand_forecast = round(max(avg_sold * 1.2, 1), 1)

        snapshots.append({
            "store_id": STORE_ID,
            "date": today_str,
            "product_id": prod_id,
            "category": sku_cat,
            "region": REGION,
            "inventory_level": max(0, stock),
            "units_sold": sold,
            "units_ordered": ordered,
            "demand_forecast": demand_forecast,
            "price": rprice,
            "discount": 0.0,
        })

    conn.close()
    if not snapshots:
        print("  [SKIP] 無資料可同步")
        return

    # 寫入 CLOUD（如果今日已有同一產品+門市的快照，先刪除再插入）
    cld = sqlite3.connect(CLOUD_DB)
    ccur = cld.cursor()
    ccur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT, date TEXT, product_id TEXT, category TEXT, region TEXT,
            inventory_level INTEGER, units_sold INTEGER, units_ordered INTEGER,
            demand_forecast REAL, price REAL, discount REAL,
            weather TEXT, holiday TEXT, competitor_pricing REAL, seasonality TEXT
        )
    """)

    for s in snapshots:
        # 刪除今日舊快照（避免重複疊加）
        ccur.execute(
            "DELETE FROM inventory_raw WHERE store_id=? AND date=? AND product_id=?",
            (s["store_id"], s["date"], s["product_id"])
        )
        ccur.execute(
            "INSERT INTO inventory_raw (store_id, date, product_id, category, region, "
            "inventory_level, units_sold, units_ordered, demand_forecast, price, discount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (s["store_id"], s["date"], s["product_id"], s["category"], s["region"],
             s["inventory_level"], s["units_sold"], s["units_ordered"],
             s["demand_forecast"], s["price"], s["discount"])
        )
    cld.commit()
    cld.close()
    print(f"  ✅ 已同步 {len(snapshots)} 筆今日快照至 CLOUD（含實際銷售/進貨數據）")


# ========== EDGE 報表（HTML + PNG） ==========

def _load_cloud_data():
    """從 CLOUD inventory_raw 讀取此門市的歷史銷售資料（與 CLOUD 報表同源）"""
    if not os.path.exists(CLOUD_DB):
        return None
    try:
        cld = sqlite3.connect(CLOUD_DB)
        df = pd.read_sql(
            "SELECT date, units_sold, inventory_level, price, discount "
            "FROM inventory_raw WHERE store_id = ? ORDER BY date",
            cld, params=(STORE_ID,)
        )
        cld.close()
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df["revenue"] = df["units_sold"] * df["price"] * (1 - df["discount"].fillna(0) / 100)
        return df
    except Exception as e:
        print(f"  [WARN] 讀取 CLOUD DB 失敗: {e}")
        return None


def action_report(conn):
    """產生 EDGE 庫存報表（HTML + PNG）到 reports/ 資料夾
    庫存讀 EDGE DB，銷售趨勢讀 CLOUD DB（確保與 CLOUD 報表同步）"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager, rcParams
        has_mpl = True
        candidates = ["Microsoft JhengHei", "Noto Sans CJK TC", "SimHei", "Arial Unicode MS"]
        names = {f.name for f in font_manager.fontManager.ttflist}
        for name in candidates:
            if name in names:
                rcParams["font.family"] = name
                rcParams["axes.unicode_minus"] = False
                break
    except ImportError:
        has_mpl = False

    global pd
    import numpy as np
    import pandas as pd

    cur = conn.cursor()

    # === 1. 庫存資料（從 EDGE DB） ===
    products = []
    cur.execute(
        "SELECT product_id, product_name, category, stock_quantity, retail_price, "
        "max_capacity, reorder_level FROM enhanced_inventory ORDER BY category, product_name"
    )
    for row in cur.fetchall():
        products.append(row)

    # === 2. 銷售資料（從 CLOUD DB — 與 CLOUD 報表同源） ===
    cloud_df = _load_cloud_data()

    # 讀取 EDGE 交易記錄（僅用於交易筆數統計）
    cur.execute("""
        SELECT product_id, transaction_type, quantity, total_amount, transaction_time
        FROM inventory_transactions
        WHERE transaction_time >= ?
        ORDER BY transaction_time DESC
    """, ((date.today() - timedelta(days=30)).isoformat(),))
    txns = cur.fetchall()

    # === KPI 計算 ===
    total_sku = len(products)
    total_stock = sum(p[3] or 0 for p in products)
    total_value = sum((p[3] or 0) * float(p[4] or 0) for p in products)
    oos = sum(1 for p in products if (p[3] or 0) <= 0)
    low_stock = sum(1 for p in products if 0 < (p[3] or 0) < (p[6] or 20))

    # 銷售 KPI 從 CLOUD 資料來（用資料中最大日期為基準，與 CLOUD 報表一致）
    if cloud_df is not None and not cloud_df.empty:
        cloud_latest = cloud_df["date"].max()
        recent_30 = cloud_df[cloud_df["date"] >= cloud_latest - pd.Timedelta(days=30)]
        cloud_sales_qty = int(recent_30["units_sold"].sum())
        cloud_sales_amt = float(recent_30["revenue"].sum())
        cloud_sales_count = len(recent_30)
    else:
        # 回退到 EDGE 交易記錄
        recent_sales = [t for t in txns if t[1] == "sell"]
        cloud_sales_qty = sum(t[2] or 0 for t in recent_sales)
        cloud_sales_amt = sum(float(t[3] or 0) for t in recent_sales)
        cloud_sales_count = len(recent_sales)

    # 交易筆數（仍用 EDGE 本地記錄）
    recent_sales_txns = [t for t in txns if t[1] == "sell"]
    recent_restock_txns = [t for t in txns if t[1] == "restock"]

    # 建立報表目錄
    report_dir = os.path.join(SCRIPT_DIR, "reports")
    os.makedirs(report_dir, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    store_zh = "南投南崗店" if STORE_ID == "Nantou Nangang" else "大阪心齋橋店"

    # --- 繪製 PNG（庫存圖 + CLOUD 銷售趨勢圖） ---
    if has_mpl and len(products) > 0:
        n_sku = len(products)
        # 垂直排列：庫存條圖(上) → 庫存價值 Top 10 + 健康度(中) → 銷售趨勢(下)
        fig = plt.figure(figsize=(18, 16))
        fig.suptitle(f"EDGE 庫存管理儀表板 — {store_zh}", fontsize=20, weight="bold", y=0.98)
        gs = fig.add_gridspec(3, 3, hspace=0.30, wspace=0.20,
                               left=0.08, right=0.97, top=0.94, bottom=0.04)

        # 1. 各品類庫存條圖（佔上排全寬，依庫存由高到低排序）
        ax1 = fig.add_subplot(gs[0, :])
        sorted_pairs = sorted([(p[3] or 0, p) for p in products], key=lambda x: x[0], reverse=True)
        sorted_products = [sp[1] for sp in sorted_pairs]  # 由多至少排列，barh 會自動把最大值放最上面
        cats = [p[1] for p in sorted_products]
        stocks = [p[3] or 0 for p in sorted_products]
        colors = ["#ef4444" if s <= 0 else "#f59e0b" if s < (p[6] or 20) else "#10b981" for s, p in zip(stocks, sorted_products)]
        ax1.barh(cats, stocks, color=colors, height=0.7)
        ax1.set_title(f"目前庫存數量 ({n_sku}項，由高至低)", fontsize=16, weight="bold")
        ax1.set_xlabel("件", fontsize=13)
        ax1.grid(True, axis="x", alpha=0.3)
        ax1.tick_params(axis="y", labelsize=11)
        # 斑馬紋：每隔一行淺灰底色
        for i, row in enumerate(ax1.patches):
            if i % 2 == 1:
                row.set_alpha(0.95)
        # 確保最多的在最上面
        ax1.invert_yaxis()
        ax1.margins(y=0.01)

        # 2. 庫存價值 Top 10（中排左）
        ax2 = fig.add_subplot(gs[1, 0])
        values = [(p[3] or 0) * float(p[4] or 0) for p in products]
        sorted_idx = np.argsort(values)[::-1][:10]
        top_cats = [cats[i] for i in sorted_idx]
        top_vals = [values[i] / 10000 for i in sorted_idx]
        ax2.barh(top_cats, top_vals, color="#3b82f6", height=0.7)
        ax2.set_title("庫存價值 Top 10 (萬元)", fontsize=16, weight="bold")
        ax2.set_xlabel("萬元", fontsize=13)
        ax2.grid(True, axis="x", alpha=0.3)
        ax2.tick_params(axis="y", labelsize=12)
        ax2.margins(y=0.08)

        # 3. 庫存健康度圓餅圖（中排中）
        ax3 = fig.add_subplot(gs[1, 1])
        ok_count = total_sku - low_stock - oos
        labels, sizes, pie_colors = [], [], []
        if ok_count > 0:
            labels.append(f"正常 ({ok_count})")
            sizes.append(ok_count)
            pie_colors.append("#10b981")
        if low_stock > 0:
            labels.append(f"低庫存 ({low_stock})")
            sizes.append(low_stock)
            pie_colors.append("#f59e0b")
        if oos > 0:
            labels.append(f"缺貨 ({oos})")
            sizes.append(oos)
            pie_colors.append("#ef4444")
        if sizes:
            ax3.pie(sizes, labels=labels, colors=pie_colors, autopct="%1.0f%%", startangle=90,
                    textprops={"fontsize": 15, "weight": "bold"})
        ax3.set_title("庫存健康度", fontsize=16, weight="bold")

        # 4. 銷售趨勢圖（下排全寬）
        ax4 = fig.add_subplot(gs[2, :])
        if cloud_df is not None and not cloud_df.empty:
            daily = cloud_df.groupby("date").agg({"units_sold": "sum", "revenue": "sum"}).reset_index()
            ax4.plot(daily["date"], daily["units_sold"], color="#3b82f6", linewidth=2.5)
            ax4.fill_between(daily["date"], daily["units_sold"], alpha=0.15, color="#3b82f6")
            ax4.set_title("貨架每日銷售趨勢", fontsize=16, weight="bold")
            ax4.set_ylabel("銷售量", fontsize=13)
            ax4.grid(True, alpha=0.3)
            ax4.tick_params(axis="x", rotation=20, labelsize=11)
        else:
            txn_labels = ["銷貨", "進貨", "補貨", "其他"]
            txn_counts = [
                sum(1 for t in txns if t[1] == "sell"),
                sum(1 for t in txns if t[1] == "restock"),
                sum(1 for t in txns if t[1] == "shelf_replenish"),
                sum(1 for t in txns if t[1] not in ("sell", "restock", "shelf_replenish")),
            ]
            ax4.bar(txn_labels, txn_counts, color=["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"])
            ax4.set_title("EDGE 近30天交易筆數", fontsize=16, weight="bold")
        ax4.grid(True, axis="y", alpha=0.3)

        png_path = os.path.join(report_dir, f"edge_dashboard_{STORE_ID}.png")
        fig.savefig(png_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  ✅ 儀表板: {png_path}")

    # --- 產生 HTML ---
    rows_html = ""
    for p in sorted(products, key=lambda x: x[3] or 0, reverse=True):
        prod_id, pname, cat, stock, rprice, max_cap, reorder = p[:7]
        stock = stock or 0
        max_cap = max_cap or 200
        reorder = reorder or 20
        dname = pname
        rate = (stock / max_cap * 100) if max_cap > 0 else 0
        badge = "badge-oos" if stock <= 0 else "badge-low" if rate < 30 else "badge-ok"
        badge_text = "缺貨" if stock <= 0 else "偏低" if rate < 30 else "正常"
        rows_html += f"""
        <tr>
            <td>{dname}</td>
            <td>{cat}</td>
            <td style="text-align:right">${rprice:,.0f}</td>
            <td style="text-align:right">{stock:,}</td>
            <td style="text-align:right">{max_cap:,}</td>
            <td style="text-align:right">{reorder:,}</td>
            <td style="text-align:right">{rate:.0f}%</td>
            <td><span class="{badge}">{badge_text}</span></td>
        </tr>"""

    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>{store_zh} - EDGE 庫存報表</title>
<style>
body{{margin:0;font-family:"Microsoft JhengHei","Segoe UI",Arial,sans-serif;background:#f4f6f8;color:#1f2937}}
.header{{background:linear-gradient(120deg,#0f172a,#1e3a8a);color:white;padding:24px 42px}}
.header h1{{margin:0;font-size:28px}}
.header p{{margin:6px 0 0;font-size:14px;color:#dbeafe}}
.container{{padding:24px 42px 42px}}
.section-title{{font-size:18px;font-weight:700;margin:24px 0 12px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}
.card{{background:white;border-radius:14px;padding:16px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.card .l{{color:#64748b;font-size:13px;margin-bottom:6px}}
.card .v{{font-size:22px;font-weight:800}}
.card.red .v{{color:#dc2626}} .card.green .v{{color:#059669}} .card.blue .v{{color:#2563eb}} .card.orange .v{{color:#ea580c}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.chart{{background:white;border-radius:14px;padding:14px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.chart img{{width:100%;display:block}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
th{{background:#0f172a;color:white;padding:10px 12px;font-size:13px;text-align:left}}
td{{padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px}}
tr:nth-child(even) td{{background:#f8fafc}}
.badge-oos{{display:inline-block;padding:2px 8px;border-radius:20px;background:#fee2e2;color:#b91c1c;font-size:12px;font-weight:700}}
.badge-low{{background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:20px;font-size:12px;font-weight:700}}
.badge-ok{{background:#dcfce7;color:#166534;padding:2px 8px;border-radius:20px;font-size:12px;font-weight:700}}
.insight{{background:#ecfeff;border-left:6px solid #0891b2;padding:14px 18px;border-radius:10px;line-height:1.7;font-size:14px}}
.footer{{color:#64748b;font-size:12px;margin-top:28px;text-align:center}}
.scroll-table{{max-height:420px;overflow-y:auto;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.scroll-table table{{border-radius:0;box-shadow:none}}
.scroll-table thead th{{position:sticky;top:0;z-index:1}}
</style>
</head>
<body>
<div class="header">
  <h1>🏪 EDGE 庫存管理報表 — {store_zh}</h1>
  <p>{STORE_ID} | 區域: {REGION} | 報表時間: {now_str}</p>
</div>
<div class="container">

<div class="section-title">📊 KPI 摘要</div>
<div class="kpi-grid">
  <div class="card blue"><div class="l">產品數 (SKU)</div><div class="v">{total_sku}</div></div>
  <div class="card green"><div class="l">總庫存量</div><div class="v">{total_stock:,}</div></div>
  <div class="card"><div class="l">總庫存價值</div><div class="v">${total_value:,.0f}</div></div>
  <div class="card orange"><div class="l">近30天銷貨金額</div><div class="v">${cloud_sales_amt:,.0f}</div></div>
  <div class="card green"><div class="l">✅ 正常庫存</div><div class="v">{total_sku - low_stock - oos}</div></div>
  <div class="card" style="border:2px solid #ff9800"><div class="l">⚠️ 低庫存</div><div class="v">{low_stock}</div></div>
  <div class="card red"><div class="l">❌ 缺貨</div><div class="v">{oos}</div></div>
  <div class="card"><div class="l">近30天銷售量</div><div class="v">{cloud_sales_qty:,}</div></div>
</div>

<div class="section-title">📋 各品類庫存一覽</div>
<div class="scroll-table">
<table>
<thead><tr>
  <th>品名</th><th>類別</th><th>零售價</th><th>庫存</th><th>最大容量</th><th>補貨點</th><th>庫存率</th><th>狀態</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>"""

    if has_mpl:
        png_rel = f"edge_dashboard_{STORE_ID}.png"
        html += f"""
<div class="section-title">📈 庫存儀表板</div>
<div class="chart">
  <img src="{png_rel}" alt="庫存儀表板">
</div>"""

    html += f"""
<div class="section-title">💡 庫存洞察</div>
<div class="insight">
  <strong>庫存健康度：</strong>{total_sku} 項產品中，{total_sku - low_stock - oos} 項庫存正常，
  {low_stock} 項偏低，{oos} 項缺貨。{ "建議優先補貨低庫存品項。" if low_stock > 0 else "目前庫存狀況良好。" }
  近30天銷售（CLOUD） {cloud_sales_qty} 件，銷貨金額 ${cloud_sales_amt:,.0f}。
</div>

<div class="section-title">📄 交易記錄摘要（近30天）</div>
<table>
<thead><tr>
  <th>類型</th><th>來源</th><th>筆數</th><th>數量</th><th>金額</th>
</tr></thead>
<tbody>
  <tr><td>📤 銷貨</td><td>CLOUD</td><td>{cloud_sales_count}</td><td>{cloud_sales_qty:,}</td><td>${cloud_sales_amt:,.0f}</td></tr>
  <tr><td>📥 進貨</td><td>EDGE</td><td>{len(recent_restock_txns)}</td><td>{sum(t[2] or 0 for t in recent_restock_txns):,}</td><td>${sum(float(t[3] or 0) for t in recent_restock_txns):,.0f}</td></tr>
  <tr><td>🔄 補貨</td><td>EDGE</td><td>{sum(1 for t in txns if t[1] == "shelf_replenish"):,}</td><td>{sum(t[2] or 0 for t in txns if t[1] == "shelf_replenish"):,}</td><td>-</td></tr>
</tbody>
</table>

<div class="footer">
  USI Smart Retail OS · EDGE 端報表 · {now_str}
</div>
</div>
</body>
</html>"""

    html_path = os.path.join(report_dir, f"edge_report_{STORE_ID}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ HTML 報表: {html_path}")


# ========== 主程式 ==========

def main():
    parser = argparse.ArgumentParser(description=f"{STORE_ID} — 門市進貨/銷貨/庫存管理")
    parser.add_argument("--action", required=True,
                        choices=["restock", "sell", "status", "report"],
                        help="操作: restock(進貨) / sell(銷貨) / status(庫存) / report(報表)")
    parser.add_argument("--product", help="產品名稱 (cola, sprite, 可樂, 雪碧...)")
    parser.add_argument("--qty", type=int, default=10, help="數量")
    args = parser.parse_args()

    print(f"\n🏪 {STORE_ID}")
    print(f"   {DB_PATH}")

    if args.action == "status":
        conn = get_conn()
        action_status(conn)
        conn.close()
        return

    if args.action == "report":
        conn = get_conn()
        action_report(conn)
        conn.close()
        return

    if not args.product:
        print("❌ 請指定產品名稱 (--product)")
        sys.exit(1)

    conn = get_conn()
    if args.action == "restock":
        action_restock(conn, args.product, args.qty)
    elif args.action == "sell":
        action_sell(conn, args.product, args.qty)

    conn.close()

    '''
    # 操作後自動同步 CLOUD
    print(f"\n  🔄 正在同步至 CLOUD...")
    sync_to_cloud()
    print(f"  ✅ 同步完成")

    # 同步後自動更新兩份報表（EDGE + CLOUD）
    print(f"\n  📄 正在更新報表...")
    # 先重開 EDGE DB 連線（sync_to_cloud 已關閉）
    conn2 = get_conn()
    action_report(conn2)
    conn2.close()

    # 更新 CLOUD 端報表
    _update_cloud_report()
    print(f"  ✅ 報表已更新")
    '''

def _update_cloud_report():
    """直接從 EDGE DB + CLOUD DB 產生 CLOUD HTML 報表（內嵌版，無需 subprocess）"""
    cloud_db = os.path.join(PROJECT_DIR, "CLOUD", "database", "cloud_inventory.db")
    cloud_html = os.path.join(PROJECT_DIR, "CLOUD", "reports", "inventory_sales_report_zh.html")
    cloud_png = os.path.join(PROJECT_DIR, "CLOUD", "reports", "inventory_sales_dashboard_zh.png")
    os.makedirs(os.path.dirname(cloud_html), exist_ok=True)

    if not os.path.exists(cloud_db):
        print(f"  [SKIP] CLOUD DB 不存在: {cloud_db}")
        return

    try:
        import numpy as np
        import pandas as pd
    except ImportError:
        print(f"  [SKIP] 需要 numpy / pandas")
        return

    # matplotlib 選擇性
    has_mpl = False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager, rcParams
        has_mpl = True
        candidates = ["Noto Sans CJK TC", "Noto Sans CJK SC", "Microsoft JhengHei",
                      "Microsoft YaHei", "SimHei", "Arial Unicode MS"]
        names = {f.name for f in font_manager.fontManager.ttflist}
        for name in candidates:
            if name in names:
                rcParams["font.family"] = name
                rcParams["axes.unicode_minus"] = False
                break
    except ImportError:
        pass

    # 報表參數
    OOS_DAYS = 3
    LOW_STOCK_DAYS = 7
    TARGET_STOCK_DAYS = 14

    def money(x):
        return f"${x:,.0f}"

    # 讀取 CLOUD DB
    conn = sqlite3.connect(cloud_db)
    try:
        df = pd.read_sql("SELECT * FROM inventory_raw", conn)
    except Exception as e:
        print(f"  [WARN] 讀取 CLOUD DB 失敗: {e}")
        conn.close()
        return
    conn.close()

    if df.empty:
        print(f"  [SKIP] CLOUD DB inventory_raw 為空")
        return

    # 重新命名欄位
    df = df.rename(columns={
        "store_id": "Store ID", "date": "Date", "product_id": "Product ID",
        "category": "Category", "region": "Region",
        "inventory_level": "Inventory Level", "units_sold": "Units Sold",
        "units_ordered": "Units Ordered", "demand_forecast": "Demand Forecast",
        "price": "Price", "discount": "Discount",
    })

    df["Date"] = pd.to_datetime(df["Date"])
    df["折扣後售價"] = df["Price"] * (1 - df["Discount"].fillna(0) / 100)
    df["營收"] = df["Units Sold"] * df["折扣後售價"]

    latest_date = df["Date"].max()
    latest = df[df["Date"] == latest_date].copy()

    latest["可支撐天數"] = (
        latest["Inventory Level"] / latest["Demand Forecast"].replace(0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(999)

    latest["14天目標庫存"] = latest["Demand Forecast"] * TARGET_STOCK_DAYS
    latest["建議補貨量"] = (
        latest["14天目標庫存"] - latest["Inventory Level"] - latest["Units Ordered"]
    ).clip(lower=0).round().astype(int)

    latest["庫存狀態"] = np.select(
        [latest["可支撐天數"] <= OOS_DAYS,
         (latest["可支撐天數"] > OOS_DAYS) & (latest["可支撐天數"] <= LOW_STOCK_DAYS)],
        ["缺貨風險", "低庫存"],
        default="安全庫存"
    )

    last_30 = df[df["Date"] >= latest_date - pd.Timedelta(days=30)]
    last_90 = df[df["Date"] >= latest_date - pd.Timedelta(days=90)]

    # ---- 儀表板 PNG ----
    if has_mpl:
        try:
            daily = last_90.groupby("Date", as_index=False).agg(
                {"Units Sold": "sum", "營收": "sum", "Inventory Level": "sum"}
            ).sort_values("Date")

            status = latest.groupby(["Category", "庫存狀態"]).size().unstack(fill_value=0)
            for c in ["缺貨風險", "低庫存", "安全庫存"]:
                if c not in status.columns:
                    status[c] = 0
            status = status[["缺貨風險", "低庫存", "安全庫存"]]

            cat = latest.groupby("Category", as_index=False).agg(
                {"Inventory Level": "sum", "Demand Forecast": "sum", "建議補貨量": "sum"}
            ).sort_values("建議補貨量", ascending=False)

            top = latest.sort_values("建議補貨量", ascending=False).head(10).copy()
            if not top.empty:
                top["門市 / 商品"] = top["Store ID"] + " / " + top["Product ID"]

            kpis = {
                "門市數": df["Store ID"].nunique(),
                "商品數": df["Product ID"].nunique(),
                "近30天營收": float(last_30["營收"].sum()),
                "近30天銷售量": int(last_30["Units Sold"].sum()),
                "最新總庫存": int(latest["Inventory Level"].sum()),
                "缺貨風險SKU": int((latest["庫存狀態"] == "缺貨風險").sum()),
                "需補貨SKU": int((latest["建議補貨量"] > 0).sum()),
            }

            fig = plt.figure(figsize=(16, 9))
            fig.suptitle("庫存管理銷售系統儀表板", fontsize=22, weight="bold", y=0.965)

            cards = [
                ("門市數 / 商品數", f"{kpis['門市數']} / {kpis['商品數']}"),
                ("近30天營收", money(kpis["近30天營收"])),
                ("近30天銷售量", f"{kpis['近30天銷售量']:,}"),
                ("最新總庫存", f"{kpis['最新總庫存']:,}"),
                ("缺貨風險SKU", f"{kpis['缺貨風險SKU']:,}"),
                ("需補貨SKU", f"{kpis['需補貨SKU']:,}"),
            ]
            for i, (label, value) in enumerate(cards):
                ax = fig.add_axes([0.035 + i * 0.158, 0.80, 0.145, 0.115])
                ax.axis("off")
                ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, fill=False, linewidth=1.2))
                ax.text(0.05, 0.66, label, fontsize=10, color="#555555", transform=ax.transAxes)
                ax.text(0.05, 0.22, value, fontsize=16, weight="bold", transform=ax.transAxes)

            ax = fig.add_axes([0.06, 0.47, 0.40, 0.25])
            ax.plot(daily["Date"], daily["Units Sold"], linewidth=2)
            ax.set_title("近 90 天銷售趨勢", fontsize=12, weight="bold")
            ax.set_ylabel("銷售數量")
            ax.grid(True, alpha=0.25)
            ax.tick_params(axis="x", rotation=20, labelsize=8)

            ax = fig.add_axes([0.55, 0.47, 0.38, 0.25])
            if not status.empty:
                bottom = np.zeros(len(status))
                for col in status.columns:
                    ax.bar(status.index, status[col], bottom=bottom, label=col)
                    bottom += status[col].values
            ax.set_title("各品類最新庫存狀態", fontsize=12, weight="bold")
            ax.set_ylabel("SKU 數量")
            ax.legend(fontsize=8)
            ax.grid(True, axis="y", alpha=0.25)
            ax.tick_params(axis="x", rotation=15, labelsize=8)

            ax = fig.add_axes([0.06, 0.13, 0.40, 0.25])
            if not cat.empty:
                x = np.arange(len(cat))
                w = 0.38
                ax.bar(x - w / 2, cat["Inventory Level"], w, label="目前庫存")
                ax.bar(x + w / 2, cat["Demand Forecast"] * 7, w, label="7天需求預測")
                ax.set_xticks(x)
                ax.set_xticklabels(cat["Category"], rotation=15, fontsize=8)
            ax.set_title("目前庫存 vs 7天需求預測", fontsize=12, weight="bold")
            ax.legend(fontsize=8)
            ax.grid(True, axis="y", alpha=0.25)

            ax = fig.add_axes([0.55, 0.13, 0.38, 0.25])
            if not top.empty:
                ax.barh(top["門市 / 商品"][::-1], top["建議補貨量"][::-1])
            ax.set_title("Top 10 建議補貨清單", fontsize=12, weight="bold")
            ax.set_xlabel("建議補貨量")
            ax.grid(True, axis="x", alpha=0.25)
            ax.tick_params(axis="y", labelsize=8)

            fig.savefig(cloud_png, dpi=170, bbox_inches="tight")
            plt.close(fig)
            print(f"  ✅ CLOUD 儀表板: {cloud_png}")
        except Exception as e:
            print(f"  [WARN] 產生 CLOUD 儀表板失敗: {e}")

    # ---- HTML 報表 ----
    try:
        kpis = {
            "門市數": df["Store ID"].nunique(),
            "商品數": df["Product ID"].nunique(),
            "近30天營收": float(last_30["營收"].sum()),
            "近30天銷售量": int(last_30["Units Sold"].sum()),
            "最新總庫存": int(latest["Inventory Level"].sum()),
            "缺貨風險SKU": int((latest["庫存狀態"] == "缺貨風險").sum()),
            "需補貨SKU": int((latest["建議補貨量"] > 0).sum()),
        }

        store_summary = latest.groupby("Store ID").agg(
            產品數=("Product ID", "nunique"),
            總庫存=("Inventory Level", "sum"),
            缺貨風險=("庫存狀態", lambda x: (x == "缺貨風險").sum()),
            需補貨=("建議補貨量", lambda x: (x > 0).sum()),
        ).reset_index()

        worklist = latest.sort_values(["建議補貨量", "可支撐天數"], ascending=[False, True])
        worklist = worklist[["Store ID", "Product ID", "Category", "Region", "Inventory Level",
                             "Units Sold", "Demand Forecast", "Units Ordered", "可支撐天數",
                             "庫存狀態", "建議補貨量"]].head(15)
        worklist = worklist.rename(columns={
            "Store ID": "門市", "Product ID": "商品", "Category": "品類", "Region": "區域",
            "Inventory Level": "目前庫存", "Units Sold": "當日銷售量",
            "Demand Forecast": "需求預測", "Units Ordered": "已下單量",
        })

        kpi_html = f"""
        <h1>庫存管理銷售系統報表</h1>
        <p>📅 最新資料日期：{latest_date.date() if hasattr(latest_date, 'date') else latest_date}</p>
        <h2>📊 KPI 彙總</h2>
        <ul>
            <li>門市數：{kpis['門市數']}</li>
            <li>商品數：{kpis['商品數']}</li>
            <li>近30天營收：{money(kpis['近30天營收'])}</li>
            <li>近30天銷售量：{kpis['近30天銷售量']:,}</li>
            <li>最新總庫存：{kpis['最新總庫存']:,}</li>
            <li>缺貨風險SKU：{kpis['缺貨風險SKU']:,} ⚠️</li>
            <li>需補貨SKU：{kpis['需補貨SKU']:,}</li>
        </ul>
        """

        html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
    <meta charset="utf-8">
    <title>庫存管理銷售系統報表</title>
    <style>
        body {{
            font-family: "Microsoft JhengHei", "Noto Sans CJK TC", Arial, sans-serif;
            background: #f4f6f8; padding: 32px; color: #333; max-width: 1400px; margin: 0 auto;
        }}
        h1 {{ color: #1a237e; border-bottom: 3px solid #3949ab; padding-bottom: 10px; }}
        h2 {{ color: #283593; margin-top: 30px; }}
        img {{ max-width: 100%; border-radius: 10px; box-shadow: 0 4px 16px rgba(0,0,0,0.10); }}
        table {{
            width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px;
            overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin: 16px 0; font-size: 13px;
        }}
        th {{ background: #283593; color: #fff; padding: 10px 8px; text-align: left; font-weight: 500; }}
        td {{ padding: 8px; border-bottom: 1px solid #e0e0e0; }}
        tr:hover {{ background: #f5f5f5; }}
        ul {{ background: #fff; padding: 16px 32px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        li {{ padding: 4px 0; }}
    </style>
</head>
<body>
    {kpi_html}
    <h2>🏪 門市摘要</h2>
    {store_summary.to_html(index=False)}
    <h2>📈 儀表板</h2>
    <img src="inventory_sales_dashboard_zh.png" alt="庫存儀表板">
    <h2>📋 補貨工作清單（Top 15）</h2>
    {worklist.to_html(index=False)}
    <p style="text-align:center; color:#999; margin-top: 32px;">
        USI Smart Retail OS · 報表產生時間：{datetime.now().strftime("%Y-%m-%d %H:%M")}
    </p>
</body>
</html>"""

        with open(cloud_html, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ✅ CLOUD HTML: {cloud_html}")
    except Exception as e:
        print(f"  [WARN] 產生 CLOUD HTML 報表失敗: {e}")


if __name__ == "__main__":
    main()


