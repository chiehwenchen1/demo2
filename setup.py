#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - Setup Script
"""

import sys
from pathlib import Path

BASE = Path('.')
STORES = [
    ("Taipei Zhongxiao_台北忠孝店_台北忠孝店", "Taipei Zhongxiao", "台北忠孝店"),
    ("Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店", "Osaka Shinsaibashi", "大阪心齋橋店"),
]

def check_python():
    print("Check Python environment...")
    print(f"  Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    if sys.version_info.major < 3:
        print("  [FAIL] Need Python 3+")
        return False
    print("  [OK]")
    return True

def check_directories():
    print("\nCheck project directories...")
    dirs = []
    for folder, sid, sname in STORES:
        dirs += [
            f'EDGE/{folder}/smartshelf/original',
            f'EDGE/{folder}/smartshelf/processed',
            f'EDGE/{folder}/checkout',
            f'EDGE/{folder}/logs',
        ]
    dirs += ['EDGE/services', 'CLOUD/reports', 'COMMUNICATION', 'TOOLS']

    miss = []
    for d in dirs:
        path = BASE / d
        ok = path.exists()
        label = ""
        for folder, sid, sname in STORES:
            if folder in d:
                label = f" ({sid} / {sname})"
                break
        print(f"  {'[OK]' if ok else '[MISS]'}{label} {d}")
        if not ok:
            miss.append(d)
    return len(miss) == 0

def check_files():
    print("\nCheck project files...")
    files = [
        'EDGE/services/db_transformer.py',
        'EDGE/services/init_stores.py',
        'CLOUD/inventory/generate_cloud_reports.py',
        'TOOLS/show_db_status.py',
        'start.bat', 'setup.py',
    ]
    miss = []
    for f in files:
        ok = (BASE / f).exists()
        print(f"  {'[OK]' if ok else '[MISS]'} {f}")
        if not ok:
            miss.append(f)
    return len(miss) == 0

def check_smart_shelf():
    print("\nCheck Smart Shelf original system...")
    ok = True
    for folder, sid, sname in STORES:
        p = BASE / f'EDGE/{folder}/smartshelf/original/smart_shelf_demo_v27_phone_formalrelease'
        if p.exists():
            print(f"  [OK] {sid} ({sname}): smart_shelf_demo_v27_phone_formalrelease")
        else:
            print(f"  [MISS] {sid} ({sname}): not found")
            ok = False
    return ok

def check_edge_db():
    print("\nCheck EDGE_DB.db status...")
    ok = True
    for folder, sid, sname in STORES:
        p = BASE / f'EDGE/{folder}/EDGE_DB.db'
        if p.exists():
            print(f"  [OK] {sid} ({sname}): {p.stat().st_size:,} bytes")
        else:
            print(f"  [MISS] {sid}: run init_stores.py")
            ok = False
    return ok

def main():
    print("="*60)
    print("USI Smart Retail OS - Installation Check")
    print("="*60)

    ok = True
    ok &= check_python()
    ok &= check_directories()
    ok &= check_files()
    ok &= check_smart_shelf()
    ok &= check_edge_db()

    print(f"\n{'='*60}")
    print("[OK] All checks passed! Run 'start.bat'" if ok else "[WARN] Some checks failed")
    print("="*60)

if __name__ == '__main__':
    main()
