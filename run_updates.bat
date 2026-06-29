@echo off
chcp 65001 >nul
cd /d D:\bible

echo ===============================
echo USI_NK Store - 3-Update Cycle
echo ===============================

for /l %%i in (1,1,3) do (
    echo.
    echo === Update %%i ===
    
    python USI_SMART_RETAIL_OS/EDGE/services/usi_nk_integration.py >nul 2>&1
    
    python -c "import pandas as pd; df=pd.read_csv('inventory/retail_store_inventory_with_usi_nk.csv'); nk=df[df['Store ID']=='USI_NK']; print('Products from shelf:'); shelf=nk[nk['Product ID'].isin(['P0001','P0005','P0011'])]; [print(f\"  {r['Product ID']}: stock={r['Inventory Level']}, sold={r['Units Sold']}\") for _,r in shelf.iterrows()]"
    
    timeout /t 2 /nobreak >nul
)

echo.
echo ===============================
echo Done. Open the report:
echo inventory/report_output/inventory_sales_report_zh.html
echo ===============================
