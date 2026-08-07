# CLAUDE.md — AssetRush

多人同步大富翁．台灣真實金融版。LINE Mini App + 獨立網站雙軌。

**目前狀態：僅有規格文件，尚未開始實作。** 先讀 [docs/](docs/)。

---

## 鐵律

以下五條違反了會造成大範圍返工或線上事故。**寫任何程式碼前先確認沒有違反。**

### 1. Next.js 不持有遊戲狀態

所有規則判定、擲骰、回合推進、金額計算都在 FastAPI 的 `engine/`。

**檢驗標準：把 Next.js 整個換成一個純 SPA，遊戲仍應完全正常運作。**

禁止：在 API Route / Server Action 裡判定遊戲規則、直接寫 `games` 表、用 Vercel Cron 推進回合、在前端計算租金或資產。

### 2. `engine/` 零 I/O

`apps/backend/src/assetrush/engine/` 不得 import `supabase` / `sqlalchemy` / `httpx` / `requests` / `fastapi` / `asyncpg`。CI 會檢查。

理由：規則引擎必須能離線跑蒙地卡羅模擬（`make simulate`），那是平衡工作的前提。

### 3. 所有改變局狀態的寫入都要上鎖

```python
async with db.begin():
    await db.execute(text("select pg_advisory_xact_lock(hashtext(:gid))"), {"gid": str(game_id)})
    # + turn_seq 樂觀鎖，rowcount == 0 時拋 StaleTurnError
```

日常型下「玩家點結束回合」與「排程判定逾時」同時觸發是必然事件，不是邊界情況。

### 4. 台股紅漲綠跌

台灣股市紅色代表**上漲**、綠色代表**下跌**，與歐美相反。

- 行情數字一律用 `--market-up` / `--market-down`
- `--destructive` 只用於「玩家的錢變少」（付租金、罰款、破產）
- 兩者視覺上都是紅色，但語意完全不同，**不可互相替代**
- 漲跌**必須同時帶 ▲▼ 符號**（紅綠色盲在台灣男性約 8%）

判斷依據：這個數字描述的是**市場行情**還是**我的收支**。

### 5. 開局後世界凍結

局開始時 snapshot `config_version`，並把全部格位的基價寫入 `board_tiles` 固化。

日常型的局要跑 21 天，這期間我們一定會改數值與更新房價——**改了不能影響進行中的局**。

### 6. 認購溢價不計入任何東西

日常型的購地是**出價認購**。玩家出價高於基價的部分（溢價）：

- ❌ 不計入市值 · ❌ 不影響租金 · ❌ 不計入貸款額度 · ❌ 不可貸款支付
- ✅ 只用來決定誰得標

**溢價是純沉沒成本**——這是零和信條的延伸（多付的錢沒有變成資產），也是抑制富人無限加價的唯一機制。任何「讓溢價變成資產」的實作都會破壞平衡。

### 7. LINE 拿不到群組成員名單

開局是「貼卡片 → 大家自己點進來」的**拉**模式。`groupId` 是局的容器，**不是成員名單**。

任何依賴「讀取群組成員」的設計都做不到。詳見 [docs/09](docs/09-line-integration.md#2-最重要的一件事line-不會給你群組成員名單)。

---

## 職責邊界

| 動作 | 路徑 |
|---|---|
| **讀**局狀態 | 前端 → Supabase 直連（RLS 保護） |
| **寫**任何東西 | 前端 → Next.js BFF → FastAPI → Postgres |
| **即時推播** | 僅即時配對型：Postgres → Supabase Realtime → 前端 |

沒有任何 State 層資料表對一般使用者開放 `INSERT`/`UPDATE`/`DELETE`。RLS 能限制「改哪一列」，但擋不住「把 cash 改成 99999999」。

**日常型不開常駐 Realtime 連線。** Supabase Realtime 上限是 Free 200 / Pro 500 並發，這是本專案最先撞到的天花板。前端不直接呼叫 `supabase.channel()`，一律經 `lib/realtime/` 的 `RealtimeAdapter`。日常型唯一需要準即時的是認購競標，用 15 秒輪詢即可。

### 日常型的兩種推進路徑都要上鎖

```
玩家在當日任意時間行動  ─┐
                        ├─→ 同一局的 game state
每日 00:00 daily_settlement ─┘
```

00:00 正是「今天最後一刻」，一定有人趕著出價——競態**必然發生**。`daily_settlement` 除了 advisory lock 之外還必須**冪等**（依 `resolved_at` 判斷，重跑不重複退款），且單局失敗不影響其他局。

---

## 設計信條

**經濟共生（Zero-Sum Economy）。** A 踩到 B 的飯店付 $2,000，帳上就是 A −$2,000、B +$2,000。系統不憑空創造也不憑空銷毀貨幣。唯二例外是薪資／利息注入與稅捐回收，兩者都在 `config/` 中列明。

推論：
- **不賣數值。** 內購僅限外觀與便利性。賣數值會讓產品唯一的差異化消失。
- 稅金進國庫池（`games.treasury`）而非銷毀，供紓困類事件卡支付。
- 破產者資產歸還無主而非歸債權人——這是對信條的刻意例外，理由是避免滾雪球讓局勢中期就鎖死。

---

## 專案結構

```
config/          版本化遊戲數值 → game_configs 表。改這裡不改程式碼
                 scale / identities / occupations / properties / board /
                 endgame / events / stocks / vehicles / insurance /
                 loans / alliances / confinement
apps/backend/src/assetrush/
  engine/        ★ 純函式規則引擎，零 I/O
  services/      engine ↔ DB 橋接，advisory lock 在這層
  jobs/          APScheduler 排程
  sim/           蒙地卡羅模擬
apps/frontend/
  app/(web)/     獨立網站：SSR + RSC
  app/(liff)/    LINE Mini App：全 CSR（LIFF SDK 需要 window）
  lib/realtime/  RealtimeAdapter 抽象
supabase/migrations/
```

---

## 常用指令

```bash
make install         # 前後端相依
make dev             # web + api 同時起
make test lint
make migrate seed
make simulate GAMES=10000 MODE=blitz PLAYERS=6   # 平衡驗證
make verify-game GAME_ID=...                      # 重放事件流比對快照
make sync-stocks etl-towns                        # 手動觸發資料同步
```

---

## 開發順序

**P1（純規則引擎 + 蒙地卡羅）必須在任何 UI 之前完成。**

`docs/02-game-balance.md §9` 的數值推演是手算的，過程中就抓到兩個會讓遊戲當場壞掉的錯誤（資產門檻低於某些玩家的起始資產、30 人局破產門檻過早觸發）。手算能抓到的有限——P1 的八項模擬驗證全部通過才進 P2。

先做 UI 再回頭調數值，等於每次調整都要重測整條 UI 流程。

完整階段見 [docs/08-roadmap.md](docs/08-roadmap.md)。

---

## 外部資料

| 來源 | 端點 | 狀態 |
|---|---|---|
| TWSE OpenAPI | `openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL` | 免費無金鑰，2026-08-06 實測可用 |
| 內政部實價登錄 | `lvr.land.moi.gov.tw` / `data.gov.tw` | 無 API，季度批次檔 |

**真正需要即時的只有遊戲自己的局狀態。** 外部資料全是日更（T+1）或季更，且全部有 fallback——外部資料源失效不能阻斷遊戲。

**開發期（P1–P4）完全不需要跑爬蟲。** `config/stocks.json` 的 `seed_price` 是 2026-08-05 TWSE 的真實收盤快照，離線可跑、CI 不打外部服務。P5 才接每日同步。

TWSE 的 `Change` 欄位是**價差不是漲跌幅**，且停牌個股會回傳 `"--"`。解析與防禦集中在 ETL 一處，`stock_prices.daily_return` 寫入時就算好，引擎端只讀乾淨數字。

ETF 下市與改代號比想像中頻繁（`00679B` 已於 2026-08 消失），`seed_stocks` 執行時要比對現行清單並警告。

---

## 文件

| 文件 | 內容 |
|---|---|
| [docs/00-product-overview.md](docs/00-product-overview.md) | 產品定位、雙模式、商業模式 |
| [docs/01-game-rules.md](docs/01-game-rules.md) | 完整規則書（機制） |
| [docs/02-game-balance.md](docs/02-game-balance.md) | 數值、機率、金額（數字） |
| [docs/03-map-system.md](docs/03-map-system.md) | 368 鄉鎮 → 32 格抽樣 |
| [docs/04-economy-and-realdata.md](docs/04-economy-and-realdata.md) | 股市、房價、真實數據 |
| [docs/05-data-model.md](docs/05-data-model.md) | Postgres schema、RLS |
| [docs/06-architecture.md](docs/06-architecture.md) | 架構評估、風險清單 |
| [docs/07-design-system.md](docs/07-design-system.md) | 配色、風格、shadcn |
| [docs/08-roadmap.md](docs/08-roadmap.md) | 開發階段（為什麼是這個順序） |
| [docs/09-line-integration.md](docs/09-line-integration.md) | LINE Mini App 設定、群組資料界線、送審 |
| [docs/10-milestones.md](docs/10-milestones.md) | **M0–M11 交付清單、Config 驅動契約、Onboarding** |

改規則時：`01` 描述機制、`02` 描述數字、`config/` 是可執行的真實來源。三者必須同步。

---

## Config 驅動是硬需求

**目標：改規則 = 改 JSON，不改程式碼。** 這不會自動發生，是 M1 必須刻意設計的架構：

| 元件 | 作用 |
|---|---|
| **Effect Registry** | 卡片/落點/貸款效果查表分派，**不寫 if/else**。新增效果 = 加一個 `@effect` handler，只加不改 |
| **公式求值器** | `"NW * 0.03"` 用 `ast` 白名單求值，**禁用 `eval`** |
| **Config schema** | 載入時驗證型別 + 跨檔不變式（權重總和、效果類型存在、交叉引用） |
| **`make validate-config`** | CI 第一道關卡，打錯鍵名在 commit 就擋下 |

驗收標準見 [docs/10 §2.3](docs/10-milestones.md#23-驗收標準m1-完成的判準)——**不改任何 `.py`/`.ts`，只改 JSON 就能完成五項指定變更**。

**明確做不到也不該做的**：改變回合結構。那是遊戲本質，寫在引擎裡是對的。

---

## ⚠️ 規則與數值都還沒定稿

| | 現況 | 何時定稿 |
|---|---|---|
| **規則**（`docs/01`） | 初稿。**14 條邊界情況沒有答案**（認購者破產怎麼辦、凍結現金算不算總資產…），v1 範圍未切割 | **M1** |
| **數值**（`config/*.json`、`docs/02`） | 全是手算推導、未經驗證 | **M3**（蒙地卡羅） |

實作前先讀 [docs/10 §5 M1](docs/10-milestones.md#m1--規則定稿--config-引擎最關鍵也最長) 的邊界情況清單。**不要自己編答案**——遇到文件沒寫的情況，先問，別猜。

`docs/02` 的數值表格應由 `make sync-balance-doc` 從 config 自動產生，人只維護推導與理由。
