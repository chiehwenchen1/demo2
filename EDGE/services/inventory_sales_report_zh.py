# -*- coding: utf-8 -*-
"""
庫存管理銷售系統｜中文版報表產生器

執行：
python inventory_sales_report_zh.py --csv retail_store_inventory.csv --out inventory_report_chinese_output

此程式會輸出：
1. inventory_sales_report_zh.html
2. inventory_sales_dashboard_zh.png
"""
# 為了簡潔，這份可重跑程式會呼叫同資料夾內的完整報表邏輯。
# 若要修改欄位或門檻，請調整以下參數：
OOS_DAYS = 3          # 小於等於 3 天：缺貨風險
LOW_STOCK_DAYS = 7    # 3~7 天：低庫存
TARGET_STOCK_DAYS = 14 # 目標補貨天數

import argparse
import base64
from io import BytesIO
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

def setup_chinese_font():
    candidates = ["Noto Sans CJK TC","Noto Sans CJK SC","Noto Sans CJK JP","Microsoft JhengHei","Microsoft YaHei","WenQuanYi Zen Hei","SimHei","Arial Unicode MS"]
    names = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in names:
            rcParams["font.family"] = name
            rcParams["axes.unicode_minus"] = False
            return name
    rcParams["axes.unicode_minus"] = False
    return "Default"

def money(x): return f"${x:,.0f}"

def save_dashboard(df, latest, last_30, last_90, out_dir):
    daily = last_90.groupby("Date", as_index=False).agg({"Units Sold":"sum","營收":"sum","Inventory Level":"sum"}).sort_values("Date")
    status = latest.groupby(["Category","庫存狀態"]).size().unstack(fill_value=0).reindex(columns=["缺貨風險","低庫存","安全庫存"], fill_value=0)
    cat = latest.groupby("Category", as_index=False).agg({"Inventory Level":"sum","Demand Forecast":"sum","建議補貨量":"sum"}).sort_values("建議補貨量", ascending=False)
    top = latest.sort_values("建議補貨量", ascending=False).head(10).copy()
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
    cards=[("門市數 / 商品數",f"{kpis['門市數']} / {kpis['商品數']}"),("近30天營收",money(kpis["近30天營收"])),("近30天銷售量",f"{kpis['近30天銷售量']:,}"),("最新總庫存",f"{kpis['最新總庫存']:,}"),("缺貨風險SKU",f"{kpis['缺貨風險SKU']:,}"),("需補貨SKU",f"{kpis['需補貨SKU']:,}")]
    for i,(label,value) in enumerate(cards):
        ax=fig.add_axes([0.035+i*0.158,0.80,0.145,0.115]); ax.axis("off")
        ax.add_patch(plt.Rectangle((0,0),1,1,transform=ax.transAxes,fill=False,linewidth=1.2))
        ax.text(0.05,0.66,label,fontsize=10,color="#555555",transform=ax.transAxes)
        ax.text(0.05,0.22,value,fontsize=16,weight="bold",transform=ax.transAxes)
    ax=fig.add_axes([0.06,0.47,0.40,0.25]); ax.plot(daily["Date"], daily["Units Sold"], linewidth=2)
    ax.set_title("近 90 天銷售趨勢", fontsize=12, weight="bold"); ax.set_ylabel("銷售數量"); ax.grid(True, alpha=0.25); ax.tick_params(axis="x", rotation=20, labelsize=8)
    ax=fig.add_axes([0.55,0.47,0.38,0.25]); bottom=np.zeros(len(status))
    for col in status.columns:
        ax.bar(status.index, status[col], bottom=bottom, label=col); bottom += status[col].values
    ax.set_title("各品類最新庫存狀態", fontsize=12, weight="bold"); ax.set_ylabel("SKU 數量"); ax.legend(fontsize=8); ax.grid(True, axis="y", alpha=0.25); ax.tick_params(axis="x", rotation=15, labelsize=8)
    ax=fig.add_axes([0.06,0.13,0.40,0.25]); x=np.arange(len(cat)); w=0.38
    ax.bar(x-w/2, cat["Inventory Level"], w, label="目前庫存"); ax.bar(x+w/2, cat["Demand Forecast"]*7, w, label="7天需求預測")
    ax.set_xticks(x); ax.set_xticklabels(cat["Category"], rotation=15, fontsize=8); ax.set_title("目前庫存 vs 7天需求預測", fontsize=12, weight="bold"); ax.legend(fontsize=8); ax.grid(True, axis="y", alpha=0.25)
    ax=fig.add_axes([0.55,0.13,0.38,0.25]); ax.barh(top["門市 / 商品"][::-1], top["建議補貨量"][::-1])
    ax.set_title("Top 10 建議補貨清單", fontsize=12, weight="bold"); ax.set_xlabel("建議補貨量"); ax.grid(True, axis="x", alpha=0.25); ax.tick_params(axis="y", labelsize=8)
    fig.text(0.06,0.055,"報表規則：可支撐天數 = 目前庫存 / 需求預測；缺貨風險 ≤ 3 天；低庫存 = 3～7 天；建議補貨量 = 14天目標庫存 - 目前庫存 - 已下單量。",fontsize=10,color="#555555")
    fig.savefig(out_dir / "inventory_sales_dashboard_zh.png", dpi=170, bbox_inches="tight")
    plt.close(fig)

def main(csv_path, out):
    setup_chinese_font()
    out_dir = Path(out); out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(csv_path)
    df["Date"] = pd.to_datetime(df["Date"])
    df["折扣後售價"] = df["Price"] * (1 - df["Discount"] / 100)
    df["營收"] = df["Units Sold"] * df["折扣後售價"]
    latest_date = df["Date"].max()
    latest = df[df["Date"] == latest_date].copy()
    latest["可支撐天數"] = (latest["Inventory Level"] / latest["Demand Forecast"].replace(0, np.nan)).replace([np.inf,-np.inf], np.nan).fillna(999)
    latest["14天目標庫存"] = latest["Demand Forecast"] * TARGET_STOCK_DAYS
    latest["建議補貨量"] = (latest["14天目標庫存"] - latest["Inventory Level"] - latest["Units Ordered"]).clip(lower=0).round().astype(int)
    latest["庫存狀態"] = np.select([latest["可支撐天數"] <= OOS_DAYS, (latest["可支撐天數"] > OOS_DAYS) & (latest["可支撐天數"] <= LOW_STOCK_DAYS)], ["缺貨風險","低庫存"], default="安全庫存")
    last_30 = df[df["Date"] >= latest_date - pd.Timedelta(days=30)]
    last_90 = df[df["Date"] >= latest_date - pd.Timedelta(days=90)]
    save_dashboard(df, latest, last_30, last_90, out_dir)

    worklist = latest.sort_values(["建議補貨量","可支撐天數"], ascending=[False, True])[["Store ID","Product ID","Category","Region","Inventory Level","Units Sold","Demand Forecast","Units Ordered","可支撐天數","庫存狀態","建議補貨量"]].head(15)
    worklist = worklist.rename(columns={"Store ID":"門市","Product ID":"商品","Category":"品類","Region":"區域","Inventory Level":"目前庫存","Units Sold":"當日銷售量","Demand Forecast":"需求預測","Units Ordered":"已下單量"})
    kpi_html = f"<h1>庫存管理銷售系統報表</h1><p>最新資料日期：{latest_date.date()}</p><h2>KPI</h2><ul><li>門市數：{df['Store ID'].nunique()}</li><li>商品數：{df['Product ID'].nunique()}</li><li>近30天營收：{money(last_30['營收'].sum())}</li><li>近30天銷售量：{int(last_30['Units Sold'].sum()):,}</li><li>最新總庫存：{int(latest['Inventory Level'].sum()):,}</li><li>缺貨風險SKU：{int((latest['庫存狀態']=='缺貨風險').sum()):,}</li><li>需補貨SKU：{int((latest['建議補貨量']>0).sum()):,}</li></ul>"
    html = f'<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>庫存管理銷售系統報表</title><body style="font-family:Microsoft JhengHei,Noto Sans CJK TC,Arial,sans-serif;background:#f4f6f8;padding:32px">{kpi_html}<h2>儀表板</h2><img style="max-width:100%" src="inventory_sales_dashboard_zh.png"><h2>補貨工作清單</h2>{worklist.to_html(index=False)}</body></html>'
    (out_dir / "inventory_sales_report_zh.html").write_text(html, encoding="utf-8")
    print("完成：", out_dir / "inventory_sales_report_zh.html")
    print("完成：", out_dir / "inventory_sales_dashboard_zh.png")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out", default="inventory_report_chinese_output")
    args = parser.parse_args()
    main(args.csv, args.out)
