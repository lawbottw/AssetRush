# 05 — 資料模型

> 文件版本 v0.1｜2026-08-06｜Supabase Postgres

---

## 1. 三層資料分類

專案的所有資料落入三層，**各層的變更節奏、擁有者、失效影響完全不同**，混在一起是災難的開始。

| 層 | 內容 | 誰改 | 頻率 | 改了會怎樣 |
|---|---|---|---|---|
| **Config** | 遊戲規則數值（機率、金額、費率） | 開發者 | 版本發布時 | **不能影響進行中的局** |
| **Reference** | 外部真實資料（鄉鎮房價、股價） | 排程 job | 日更／季更 | 只影響新開的局 |
| **State** | 對局狀態（誰在哪、誰有什麼） | 遊戲引擎 | 每個動作 | 就是遊戲本身 |

### 1.1 關鍵設計：開局時 snapshot config

```
局開始 → 記錄 config_version → 整局都讀這個版本的設定
```

沒有這個機制，任何一次數值調整都會讓進行中的局規則突變——日常型的局要跑 21 天，這段期間我們一定會改數值。

同樣的原則套用在 Reference 層：**32 格的基價在開局時寫入 `board_tiles` 固化**，季度房價 ETL 不影響進行中的局。

**局一旦開始，它的世界就凍結了。**

---

## 2. Config 層

### 2.1 `game_configs`

```sql
create table game_configs (
  version       text primary key,              -- '2026.08.1'
  payload       jsonb not null,                -- 所有 config/*.json 合併後的內容
  is_active     boolean not null default false,-- 新局採用哪一版
  released_at   timestamptz not null default now(),
  notes         text
);

create unique index on game_configs (is_active) where is_active;
```

`payload` 的結構對應 [02 §10](02-game-balance.md#12-設定檔對照) 的設定檔清單：

```json
{
  "scale":       { "K": 0.4, "gamma": 1.0, "lap_per_quarter": 1 },
  "identities":  { ... },
  "occupations": { ... },
  "properties":  { ... },
  "board":       { ... },
  "endgame":     { ... },
  "events":      { ... },
  "stocks":      { ... },
  "vehicles":    { ... },
  "insurance":   { ... },
  "loans":       { ... },
  "alliances":   { ... },
  "confinement": { ... }
}
```

**為什麼用單一 jsonb 而不是拆成關聯表：** 這些數值只被規則引擎整包讀取、從不做關聯查詢，且必須整組原子性地版本化。拆成十張表只會讓「取得 v2026.08.1 的完整規則」變成十次 join。

`config/*.json` 是版控在 repo 裡的真實來源，`make seed-config` 會把它們合併後 UPSERT 進這張表。

---

## 3. Reference 層

### 3.1 `towns` — 368 個鄉鎮市區

```sql
create table towns (
  code                text primary key,        -- 行政區代碼 '63000050'
  name                text not null,           -- '信義區'
  county              text not null,           -- '台北市'
  region              text not null,           -- '北北基'
  population          integer not null,
  avg_price_per_ping  numeric(12,0),           -- 元/坪，季更
  price_tier          smallint,                -- 1-5，隨房價重算
  txn_count           integer,                 -- 上季交易筆數（判斷資料可信度）
  is_imputed          boolean default false,   -- 是否為補值（交易量 < 10）
  is_active           boolean default true,
  updated_at          timestamptz default now()
);

create index on towns (region);
create index on towns (county);
create index on towns (price_tier) where is_active;
```

### 3.2 `town_price_history`

```sql
create table town_price_history (
  town_code           text references towns(code),
  quarter             text not null,           -- '2026Q2'
  avg_price_per_ping  numeric(12,0) not null,
  txn_count           integer,
  primary key (town_code, quarter)
);
```

每年長 1,472 列。保留給未來的「房價走勢」玩法（見 [04 §8](04-economy-and-realdata.md#8-未來可接的真實數據v2)）。

### 3.3 `stocks` — 50 檔標的

```sql
create type etf_kind as enum ('none','passive','active');

create table stocks (
  code        text primary key,       -- '2330' / '00980A'
  name        text not null,          -- '台積電'
  sector      text,                   -- 個股用
  style       text,                   -- ETF 用：'市值型' '高股息' 'AI主題'...
  etf_kind    etf_kind not null default 'none',
  seed_price  numeric(10,2),          -- 真實收盤快照，供 P1–P4 離線使用
  is_active   boolean default true
);
```

30 個股 + 8 被動 ETF + **12 主動式 ETF**（代號結尾 `A`）。

`seed_price` 是 2026-08-05 TWSE 的**真實收盤快照**，不是虛構值——讓 P1–P4 完全不依賴外部 API（見 [04 §3.6](04-economy-and-realdata.md#36-開發期的種子資料)）。

### 3.4 `stock_prices` — 每日收盤

```sql
create table stock_prices (
  code           text references stocks(code),
  trade_date     date not null,
  close_price    numeric(10,2),
  change_amount  numeric(10,2),
  daily_return   numeric(8,6),   -- 已算好並夾在 ±10%，引擎直接讀這欄
  raw            jsonb,          -- TWSE 原始回傳，保留供除錯
  primary key (code, trade_date)
);

create index on stock_prices (trade_date desc);
```

**`daily_return` 在寫入時就算好**，而不是查詢時計算。因為 TWSE 的 `Change` 是價差不是漲跌幅，而且原始資料有 `"--"` 之類的髒值（見 [04 §3.3](04-economy-and-realdata.md#35-漲跌幅計算與防禦)）——把解析與防禦集中在 ETL 一處，引擎端就永遠拿到乾淨的數字。`raw` 保留原始 JSON，出問題時可回溯。

一年約 9,800 列。

### 3.5 `market_calendar`

```sql
create table market_calendar (
  trade_date  date primary key,
  is_open     boolean not null,
  source      text not null      -- 'api' | 'manual' | 'inferred'
);
```

---

## 4. State 層

### 4.1 `games`

```sql
create type game_mode   as enum ('blitz', 'daily');
create type game_status as enum ('lobby','recruiting','starting','active','settling','finished','aborted');

create table games (
  id                uuid primary key default gen_random_uuid(),
  mode              game_mode not null,
  status            game_status not null default 'lobby',

  config_version    text not null references game_configs(version),
  game_seed         bigint not null,          -- 棋盤抽樣 + 骰子種子來源
  server_seed_hash  text not null,            -- 開局公布
  server_seed       text,                     -- 僅結算後公開
  board_theme       text default 'standard',

  host_user_id      uuid not null references users(id),
  line_group_id     text,                     -- 來自 LINE 群組的局

  -- 開局時計算並固定（即時配對型由目標時長反推，見 02 §4.2）
  player_count_at_start  smallint,
  target_minutes         smallint,            -- 即時配對型：房主選的 20/30/45
  total_tiles            smallint,            -- 自動配置或依人數查表
  lap_limit              smallint,            -- 即時配對型 2-12；日常型 21
  net_worth_threshold    numeric(14,0),       -- 動態門檻，見 02 §4.3
  bankrupt_threshold     smallint,            -- 觸發結束所需的破產人數

  -- 進度
  current_turn_seq  integer not null default 0,   -- 樂觀鎖版本號（兩模式共用）
  current_day       integer not null default 0,   -- 日常型：第幾天（＝第幾圈）
  current_player_id uuid,                         -- 僅即時配對型有意義
  turn_deadline     timestamptz,                  -- 僅即時配對型：20 秒倒數

  treasury          numeric(14,0) not null default 0,  -- 國庫池

  created_at        timestamptz default now(),
  started_at        timestamptz,
  finished_at       timestamptz,
  end_reason        text                      -- 'net_worth'|'bankruptcy'|'lap_limit'|'time_limit'
);

create index on games (status, turn_deadline) where status = 'active' and turn_deadline is not null;
create index on games (status, current_day) where status = 'active';
create index on games (line_group_id);
```

`current_turn_seq` 同時是**樂觀鎖的版本號**（見 [06](06-architecture.md#風險-1--並發回合競態)）。

### 4.2 `game_players`

```sql
create table game_players (
  id              uuid primary key default gen_random_uuid(),
  game_id         uuid not null references games(id) on delete cascade,
  user_id         uuid not null references users(id),

  base_turn_order smallint not null,           -- 開局擲 1D100 決定
  player_color    text not null,               -- UI 用

  -- 身分（開局抽取）
  background_key  text not null,               -- 'ordinary' | 'wealthy' ...
  occupation_key  text not null,
  occupation_tier smallint not null,

  -- 快照狀態（權威來源仍是 game_events，這裡是物化視圖）
  cash            numeric(14,0) not null,
  debt            numeric(14,0) not null default 0,
  net_worth       numeric(14,0) not null,      -- 每次動作後重算
  position        smallint not null default 0,
  lap             smallint not null default 0,

  vehicle_key     text,
  vehicle_value   numeric(12,0) default 0,
  side_job_key    text,
  study_remaining     smallint default 0,
  jail_remaining      smallint default 0,      -- 服刑：可操作地產，但無季度事務
  hospital_remaining  smallint default 0,      -- 住院：不可操作地產，也無季度事務
  default_count       smallint default 0,      -- 貸款違約次數，3 次進黑名單
  alliance_id     uuid,                        -- 所屬家庭/伴侶
  salary_modifier numeric(4,2) default 1.0,    -- 減薪/MBA 加成的累乘

  is_bankrupt     boolean default false,
  is_idle         boolean default false,       -- 連續 3 天未親自行動
  consecutive_afk smallint default 0,
  bankrupt_at_seq integer,

  -- 日常型：非同步行動追蹤
  last_acted_day    integer default 0,         -- 最後行動的天數（＝ current_day 表示今天已動）
  acted_at          timestamptz,

  joined_at       timestamptz default now(),
  unique (game_id, user_id),
  unique (game_id, base_turn_order)
);

create index on game_players (game_id, base_turn_order) where not is_bankrupt;
create index on game_players (game_id, last_acted_day) where not is_bankrupt;
```

**`turn_window_start` / `turn_window_end` 已移除** —— 日常型改為非同步後不再有回合時窗。

**當日順位是計算欄位，不落庫**：

```sql
-- 順位每日輪替一位，只在同價競標時作為仲裁權
daily_turn_order = (base_turn_order + current_day) % alive_player_count
```

存成欄位就得每天 UPDATE 全部玩家；用算的則永遠正確且零維護成本。
```

### 4.3 `board_tiles` — 本局固化的棋盤

```sql
-- 7 種功能格 + property。exchange / dmv_academy 已移除（改由季度事務承擔）
create type tile_kind as enum
  ('start','property','opportunity','fate','tax','jail','hospital');

create table board_tiles (
  game_id      uuid not null references games(id) on delete cascade,
  idx          smallint not null,              -- 0..31
  kind         tile_kind not null,

  -- kind='property' 時填寫，開局固化（房價 ETL 不影響進行中的局）
  town_code    text references towns(code),
  town_name    text,
  county       text,
  region       text,
  base_price   numeric(12,0),
  price_tier   smallint,

  sponsor      jsonb,                          -- 品牌置入覆寫層，見 03 §5

  primary key (game_id, idx)
);
```

雖然棋盤可由 `game_seed` 完全重算，仍**物化成表**——因為「這格的地主是誰、什麼等級」的查詢每個回合都要跑，不可能每次重跑抽樣演算法。

### 4.4 `properties` — 地產持有狀態

```sql
create table properties (
  game_id        uuid not null references games(id) on delete cascade,
  tile_idx       smallint not null,
  owner_id       uuid references game_players(id),  -- null = 無主
  level          smallint not null default 0,       -- 0..4
  invested       numeric(12,0) not null default 0,  -- 累計升級投入（算市值用）
  is_mortgaged   boolean not null default false,
  frozen_by_offer uuid,                              -- 掛在交易 offer 中，不可動用
  updated_at     timestamptz default now(),
  primary key (game_id, tile_idx)
);

create index on properties (game_id, owner_id) where owner_id is not null;
```

`frozen_by_offer` 是[交易凍結](01-game-rules.md#72-交易流程)的實作——offer 送出後標的被鎖住，避免同一格地被同時賣給兩個人。日常型的 offer 有 48 小時 TTL，這段期間的一致性必須靠這個欄位保證。

**`invested` 只累計升級成本，不含[認購溢價](01-game-rules.md#-溢價是純沉沒成本)** —— 溢價是沉沒成本，不計入市值、租金或貸款額度。

### 4.5 `property_claims` — 出價認購（日常型）

```sql
create type claim_status as enum ('pending','won','lost');

create table property_claims (
  id          uuid primary key default gen_random_uuid(),
  game_id     uuid not null references games(id) on delete cascade,
  tile_idx    smallint not null,
  player_id   uuid not null references game_players(id) on delete cascade,
  bid_amount  numeric(12,0) not null,   -- >= base_price
  game_day    integer not null,
  status      claim_status not null default 'pending',
  created_at  timestamptz default now(),
  resolved_at timestamptz,

  -- 同一玩家同一天對同一格只能有一筆有效出價（加價 = UPDATE 而非新增）
  unique (game_id, tile_idx, player_id, game_day)
);

create index on property_claims (game_id, game_day, tile_idx) where status = 'pending';
create index on property_claims (game_id, player_id) where status = 'pending';
```

> **命名注意**：事件流用 `bid_*` 而非 `claim_*`，因為 `claim` 在保險語境已用於「理賠」。表名保留 `property_claims`（認購），事件則一律用 `bid`。

**仲裁邏輯**（於 `daily_settlement` 排程執行，見 [04 §5](04-economy-and-realdata.md#5-排程作業)）：

```sql
-- 每格取最高價；同價則當日順位在前者勝
select distinct on (tile_idx) id, player_id, bid_amount
  from property_claims c
  join game_players p on p.id = c.player_id
 where c.game_id = $1 and c.game_day = $2 and c.status = 'pending'
 order by tile_idx,
          bid_amount desc,
          ((p.base_turn_order + $2) % $3) asc;   -- $3 = alive_player_count
```

**設計要點：**

| 項目 | 說明 |
|---|---|
| 出價時凍結現金 | 記在 `game_players.cash` 的扣除 + 一筆 `bid_placed` 事件；落選時退款 |
| 結算前 `properties.owner_id` 仍為 `null` | 該格在當日仍是無主——別人不付租金、且可加價競標 |
| 加價用 `UPDATE` | unique 約束保證同人同格同天只有一筆，避免「出價紀錄洗版」 |
| `resolved_at` | 冪等的依據：`daily_settlement` 重跑時跳過已 resolved 的列 |

**這張表只有日常型會用。** 即時配對型是即時嚴格輪流，同一時間只有一人決策，購地立即成交、不經認購。

### 4.6 `holdings` — 持股

```sql
create table holdings (
  game_id     uuid not null references games(id) on delete cascade,
  player_id   uuid not null references game_players(id) on delete cascade,
  stock_code  text not null references stocks(code),
  shares      integer not null check (shares >= 0),
  avg_cost    numeric(10,2) not null,          -- 停損型 Standing Order 用
  primary key (game_id, player_id, stock_code)
);
```

### 4.7 `game_stock_prices` — 局內股價

```sql
create table game_stock_prices (
  game_id     uuid not null references games(id) on delete cascade,
  stock_code  text not null references stocks(code),
  price       numeric(12,2) not null,          -- 開局一律 1000.00
  last_return numeric(8,6),
  updated_lap smallint,                        -- 即時配對型：已套用到第幾圈
  updated_at  timestamptz default now(),
  primary key (game_id, stock_code)
);
```

局內股價獨立於 `stock_prices`——後者是真實世界的收盤資料，前者是套用漲跌幅後的遊戲價（見 [04 §3](04-economy-and-realdata.md#3-價格)）。

### 4.8 `alliances` — 家庭／伴侶

```sql
create type alliance_tier as enum ('couple','married','family_small','family_large');

create table alliances (
  id            uuid primary key default gen_random_uuid(),
  game_id       uuid not null references games(id) on delete cascade,
  tier          alliance_tier not null,
  name          text,                              -- 玩家自訂家庭名稱
  pool_balance  numeric(14,0) not null default 0,  -- 家庭基金
  created_at_seq integer not null,
  dissolved_at_seq integer,
  is_active     boolean default true
);

create table alliance_members (
  alliance_id     uuid not null references alliances(id) on delete cascade,
  player_id       uuid not null references game_players(id) on delete cascade,
  contributed     numeric(14,0) not null default 0,  -- 累計繳交家用，用於算持份
  joined_at_seq   integer not null,
  left_at_seq     integer,
  primary key (alliance_id, player_id)
);

create index on alliance_members (player_id);
```

**持份 = `contributed / SUM(contributed)`**，於分潤與代償時即時計算，不預存——因為每次繳交家用都會改變所有人的持份，預存等於每圈更新 N 列。

`game_players.alliance_id` 是為了避免每次讀玩家狀態都要 join `alliance_members` 而做的**刻意冗餘**，與 [§5.3](#53-快照-vs-事件的一致性) 的快照原則一致。

### 4.9 `loans` — 貸款

```sql
create type loan_kind as enum
  ('credit','mortgage','stock_pledge','student','private');

create table loans (
  id            uuid primary key default gen_random_uuid(),
  game_id       uuid not null references games(id) on delete cascade,
  player_id     uuid not null references game_players(id) on delete cascade,
  kind          loan_kind not null,
  principal     numeric(14,0) not null,
  balance       numeric(14,0) not null,
  rate_per_lap  numeric(6,4) not null,      -- 違約會上調，故存在列上而非讀 config
  collateral    jsonb,                       -- 抵押的 tile_idx[] 或質押的 stock_code[]
  opened_at_seq integer not null,
  closed_at_seq integer
);

create index on loans (game_id, player_id) where closed_at_seq is null;
```

**`rate_per_lap` 存在列上而不是每次讀 config**，因為[違約會讓該筆貸款的利率永久上調](01-game-rules.md#123-還款與違約)。這是少數「規則產生的狀態」必須落在 State 層的例子。

`collateral` 用 jsonb 而非關聯表：擔保品組合只在該筆貸款的生命週期內有意義，且從不跨貸款查詢。

### 4.10 `insurance_policies`

```sql
create table insurance_policies (
  game_id      uuid not null references games(id) on delete cascade,
  player_id    uuid not null references game_players(id) on delete cascade,
  policy_key   text not null,                  -- 'health'|'accident'|'fire'|'liability'
  active_since integer not null,               -- turn_seq
  primary key (game_id, player_id, policy_key)
);
```

---

## 5. 事件溯源

### 5.1 `game_events` — append-only

```sql
create table game_events (
  id          bigserial primary key,
  game_id     uuid not null references games(id) on delete cascade,
  turn_seq    integer not null,
  round_no    integer not null,
  actor_id    uuid references game_players(id),  -- null = 系統事件
  event_type  text not null,
  payload     jsonb not null,
  created_at  timestamptz default now()
);

create index on game_events (game_id, id);
create index on game_events (game_id, event_type);
```

**這張表是整局的權威真相，且永不修改、永不刪除。**

`event_type` 以 `apps/backend/src/assetrush/engine/event_codec.py::EVENT_TYPES` 為唯一來源。
目前完整清單如下；新增 engine Event 時，codec round-trip 測試會要求同步更新持久化契約：

| 類別 | 事件 |
|---|---|
| 通用狀態 | `cash_adjusted` `treasury_adjusted` `phase_advanced` `player_modifier_added` `pending_effect_added` |
| 回合與卡片 | `dice_rolled` `player_moved` `daily_roll_used` `landing_dispatched` `card_drawn` `health_check_triggered` `turn_skipped` |
| 日常型與認購 | `bid_placed` `bid_raised` `bid_cancelled` `bid_won` `bid_lost` `standing_orders_executed` `daily_settlement_completed` |
| 地產 | `property_purchased` `property_upgraded` `rent_paid` `property_mortgaged` `property_redeemed` `property_sold_to_bank` |
| 季度事務 | `quarterly_affairs_triggered` `salary_paid` `stock_price_advanced` `stock_bought` `stock_sold` `loan_opened` `loan_payment_made` `vehicle_purchased` `vehicle_upkeep_paid` `insurance_purchased` `insurance_premium_paid` `education_started` `education_progressed` `career_changed` `health_check_resolved` |
| 交易與清算 | `trade_offer_invalidated` `loan_defaulted` `player_blacklisted` `stock_liquidated` `vehicle_liquidated` `family_bailout_applied` `private_loan_rescue` `player_bankrupted` `bankruptcy_threshold_reached` |
| 監禁／醫療 | `player_confined` `confinement_advanced` `confinement_released` `confinement_release_paid` |
| 家庭 | `alliance_proposed` `alliance_formed` `alliance_proposal_resolved` `alliance_member_joined` `alliance_member_left` `alliance_tier_changed` `alliance_dissolved` `alliance_pool_contributed` `alliance_pool_paid` `alliance_pool_distributed` `alliance_bailout_attempted` `alliance_bailout_succeeded` `alliance_ruined` |

### 5.2 為什麼要事件溯源

一般 CRUD 就能跑遊戲。多做一層事件流是為了三件具體的事：

| 用途 | 說明 |
|---|---|
| **戰報** | 局末戰報（產品的主要擴散點，見 [00](00-product-overview.md#病毒擴散機制)）需要「最大一筆租金」「誰最早破產」這類敘事素材。有事件流，這是一句 SQL；沒有，就得在每個動作裡埋統計欄位 |
| **爭議仲裁** | 「我明明有錢為什麼破產了」——重播事件流即可完整還原 |
| **平衡分析** | 蒐集數千局的事件流，才能回答「進修真的有用嗎」「即時配對型是不是先手優勢太大」。這是 [02 §9](02-game-balance.md#11-可玩性推演) 手算推導的後續驗證來源 |

### 5.3 快照 vs 事件的一致性

`game_players.cash` 等欄位是**物化快照**，與 `game_events` 並存。

- **寫入**：同一個 transaction 內同時 append 事件 + 更新快照
- **讀取**：一律讀快照（每回合要讀好幾次，重放事件太慢）
- **校驗**：`make verify-game GAME_ID=...` 重放事件流並比對快照，CI 中對測試局固定執行

允許冗餘、但用工具強制一致——比「純事件溯源、每次讀取都重放」實際得多。

### 5.4 `trade_offers`

```sql
create type offer_status as enum ('pending','accepted','rejected','expired','cancelled');

create table trade_offers (
  id           uuid primary key default gen_random_uuid(),
  game_id      uuid not null references games(id) on delete cascade,
  from_player  uuid not null references game_players(id),
  to_player    uuid not null references game_players(id),
  give         jsonb not null,   -- {cash, properties[], stocks[], vehicle, rent_free_laps}
  want         jsonb not null,
  status       offer_status not null default 'pending',
  expires_at   timestamptz not null,
  message      text,
  created_at   timestamptz default now(),
  resolved_at  timestamptz
);

create index on trade_offers (game_id, to_player) where status = 'pending';
create index on trade_offers (expires_at) where status = 'pending';
```

同一玩家最多 5 筆 `pending`（見 [01 §7.2](01-game-rules.md#72-交易流程)），由應用層檢查。

### 5.5 `standing_orders`

```sql
create table standing_orders (
  game_id    uuid not null references games(id) on delete cascade,
  player_id  uuid not null references game_players(id) on delete cascade,
  slot       smallint not null,              -- 0..7（免費版僅 0..2）
  rule       jsonb not null,                 -- {category, condition, action, params}
  is_enabled boolean default true,
  primary key (game_id, player_id, slot)
);
```

`rule` 的形狀：

```json
{
  "category": "buy_property",
  "condition": { "cash_above": 200000, "base_price_below": 150000 },
  "action": "buy"
}
```

**這張表必須對其他玩家不可見**（見 §6 RLS）。知道對手的自動決策規則等同於看到他的底牌。

---

## 6. RLS 策略

Supabase 的 RLS 是唯一擋在前端與資料之間的東西——前端直連 Postgres 讀取局狀態（見 [06](06-architecture.md)），寫入才走 FastAPI。

### 6.1 通則

```sql
-- 所有 State 層資料表
alter table games            enable row level security;
alter table game_players     enable row level security;
alter table board_tiles      enable row level security;
alter table properties       enable row level security;
alter table holdings         enable row level security;
alter table game_events      enable row level security;
alter table trade_offers     enable row level security;
alter table standing_orders  enable row level security;
```

判斷「我是否在這局」的 helper：

```sql
create or replace function is_in_game(g uuid)
returns boolean language sql security definer stable as $$
  select exists (
    select 1 from game_players
    where game_id = g and user_id = auth.uid()
  );
$$;
```

### 6.2 公開與私密的界線

| 資料 | 可見性 | 理由 |
|---|---|---|
| `games`、`board_tiles`、`properties` | 同局玩家全可見 | 棋盤本來就攤在桌上 |
| `game_players` 的現金、資產、位置 | 同局玩家全可見 | 大富翁的錢是攤開的 |
| `game_events` | 同局玩家全可見 | 局內公開紀錄 |
| `games.server_seed` | **`status='finished'` 前全體不可見** | 可預測骰子 |
| `standing_orders` | **僅本人** | 等同底牌 |
| `trade_offers` | **僅收發雙方** | 私下議價 |
| `holdings` | 同局可見**股數**，`avg_cost` 僅本人 | 成本價會洩漏停損點 |
| `alliances` 基本資訊與成員 | 同局全可見 | 誰跟誰是一家人是公開資訊，影響所有人的決策 |
| `alliance_members.contributed` | **僅同家庭成員** | 持份是家庭內部的分配依據 |
| `loans` | 同局可見**總負債**，逐筆明細僅本人 | 總負債影響淨資產排名（公開）；借了哪幾筆是策略資訊 |
| `property_claims` | **同局全可見** | 「有幾人在搶、目前最高價、誰出的」是刻意公開的——隱藏出價會讓競標變成盲猜，而我們要的是「看到對手在搶所以我要加價」的張力 |

```sql
create policy "同局可讀" on properties
  for select using (is_in_game(game_id));

create policy "僅本人可讀寫" on standing_orders
  for all using (
    player_id in (select id from game_players where user_id = auth.uid())
  );

create policy "僅收發雙方" on trade_offers
  for select using (
    from_player in (select id from game_players where user_id = auth.uid())
    or to_player in (select id from game_players where user_id = auth.uid())
  );
```

`games.server_seed` 無法用資料列級的 RLS 遮蔽單一欄位，處理方式是**該欄位不透過 PostgREST 暴露**：建立一個排除 `server_seed` 的 view 給前端讀，原表只允許 service_role 存取。

### 6.3 寫入一律走 FastAPI

**沒有任何 State 層資料表對一般使用者開放 `INSERT` / `UPDATE` / `DELETE`。** 所有寫入由 FastAPI 以 service_role 執行。

前端直接寫入等於讓玩家自己改現金餘額。RLS 能限制「改哪一列」，但擋不住「把 cash 改成 99999999」——遊戲規則不是資料列權限能表達的。

---

## 7. 索引與資料量估算

以 1,000 個同時進行的日常型局、每局 10 人估算：

| 表 | 列數估算 | 成長來源 |
|---|---|---|
| `games` | 1,000 活躍 + 歷史累積 | 每局一列 |
| `game_players` | 10,000 | 人數 × 局數 |
| `board_tiles` | 32,000 | 32 × 局數 |
| `properties` | 24,000 | 24 × 局數 |
| `game_events` | **~6,000,000** | 每局 60 回合 × 10 人 × 約 10 事件 |
| `stock_prices` | 9,800 / 年 | 40 × 245 |
| `towns` | 368 | 固定 |

`game_events` 是唯一會長大的表。對策：

```sql
-- 依 game_id 的 hash 分區，或依時間分區
-- 局結束 90 天後，事件流壓縮為戰報 JSON 後歸檔到冷儲存
```

v1 不需要分區（600 萬列對 Postgres 是小事），但 schema 設計時把 `game_id` 放在所有索引的第一欄，讓未來要分區時不必重寫查詢。

---

## 8. 使用者與帳號

```sql
-- Supabase auth.users 之外的應用層資料
create table users (
  id            uuid primary key references auth.users(id),
  display_name  text not null,
  avatar_config jsonb,                    -- 參數化 SVG 頭像的部件組合，見 07
  line_user_id  text unique,              -- LIFF 登入
  locale        text default 'zh-TW',
  push_enabled  boolean default true,
  created_at    timestamptz default now()
);

create index on users (line_user_id);
```

**雙軌登入的帳號合併**：同一個人可能先用 LINE 玩、後來用網站登入。以 `line_user_id` 為主鍵之一做關聯，允許一個 `users` 列同時綁定 LINE 與 email。合併流程放在 P6（見 [08](08-roadmap.md)）。

---

## 9. Migration 管理

```
supabase/migrations/
  20260810000000_init_config.sql             -- game_configs
  20260825000100_init_identity_reference.sql -- users + Reference 層
  20260825000200_init_state.sql              -- 正規化 State + 私有 lossless snapshots
  20260825000300_init_events.sql             -- game_events + 非同步輔助表
  20260825000400_rls_policies.sql            -- 所有 RLS（M4 #36）
```

由 `make migrate` 執行。RLS 政策獨立成一個 migration，因為它會被反覆調整——政策改動不該和 schema 改動混在同一個檔案裡。
