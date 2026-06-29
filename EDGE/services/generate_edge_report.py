#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - EDGE Store Report Generator
Reads each store's EDGE_DB.db and produces HTML+PNG inventory reports.
Output: EDGE/<store_folder>/reports/
"""

import sqlite3, base64, json
from io import BytesIO
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

OOS_DAYS = 3          # ≤ 3 天：缺貨風險
LOW_STOCK_DAYS = 7    # 3~7 天：低庫存
TARGET_STOCK_DAYS = 14

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')

STORE_FOLDERS = [
    ("Taipei Zhongxiao", PROJECT / 'EDGE/Taipei Zhongxiao_台北忠孝店_台北忠孝店',
     {"zh":"台北忠孝店","en":"Taipei Zhongxiao Store","ja":"台北忠孝店","region":"North"}),
    ("Osaka Shinsaibashi", PROJECT / 'EDGE/Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店',
     {"zh":"大阪心齋橋店","en":"Osaka Shinsaibashi Store","ja":"大阪心斎橋店","region":"Kansai"}),
]

def setup_font():
    for name in ["Noto Sans CJK TC","Microsoft JhengHei","SimHei","Arial Unicode MS"]:
        if name in {f.name for f in font_manager.fontManager.ttflist}:
            rcParams["font.family"] = name; rcParams["axes.unicode_minus"] = False; return
    rcParams["axes.unicode_minus"] = False

def money(x): return f"NT${x:,.0f}"

def fig_to_b64(fig):
    buf = BytesIO(); fig.savefig(buf,format="png",dpi=140,bbox_inches="tight"); buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode(); plt.close(fig); return b64

def generate_store_report(sid, store_path, info):
    db_path = store_path / 'EDGE_DB.db'
    reports_dir = store_path / 'reports'
    reports_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  EDGE: {sid} — {info['zh']} / {info['en']} / {info['ja']}")
    print(f"{'='*60}")

    if not db_path.exists():
        print(f"  [MISS] EDGE_DB.db not found")
        return

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # ── Load enhanced_inventory ──
    cur.execute("""
        SELECT product_id, product_name, category, stock_quantity,
               unit_price, retail_price, max_capacity, reorder_level,
               shelf_position, supplier_id, last_restock
        FROM enhanced_inventory ORDER BY category, product_name
    """)
    rows = cur.fetchall()
    if not rows:
        print(f"  [SKIP] No data")
        conn.close(); return

    # ── Build DataFrame ──
    records = []
    for r in rows:
        stock = r[3]
        max_cap = r[6] or 100
        pct = stock / max_cap if max_cap > 0 else 0
        reorder = r[7] or int(max_cap * 0.2)
        if stock <= 0: status = "OUT_OF_STOCK"
        elif stock <= reorder: status = "LOW_STOCK"
        else: status = "IN_STOCK"
        records.append({
            "product_id": r[0], "product_name": r[1], "category": r[2],
            "stock": stock, "unit_price": r[4] or 0, "retail_price": r[5] or 0,
            "max_capacity": max_cap, "reorder_level": reorder,
            "stock_pct": round(pct*100, 1), "status": status,
            "shelf": r[8] or "", "supplier": r[9] or "", "last_restock": r[10] or "",
            "value": stock * (r[5] or 0),
        })

    df = pd.DataFrame(records)
    total_items = len(df)
    total_stock = int(df['stock'].sum())
    total_value = float(df['value'].sum())

    oos_count = len(df[df['status']=='OUT_OF_STOCK'])
    low_count = len(df[df['status']=='LOW_STOCK'])
    in_count = len(df[df['status']=='IN_STOCK'])
    unique_cats = df['category'].nunique()

    # ── Chart 1: Stock health by category ──
    status_by_cat = df.groupby(['category','status']).size().unstack(fill_value=0)
    for c in ['OUT_OF_STOCK','LOW_STOCK','IN_STOCK']:
        if c not in status_by_cat.columns: status_by_cat[c] = 0
    status_by_cat = status_by_cat[['OUT_OF_STOCK','LOW_STOCK','IN_STOCK']]

    fig, ax = plt.subplots(figsize=(8.6, 3.5))
    if not status_by_cat.empty:
        bottom = np.zeros(len(status_by_cat))
        colors = {"OUT_OF_STOCK":"#f44336","LOW_STOCK":"#ff9800","IN_STOCK":"#4caf50"}
        labels = {"OUT_OF_STOCK":"缺貨","LOW_STOCK":"低庫存","IN_STOCK":"正常"}
        for cn in status_by_cat.columns:
            ax.bar(status_by_cat.index, status_by_cat[cn], bottom=bottom, label=labels.get(cn,cn), color=colors.get(cn))
            bottom += status_by_cat[cn].values
    ax.set_title(f"{info['zh']} - 庫存狀態 by 品類", fontsize=13, weight="bold")
    ax.set_ylabel("SKU 數"); ax.legend(fontsize=9); ax.grid(True,axis="y",alpha=.25)
    ax.tick_params(axis="x", rotation=20)
    fig1_b64 = fig_to_b64(fig)

    # ── Chart 2: Top 10 by stock value ──
    top10 = df.sort_values('value', ascending=False).head(10)
    fig, ax = plt.subplots(figsize=(8.6, 3.5))
    if not top10.empty:
        labels = [f"{r['product_name'][:15]} ({r['shelf']})" for _, r in top10.iterrows()]
        ax.barh(labels[::-1], top10['value'][::-1] / 10000, color="#2196F3")
    ax.set_title(f"{info['zh']} - Top 10 庫存價值 (萬元)", fontsize=13, weight="bold")
    ax.set_xlabel("NT$ 萬"); ax.grid(True,axis="x",alpha=.25)
    fig2_b64 = fig_to_b64(fig)

    # ── Chart 3: Stock distribution (pie) ──
    fig, ax = plt.subplots(figsize=(6, 5))
    sizes = [in_count, low_count, oos_count]
    if sum(sizes) > 0:
        colors3 = ["#4caf50","#ff9800","#f44336"]
        labels3 = [f"正常 ({in_count})", f"低庫存 ({low_count})", f"缺貨 ({oos_count})"]
        ax.pie([x for x in sizes if x>0], labels=[l for x,l in zip(sizes,labels3) if x>0],
               autopct="%1.1f%%", startangle=90, colors=[c for c,s in zip(colors3,sizes) if s>0])
    ax.set_title(f"{info['zh']} - 庫存健康度", fontsize=13, weight="bold")
    fig3_b64 = fig_to_b64(fig)

    # ── Chart 4: Category stock total ──
    cat_totals = df.groupby('category')['stock'].sum().sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(8.6, 3.5))
    if not cat_totals.empty:
        ax.bar(cat_totals.index, cat_totals.values, color="#1565C0")
    ax.set_title(f"{info['zh']} - 各品類庫存總量", fontsize=13, weight="bold")
    ax.set_ylabel("庫存數量"); ax.grid(True,axis="y",alpha=.25)
    ax.tick_params(axis="x", rotation=20)
    fig4_b64 = fig_to_b64(fig)

    # ── Build HTML ──
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Top 15 table rows
    table_rows = ""
    for _, r in df.sort_values('value', ascending=False).head(15).iterrows():
        badge = ""
        if r['status'] == 'OUT_OF_STOCK': badge = '<span class="badge-oos">缺貨</span>'
        elif r['status'] == 'LOW_STOCK': badge = '<span class="badge-low">低庫存</span>'
        else: badge = '<span class="badge-ok">正常</span>'
        table_rows += f"""<tr>
            <td>{r['product_id']}</td>
            <td>{r['product_name']}</td>
            <td>{r['category']}</td>
            <td>{r['stock']:,}</td>
            <td>NT${r['retail_price']:,.0f}</td>
            <td>{r['shelf']}</td>
            <td>{badge}</td>
            <td><strong>NT${r['value']:,.0f}</strong></td>
        </tr>\n"""

    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>{info['zh']} - EDGE 庫存報表</title>
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
</style>
</head>
<body>
<div class="header">
  <h1>🏪 EDGE 庫存管理報表 — {info['zh']}</h1>
  <p>{info['en']} / {info['ja']} | 區域: {info['region']} | 報表時間: {now_str}</p>
</div>
<div class="container">

<div class="section-title">📊 KPI 摘要</div>
<div class="kpi-grid">
  <div class="card blue"><div class="l">產品數 (SKU)</div><div class="v">{total_items}</div></div>
  <div class="card green"><div class="l">總庫存量</div><div class="v">{total_stock:,}</div></div>
  <div class="card"><div class="l">總庫存價值</div><div class="v">{money(total_value)}</div></div>
  <div class="card orange"><div class="l">品類數</div><div class="v">{unique_cats}</div></div>
  <div class="card green"><div class="l">✅ 正常庫存</div><div class="v">{in_count}</div></div>
  <div class="card" style="border:2px solid #ff9800"><div class="l">⚠️ 低庫存</div><div class="v">{low_count}</div></div>
  <div class="card red"><div class="l">❌ 缺貨</div><div class="v">{oos_count}</div></div>
  <div class="card blue"><div class="l">品類</div><div class="v" style="font-size:18px">{', '.join(cat_totals.index.tolist())}</div></div>
</div>

<div class="section-title">📈 儀表板圖表</div>
<div class="grid-2">
  <div class="chart"><img src="data:image/png;base64,{fig1_b64}"></div>
  <div class="chart"><img src="data:image/png;base64,{fig2_b64}"></div>
  <div class="chart"><img src="data:image/png;base64,{fig3_b64}"></div>
  <div class="chart"><img src="data:image/png;base64,{fig4_b64}"></div>
</div>

<div class="section-title">🏷️ 庫存詳情 (Top 15 by 價值)</div>
<table>
  <thead><tr><th>Product ID</th><th>名稱</th><th>品類</th><th>庫存</th><th>單價</th><th>貨架</th><th>狀態</th><th>價值</th></tr></thead>
  <tbody>{table_rows}</tbody>
</table>

<div class="section-title">💡 系統說明</div>
<div class="insight">
  EDGE 端庫存管理報表：從 Smart Shelf 原始資料 (read-only) 透過 db_transformer 轉換成 EDGE_DB.db，<br>
  合併價格、庫存、供應商資訊。提供單店精準的庫存健康度分析與補貨建議。
  當庫存量 ≤ 再訂購點 (Reorder Level) 時標記為低庫存，≤ 0 時為缺貨。
</div>
<div class="footer">
  USI Smart Retail OS — EDGE {sid} | Generated {now_str} | 原始資料唯讀保護
</div>
</div>
</body>
</html>"""

    html_path = reports_dir / f"edge_report_{sid}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"  [HTML] {html_path}")

    # ── Dashboard PNG ──
    fig = plt.figure(figsize=(16, 9))
    fig.suptitle(f"EDGE 庫存管理儀表板 — {info['zh']}", fontsize=22, weight="bold", y=0.97)

    kpi_items = [
        ("SKU", f"{total_items}"), ("庫存量", f"{total_stock:,}"),
        ("總價值", money(total_value)), ("正常", f"{in_count}"),
        ("低庫存", f"{low_count}"), ("缺貨", f"{oos_count}"),
    ]
    for i, (lbl, val) in enumerate(kpi_items):
        ax = fig.add_axes([0.035+i*0.158, 0.815, 0.145, 0.095])
        ax.axis("off")
        ax.add_patch(plt.Rectangle((0,0),1,1,transform=ax.transAxes,fill=False,linewidth=1.2))
        ax.text(0.05, 0.6, lbl, fontsize=10, color="#555", transform=ax.transAxes)
        ax.text(0.05, 0.2, val, fontsize=14, weight="bold", transform=ax.transAxes)

    # Chart areas (4 charts on 2x2 grid)
    for chart_idx, (title, b64_img, y_start) in enumerate([
        (f"{info['zh']} 庫存狀態 by 品類", fig1_b64, 0.55),
        (f"Top 10 庫存價值 (萬元)", fig2_b64, 0.55),
        ("庫存健康度", fig3_b64, 0.22),
        ("各品類庫存總量", fig4_b64, 0.22),
    ]):
        if chart_idx % 2 == 0: x = 0.06
        else: x = 0.52
        ax = fig.add_axes([x, y_start, 0.42, 0.24])
        ax.imshow(plt.imread(BytesIO(base64.b64decode(b64_img))))
        ax.axis("off")
        ax.set_title(title, fontsize=11, weight="bold")

    png_path = reports_dir / f"edge_dashboard_{sid}.png"
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [PNG]  {png_path}")

    conn.close()
    print(f"  [OK] Report generated for {sid}")

def main():
    setup_font()
    print("="*60)
    print("  USI SMART RETAIL OS — EDGE REPORT GENERATOR")
    print()

    for sid, store_path, info in STORE_FOLDERS:
        generate_store_report(sid, store_path, info)

    print(f"\n{'='*60}")
    print("  All EDGE reports generated!")
    print("  Dashboard: http://127.0.0.1:5022")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
