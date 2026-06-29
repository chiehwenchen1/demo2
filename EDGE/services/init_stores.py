#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - Initialize all store databases
"""

import subprocess, sys
from pathlib import Path

PROJECT = Path('D:/bible/USI_SMART_RETAIL_OS')
TRANSFORMER = PROJECT / 'EDGE/services/db_transformer.py'

STORE_FOLDERS = [
    "Taipei Zhongxiao_台北忠孝店_台北忠孝店",
    "Nantou Nangang_南投南崗店_南投南崗店",
    "Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店",
]

def main():
    print("="*60)
    print("USI Smart Retail OS - Initialize All Stores")
    print("="*60)

    for folder in STORE_FOLDERS:
        print(f"\n{'='*40}")
        print(f"Processing: {folder}")
        print('='*40)

        result = subprocess.run(
            [sys.executable, str(TRANSFORMER), folder],
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.stderr:
            print(f"[STDERR] {result.stderr}")

        if result.returncode != 0:
            print(f"  [FAIL] {folder} initialization failed")
        else:
            print(f"  [OK] {folder} initialized successfully")

    print(f"\n{'='*60}")
    print("All stores initialized")
    print('='*60)

if __name__ == '__main__':
    main()
