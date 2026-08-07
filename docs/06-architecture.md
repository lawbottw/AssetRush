# 06 — 技術架構評估

> 文件版本 v0.1｜2026-08-06
> 本文件回答使用者的直接提問：**「Next.js 是否足夠好、能做到？」**

---

## 1. 結論先講

**夠。但前提是 Next.js 絕對不能持有遊戲的權威狀態。**

Next.js 在這個專案裡是**渲染層與 BFF**，不是遊戲伺服器。所有規則判定、擲骰、回合推進、金額計算都在 FastAPI。

把 Next.js 當遊戲伺服器用，會在三個地方立刻壞掉：

| 問題 | 原因 |
|---|---|
| 回合競態 | Serverless function 無狀態、可任意並行。兩個 request 同時推進同一局的回合，沒有共用記憶體可以放鎖 |
| 排程作業 | 日常型的 `daily_settlement`（每日 00:00 仲裁全部認購 + 託管 + 推播）是關鍵路徑，需要交易性與冪等性。Vercel Cron 無狀態且會超時 |
| 規則引擎的可測性 | 遊戲規則需要跑蒙地卡羅模擬驗證平衡（[02 §9](02-game-balance.md#11-可玩性推演) 的手算推導需要程式複驗）。規則若散在 API routes 裡，就無法離線批量執行 |

這三件事在 FastAPI 都是常規操作。**技術棧的選擇本身沒問題，職責劃分才是關鍵。**

---

## 2. 架構總覽

```
┌──────────────────────┐   ┌──────────────────────┐
│  LINE Mini App       │   │  獨立網站 (PWA)       │
│  (LIFF / WebView)    │   │                      │
│  /liff/*  全 CSR      │   │  /  SSR + RSC        │
└──────────┬───────────┘   └──────────┬───────────┘
           └───────────┬──────────────┘
                       ↓
        ┌──────────────────────────────────┐
        │  Next.js 15 (App Router)         │
        │  · 渲染層 + BFF                   │
        │  · Auth 交換、LIFF token 驗證      │
        │  · 不做遊戲邏輯                    │
        └──────────┬───────────────────────┘
                   │ 內部 HTTP (server-only)
                   ↓
        ┌──────────────────────────────────┐
        │  FastAPI (uv)                    │
        │  · 唯一的規則引擎                  │
        │  · 伺服器端骰子 RNG                │
        │  · 回合狀態機 + advisory lock      │
        │  · APScheduler 排程                │
        └──────────┬───────────────────────┘
                   │ service_role
                   ↓
        ┌──────────────────────────────────┐
        │  Supabase                        │
        │  · Postgres (RLS)                │
        │  · Realtime (僅即時配對型)             │
        │  · Auth                          │
        └──────────────────────────────────┘
                   ↑
                   └── 前端「讀取」直連（RLS 保護）
```

### 2.1 資料流的兩條路徑

| 動作 | 路徑 |
|---|---|
| **讀**局狀態 | 前端 → Supabase（直連，RLS 保護） |
| **寫**任何東西 | 前端 → Next.js BFF → FastAPI → Postgres |
| **即時推播**（即時配對型） | Postgres → Supabase Realtime → 前端 |

讀取直連 Supabase 省掉一整層轉發，且 RLS 已經表達了「誰能看什麼」。寫入絕不直連——原因見 [05 §6.3](05-data-model.md#63-寫入一律走-fastapi)。

---

## 3. 風險清單

依嚴重度排序。**前兩項是這個專案真正會出事的地方**，其餘是常規工程問題。

### 風險 1 🔴 並發回合競態

**情境**：

| 模式 | 競態場景 |
|---|---|
| 即時配對型 | 玩家 A 點「結束回合」的同時，20 秒倒數逾時觸發 Standing Orders → 回合被推進兩次 |
| **日常型** | **00:00 `daily_settlement` 開始仲裁認購的同時，玩家 A 正在出價** → 出價可能被算進今天、也可能被漏掉、或現金被重複凍結 |

日常型的場景**必然發生**——非同步意味著玩家隨時可能在結算邊界上操作，而 00:00 正是「今天最後一刻」，會有人趕著出價。

**對策：雙層鎖**

```python
# 第一層：Postgres advisory lock，序列化同一局的所有寫入
async with db.begin():
    await db.execute(
        text("select pg_advisory_xact_lock(hashtext(:gid))"),
        {"gid": str(game_id)},
    )

    # 第二層：turn_seq 樂觀鎖，擋掉過期的請求
    result = await db.execute(
        text("""
            update games
               set current_turn_seq = current_turn_seq + 1, ...
             where id = :gid and current_turn_seq = :expected_seq
         returning current_turn_seq
        """),
        {"gid": game_id, "expected_seq": client_seq},
    )
    if result.rowcount == 0:
        raise StaleTurnError()   # 客戶端拿著舊狀態，要求重新拉取
```

`pg_advisory_xact_lock` 在 transaction 結束時自動釋放，不會有忘記解鎖的問題。以 `game_id` 為鎖鍵，不同局之間完全不互相阻塞。

**每一個會改變局狀態的 API 都必須走這個模式。** 這條規則寫進 `CLAUDE.md`。

**`daily_settlement` 的額外要求：冪等。**

它是日常型唯一的關鍵路徑，一旦中途失敗必須能安全重跑：

```python
# 依 resolved_at 判斷，不重複退款、不重複推進
update property_claims set status = ..., resolved_at = now()
 where game_id = :gid and game_day = :day and resolved_at is null
```

且**單局失敗不能影響其他局**——每局各自 transaction，失敗只記錄並跳過。

---

### 風險 2 🔴 Supabase Realtime 並發連線上限

**實際數字**（已查證）：

| 方案 | 並發 Realtime 連線 |
|---|---|
| Free | 200 |
| Pro ($25/月) | **500** |

**這是本專案最先會撞到的天花板。** 500 個並發連線 ≈ 500 位同時在線玩家。以即時配對型每桌 6 人計，只能支撐 **83 桌同時進行**。

對一個目標是「病毒式擴散到大量 LINE 群組」的產品，這個數字很快就不夠。

**對策：只有即時配對型開 Realtime**

這是[兩種模式參數差異](01-game-rules.md#16-兩種模式的參數差異)表最後一列的技術理由。

| 模式 | 連線策略 | 理由 |
|---|---|---|
| **日常型** | **不開常駐連線** | 非同步行動，玩家每天只上線 3–5 分鐘。開 App 時拉一次最新狀態即可。用 WebSocket 掛著 24 小時只為了等一天一次的結算，是純粹的浪費 |
| **即時配對型** | 常駐 WebSocket | 20 秒一回合，必須即時看到別人在骰什麼 |

**非同步改制讓這個決策更站得住腳。** 第一版的日常型還有「輪到你了」需要即時通知；現在連那個都沒有了——玩家想玩就玩，唯一的同步點是每日 00:00 的結算，而那由推播處理。

唯一需要準即時的是**認購競標**（「有人加價了」希望能即時看到）。對策是**輪詢而非 WebSocket**：開著出價畫面時每 15 秒拉一次。以每天實際出價的人數估算，這個流量遠低於常駐連線的成本。

日常型是主打模式，也是玩家數量的大宗。把它從 Realtime 移開，等於把連線壓力集中在即時配對型這個規模小得多的族群上。

**升級路徑**（撞到 500 之後）：

| 階段 | 方案 |
|---|---|
| 短期 | 聯繫 Supabase 客製上限（官方支援超出 Pro 的自訂配額） |
| 中期 | 自架 open-source Supabase Realtime（Elixir/Phoenix，本身可承載數百萬連線） |
| 長期 | 即時配對型改用 FastAPI 自建 SSE/WebSocket，Realtime 只留給 presence |

**架構上要先做的事**：把即時層抽象成一個 `RealtimeAdapter` 介面，前端不直接呼叫 `supabase.channel()`。這樣日後換實作不必改動遊戲程式碼。這件事在 P3 就要做，而不是等撞牆才做。

---

### 風險 3 🟡 骰子公平性的信任問題

朋友之間玩、且有內購——**「系統是不是讓我骰爛好逼我課金」這個質疑一定會出現。**

**對策：Commit–Reveal**（規則見 [01 §2.2](01-game-rules.md#22-骰子公平性保證commitreveal)）

```python
# 開局：產生 seed，只公布 hash
server_seed = secrets.token_hex(32)
games.server_seed_hash = hashlib.sha256(server_seed.encode()).hexdigest()
# server_seed 存在 DB 但不透過 PostgREST 暴露（見 05 §6.2）

# 每次擲骰：確定性推導
def roll(server_seed: str, game_id: str, turn_seq: int, player_id: str) -> int:
    msg = f"{game_id}:{turn_seq}:{player_id}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") % 6 + 1

# 局結束：公開 server_seed，任何人可驗算每一次擲骰
```

局末的戰報上附一個「驗證骰子」連結，玩家可自行核對。**成本極低，但它消除了一整類客訴。**

---

### 風險 4 🟡 LIFF 必須 client-side 初始化

LIFF SDK 需要 `window`，在 RSC / SSR 環境會直接爆掉。

**對策：路由分軌**

```
app/
  (web)/            ← 獨立網站：SSR + RSC，完整 Next.js 能力
    page.tsx
    games/[id]/page.tsx
  (liff)/           ← LINE Mini App：全 CSR
    layout.tsx      ← 'use client'，dynamic import LIFF SDK
    liff/[...]/page.tsx
```

```tsx
// app/(liff)/layout.tsx
'use client';
import { useEffect, useState } from 'react';

export default function LiffLayout({ children }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    (async () => {
      const liff = (await import('@line/liff')).default;
      await liff.init({ liffId: process.env.NEXT_PUBLIC_LIFF_ID! });
      if (!liff.isLoggedIn()) return liff.login();
      setReady(true);
    })();
  }, []);
  if (!ready) return <BoardSkeleton />;
  return children;
}
```

**代價**：LINE 版失去 SSR 的首屏優勢。緩解方式是把棋盤骨架做成純 CSS 的 skeleton（見 [07](07-design-system.md)），在 LIFF 初始化的 300–800ms 內就有東西可看。

**兩軌共用同一套 component**，差異只在資料取得方式與 auth 來源。這是路由群組而非兩個專案的原因。

---

### 風險 5 🟡 iOS LINE WebView 的 session 掉失

LINE 在 iOS 用 WKWebView 開啟 Mini App。第三方 cookie 政策、ITP、以及 in-app browser 的儲存隔離都可能讓 session 消失。

**對策**：

| 項目 | 設定 |
|---|---|
| Cookie | `SameSite=None; Secure; HttpOnly`（缺 `Secure` 在 `SameSite=None` 下會被直接丟棄） |
| 網域 | Next.js 與 API 走**同一個 apex domain**（`assetrush.tw` / `api.assetrush.tw`），避免跨站 |
| 備援 | LIFF 的 `liff.getIDToken()` 隨時可重新取得身分。session 掉失時靜默重新交換，不要求使用者重登 |
| 儲存 | 不依賴 `localStorage` 存 auth（WKWebView 清除策略不可預期），只做 UI 偏好 |

**這一項必須在真機上測**——iOS + LINE 的組合無法用桌機瀏覽器模擬。列為 P6 的驗收條件。

---

### 風險 6 🟡 規則引擎的可測性

[02 §9](02-game-balance.md#11-可玩性推演) 的數值推演是**手算**的，而且推演過程本身就抓到兩個會讓遊戲當場壞掉的錯誤（資產門檻低於某些玩家的起始資產、30 人局破產門檻過早觸發）。手算能抓到的問題有限。

**對策：規則引擎必須是可離線執行的純函式**

```python
# packages/engine/  ← 零 I/O、零 DB、零 HTTP
def apply_action(state: GameState, action: Action, config: Config) -> tuple[GameState, list[Event]]:
    ...
```

如此可以：

```bash
make simulate GAMES=10000 MODE=daily PLAYERS=10
# → 輸出：勝率 vs 起始身分的相關性、平均局長、破產時點分布、
#         各結束條件的觸發比例、進修的實際回報率
```

**這是 P1 的核心交付，而且必須在任何 UI 之前完成。** 先做 UI 再回頭調數值，等於每次調整都要重測整條 UI 流程。

---

### 風險 7 🟢 外部資料源

TWSE OpenAPI 無 SLA、實價登錄是季度批次檔。

**已在 [04 §6](04-economy-and-realdata.md#6-fallback-策略) 完整處理。** 核心原則：外部資料源失效不能阻斷遊戲，所有降級路徑都指向「遊戲繼續，只是真實性下降」。

實務上這是最低風險項——因為[真正需要即時的只有遊戲自己的狀態](04-economy-and-realdata.md#1-資料即時性分級)，外部資料全是日更或季更。

---

## 4. Next.js 的具體使用界線

### 4.1 可以做

| 用途 | 說明 |
|---|---|
| RSC 渲染大廳、歷史戰報、靜態頁 | 這些是讀取密集、無狀態的頁面 |
| Server Actions 處理表單 | 建立局、修改暱稱、Standing Orders 設定 |
| BFF 聚合 | 把「局狀態 + 我的持股 + 待處理 offer」合併成一次請求 |
| Auth token 交換 | LIFF ID token → Supabase JWT |
| 靜態資產與 PWA manifest | |

### 4.2 不可以做

| 反模式 | 為什麼 |
|---|---|
| 在 API Route 裡判定遊戲規則 | 無法上 advisory lock、無法離線模擬 |
| 在 Server Action 裡直接寫 `games` 表 | 繞過回合鎖 |
| 用 Vercel Cron 跑回合推進 | 無狀態、超時、無法保證 exactly-once |
| 在前端計算租金／資產再送給後端 | 客戶端可竄改 |
| 用 `revalidatePath` 當作即時同步機制 | 那是快取失效，不是推播 |

**檢驗標準：把 Next.js 整個換成一個純 SPA，遊戲仍應完全正常運作。** 如果做不到，代表遊戲邏輯漏到渲染層去了。這條寫進 `CLAUDE.md`。

---

## 5. 專案結構

```
AssetRush/
├── Makefile                  # 所有操作的唯一入口
├── CLAUDE.md
├── docs/
├── config/                   # 版本化的遊戲數值（見 02 §10）
│   ├── scale.json
│   ├── identities.json
│   ├── occupations.json
│   ├── properties.json
│   ├── endgame.json
│   ├── events.json
│   ├── stocks.json
│   ├── vehicles.json
│   └── insurance.json
├── apps/
│   ├── frontend/             # Next.js 15
│   │   ├── app/
│   │   │   ├── (web)/        # SSR + RSC
│   │   │   └── (liff)/       # 全 CSR
│   │   ├── components/ui/    # shadcn
│   │   └── lib/
│   │       ├── realtime/     # RealtimeAdapter 抽象（見風險 2）
│   │       └── api/          # FastAPI client
│   └── backend/              # FastAPI (uv)
│       ├── pyproject.toml
│       └── src/assetrush/
│           ├── engine/       # ★ 純函式規則引擎，零 I/O
│           │   ├── state.py
│           │   ├── actions.py
│           │   ├── rules/
│           │   ├── board.py  # 32 格抽樣（見 03 §3）
│           │   └── rng.py    # commit-reveal
│           ├── routers/
│           ├── services/     # engine ↔ DB 的橋接，advisory lock 在這層
│           ├── jobs/         # APScheduler（見 04 §5）
│           └── sim/          # 蒙地卡羅模擬（見風險 6）
└── supabase/
    └── migrations/
```

**`engine/` 是這個專案唯一不可妥協的邊界。** 它不能 import 任何 DB、HTTP、或 Supabase 相關的東西。這個約束讓蒙地卡羅模擬、單元測試、與未來可能的離線單機模式都成為可能。

---

## 6. Makefile

> **真實來源是 repo 根目錄的 `Makefile`**，以下是設計意圖。兩處實作上的差異：
> `dev` 不能用 `make -j2`（GnuWin32 make 3.81 在 Windows 不支援 `-j`，會靜默退回
> `-j1`，結果只有一邊起得來），改為單一 recipe 內背景執行 + `trap` 記 PID。

```makefile
.PHONY: install dev build test lint migrate seed simulate

install:            ## 安裝前後端相依
	cd apps/frontend && pnpm install
	cd apps/backend && uv sync

dev:                ## 同時啟動 frontend + backend
	# 實作見根目錄 Makefile：背景執行 + trap，不用 make -j2
dev-frontend:
	cd apps/frontend && pnpm dev
dev-backend:
	cd apps/backend && uv run uvicorn assetrush.main:app --reload --port 8000

build:
	cd apps/frontend && pnpm build
	cd apps/backend && uv build

test:
	cd apps/backend && uv run pytest
	cd apps/frontend && pnpm test

lint:
	cd apps/backend && uv run ruff check . && uv run mypy src
	cd apps/frontend && pnpm lint

migrate:            ## 套用 Supabase migration
	supabase db push

seed:               ## 灌入 towns / stocks / config
	cd apps/backend && uv run python -m assetrush.scripts.seed_towns
	cd apps/backend && uv run python -m assetrush.scripts.seed_stocks
	make seed-config

seed-config:        ## config/*.json → game_configs 表
	cd apps/backend && uv run python -m assetrush.scripts.seed_config

sync-stocks:        ## 手動觸發 TWSE 同步
	cd apps/backend && uv run python -m assetrush.jobs.sync_stock_prices

etl-towns:          ## 手動觸發實價登錄 ETL
	cd apps/backend && uv run python -m assetrush.jobs.etl_town_prices

simulate:           ## 蒙地卡羅平衡驗證（見風險 6）
	cd apps/backend && uv run python -m assetrush.sim.run \
		--games $(or $(GAMES),1000) \
		--mode $(or $(MODE),blitz) \
		--players $(or $(PLAYERS),6)

verify-game:        ## 重放事件流並比對快照（見 05 §5.3）
	cd apps/backend && uv run python -m assetrush.scripts.verify_game $(GAME_ID)
```

---

## 7. 部署與成本

| 元件 | 方案 | 月成本估算 |
|---|---|---|
| Next.js | Vercel Hobby → Pro | $0 → $20 |
| FastAPI | Fly.io / Railway（需常駐，因為有排程器） | $5 – $25 |
| Supabase | Free → Pro | $0 → $25 |
| **合計（早期）** | | **$0 – $70/月** |

**FastAPI 不能部署在 serverless**——APScheduler 需要常駐 process。這是選擇 Fly.io / Railway 而非 Vercel Functions 的原因。

### 7.1 成本的第一個轉折點

不是流量，是 **Supabase Realtime 的 500 連線上限**（風險 2）。到達時的選擇：

- 客製配額（跟 Supabase 談，成本未知）
- 自架 Realtime（一台 $20/月的機器可跑數萬連線，但多了維運）

因為日常型不佔連線，這個轉折點會來得比預期晚很多——**這正是那個設計決策的價值**。

---

## 8. 技術決策摘要

| 決策 | 選擇 | 理由 |
|---|---|---|
| 遊戲邏輯放哪 | **FastAPI** | 需要 advisory lock、常駐排程、離線模擬 |
| Next.js 的角色 | **渲染層 + BFF** | 換成純 SPA 遊戲也該能跑 |
| 讀取路徑 | **前端直連 Supabase** | 省一層轉發，RLS 已表達可見性 |
| 寫入路徑 | **一律經 FastAPI** | RLS 擋不住「把 cash 改成 99999999」 |
| 即時層 | **僅即時配對型用 Realtime** | 500 連線上限是最先撞到的天花板 |
| 即時層抽象 | **RealtimeAdapter 介面** | 日後換實作不改遊戲程式碼 |
| 規則引擎 | **純函式、零 I/O** | 可蒙地卡羅模擬，這是平衡工作的前提 |
| 骰子 | **伺服器端 HMAC + commit-reveal** | 消除公平性客訴 |
| LINE 整合 | **路由群組分軌，全 CSR** | LIFF 需要 window |
| Config | **開局 snapshot 版本** | 21 天的局期間一定會改數值 |
