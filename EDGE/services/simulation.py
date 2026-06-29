#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script 2: simulation.py
EDGE 門市模擬控制器
支援操作:
  --action restock --product <name> --qty <n>   （進貨：增加庫存）
  --action sell --product <name> --qty <n>       （銷貨：減少庫存，記錄銷售）
  --action shelf-replenish --product <name> --qty <n>  （補貨：倉庫→貨架）
  --action status                                  （顯示庫存狀態）
  --action batch --days <n>                        （批次產生隨機交易記錄）
  --store <store>                                  （指定門市，預設 Taipei Zhongxiao）

用法:
  python simulation.py --action status
  python simulation.py --action restock --product cola --qty 50
  python simulation.py --action sell --product sprite --qty 10
  python simulation.py --action shelf-replenish --product pepsi --qty 30
  python simulation.py --action batch --days 90
"""
import argparse
import csv
import os
import random
import sqlite3
import sys
import uuid
from datetime import datetime, date, timedelta

# 專案根目錄
PROJECT = "D:/bible/USI_SMART_RETAIL_OS"

# sku_v2 類別名稱 → EDGE enhanced_inventory 中的 category 名稱
CATEGORY_MAP = {
    "coke":        "cola",
    "sprite":      "sprite",
    "pepsi":       "pepsi",
    "coke_large":  "big_cola",
    "heineken":    "beer1",
    "budweiser":   "beer2",
    "jagarico":    "cookie1",
    "cadina":      "cookie2",
    "miso_soup":   "soup",
    "heinz_ketchup": "tomato",
}

# EDGE category → 中文品名（直接用 EDGE category 配對）
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

# 可用的 sku 別名（支援中文 & 英文）
PRODUCT_ALIASES = {
    "cola": "cola",
    "coke": "cola",
    "可樂": "cola",
    "coke_large": "big_cola",
    "big_cola": "big_cola",
    "大瓶可樂": "big_cola",
    "sprite": "sprite",
    "雪碧": "sprite",
    "pepsi": "pepsi",
    "百事可樂": "pepsi",
    "heineken": "beer1",
    "海尼根": "beer1",
    "beer1": "beer1",
    "budweiser": "beer2",
    "百威": "beer2",
    "beer2": "beer2",
    "jagarico": "cookie1",
    "calbee": "cookie1",
    "cookie1": "cookie1",
    "cadina": "cookie2",
    "卡迪那": "cookie2",
    "cookie2": "cookie2",
    "miso_soup": "soup",
    "味噌湯": "soup",
    "soup": "soup",
    "heinz_ketchup": "tomato",
    "番茄醬": "tomato",
    "tomato": "tomato",
}

# 門市資料庫路徑
def get_store_db(store_id):
    """根據 store_id 回傳 EDGE 資料庫路徑"""
    if store_id == "Taipei Zhongxiao":
        return os.path.join(PROJECT, "EDGE", "Taipei Zhongxiao_台北忠孝店_台北忠孝店", "EDGE_DB.db")
    elif store_id == "Osaka Shinsaibashi":
        return os.path.join(PROJECT, "EDGE", "Osaka Shinsaibashi_大阪心齋橋店_大阪心斎橋店", "EDGE_DB.db")
    else:
        return None

def get_edge_category(alias):
    """將使用者輸入的別名轉換為 EDGE category 名稱"""
    if alias in CATEGORY_MAP:
        return CATEGORY_MAP[alias]
    if alias in PRODUCT_ALIASES:
        edge_cat = PRODUCT_ALIASES[alias]
        return edge_cat
    return alias  # 直接使用原始輸入

def _store_prefix(store_id):
    """門市簡稱前綴"""
    return store_id.replace("Taipei Zhongxiao", "Taipei").replace("Osaka Shinsaibashi", "Osaka")

def resolve_product(conn, store_id, category_alias):
    """根據類別別名查詢產品"""
    edge_cat = get_edge_category(category_alias)
    prefix = _store_prefix(store_id)
    
    # 用簡短 product_id 格式查詢
    cur = conn.cursor()
    cur.execute(
        "SELECT id, product_id, product_name, category, stock_quantity, retail_price, max_capacity, reorder_level, barcode "
        "FROM enhanced_inventory WHERE category = ? AND product_id LIKE ?",
        (edge_cat, f"{prefix}%{edge_cat}")
    )
    row = cur.fetchone()
    if row:
        return row
    
    # 直接查 category（容錯）
    cur.execute(
        "SELECT id, product_id, product_name, category, stock_quantity, retail_price, max_capacity, reorder_level, barcode "
        "FROM enhanced_inventory WHERE category = ?",
        (edge_cat,)
    )
    row = cur.fetchone()
    return row

def get_all_products(conn, store_id):
    """取得門市所有 sku_v2 相關的庫存產品"""
    prefix = _store_prefix(store_id)
    cur = conn.cursor()
    products = []
    for edge_cat in CATEGORY_MAP.values():
        cur.execute(
            "SELECT id, product_id, product_name, category, stock_quantity, retail_price, max_capacity, reorder_level "
            "FROM enhanced_inventory WHERE category = ? AND product_id LIKE ?",
            (edge_cat, f"{prefix}%{edge_cat}")
        )
        row = cur.fetchone()
        if row:
            products.append(row)
        else:
            # 直接查 category（容錯）
            cur.execute(
                "SELECT id, product_id, product_name, category, stock_quantity, retail_price, max_capacity, reorder_level "
                "FROM enhanced_inventory WHERE category = ?",
                (edge_cat,)
            )
            row = cur.fetchone()
            if row:
                products.append(row)
    return products


def get_all_products_with_sku_name(conn, store_id, sku_prices):
    """取得產品列表，含 sku_v2 中文品名（直接用 EDGE category 配對）"""
    raw = get_all_products(conn, store_id)
    result = []
    for p in raw:
        pid, prod_id, pname, cat, stock, rprice, max_cap, reorder = p
        display_name = CATEGORY_TO_NAME.get(cat, pname)
        result.append((pid, prod_id, display_name, cat, stock, rprice, max_cap, reorder))
    return result

def record_transaction(conn, product_id, txn_type, qty, prev_stock, new_stock, total_amount=0):
    """記錄交易到 inventory_transactions 和 transaction_log"""
    cur = conn.cursor()
    txn_id = f"TXN-{uuid.uuid4().hex.upper()}"
    now = datetime.now().isoformat()
    
    # 寫入 inventory_transactions
    cur.execute(
        "INSERT INTO inventory_transactions (transaction_id, product_id, transaction_type, quantity, "
        "previous_stock, new_stock, total_amount, transaction_time, device_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (txn_id, product_id, txn_type, qty, prev_stock, new_stock, total_amount, now, "SIMULATION")
    )
    
    # 寫入 transaction_log
    try:
        cur.execute(
            "INSERT INTO transaction_log (transaction_id, product_name, quantity, total_price, payment_method, customer_id, checkout_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (txn_id, product_id, qty, total_amount, "SYSTEM" if txn_type == "restock" else "CASH", "SIM", now)
        )
    except Exception as e:
        pass  # transaction_log 可選
    
    return txn_id

def action_restock(conn, store_id, product_alias, qty):
    """進貨：增加庫存（倉庫庫存增加/或直接增加 stock_quantity）"""
    product = resolve_product(conn, store_id, product_alias)
    if not product:
        print(f"❌ 找不到產品: {product_alias}，請確認類別名稱")
        return False
    
    pid, prod_id, pname, cat, stock, rprice, max_cap, reorder, barcode = product
    prev_stock = stock
    new_stock = prev_stock + qty
    total_amount = qty * rprice * 0.6  # 以成本價計算進貨金額
    
    cur = conn.cursor()
    cur.execute("UPDATE enhanced_inventory SET stock_quantity = ? WHERE id = ?", (new_stock, pid))
    record_transaction(conn, prod_id, "restock", qty, prev_stock, new_stock, total_amount)
    conn.commit()
    
    print(f"✅ 進貨完成: {pname} ({cat}) +{qty} 件")
    print(f"   原庫存: {prev_stock} → 新庫存: {new_stock}")
    print(f"   進貨金額: ${total_amount:.2f}")
    return True

def action_sell(conn, store_id, product_alias, qty):
    """銷貨：減少庫存，記錄銷售交易"""
    product = resolve_product(conn, store_id, product_alias)
    if not product:
        print(f"❌ 找不到產品: {product_alias}，請確認類別名稱")
        return False
    
    pid, prod_id, pname, cat, stock, rprice, max_cap, reorder, barcode = product
    if stock < qty:
        print(f"❌ 庫存不足！{pname} 目前庫存: {stock}，需求: {qty}")
        return False
    
    prev_stock = stock
    new_stock = prev_stock - qty
    total_amount = qty * rprice  # 以零售價計算銷售金額
    
    cur = conn.cursor()
    cur.execute("UPDATE enhanced_inventory SET stock_quantity = ? WHERE id = ?", (new_stock, pid))
    record_transaction(conn, prod_id, "sell", qty, prev_stock, new_stock, total_amount)
    conn.commit()
    
    print(f"✅ 銷貨完成: {pname} ({cat}) -{qty} 件")
    print(f"   原庫存: {prev_stock} → 新庫存: {new_stock}")
    print(f"   銷售金額: ${total_amount:.2f}")
    return True

def action_shelf_replenish(conn, store_id, product_alias, qty):
    """
    補貨（貨架補貨）：從倉庫移動到貨架
    此系統中 enhanced_inventory 的 stock_quantity 即代表貨架庫存
    補貨操作：如果庫存已足則跳過，否則增加庫存（模擬從倉庫上架）
    實際應用中可區分 warehouse_stock 和 shelf_stock
    """
    product = resolve_product(conn, store_id, product_alias)
    if not product:
        print(f"❌ 找不到產品: {product_alias}")
        return False
    
    pid, prod_id, pname, cat, stock, rprice, max_cap, reorder, barcode = product
    
    # 檢查是否已接近最大容量
    if stock >= max_cap:
        print(f"ℹ️  貨架已滿！{pname} 目前庫存: {stock}/{max_cap}，無需補貨")
        return True
    
    # 計算可補貨量：不超過最大容量
    actual_qty = min(qty, max_cap - stock)
    if actual_qty <= 0:
        print(f"ℹ️  貨架已滿，無需補貨")
        return True
    
    prev_stock = stock
    new_stock = prev_stock + actual_qty
    
    cur = conn.cursor()
    cur.execute("UPDATE enhanced_inventory SET stock_quantity = ?, last_restock = ? WHERE id = ?",
                (new_stock, datetime.now().isoformat(), pid))
    record_transaction(conn, prod_id, "shelf_replenish", actual_qty, prev_stock, new_stock, 0)
    conn.commit()
    
    print(f"✅ 補貨完成: {pname} ({cat}) +{actual_qty} 件")
    print(f"   貨架: {prev_stock} → {new_stock} (最大容量: {max_cap})")
    return True

def action_status(conn, store_id):
    """顯示目前庫存狀態（使用 sku_v2 中文品名）"""
    products = get_all_products_with_sku_name(conn, store_id, {})
    if not products:
        print(f"❌ {store_id} 中找不到任何產品")
        return
    
    print(f"\n{'='*80}")
    print(f"  {store_id} — 目前庫存狀態")
    print(f"{'='*80}")
    print(f"  {'品名':<22s} {'類別':<12s} {'零售價':>8s} {'庫存':>6s} {'最大':>6s} {'補貨點':>6s} {'庫存率':>8s}")
    print(f"  {'-'*70}")
    
    total_stock = 0
    total_value = 0
    oos_count = 0
    
    for p in products:
        pid, prod_id, display_name, cat, stock, rprice, max_cap, reorder = p
        max_cap = max_cap or 200
        reorder = reorder or 20
        
        rate = (stock / max_cap * 100) if max_cap > 0 else 0
        status_icon = "🟢" if rate > 50 else "🟡" if rate > 20 else "🔴"
        
        print(f"  {status_icon} {display_name:<20s} {cat:<12s} ${rprice:>6.1f} {stock:>6d} {max_cap:>6d} {reorder:>6d} {rate:>7.0f}%")
        
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

def action_batch(conn, store_id, days):
    """
    批次產生 days 天的隨機銷售歷史
    每天每項產品隨機銷售 1~15 件
    從今天往回推 days 天
    """
    products = get_all_products_with_sku_name(conn, store_id, {})
    if not products:
        print(f"❌ {store_id} 中找不到任何產品")
        return
    
    start_date = date.today() - timedelta(days=days)
    
    print(f"🔄 正在產生 {store_id} 過去 {days} 天的模擬銷售資料...")
    print(f"   起始日期: {start_date}")
    print(f"   產品數: {len(products)}")
    
    total_transactions = 0
    
    for p in products:
        # products 回傳 8 個欄位（無 barcode）
        if len(p) >= 9:
            pid, prod_id, pname, cat, stock, rprice, max_cap, reorder, _ = p
        else:
            pid, prod_id, pname, cat, stock, rprice, max_cap, reorder = p
        max_cap = max_cap or 200
        reorder = reorder or 20
        
        current_stock = random.randint(80, 150)  # 初始庫存
        
        for day_offset in range(days):
            sim_date = start_date + timedelta(days=day_offset)
            
            # 週末或假日銷售較多
            is_weekend = sim_date.weekday() >= 5  # 週六、日
            # 隨機決定今天是否有銷售（80% 機率有銷售）
            if random.random() < 0.2:
                continue
            
            # 銷售量：平日 1~8 件，週末 2~15 件
            sell_qty = random.randint(2, 12) if is_weekend else random.randint(1, 8)
            sell_qty = min(sell_qty, current_stock)  # 不能超過庫存
            
            if sell_qty <= 0:
                continue
            
            prev_stock = current_stock
            current_stock -= sell_qty
            
            # 直接寫入 inventory_transactions
            txn_id = f"BATCH-{uuid.uuid4().hex.upper()}"
            txn_time = sim_date.strftime("%Y-%m-%d") + f"T{random.randint(8,21):02d}:{random.randint(0,59):02d}:00"
            total_amount = sell_qty * rprice
            
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO inventory_transactions (transaction_id, product_id, transaction_type, quantity, "
                "previous_stock, new_stock, total_amount, transaction_time, device_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (txn_id, prod_id, "sell", sell_qty, prev_stock, current_stock, total_amount, txn_time, "SIM_BATCH")
            )
            
            # 寫入 transaction_log
            try:
                cur.execute(
                    "INSERT INTO transaction_log (transaction_id, product_name, quantity, total_price, "
                    "payment_method, customer_id, checkout_time) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (txn_id, pname, sell_qty, total_amount, "CASH", f"CUST-{random.randint(1000,9999)}", txn_time)
                )
            except Exception:
                pass
            
            total_transactions += 1
            
            # 如果庫存低於補貨點，自動少量補貨（進貨）
            if current_stock < reorder * 2:
                restock_qty = random.randint(30, 80)
                prev = current_stock
                current_stock += restock_qty
                rtxn_id = f"BATCH-R-{uuid.uuid4().hex.upper()}"
                cur.execute(
                    "INSERT INTO inventory_transactions (transaction_id, product_id, transaction_type, quantity, "
                    "previous_stock, new_stock, total_amount, transaction_time, device_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rtxn_id, prod_id, "restock", restock_qty, prev, current_stock, 
                     restock_qty * rprice * 0.6, txn_time, "SIM_AUTO_RESTOCK")
                )
                total_transactions += 1
        
        # 更新最終庫存到 enhanced_inventory
        cur = conn.cursor()
        cur.execute("UPDATE enhanced_inventory SET stock_quantity = ? WHERE id = ?", (current_stock, pid))
        
        if (day_offset + 1) % 10 == 0 or (day_offset + 1) == days:
            conn.commit()
    
    conn.commit()
    print(f"\n✅ 批次模擬完成！")
    print(f"   門市: {store_id}")
    print(f"   天數: {days}")
    print(f"   產生交易: {total_transactions:,} 筆")

def main():
    parser = argparse.ArgumentParser(description="EDGE 門市庫存模擬控制器")
    parser.add_argument("--action", required=True,
                        choices=["restock", "sell", "shelf-replenish", "status", "batch"],
                        help="操作類型")
    parser.add_argument("--store", default="Taipei Zhongxiao",
                        choices=["Taipei Zhongxiao", "Osaka Shinsaibashi"],
                        help="門市 (預設: Taipei Zhongxiao)")
    parser.add_argument("--product", help="產品別名 (ex: cola, sprite, pepsi, heineken, 可樂, 雪碧...)")
    parser.add_argument("--qty", type=int, default=10, help="數量")
    parser.add_argument("--days", type=int, default=30, help="批次模擬天數")
    
    args = parser.parse_args()
    
    db_path = get_store_db(args.store)
    if not db_path or not os.path.exists(db_path):
        print(f"❌ 找不到資料庫: {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    
    print(f"\n🔧 USI Smart Retail OS — EDGE 模擬控制器")
    print(f"   門市: {args.store}")
    print(f"   操作: {args.action}")
    print()
    
    if args.action == "status":
        action_status(conn, args.store)
    elif args.action == "restock":
        if not args.product:
            print("❌ 請指定產品名稱 (--product)")
            sys.exit(1)
        action_restock(conn, args.store, args.product, args.qty)
    elif args.action == "sell":
        if not args.product:
            print("❌ 請指定產品名稱 (--product)")
            sys.exit(1)
        action_sell(conn, args.store, args.product, args.qty)
    elif args.action == "shelf-replenish":
        if not args.product:
            print("❌ 請指定產品名稱 (--product)")
            sys.exit(1)
        action_shelf_replenish(conn, args.store, args.product, args.qty)
    elif args.action == "batch":
        action_batch(conn, args.store, args.days)
    
    conn.close()

if __name__ == "__main__":
    main()
