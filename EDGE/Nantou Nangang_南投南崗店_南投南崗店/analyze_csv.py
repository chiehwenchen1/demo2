# -*- coding: utf-8 -*-
"""分析 sku_v3.csv 的重複與對應問題"""
import csv
from pathlib import Path

CSV_PATH = Path(r"D:\bible\USI_SMART_RETAIL_OS\EDGE\Nantou Nangang_南投南崗店_南投南崗店\sku_v3.csv")

with open(str(CSV_PATH), encoding="utf-8-sig") as f:
    rows = list(csv.reader(f))

print(f"CSV 共 {len(rows)} 行\n")
print(f"{'#':>3} {'名稱':25s} {'條碼':20s} {'價格':>6s} {'category':20s}")
print("-" * 75)
barcodes = {}
for i, row in enumerate(rows):
    name, bar, price, cat = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
    dup = ""
    if bar in barcodes:
        dup = f" <- 跟第 {barcodes[bar]} 行同條碼!"
    barcodes[bar] = i + 1
    print(f"{i+1:3d} {name:25s} {bar:20s} {price:>6s} {cat:20s}{dup}")
