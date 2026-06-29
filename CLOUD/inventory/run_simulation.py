#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 5: run_simulation.py
CLOUD 層級模擬編排器
- 批次執行 EDGE 模擬（產生多日銷售資料）
- 同步 EDGE → CLOUD
- 產生報表

用法:
  python run_simulation.py --days 90 --stores all     # 完整流程
  python run_simulation.py --days 90 --stores taipei  # 僅台北
  python run_simulation.py --days 90 --stores osaka   # 僅大阪
  python run_simulation.py --skip-sync                # 跳過同步（僅報表）
  python run_simulation.py --skip-report              # 跳過報表（僅同步）
  python run_simulation.py --init-prices              # 初始化價格後再執行
"""
import argparse
import os
import sys
import time
from datetime import datetime

# 專案根目錄
PROJECT = "D:/bible/USI_SMART_RETAIL_OS"

def run_script(script_path, args_str=""):
    """執行指定的 Python 腳本"""
    full_path = os.path.join(PROJECT, script_path)
    if not os.path.exists(full_path):
        print(f"[ERROR] 找不到腳本: {full_path}")
        return False
    
    cmd = f'python3 "{full_path}" {args_str}'
    print(f"\n  🔧 {cmd}")
    print(f"  {'─' * 60}")
    start = time.time()
    result = os.system(cmd)
    elapsed = time.time() - start
    print(f"  {'─' * 60}")
    
    if result == 0:
        print(f"  ✅ 完成（耗時 {elapsed:.1f} 秒）")
        return True
    else:
        print(f"  ❌ 失敗（exit code={result}，耗時 {elapsed:.1f} 秒）")
        return False

def main():
    parser = argparse.ArgumentParser(description="USI Smart Retail OS — 完整模擬流程編排器")
    parser.add_argument("--days", type=int, default=90, help="模擬天數 (預設: 90)")
    parser.add_argument("--stores", default="all", choices=["all", "taipei", "osaka"],
                        help="門市選擇 (預設: all)")
    parser.add_argument("--init-prices", action="store_true",
                        help="先初始化價格再執行模擬")
    parser.add_argument("--skip-sim", action="store_true",
                        help="跳過 EDGE 模擬步驟")
    parser.add_argument("--skip-sync", action="store_true",
                        help="跳過 EDGE→CLOUD 同步步驟")
    parser.add_argument("--skip-report", action="store_true",
                        help="跳過報表產生步驟")
    args = parser.parse_args()
    
    print(f"""
{'='*60}
  USI Smart Retail OS — 完整模擬流程
  開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  模擬天數: {args.days} 天
  門市選擇: {args.stores}
  步驟: {'價格初始化, ' if args.init_prices else ''}{'EDGE模擬, ' if not args.skip_sim else ''}{'EDGE→CLOUD同步, ' if not args.skip_sync else ''}{'報表產生' if not args.skip_report else ''}
{'='*60}
""")
    
    # Step 0: 初始化價格（可選）
    if args.init_prices:
        print("\n" + "═" * 50)
        print("Step 0: 初始化 EDGE 價格")
        print("═" * 50)
        success = run_script("EDGE/services/init_edge_prices.py")
        if not success:
            print("[ERROR] 價格初始化失敗，終止流程")
            sys.exit(1)
    
    # Step 1: 執行 EDGE 模擬
    if not args.skip_sim:
        print("\n" + "═" * 50)
        print("Step 1: EDGE 門市批次模擬")
        print("═" * 50)
        
        stores_to_sim = []
        if args.stores in ("all", "taipei"):
            stores_to_sim.append("Taipei Zhongxiao")
        if args.stores in ("all", "osaka"):
            stores_to_sim.append("Osaka Shinsaibashi")
        
        for store in stores_to_sim:
            sim_script = os.path.join(PROJECT, "EDGE/services/simulation.py")
            cmd = f'--action batch --days {args.days} --store "{store}"'
            success = run_script("EDGE/services/simulation.py", cmd)
            if not success:
                print(f"  [WARN] {store} 模擬失敗，繼續執行")
    else:
        print("\n  ⏭️  跳過 EDGE 模擬")
    
    # Step 2: 同步 EDGE → CLOUD
    if not args.skip_sync:
        print("\n" + "═" * 50)
        print("Step 2: 同步 EDGE 資料至 CLOUD")
        print("═" * 50)
        
        sync_cmd = f"--days {args.days} --export-csv"
        success = run_script("CLOUD/inventory/sync_edge_to_cloud.py", sync_cmd)
        if not success:
            print("[ERROR] 同步失敗，終止流程")
            sys.exit(1)
    else:
        print("\n  ⏭️  跳過 EDGE→CLOUD 同步")
    
    # Step 3: 產生 CLOUD 報表
    if not args.skip_report:
        print("\n" + "═" * 50)
        print("Step 3: 產生 CLOUD 報表")
        print("═" * 50)
        
        report_cmd = ""
        success = run_script("CLOUD/inventory/generate_cloud_report.py", report_cmd)
        if not success:
            print("[ERROR] 報表產生失敗")
            sys.exit(1)
    else:
        print("\n  ⏭️  跳過報表產生")
    
    # 完成
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"""
{'='*60}
  ✅ 完整模擬流程完成！
  結束時間: {end_time}
  輸出檔案:
    - CLOUD/reports/inventory_sales_report_zh.html
    - CLOUD/reports/inventory_sales_dashboard_zh.png
    - CLOUD/inventory/retail_store_inventory.csv
{'='*60}
""")

if __name__ == "__main__":
    main()
