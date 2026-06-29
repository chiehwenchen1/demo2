#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS – CLOUD Web Dashboard
Flask web app serving inventory reports from consolidated CSV + EDGE stores.
Tabs: Overview, Per-Store Detail, Replenishment Worklist
Runs on port 5022
"""

import sqlite3, sys, base64
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
from flask import Flask, render_template_string, jsonify

# ── Config ──
PROJECT = Path("D:/bible/USI_SMART_RETAIL_OS")
CLOUD_CSV = PROJECT / "CLOUD" / "inventory" / "cloud_consolidated.csv"
TEMPLATE_PATH = PROJECT / "CLOUD" / "web" / "template.html"
OOS_DAYS = 3; LOW_STOCK_DAYS = 7; TARGET_STOCK_DAYS = 14

STORE_NAMES = {
    "Shibuya":       {"zh":"澀谷店",   "ja":"渋谷店",   "en":"Shibuya Store",       "region":"Kanto"},
    "Ginza":         {"zh":"銀座店",   "ja":"銀座店",   "en":"Ginza Store",         "region":"Kanto"},
    "Shinjuku":      {"zh":"新宿店",   "ja":"新宿店",   "en":"Shinjuku Store",      "region":"Kanto"},
    "Ueno":          {"zh":"上野店",   "ja":"上野店",   "en":"Ueno Store",          "region":"Kanto"},
    "Ikebukuro":     {"zh":"池袋店",   "ja":"池袋店",   "en":"Ikebukuro Store",     "region":"Kanto"},
    "Taipei Zhongxiao":  {"zh":"台北忠孝店","ja":"台北忠孝店","en":"Taipei Zhongxiao Store","region":"North"},
    "Osaka Shinsaibashi":{"zh":"大阪心齋橋店","ja":"大阪心斎橋店","en":"Osaka Shinsaibashi Store","region":"Kansai"},
    "Nantou Nangang":    {"zh":"南投南崗店",  "ja":"南投南崗店",  "en":"Nantou Nangang Store",  "region":"Central"},
}

CSV_5 = {"Shibuya","Ginza","Shinjuku","Ueno","Ikebukuro"}
EDGE_2 = {"Taipei Zhongxiao","Osaka Shinsaibashi","Nantou Nangang"}

app = Flask(__name__)

# ── Matplotlib ──
def setup_font():
    for name in ["Noto Sans CJK TC","Microsoft JhengHei","SimHei","Arial Unicode MS"]:
        if name in {f.name for f in font_manager.fontManager.ttflist}:
            rcParams["font.family"] = name; rcParams["axes.unicode_minus"] = False; return
    rcParams["axes.unicode_minus"] = False
setup_font()

def money(x): return f"NT${x:,.0f}"

def fig_b64(fig):
    buf = BytesIO(); fig.savefig(buf,format="png",dpi=120,bbox_inches="tight"); buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode(); plt.close(fig); return b64

# ── Column Normalizer ──
COL_MAP = {
    "store_id":"Store_ID","date":"Date","product_id":"Product_ID",
    "category":"Category","region":"Region","inventory_level":"Inventory_Level",
    "units_sold":"Units_Sold","units_ordered":"Units_Ordered",
    "demand_forecast":"Demand_Forecast","price":"Price","discount":"Discount",
}

def norm_cols(df):
    rename = {}
    for c in df.columns:
        cn = c.strip().lower()
        if cn in COL_MAP: rename[c] = COL_MAP[cn]
    return df.rename(columns=rename)

# ── Load Data ──
def load_all_data():
    """Load data. Returns (csv_hist, edge_snap) where csv_hist has full time
    series for all stores but edge stores only have synthetic todays."""
    if not CLOUD_CSV.exists():
        print("[ERROR] CSV not found")
        return None, None

    df = norm_cols(pd.read_csv(CLOUD_CSV))
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df["Store_ID"] = df["Store_ID"].astype(str)
    df["Price"] = df["Price"].fillna(0).astype(float)
    df["Discount"] = df["Discount"].fillna(0).astype(float)
    df["Discount_Price"] = df["Price"] * (1 - df["Discount"] / 100)
    df["Revenue"] = df["Units_Sold"] * df["Discount_Price"]

    # Split into CSV stores (historical) and EDGE stores (synthetic)
    hist = df[df["Store_ID"].isin(CSV_5)].copy()
    edge = df[df["Store_ID"].isin(EDGE_2)].copy()

    print(f"  CSV stores: {len(hist)} rows ({hist['Store_ID'].nunique()} stores), dates {hist['Date'].min()}..{hist['Date'].max()}")
    print(f"  EDGE stores: {len(edge)} rows ({edge['Store_ID'].nunique()} stores), dates {edge['Date'].min()}..{edge['Date'].max()}")
    return hist, edge

def compute_snapshot(hist, edge):
    """Compute latest-status snapshot from each source and merge."""
    snaps = []

    # Historical CSV stores: use their own latest date
    if hist is not None and not hist.empty:
        ld = hist["Date"].max()
        snap = hist[hist["Date"] == ld].copy()
        snaps.append(snap)
        print(f"  CSV snap: {len(snap)} SKUs @ {ld}")

    # EDGE stores: use their latest date (today)
    if edge is not None and not edge.empty:
        ld = edge["Date"].max()
        snap = edge[edge["Date"] == ld].copy()
        snaps.append(snap)
        print(f"  EDGE snap: {len(snap)} SKUs @ {ld}")

    # Nantou Nangang: check if there's direct EDGE data to add
    nantou_today = load_nantou_edge_snapshot()
    if nantou_today is not None and not nantou_today.empty:
        snaps.append(nantou_today)
        print(f"  Nantou EDGE snap: {len(nantou_today)} SKUs")

    if not snaps:
        return pd.DataFrame()

    latest = pd.concat(snaps, ignore_index=True)
    latest["SustainDays"] = (latest["Inventory_Level"] / latest["Demand_Forecast"].replace(0,np.nan))\
        .replace([np.inf,-np.inf],np.nan).fillna(999)
    latest["Target14"] = latest["Demand_Forecast"] * TARGET_STOCK_DAYS
    latest["ReplenishQty"] = (latest["Target14"] - latest["Inventory_Level"] - latest["Units_Ordered"])\
        .clip(lower=0).round().astype(int)
    latest["Status"] = np.select(
        [latest["SustainDays"]<=OOS_DAYS, (latest["SustainDays"]>OOS_DAYS)&(latest["SustainDays"]<=LOW_STOCK_DAYS)],
        ["OOS","LOW"], default="OK")
    return latest

# ── Charts ──
def make_charts(latest, hist_last_90):
    C = {}
    # 1. Sales trend
    if hist_last_90 is not None and not hist_last_90.empty:
        daily = hist_last_90.groupby("Date",as_index=False).agg(S=("Units_Sold","sum"),R=("Revenue","sum")).sort_values("Date")
        f,ax = plt.subplots(figsize=(8,3.5))
        ax.fill_between(daily["Date"],daily["S"],alpha=.15,color="#2196F3")
        ax.plot(daily["Date"],daily["S"],linewidth=2,color="#1565C0")
        ax.set_title("Sales Trend (90d)",fontsize=14,weight="bold"); ax.set_ylabel("Units")
        ax.grid(True,alpha=.2); ax.tick_params(axis="x",rotation=25,labelsize=8)
        C["sales_trend"] = fig_b64(f)

        f,ax = plt.subplots(figsize=(8,3.5))
        ax.fill_between(daily["Date"],daily["R"]/10000,alpha=.15,color="#4CAF50")
        ax.plot(daily["Date"],daily["R"]/10000,linewidth=2,color="#2E7D32")
        ax.set_title("Revenue Trend (90d, NT$10k)",fontsize=14,weight="bold"); ax.set_ylabel("NT$10k")
        ax.grid(True,alpha=.2); ax.tick_params(axis="x",rotation=25,labelsize=8)
        C["revenue_trend"] = fig_b64(f)

    # 3. Stock health
    cs = latest.groupby(["Category","Status"]).size().unstack(fill_value=0)
    for c in ["OOS","LOW","OK"]:
        if c not in cs.columns: cs[c]=0
    f,ax = plt.subplots(figsize=(8,3.5))
    if not cs.empty:
        bot = np.zeros(len(cs)); cols={"OOS":"#f44336","LOW":"#ff9800","OK":"#4caf50"}
        for cn in ["OOS","LOW","OK"]:
            val = cs[cn] if cn in cs.columns else [0]
            ax.bar(cs.index,val,bottom=bot,label=cn,color=cols[cn])
            bot += val.values if hasattr(val,'values') else val
    ax.set_title("Stock Health by Category",fontsize=14,weight="bold"); ax.set_ylabel("SKU")
    ax.legend(fontsize=9); ax.grid(True,axis="y",alpha=.2); ax.tick_params(axis="x",rotation=15)
    C["stock_status"] = fig_b64(f)

    # 4. Inv vs demand
    ct = latest.groupby("Category",as_index=False).agg(Iv=("Inventory_Level","sum"),Dm=("Demand_Forecast","sum")).sort_values("Iv",ascending=False)
    f,ax = plt.subplots(figsize=(8,3.5))
    if not ct.empty:
        x=np.arange(len(ct)); w=.35
        ax.bar(x-w/2,ct["Iv"],w,label="Inventory",color="#2196F3")
        ax.bar(x+w/2,ct["Dm"]*7,w,label="7d Demand",color="#FF9800")
        ax.set_xticks(x); ax.set_xticklabels(ct["Category"],rotation=15)
    ax.set_title("Inventory vs 7d Demand",fontsize=14,weight="bold"); ax.legend(fontsize=9); ax.grid(True,axis="y",alpha=.2)
    C["inv_vs_demand"] = fig_b64(f)

    # 5. Top replenish
    tp = latest.sort_values("ReplenishQty",ascending=False).head(10).copy()
    if not tp.empty:
        tp["Label"] = tp["Store_ID"] + " / " + tp["Product_ID"]
        f,ax = plt.subplots(figsize=(8,3.5))
        ax.barh(tp["Label"][::-1],tp["ReplenishQty"][::-1],color="#FF5722")
        ax.set_title("Top 10 Replenishment",fontsize=14,weight="bold"); ax.set_xlabel("Qty")
        ax.grid(True,axis="x",alpha=.2); ax.tick_params(axis="y",labelsize=8)
        C["top_replenish"] = fig_b64(f)

    # 6. Store pie
    si = latest.groupby("Store_ID",as_index=False).agg(T=("Inventory_Level","sum"))
    f,ax = plt.subplots(figsize=(7,4))
    if not si.empty:
        lbls = [STORE_NAMES.get(s,{}).get("zh",s) for s in si["Store_ID"]]
        ax.pie(si["T"],labels=lbls,autopct="%1.1f%%",startangle=90,pctdistance=.75,
               colors=["#2196F3","#4CAF50","#FF9800","#9C27B0","#F44336","#00BCD4","#795548"])
    ax.set_title("Store Inventory Share",fontsize=14,weight="bold")
    C["store_pie"] = fig_b64(f)
    return C

def load_nantou_edge_snapshot():
    """Load Nantou Nangang EDGE data directly from its DB."""
    import sqlite3
    nantou_db = PROJECT / "EDGE" / "Nantou Nangang_南投南崗店_南投南崗店" / "EDGE_DB.db"
    if not nantou_db.exists():
        return None
    try:
        conn = sqlite3.connect(str(nantou_db))
        df = pd.read_sql_query(
            "SELECT product_id, product_name, category, stock_quantity, retail_price, max_capacity FROM enhanced_inventory",
            conn
        )
        conn.close()
        if df.empty:
            return None
        df["Store_ID"] = "Nantou Nangang"
        df["Date"] = datetime.now().strftime("%Y-%m-%d")
        df.rename(columns={
            "product_id": "Product_ID",
            "stock_quantity": "Inventory_Level",
            "retail_price": "Price",
        }, inplace=True)
        df["Category"] = df["category"]
        df["Region"] = "Central"
        df["Units_Sold"] = 0
        df["Units_Ordered"] = 0
        df["Demand_Forecast"] = df["Inventory_Level"] * 0.1
        df["Discount"] = 0
        df["Discount_Price"] = df["Price"]
        df["Revenue"] = 0
        print(f"  Nantou EDGE direct: {len(df)} products, cols={list(df.columns)}")
        return df
    except Exception as e:
        print(f"  Nantou EDGE load error: {e}")
        return None

def store_pie_chart(latest, sid):
    sdf = latest[latest["Store_ID"]==sid]
    if sdf.empty: return ""
    sc = sdf["Status"].value_counts()
    f,ax = plt.subplots(figsize=(5,3.5))
    cm = {"OOS":"#f44336","LOW":"#ff9800","OK":"#4caf50"}
    ax.pie(sc.values,labels=sc.index,autopct="%1.1f%%",startangle=90,colors=[cm.get(s,"#999") for s in sc.index])
    ax.set_title(f"Health - {STORE_NAMES.get(sid,{}).get('zh',sid)}",fontsize=12,weight="bold")
    return fig_b64(f)

# ── Routes ──
def get_template():
    if TEMPLATE_PATH.exists(): return TEMPLATE_PATH.read_text(encoding="utf-8")
    return "<h1>Template missing</h1>"

@app.route("/")
def dashboard():
    hist, edge = load_all_data()
    if hist is None:
        return "<h1>No data found</h1>"

    latest = compute_snapshot(hist, edge)
    if latest.empty:
        return "<h1>No products in snapshot</h1>"

    # Compute last-30/last-90 from CSV historical data only
    csv_ld = hist["Date"].max()
    hist_last_30 = hist[hist["Date"] >= csv_ld - timedelta(30)]
    hist_last_90 = hist[hist["Date"] >= csv_ld - timedelta(90)]

    kpis = {
        "store_count": int(latest["Store_ID"].nunique()),
        "sku_count": len(latest),
        "revenue_30d": float(hist_last_30["Revenue"].sum()),
        "sales_30d": int(hist_last_30["Units_Sold"].sum()),
        "total_inv": int(latest["Inventory_Level"].sum()),
        "oos_sku": int((latest["Status"]=="OOS").sum()),
        "need_repl": int((latest["ReplenishQty"]>0).sum()),
    }

    charts = make_charts(latest, hist_last_90)

    all_stores = sorted(latest["Store_ID"].unique())
    stores = []
    store_details = []
    for sid in all_stores:
        sdf = latest[latest["Store_ID"]==sid]
        info = STORE_NAMES.get(sid, {"zh":sid,"ja":sid,"en":sid,"region":"?"})
        oos = int((sdf["Status"]=="OOS").sum())
        low = int((sdf["Status"]=="LOW").sum())
        ok = int((sdf["Status"]=="OK").sum())
        repl = int((sdf["ReplenishQty"]>0).sum())
        inv_total = int(sdf["Inventory_Level"].sum())
        stores.append({"id":sid,"zh":info["zh"],"ja":info["ja"],"region":info["region"],
                       "sku":len(sdf),"inv":inv_total,"oos":oos,"repl":repl})
        store_details.append({"id":sid,"zh":info["zh"],"ja":info["ja"],"region":info["region"],
                              "sku":len(sdf),"inv":inv_total,"oos":oos,"low":low,"ok":ok,"repl":repl,
                              "pie":store_pie_chart(latest,sid)})

    wl = latest.sort_values(["ReplenishQty","SustainDays"],ascending=[False,True]).head(50)
    worklist = [{"store_id":r["Store_ID"],"product_id":r["Product_ID"],"category":r["Category"],
                 "inv":int(r["Inventory_Level"]),"demand":float(r["Demand_Forecast"]),
                 "ordered":int(r["Units_Ordered"]),"days":float(r["SustainDays"]),
                 "status":r["Status"],"replenish":int(r["ReplenishQty"])}
                for _,r in wl.iterrows()]

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    return render_template_string(get_template(),
        kpis=kpis, charts=charts, stores=stores, store_details=store_details,
        worklist=worklist, now_str=now_str, money_fmt=money,
        store_zh=lambda x: STORE_NAMES.get(x,{}).get("zh",x))

@app.route("/api/health")
def health():
    return jsonify({"status":"ok","timestamp":datetime.now().isoformat(),"stores":list(STORE_NAMES.keys())})

if __name__ == "__main__":
    print("="*60)
    print("USI Smart Retail OS - CLOUD Web Dashboard")
    print("Port 5022")
    print("="*60)
    app.run(host="0.0.0.0", port=5022, debug=False)
