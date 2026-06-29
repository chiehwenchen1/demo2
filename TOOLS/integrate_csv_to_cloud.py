#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS – TOOLS / Integrate CSV to CLOUD

1. Reads D:\bible\inventory\retail_store_inventory.csv (73,100 rows)
2. Maps S001-S005 to 5 Japanese stores
3. Creates cloud_inventory.db with inventory_raw, store_info, sales_summary
4. Exports cloud_consolidated.csv

Japanese Store Names:
  S001 → Shibuya       (渋谷店 / 涩谷店)
  S002 → Ginza         (銀座店 / 银座店)
  S003 → Shinjuku      (新宿店 / 新宿店)
  S004 → Ueno          (上野店 / 上野店)
  S005 → Ikebukuro     (池袋店 / 池袋店)
"""

import sqlite3, os, csv
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT = Path("D:/bible/USI_SMART_RETAIL_OS")
CSV_PATH = Path("D:/bible/inventory/retail_store_inventory.csv")
DB_PATH = PROJECT / "CLOUD" / "database" / "cloud_inventory.db"
CLOUD_CSV_DIR = PROJECT / "CLOUD" / "inventory"
CLOUD_CSV = CLOUD_CSV_DIR / "cloud_consolidated.csv"

# Store ID mapping: S001-S005 → Japanese stores
STORE_MAP = {
    "S001": {
        "new_id": "Shibuya",
        "name_zh": "澀谷店",
        "name_en": "Shibuya Store",
        "name_ja": "渋谷店",
        "region": "Kanto"
    },
    "S002": {
        "new_id": "Ginza",
        "name_zh": "銀座店",
        "name_en": "Ginza Store",
        "name_ja": "銀座店",
        "region": "Kanto"
    },
    "S003": {
        "new_id": "Shinjuku",
        "name_zh": "新宿店",
        "name_en": "Shinjuku Store",
        "name_ja": "新宿店",
        "region": "Kanto"
    },
    "S004": {
        "new_id": "Ueno",
        "name_zh": "上野店",
        "name_en": "Ueno Store",
        "name_ja": "上野店",
        "region": "Kanto"
    },
    "S005": {
        "new_id": "Ikebukuro",
        "name_zh": "池袋店",
        "name_en": "Ikebukuro Store",
        "name_ja": "池袋店",
        "region": "Kanto"
    }
}

def load_and_rename_csv():
    """Load the CSV, rename stores, compute derived fields."""
    print(f"📂 Reading CSV: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    print(f"   Total rows: {len(df):,}")
    print(f"   Original stores: {df['Store ID'].unique()}")

    # Rename stores
    store_map_df = {k: v["new_id"] for k, v in STORE_MAP.items()}
    df["Store ID"] = df["Store ID"].map(store_map_df)
    unknown = df["Store ID"].isna().sum()
    if unknown > 0:
        print(f"   ⚠️  {unknown} rows with unknown store IDs dropped")
        df = df.dropna(subset=["Store ID"])
    df["Store ID"] = df["Store ID"].astype(str)

    print(f"   Renamed stores: {sorted(df['Store ID'].unique())}")

    # Parse dates
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    # Compute derived fields
    df["折扣後售價"] = df["Price"] * (1 - df["Discount"] / 100)
    df["營收"] = df["Units Sold"] * df["折扣後售價"]

    return df

def create_database(df):
    """Create cloud_inventory.db with inventory_raw, store_info, sales_summary."""
    os.makedirs(str(DB_PATH.parent), exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
        print("   🗑️  Removed existing cloud_inventory.db")

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # --- inventory_raw table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Date TEXT,
            Store_ID TEXT,
            Product_ID TEXT,
            Category TEXT,
            Region TEXT,
            Inventory_Level INTEGER,
            Units_Sold INTEGER,
            Units_Ordered INTEGER,
            Demand_Forecast REAL,
            Price REAL,
            Discount REAL,
            Weather_Condition TEXT,
            Holiday_Promotion INTEGER,
            Competitor_Pricing REAL,
            Seasonality TEXT,
            Discounted_Price REAL,
            Revenue REAL
        )
    """)

    # Insert raw data
    insert_sql = """
        INSERT INTO inventory_raw 
        (Date, Store_ID, Product_ID, Category, Region, Inventory_Level, Units_Sold, Units_Ordered,
         Demand_Forecast, Price, Discount, Weather_Condition, Holiday_Promotion, 
         Competitor_Pricing, Seasonality, Discounted_Price, Revenue)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    records = []
    for _, row in df.iterrows():
        records.append((
            str(row["Date"].date()) if hasattr(row.get("Date"), "date") else str(row["Date"]),
            row["Store ID"],
            row["Product ID"],
            row["Category"],
            row["Region"],
            int(row["Inventory Level"]),
            int(row["Units Sold"]),
            int(row["Units Ordered"]),
            float(row["Demand Forecast"]),
            float(row["Price"]),
            float(row["Discount"]),
            str(row.get("Weather Condition", row.get("Weather_Condition", ""))),
            int(row.get("Holiday/Promotion", row.get("Holiday_Promotion", 0))),
            float(row.get("Competitor Pricing", row.get("Competitor_Pricing", 0))),
            str(row.get("Seasonality", "")),
            float(row["折扣後售價"]),
            float(row["營收"]),
        ))

    cur.executemany(insert_sql, records)
    print(f"   ✅ inventory_raw: {len(records):,} rows inserted")

    # --- store_info table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS store_info (
            store_id TEXT PRIMARY KEY,
            name_zh TEXT,
            name_en TEXT,
            name_ja TEXT,
            region TEXT
        )
    """)
    for sid, info in STORE_MAP.items():
        cur.execute(
            "INSERT OR REPLACE INTO store_info VALUES (?,?,?,?,?)",
            (info["new_id"], info["name_zh"], info["name_en"], info["name_ja"], info["region"])
        )
    print(f"   ✅ store_info: {len(STORE_MAP)} stores inserted")

    # --- sales_summary table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sales_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Store_ID TEXT,
            Date TEXT,
            Total_Units_Sold INTEGER,
            Total_Revenue REAL,
            Avg_Inventory_Level REAL,
            Product_Count INTEGER,
            UNIQUE(Store_ID, Date)
        )
    """)

    # Compute per-store daily aggregates
    daily = df.groupby(["Store ID", df["Date"].dt.date]).agg(
        Total_Units_Sold=("Units Sold", "sum"),
        Total_Revenue=("營收", "sum"),
        Avg_Inventory_Level=("Inventory Level", "mean"),
        Product_Count=("Product ID", "nunique"),
    ).reset_index()

    summary_records = []
    for _, row in daily.iterrows():
        summary_records.append((
            row["Store ID"],
            str(row["Date"]),
            int(row["Total_Units_Sold"]),
            float(row["Total_Revenue"]),
            float(row["Avg_Inventory_Level"]),
            int(row["Product_Count"]),
        ))

    cur.executemany(
        "INSERT OR IGNORE INTO sales_summary (Store_ID, Date, Total_Units_Sold, Total_Revenue, Avg_Inventory_Level, Product_Count) VALUES (?,?,?,?,?,?)",
        summary_records
    )
    print(f"   ✅ sales_summary: {len(summary_records):,} daily records inserted")

    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_store ON inventory_raw(Store_ID)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_date ON inventory_raw(Date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_category ON inventory_raw(Category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_summary_store ON sales_summary(Store_ID)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_summary_date ON sales_summary(Date)")

    conn.commit()
    conn.close()
    print(f"   🗄️  Database: {DB_PATH}")

def export_consolidated_csv(df):
    """Export consolidated CSV with Japanese store names."""
    os.makedirs(str(CLOUD_CSV_DIR), exist_ok=True)

    # Prepare columns for CLOUD
    export_df = df.rename(columns={
        "Store ID": "Store_ID",
        "Product ID": "Product_ID",
        "Inventory Level": "Inventory_Level",
        "Units Sold": "Units_Sold",
        "Units Ordered": "Units_Ordered",
        "Demand Forecast": "Demand_Forecast",
        "Weather Condition": "Weather_Condition",
        "Holiday/Promotion": "Holiday_Promotion",
        "Competitor Pricing": "Competitor_Pricing",
    })

    export_df.to_csv(CLOUD_CSV, index=False, encoding="utf-8-sig")
    print(f"   📄 CSV: {CLOUD_CSV} ({len(export_df):,} rows)")
    return export_df

def main():
    print("=" * 60)
    print("USI Smart Retail OS — CLOUD CSV Integration")
    print("=" * 60)

    # Step 1: Load and rename
    df = load_and_rename_csv()

    # Step 2: Create database
    create_database(df)

    # Step 3: Export CSV
    export_consolidated_csv(df)

    # Summary
    print(f"\n{'=' * 60}")
    print("📊 整合完成！")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    for table in ["inventory_raw", "store_info", "sales_summary"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        cnt = cur.fetchone()[0]
        print(f"   {table}: {cnt:,} rows")
    conn.close()
    print("=" * 60)

if __name__ == "__main__":
    main()
