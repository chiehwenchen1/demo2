@echo off
chcp 65001 >nul
title USI Smart Retail OS

echo ========================================
echo   USI SMART RETAIL OS
echo   Beyond Toshiba ELERA
echo ========================================
echo   Taipei Zhongxiao / 台北忠孝店 / 台北忠孝店
echo   Osaka Shinsaibashi / 大阪心齋橋店 / 大阪心斎橋店
echo ========================================
echo.

echo [Step 1] Check Python...
python --version
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

echo.
echo [Step 2] Transform databases (read-only original -^> EDGE_DB.db)
python EDGE\services\init_stores.py
if errorlevel 1 (
    echo [ERROR] Transform failed
    pause
    exit /b 1
)

echo.
echo [Step 3] Generate cloud reports...
python CLOUD\inventory\generate_cloud_reports.py

echo.
echo ========================================
echo   [OK] System Ready!
echo ========================================
echo.
echo   EDGE_DB:  Taipei Zhongxiao/EDGE_DB.db
echo             Osaka Shinsaibashi/EDGE_DB.db
echo   CLOUD:    reports/inventory_summary.json
echo   STATUS:   python TOOLS\show_db_status.py
echo.
echo ========================================
pause
