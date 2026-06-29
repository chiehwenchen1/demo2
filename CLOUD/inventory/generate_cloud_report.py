#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 4: generate_cloud_report.py
根據 cloud_inventory.db 資料產生報表
- 讀取 inventory_raw 表格
- 套用 inventory_sales_report_zh.py 的報表邏輯
- 輸出 HTML 報表 + 儀表板 PNG

用法:
  python generate_cloud_report.py                           # 使用 cloud_inventory.db
  python generate_cloud_report.py --csv retail_store_inventory.csv  # 使用 CSV
  python generate_cloud_report.py --out CLOUD/reports       # 指定輸出目錄
"""
import argparse
import csv
import io
import os
import sqlite3
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

# 修正 Windows cp950 無法處理 emoji 的問題
if sys.stdout.encoding and sys.stdout.encoding.upper() in ('CP950', 'BIG5', 'BIG5-HKSCS'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd

# 嘗試匯入 matplotlib
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager, rcParams
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("[WARN] matplotlib 未安裝，儀表板 PNG 將不會產生")

# 專案根目錄
PROJECT = Path("D:/bible/USI_SMART_RETAIL_OS")
CLOUD_DB = PROJECT / "CLOUD" / "database" / "cloud_inventory.db"
DEFAULT_OUT = PROJECT / "CLOUD" / "reports"

# 報表參數（與 inventory_sales_report_zh.py 一致）
OOS_DAYS = 3          # <= 3 天：缺貨風險
LOW_STOCK_DAYS = 7    # 3~7 天：低庫存
TARGET_STOCK_DAYS = 14 # 目標補貨天數

# 載入 SVM 產品名稱對照表
SKU_NAME_MAP = {}
sku_csv = PROJECT / "EDGE" / "Nantou Nangang_南投南崗店_南投南崗店" / "sku_v3.csv"
if sku_csv.exists():
    with open(str(sku_csv), encoding="utf-8-sig") as f:
        import csv
        for row in csv.DictReader(f):
            short = row.get("short_name", "").strip()
            ch = row.get("ch_name", "").strip()
            if short and ch:
                SKU_NAME_MAP[short] = ch
    print(f"  [SKU] 載入 {len(SKU_NAME_MAP)} 個產品中文名稱")

def get_product_name(category, product_id):
    """根據 category 或 product_id 回傳中文品名"""
    # 先從 category (short_name) 查
    name = SKU_NAME_MAP.get(category)
    if name:
        return name
    # 從 product_id 的最後部分查 (例如 "Nantou cola" → "cola")
    for short, ch in SKU_NAME_MAP.items():
        if short in product_id or short in category:
            return ch
    # 都找不到就用原始 product_id
    return product_id

def setup_chinese_font():
    """設定中文字型（與 inventory_sales_report_zh.py 一致）"""
    candidates = ["Noto Sans CJK TC", "Noto Sans CJK SC", "Noto Sans CJK JP",
                  "Microsoft JhengHei", "Microsoft YaHei", "WenQuanYi Zen Hei",
                  "SimHei", "Arial Unicode MS"]
    names = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in names:
            rcParams["font.family"] = name
            rcParams["axes.unicode_minus"] = False
            return name
    rcParams["axes.unicode_minus"] = False
    return "Default"

def money(x):
    """格式化金額"""
    return f"${x:,.0f}"

def load_data_from_db():
    """從 cloud_inventory.db 載入資料"""
    if not CLOUD_DB.exists():
        print(f"[ERROR] CLOUD DB 不存在: {CLOUD_DB}")
        print("  請先執行 sync_edge_to_cloud.py 同步資料")
        sys.exit(1)
    
    conn = sqlite3.connect(str(CLOUD_DB))
    try:
        df = pd.read_sql("SELECT * FROM inventory_raw", conn)
    except Exception as e:
        print(f"[ERROR] 讀取 inventory_raw 失敗: {e}")
        conn.close()
        sys.exit(1)
    conn.close()
    
    if df.empty:
        print("[ERROR] inventory_raw 為空，請先執行 sync_edge_to_cloud.py")
        sys.exit(1)
    
    # 重新命名欄位符合報表格式
    df = df.rename(columns={
        "store_id": "Store ID",
        "date": "Date",
        "product_id": "Product ID",
        "category": "Category",
        "region": "Region",
        "inventory_level": "Inventory Level",
        "units_sold": "Units Sold",
        "units_ordered": "Units Ordered",
        "demand_forecast": "Demand Forecast",
        "price": "Price",
        "discount": "Discount",
    })
    
    return df

def save_dashboard(df, latest, last_30, last_90, out_dir):
    """產生儀表板 PNG - 每個圖表獨立一張圖（不合成 2x2）"""
    if not HAS_MATPLOTLIB:
        return
    
    setup_chinese_font()
    
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
        top["門市 / 商品"] = top.apply(
            lambda r: r["Store ID"] + " / " + (
                SKU_NAME_MAP.get(str(r["Category"]).strip(), r["Product ID"])
            ), axis=1
        )
    
    # --- 圖1: 銷售趨勢 ---
    fig1, ax1 = plt.subplots(figsize=(12, 4))
    ax1.plot(daily["Date"], daily["Units Sold"], linewidth=2)
    ax1.set_title("近 90 天銷售趨勢", fontsize=14, weight="bold")
    ax1.set_ylabel("銷售數量")
    ax1.grid(True, alpha=0.25)
    ax1.tick_params(axis="x", rotation=20)
    fig1.tight_layout()
    fig1.savefig(str(out_dir / "chart_sales_trend.png"), dpi=150, bbox_inches="tight")
    plt.close(fig1)
    
    # --- 圖2: 庫存狀態 ---
    fig2, ax2 = plt.subplots(figsize=(12, 4))
    if not status.empty:
        bottom = np.zeros(len(status))
        for col in status.columns:
            ax2.bar(status.index, status[col], bottom=bottom, label=col)
            bottom += status[col].values
    ax2.set_title("各品類最新庫存狀態", fontsize=14, weight="bold")
    ax2.set_ylabel("SKU 數量")
    ax2.legend(fontsize=10)
    ax2.grid(True, axis="y", alpha=0.25)
    ax2.tick_params(axis="x", rotation=15)
    fig2.tight_layout()
    fig2.savefig(str(out_dir / "chart_stock_status.png"), dpi=150, bbox_inches="tight")
    plt.close(fig2)
    
    # --- 圖3: 庫存 vs 預測 ---
    fig3, ax3 = plt.subplots(figsize=(12, 4))
    if not cat.empty:
        x = np.arange(len(cat))
        w = 0.38
        ax3.bar(x - w / 2, cat["Inventory Level"], w, label="目前庫存")
        ax3.bar(x + w / 2, cat["Demand Forecast"] * 7, w, label="7天需求預測")
        ax3.set_xticks(x)
        ax3.set_xticklabels(cat["Category"], rotation=15, fontsize=9)
    ax3.set_title("目前庫存 vs 7天需求預測", fontsize=14, weight="bold")
    ax3.legend(fontsize=10)
    ax3.grid(True, axis="y", alpha=0.25)
    fig3.tight_layout()
    fig3.savefig(str(out_dir / "chart_inventory_vs_forecast.png"), dpi=150, bbox_inches="tight")
    plt.close(fig3)
    
    # --- 圖4: 建議補貨清單 ---
    fig4, ax4 = plt.subplots(figsize=(12, 4))
    if not top.empty:
        ax4.barh(top["門市 / 商品"][::-1], top["建議補貨量"][::-1])
    ax4.set_title("Top 10 建議補貨清單", fontsize=14, weight="bold")
    ax4.set_xlabel("建議補貨量")
    ax4.grid(True, axis="x", alpha=0.25)
    ax4.tick_params(axis="y", labelsize=9)
    fig4.tight_layout()
    fig4.savefig(str(out_dir / "chart_restock_list.png"), dpi=150, bbox_inches="tight")
    plt.close(fig4)
    
    print(f"  ✅ 4 張圖表已產生：chart_sales_trend.png, chart_stock_status.png, chart_inventory_vs_forecast.png, chart_restock_list.png")

def load_sku_name_map():
    """從 sku_v3.csv 載入 product_id → ch_name 對應表"""
    sku_path = PROJECT / "EDGE" / "Nantou Nangang_南投南崗店_南投南崗店" / "sku_v3.csv"
    if not sku_path.exists():
        print(f"  [WARN] sku_v3.csv 不存在: {sku_path}")
        return {}
    mapping = {}
    with open(str(sku_path), encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            product_id = row.get("product_id", "").strip()
            ch_name = row.get("ch_name", "").strip()
            if product_id and ch_name:
                mapping[product_id] = ch_name
    print(f"  [OK] 載入 {len(mapping)} 個商品名稱對應")
    return mapping


def generate_html_report(df, latest, last_30, out_dir):
    """產生 HTML 報表 — 使用 EDGE 報表風格（KPI 卡片、漸層 header、badge）"""
    # 載入 SKU 對應表，將 Product ID 換成中文品名
    sku_name_map = load_sku_name_map()
    
    kpis = {
        "門市數": df["Store ID"].nunique(),
        "商品數": df["Product ID"].nunique(),
        "近30天營收": float(last_30["營收"].sum()),
        "近30天銷售量": int(last_30["Units Sold"].sum()),
        "最新總庫存": int(latest["Inventory Level"].sum()),
        "缺貨風險SKU": int((latest["庫存狀態"] == "缺貨風險").sum()),
        "需補貨SKU": int((latest["建議補貨量"] > 0).sum()),
    }
    
    latest_date = df["Date"].max()
    
    # 補貨工作清單 — 將 Product ID 替換為中文品名
    worklist = latest.sort_values(["建議補貨量", "可支撐天數"], ascending=[False, True])
    worklist = worklist[["Store ID", "Product ID", "Category", "Region", "Inventory Level",
                         "Units Sold", "Demand Forecast", "Units Ordered", "可支撐天數",
                         "庫存狀態", "建議補貨量"]].head(15).copy()
    def lookup_name(row):
        cat = str(row["Category"]).strip()
        name = sku_name_map.get(cat)
        if name:
            return name
        pid = str(row["Product ID"]).strip().lower()
        for short, ch in sku_name_map.items():
            if short.lower() in pid or short.lower() in cat.lower():
                return ch
        return pid
    worklist["Product ID"] = worklist.apply(lookup_name, axis=1)
    worklist = worklist.rename(columns={
        "Store ID": "門市", "Product ID": "商品", "Category": "品類", "Region": "區域",
        "Inventory Level": "目前庫存", "Units Sold": "當日銷售量",
        "Demand Forecast": "需求預測", "Units Ordered": "已下單量"
    })
    
    # 門市摘要
    store_summary = latest.groupby("Store ID").agg(
        產品數=("Product ID", "nunique"),
        總庫存=("Inventory Level", "sum"),
        缺貨風險=("庫存狀態", lambda x: (x == "缺貨風險").sum()),
        需補貨=("建議補貨量", lambda x: (x > 0).sum()),
    ).reset_index()
    
    # 庫存狀態 badge helper
    def status_badge(status):
        if status == "缺貨風險":
            return '<span class="badge-oos">缺貨風險</span>'
        elif status == "低庫存":
            return '<span class="badge-low">低庫存</span>'
        else:
            return '<span class="badge-ok">正常</span>'
    
    # 各商品庫存一覽 (多門市合併)
    latest_inv = latest[["Store ID", "Category", "Inventory Level", "Demand Forecast", "可支撐天數", "庫存狀態"]].copy()
    latest_inv["庫存狀態標籤"] = latest_inv["庫存狀態"].apply(status_badge)
    latest_inv["庫存狀態標籤"] = latest_inv["庫存狀態"].apply(status_badge)
    # 中文品名
    def inv_name(cat):
        c = str(cat).strip()
        return sku_name_map.get(c, c)
    latest_inv["品名"] = latest_inv["Category"].apply(inv_name)
    latest_inv["可支撐天數顯示"] = latest_inv["可支撐天數"].apply(lambda x: f"{x:.1f}" if x < 999 else "充足")
    inv_rows = ""
    for _, r in latest_inv.iterrows():
        inv_rows += f"""        <tr>
            <td>{r['Store ID']}</td>
            <td>{r['品名']}</td>
            <td>{r['Category']}</td>
            <td style="text-align:right">{int(r['Inventory Level']):,}</td>
            <td style="text-align:right">{int(r['Demand Forecast']):,}</td>
            <td style="text-align:right">{r['可支撐天數顯示']}</td>
            <td>{r['庫存狀態標籤']}</td>
        </tr>
"""
    
    # 補貨工作清單 rows
    wl_rows = ""
    for _, r in worklist.iterrows():
        stock = int(r["目前庫存"])
        sold = int(r["當日銷售量"]) if pd.notna(r["當日銷售量"]) else 0
        demand = int(r["需求預測"]) if pd.notna(r["需求預測"]) else 0
        ordered = int(r["已下單量"]) if pd.notna(r["已下單量"]) else 0
        restock = int(r["建議補貨量"])
        wl_rows += f"""        <tr>
            <td>{r['門市']}</td>
            <td>{r['商品']}</td>
            <td>{r['品類']}</td>
            <td style="text-align:right">{stock:,}</td>
            <td style="text-align:right">{sold:,}</td>
            <td style="text-align:right">{restock:,}</td>
            <td>{status_badge(r.get('庫存狀態', '安全庫存'))}</td>
        </tr>
"""
    
    # 門市摘要 rows
    sm_rows = ""
    for _, r in store_summary.iterrows():
        sm_rows += f"""        <tr>
            <td>{r['Store ID']}</td>
            <td style="text-align:right">{int(r['產品數'])}</td>
            <td style="text-align:right">{int(r['總庫存']):,}</td>
            <td style="text-align:right">{int(r['缺貨風險'])}</td>
            <td style="text-align:right">{int(r['需補貨'])}</td>
        </tr>
"""
    
    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>CLOUD 庫存管理銷售報表</title>
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
.chart{{background:white;border-radius:14px;padding:14px;margin-bottom:16px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.chart img{{width:100%;display:block}}
.chart-title{{font-size:14px;font-weight:700;margin-bottom:8px;color:#0f172a}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.06);margin-bottom:16px}}
th{{background:#0f172a;color:white;padding:10px 12px;font-size:13px;text-align:left}}
td{{padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px}}
tr:nth-child(even) td{{background:#f8fafc}}
.badge-oos{{display:inline-block;padding:2px 8px;border-radius:20px;background:#fee2e2;color:#b91c1c;font-size:12px;font-weight:700}}
.badge-low{{background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:20px;font-size:12px;font-weight:700}}
.badge-ok{{background:#dcfce7;color:#166534;padding:2px 8px;border-radius:20px;font-size:12px;font-weight:700}}
.footer{{color:#64748b;font-size:12px;margin-top:28px;text-align:center}}
.scroll-table{{max-height:420px;overflow-y:auto;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.06)}}
.scroll-table table{{border-radius:0;box-shadow:none;margin-bottom:0}}
.scroll-table thead th{{position:sticky;top:0;z-index:1}}
</style>
</head>
<body>
<div class="header">
  <h1>📊 CLOUD 庫存管理銷售報表</h1>
  <p>最新資料：{latest_date.date() if hasattr(latest_date, 'date') else latest_date} | 系統產生時間：{datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
</div>
<div class="container">

<div class="section-title">📊 KPI 摘要</div>
<div class="kpi-grid">
  <div class="card blue"><div class="l">🏪 門市數</div><div class="v">{kpis['門市數']}</div></div>
  <div class="card blue"><div class="l">📦 商品數 (SKU)</div><div class="v">{kpis['商品數']}</div></div>
  <div class="card green"><div class="l">💰 近30天營收</div><div class="v">{money(kpis['近30天營收'])}</div></div>
  <div class="card green"><div class="l">📦 近30天銷售量</div><div class="v">{kpis['近30天銷售量']:,}</div></div>
  <div class="card blue"><div class="l">📦 最新總庫存</div><div class="v">{kpis['最新總庫存']:,}</div></div>
  <div class="card orange"><div class="l">⚠️ 需補貨 SKU</div><div class="v">{kpis['需補貨SKU']}</div></div>
  <div class="card red"><div class="l">❌ 缺貨風險 SKU</div><div class="v">{kpis['缺貨風險SKU']}</div></div>
  <div class="card green"><div class="l">✅ 安全庫存</div><div class="v">{kpis['商品數'] - kpis['缺貨風險SKU'] - kpis['需補貨SKU']}</div></div>
</div>

<div class="section-title">🏪 門市摘要</div>
<div class="scroll-table">
<table>
<thead><tr><th>門市</th><th>產品數</th><th>總庫存</th><th>缺貨風險</th><th>需補貨</th></tr></thead>
<tbody>
{sm_rows}</tbody>
</table>
</div>

<div class="section-title">📈 庫存儀表板</div>
<div class="chart"><div class="chart-title">近 90 天銷售趨勢</div><img src="chart_sales_trend.png" alt="銷售趨勢"></div>
<div class="chart"><div class="chart-title">各品類最新庫存狀態</div><img src="chart_stock_status.png" alt="庫存狀態"></div>
<div class="chart"><div class="chart-title">目前庫存 vs 7天需求預測</div><img src="chart_inventory_vs_forecast.png" alt="庫存 vs 預測"></div>
<div class="chart"><div class="chart-title">Top 10 建議補貨清單</div><img src="chart_restock_list.png" alt="建議補貨清單"></div>

<div class="section-title">📋 各門市商品庫存一覽</div>
<div class="scroll-table">
<table>
<thead><tr><th>門市</th><th>品名</th><th>類別</th><th>庫存</th><th>需求預測</th><th>可支撐天數</th><th>狀態</th></tr></thead>
<tbody>
{inv_rows}</tbody>
</table>
</div>

<div class="section-title">📋 建議補貨清單（Top 15）</div>
<div class="scroll-table">
<table>
<thead><tr><th>門市</th><th>商品</th><th>品類</th><th>目前庫存</th><th>當日銷售量</th><th>建議補貨量</th><th>狀態</th></tr></thead>
<tbody>
{wl_rows}</tbody>
</table>
</div>

<div class="footer">
  USI Smart Retail OS · CLOUD 端報表
</div>
</div>
</body>
</html>"""
    
    html_path = out_dir / "inventory_sales_report_zh.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  ✅ HTML: {html_path}")

def main():
    parser = argparse.ArgumentParser(description="CLOUD 庫存報表產生器")
    parser.add_argument("--csv", help="直接使用 CSV 檔案路徑（取代 DB 讀取）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="輸出目錄")
    args = parser.parse_args()
    
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("USI Smart Retail OS — CLOUD 庫存報表產生器")
    print("=" * 60)
    
    # 載入資料
    if args.csv:
        print(f"\n📂 讀取 CSV: {args.csv}")
        df = pd.read_csv(args.csv)
    else:
        print(f"\n🗄️ 讀取 CLOUD DB: {CLOUD_DB}")
        df = load_data_from_db()
    
    print(f"   記錄數: {len(df):,}")
    print(f"   門市數: {df['Store ID'].nunique()}")
    print(f"   產品數: {df['Product ID'].nunique()}")
    
    # 日期處理
    df["Date"] = pd.to_datetime(df["Date"])
    
    # 計算營收
    df["折扣後售價"] = df["Price"] * (1 - df["Discount"] / 100)
    df["營收"] = df["Units Sold"] * df["折扣後售價"]
    
    latest_date = df["Date"].max()
    latest = df[df["Date"] == latest_date].copy()
    
    # 計算庫存指標
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
    
    print(f"\n   最新日期: {latest_date.date()}")
    print(f"   近30天記錄: {len(last_30):,}")
    print(f"   近90天記錄: {len(last_90):,}")
    
    # 產生報表
    print(f"\n📊 產生報表至: {out_dir}")
    generate_html_report(df, latest, last_30, out_dir)
    save_dashboard(df, latest, last_30, last_90, out_dir)
    
    print(f"\n{'='*60}")
    print(f"✅ 報表產生完成！")
    print(f"   HTML: {out_dir / 'inventory_sales_report_zh.html'}")
    print(f"   PNG:  {out_dir / 'inventory_sales_dashboard_zh.png'}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
