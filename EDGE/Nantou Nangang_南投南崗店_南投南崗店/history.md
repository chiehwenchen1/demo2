# history.md

> 自動記錄 — 2026-04-29 操作紀錄

---

## 南投南崗店門市 — 初建立

### 建立方式

由 `Taipei Zhongxiao_台北忠孝店_台北忠孝店` 完整複製，所有 `Taipei Zhongxiao` → `Nantou Nangang`、`台北忠孝店` → `南投南崗店`

### 建立項目

#### 📁 門市資料結構
| 項目 | 狀態 |
|------|------|
| `checkout/` | ✅ 複製 |
| `handheld/USI_SM_OS_APP_V1/` | ✅ 複製+文字替換 |
| `local_db/` | ✅ 複製 |
| `logs/` | ✅ 複製 |
| `reports/` | ✅ 複製+改名 |
| `smartshelf/` | ✅ 複製 |
| `EDGE_DB.db` | ✅ 原始資料庫 (未改動) |
| `EDGE_DB.sqbpro` | ✅ 複製 |
| `generate_edge_slide_html.py` | ✅ REGION → Central |

#### 📄 store_ops.py 調整
- 自動判斷邏輯：識別「南投/Nantou」→ `STORE_ID = "Nantou Nangang"`、`REGION = "Central"`

#### 📄 SKU 商品清單
- `sku_v3.csv` (34 項商品，同台北忠孝店)
- 已刪除 `sku.csv`、`sku_v2.csv`、`sku_v3_ori.csv`
- **索引規則**：條碼 (B 欄) 為資料庫索引，品名 (A 欄) 為顯示用

### 系統註冊

| 檔案 | 變更 |
|------|------|
| `store_config.json` (專案根目錄) | 新增 `USI_NG_LAB_5501` |
| `EDGE/services/init_stores.py` | 加入初始化清單 |

### Handheld APP
- 完整複製自台北忠孝店
- 替換文字：`Taipei Zhongxiao` → `Nantou Nangang`、`Zhongxiao` → `Nangang`、`台北忠孝店` → `南投南崗店`
- 無硬編碼店名殘留

### CLOUD 端
- `CLOUD/inventory/Nantou Nangang/` + inventory CSV
- `CLOUD/inventory/Nantou Nangang_南投南崗店_南投南崗店/` + inventory CSV
