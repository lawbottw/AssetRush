# 07 — 設計系統：視覺風格與配色

> 文件版本 v0.1｜2026-08-06
> shadcn/ui + Tailwind v4 + OKLCH

---

## 1. 風格決定：扁平幾何卡通，**不採像素風**

使用者要求「簡易 + 卡通風格、最低成本、盡量避免人工美術或動畫、全部以程式能完成為主」，並提到像素／馬賽克風可能較容易。

**評估結果：像素風在這個專案裡反而比較貴。**

| | 像素／馬賽克風 | 扁平幾何卡通 ✅ |
|---|---|---|
| 資產來源 | 每個 sprite 都要**逐格手繪**（建築 5 級 × 24 種鄉鎮風貌、頭像部件、道具…） | 純 CSS/SVG 由參數生成 |
| 新增一種建築等級 | 重畫一整套 sprite | 改幾個 SVG 參數 |
| 不同 DPR / 螢幕縮放 | 非整數倍縮放會糊掉或產生鋸齒，須為多種尺寸各出一套 | 向量，任意縮放銳利 |
| 深色模式 | 每張圖要出兩套 | CSS 變數自動切換 |
| 與 shadcn 的一致性 | 衝突（shadcn 是扁平現代語彙），需大量覆寫 | 天然一致 |
| 品牌置入替換 | 贊助商 logo 要「像素化」才不突兀，實務上做不到 | 直接放 SVG logo |
| RWD | 像素風在窄螢幕縮小後不可讀 | 元件自適應 |

**像素風的「便宜」是幻覺**——它便宜在「可以畫得很醜也沒關係」，但**畫的動作本身還是人工美術**，而這正是使用者要避免的。扁平幾何的資產是**程式碼**，不是圖檔。

### 1.1 所有視覺元素的實作方式（零圖檔）

| 元素 | 實作 |
|---|---|
| 棋盤格 | CSS Grid + 圓角 div |
| 建築（L0–L4） | 參數化 SVG：`<rect>` 疊窗戶格線，高度／窗數／屋頂隨等級變化 |
| 玩家棋子 | SVG 圓形 + 膠囊身體，填玩家色 |
| 頭像 | 參數化 SVG 部件組合（見 §5） |
| 骰子 | CSS 3D `transform` + `@keyframes` 翻滾 |
| 金錢／道具圖示 | `lucide-react`（shadcn 內建） |
| 圖表（資產曲線、股價） | 純 SVG `<path>`，或 Recharts |
| 區域色帶、價格條 | CSS 變數 + `linear-gradient` |
| 載入骨架 | shadcn `Skeleton` |
| 慶祝特效 | CSS 粒子動畫（`@keyframes` + `transform`），零 JS 函式庫 |

**唯一需要人工的圖檔是 app icon 與 OG image。** 其餘全部是程式碼。

---

## 2. 配色

### 2.1 主題概念：「台幣綠 × 財經儀表板」

主色取翡翠綠——它同時指向金錢、成長與新台幣的視覺記憶，而且刻意避開太飽和的正綠（那會讀成醫療或環保）。輔以暖砂底色讓棋盤有紙板桌遊的溫度，避免整體看起來像券商 App。

### 2.2 語意色（Tailwind v4 / OKLCH）

```css
/* apps/web/app/globals.css */
:root {
  --background:          oklch(0.98 0.005 85);
  --foreground:          oklch(0.22 0.02 160);

  --card:                oklch(1 0 0);
  --card-foreground:     oklch(0.22 0.02 160);
  --popover:             oklch(1 0 0);
  --popover-foreground:  oklch(0.22 0.02 160);

  /* 主色：翡翠綠 — 金錢、成長、主 CTA */
  --primary:             oklch(0.62 0.15 162);
  --primary-foreground:  oklch(0.99 0.01 162);

  /* 次色：暖砂 — 棋盤底、卡片背景 */
  --secondary:           oklch(0.94 0.03 85);
  --secondary-foreground:oklch(0.30 0.04 85);

  /* 強調：金桔橙 — 骰子、獎勵、次要 CTA */
  --accent:              oklch(0.72 0.17 55);
  --accent-foreground:   oklch(0.20 0.03 55);

  --muted:               oklch(0.95 0.01 85);
  --muted-foreground:    oklch(0.52 0.02 160);

  /* 破壞性：朱紅 — 破產、扣款、刪除 */
  --destructive:         oklch(0.58 0.21 25);
  --destructive-foreground: oklch(0.99 0.01 25);

  --border:              oklch(0.90 0.01 85);
  --input:               oklch(0.90 0.01 85);
  --ring:                oklch(0.62 0.15 162);
  --radius:              0.75rem;
}

.dark {
  --background:          oklch(0.19 0.02 160);
  --foreground:          oklch(0.95 0.01 85);

  --card:                oklch(0.24 0.02 160);
  --card-foreground:     oklch(0.95 0.01 85);
  --popover:             oklch(0.24 0.02 160);
  --popover-foreground:  oklch(0.95 0.01 85);

  --primary:             oklch(0.70 0.15 162);
  --primary-foreground:  oklch(0.16 0.03 162);

  --secondary:           oklch(0.30 0.02 85);
  --secondary-foreground:oklch(0.92 0.02 85);

  --accent:              oklch(0.76 0.16 55);
  --accent-foreground:   oklch(0.18 0.03 55);

  --muted:               oklch(0.28 0.01 160);
  --muted-foreground:    oklch(0.68 0.02 160);

  --destructive:         oklch(0.65 0.19 25);
  --destructive-foreground: oklch(0.98 0.01 25);

  --border:              oklch(0.32 0.01 160);
  --input:               oklch(0.32 0.01 160);
  --ring:                oklch(0.70 0.15 162);
}
```

### 2.3 ⚠️ 台股紅漲綠跌 — 必須獨立的語意變數

**這是本專案最容易被寫錯、且錯了會讓全台灣使用者讀反資訊的一條。**

台灣股市的慣例是**紅色代表上漲、綠色代表下跌**，與歐美相反。而 shadcn 的預設語意是 `destructive`（紅）= 負面、`success`（綠）= 正面。

若直接把行情數字綁到 `destructive` / `success`，畫面上「台積電 +2.3%」會是綠色——台灣使用者會直覺讀成「跌了」。

```css
:root {
  /* 台股語意：紅漲綠跌。絕不複用 destructive / success */
  --market-up:            oklch(0.58 0.20 22);   /* 紅 = 漲 */
  --market-up-foreground: oklch(0.99 0.01 22);
  --market-up-subtle:     oklch(0.95 0.04 22);   /* 背景底色用 */

  --market-down:            oklch(0.58 0.15 155); /* 綠 = 跌 */
  --market-down-foreground: oklch(0.99 0.01 155);
  --market-down-subtle:     oklch(0.94 0.03 155);

  --market-flat:          oklch(0.55 0.01 160);
}

.dark {
  --market-up:          oklch(0.66 0.19 22);
  --market-up-subtle:   oklch(0.28 0.06 22);
  --market-down:        oklch(0.66 0.14 155);
  --market-down-subtle: oklch(0.26 0.04 155);
  --market-flat:        oklch(0.62 0.01 160);
}
```

**強制規則（寫入 `CLAUDE.md`）：**

> 任何顯示漲跌的元素一律使用 `--market-up` / `--market-down`。
> `--destructive` 只用於「玩家的錢變少」（付租金、罰款、破產）。
> 這兩者在視覺上都是紅色，但語意完全不同，不可互相替代。

**注意一個弔詭的交集**：股票下跌會讓玩家資產減少，但它必須顯示為**綠色**（台股語意），而付租金導致的現金減少要顯示為**紅色**（損失語意）。這不是矛盾，是兩套並存的慣例——實作時依「這個數字描述的是市場行情還是我的收支」來選擇。

### 2.4 無障礙備援

紅綠色盲在台灣男性約 8%，而紅綠正是這款遊戲最關鍵的資訊維度。

**所有漲跌顯示必須同時帶符號**，不能只靠顏色：

```
▲ +2.35%   （紅）
▼ −1.08%   （綠）
━  0.00%   （灰）
```

設定中提供「色盲友善模式」，將 `--market-up` 改為橙色系、`--market-down` 改為藍色系。這是一次性的 CSS 變數覆寫，成本極低。

### 2.5 `@theme inline` 註冊

Tailwind v4 需要把 CSS 變數註冊成 utility：

```css
@import "tailwindcss";
@import "tw-animate-css";

@theme inline {
  --color-background:      var(--background);
  --color-foreground:      var(--foreground);
  --color-primary:         var(--primary);
  --color-secondary:       var(--secondary);
  --color-accent:          var(--accent);
  --color-destructive:     var(--destructive);
  --color-muted:           var(--muted);
  --color-border:          var(--border);

  /* 市場語意 */
  --color-market-up:       var(--market-up);
  --color-market-down:     var(--market-down);
  --color-market-flat:     var(--market-flat);

  /* 六大區域 */
  --color-region-north:    var(--region-north);
  --color-region-taoyuan:  var(--region-taoyuan);
  --color-region-central:  var(--region-central);
  --color-region-south:    var(--region-south);
  --color-region-kaoping:  var(--region-kaoping);
  --color-region-east:     var(--region-east);

  --radius-lg: var(--radius);
  --radius-md: calc(var(--radius) - 2px);
  --radius-sm: calc(var(--radius) - 4px);
}
```

之後即可用 `text-market-up`、`bg-region-north` 等 utility。

---

## 3. 六大區域色帶

取代經典大富翁的地產色組。因為棋盤每局都不同（見 [03](03-map-system.md)），玩家沒有棋盤記憶可依賴，**色帶是辨識地理歸屬的主要線索**。

| 區域 | CSS 變數 | 淺色 | 深色 |
|---|---|---|---|
| 北北基 | `--region-north` | `oklch(0.55 0.16 265)` 靛藍 | `oklch(0.66 0.15 265)` |
| 桃竹苗 | `--region-taoyuan` | `oklch(0.62 0.12 200)` 青綠 | `oklch(0.72 0.11 200)` |
| 中彰投 | `--region-central` | `oklch(0.72 0.15 70)` 琥珀 | `oklch(0.78 0.14 70)` |
| 雲嘉南 | `--region-south` | `oklch(0.58 0.16 35)` 赭紅 | `oklch(0.68 0.15 35)` |
| 高屏 | `--region-kaoping` | `oklch(0.60 0.19 350)` 桃紅 | `oklch(0.70 0.17 350)` |
| 宜花東離島 | `--region-east` | `oklch(0.55 0.15 300)` 紫 | `oklch(0.66 0.14 300)` |

六色在 OKLCH 中的**色相間距均勻**（265 / 200 / 70 / 35 / 350 / 300），且明度都控制在 0.55–0.72，確保：
- 彼此可辨
- 與 `--primary`（162 翡翠綠）色相距離夠遠，不會混淆
- 與 `--market-up`（22 紅）／`--market-down`（155 綠）也拉開距離

⚠️ **雲嘉南赭紅（35）與 market-up 紅（22）色相僅差 13。** 兩者不會出現在同一個視覺脈絡（色帶在格子頂端、漲跌在股市面板），但棋盤上同時顯示租金變化時需注意。緩解方式：色帶固定為**細條狀**（4px），漲跌數字固定帶符號與較大字重，形狀差異足以區辨。

---

## 4. 棋盤格的視覺編碼

每格必須在一眼內傳達四件事：

```
┌──────────────────────┐
│ ████████████████████ │ ← 區域色帶（4px）
│  信義區               │ ← 鄉鎮名（14px, semibold）
│  台北市               │ ← 縣市（11px, muted）
│  ▮▮▮▮▮               │ ← 價格條（1–5 格，tier）
│                      │
│      ▄▄▄▄▄▄          │ ← SVG 建築（依等級）
│      █ □ █           │
│  ────────────        │
│  $440,000            │ ← 基價
└──────────────────────┘
   ╰─ 邊框 = 地主的玩家色（無主則為 border）
```

### 4.1 建築的 SVG 參數化

```tsx
// 完全由等級推導，零圖檔
const BUILDING = {
  0: { floors: 0, width: 0,  label: '素地' },
  1: { floors: 1, width: 24, label: '套房' },
  2: { floors: 2, width: 30, label: '公寓' },
  3: { floors: 4, width: 34, label: '大樓' },
  4: { floors: 6, width: 40, label: '商辦' },
} as const;

function Building({ level, color }: { level: 0|1|2|3|4; color: string }) {
  const { floors, width } = BUILDING[level];
  if (!floors) return <EmptyLot />;
  const h = floors * 9 + 6;
  return (
    <svg viewBox={`0 0 ${width} ${h}`} className="w-full h-auto">
      <rect x="0" y="6" width={width} height={h - 6} rx="2" fill={color} />
      {/* 屋頂 */}
      <path d={`M-2 6 L${width / 2} 0 L${width + 2} 6 Z`} fill={color} opacity="0.75" />
      {/* 窗戶格線 */}
      {Array.from({ length: floors }).map((_, f) =>
        Array.from({ length: Math.floor(width / 12) }).map((_, c) => (
          <rect key={`${f}-${c}`}
            x={5 + c * 12} y={11 + f * 9} width="6" height="5"
            rx="1" fill="var(--card)" opacity="0.85" />
        ))
      )}
    </svg>
  );
}
```

一個 40 行的元件涵蓋全部 5 個等級 × 任意顏色。**這就是「不採像素風」的具體收益**。

---

## 5. 參數化頭像

不用第三方頭像服務（外部依賴 + LINE WebView 的網路成本），自建部件組合。

| 部件 | 選項數 |
|---|---|
| 臉型 | 4 |
| 髮型 | 8 |
| 髮色 | 6 |
| 眼睛 | 5 |
| 嘴巴 | 5 |
| 膚色 | 5 |
| 配件（眼鏡、口罩、無…） | 5 |
| 背景色 | 8 |

**組合數 = 4×8×6×5×5×5×5×8 = 960,000 種**

每個部件是一段 SVG `<path>`，全部部件加起來約 200 行程式碼。存在 `users.avatar_config` 的只是一組索引：

```json
{ "face": 2, "hair": 5, "hairColor": 1, "eyes": 3, "mouth": 0, "skin": 2, "accessory": 4, "bg": 6 }
```

**內購的造型商品就是解鎖額外的部件索引**——新增一個髮型 = 新增一段 `<path>`，零美術外包。

---

## 6. 動效

全部 CSS，不引入動畫函式庫。

| 動效 | 實作 | 時長 |
|---|---|---|
| 骰子翻滾 | `@keyframes` + `transform: rotateX/Y` | 800ms |
| 棋子移動 | 逐格 `transition: transform`，每格 120ms | 依步數 |
| 金額變化 | 數字跳動（`requestAnimationFrame` 補間）+ 顏色閃爍 | 400ms |
| 購地成功 | 建築由 `scale(0)` 彈出，`cubic-bezier(.34,1.56,.64,1)` | 500ms |
| 破產 | 資產卡片依序淡出下墜 | 1200ms |
| 壟斷達成 | 該縣市所有格的色帶脈動 + CSS 粒子 | 1500ms |
| 回合倒數（即時配對型） | 20 秒環形進度條，最後 5 秒轉為 `--destructive` 並脈動 | 20s |
| 認購被超越（日常型） | 出價卡片抖動 + 新最高價數字翻牌 | 600ms |
| 每日結算揭曉 | 認購結果逐格翻牌，得標者高亮 | 依格數 |

### 6.1 尊重系統偏好

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

棋子移動改為直接跳到終點，遊戲仍完全可玩。

---

## 7. 字體

LINE WebView 的載入時間直接影響首次體驗，字體是最大的單一資產。

| 用途 | 字體 | 策略 |
|---|---|---|
| 中文介面 | **Noto Sans TC** | **subset 化**，只保留遊戲用得到的字（介面詞彙 + 368 個鄉鎮名 + 縣市名 + 職業／卡片文案），約 2,500 字 → 從 ~7MB 降到 ~250KB |
| 數字／金額 | **系統等寬**（`ui-monospace`, `SF Mono`, `Menlo`） | 零下載。金額對齊需要等寬 |
| 英文／代號 | 系統 sans | 零下載 |

**subset 的字表由建置腳本從 `config/*.json` + `towns` 表 + i18n 檔自動產生**，而不是手動維護——新增一張事件卡就自動納入其中的字。

```makefile
subset-font:        ## 產生 subset 字型
	cd apps/web && pnpm tsx scripts/build-font-subset.ts
```

---

## 8. LINE Mini App 的特殊考量

| 限制 | 對策 |
|---|---|
| 可視高度比一般瀏覽器小（上方有 LINE 標題列） | 棋盤在手機採捲動長條 + 迷你環（見 [03 §6.2](03-map-system.md#62-手機直式捲動長條--迷你環)），不用正方環 |
| LIFF 初始化 300–800ms 的空白 | 純 CSS 的棋盤 skeleton 立即渲染 |
| 使用者可能隨時被 LINE 訊息打斷 | 所有狀態伺服器端保存，回來時無縫接續 |
| 分享卡片是 Flex Message（非網頁） | 戰報需另外設計 Flex JSON 版面，配色沿用同一組 OKLCH → 轉 hex |
| 深色模式跟隨 LINE 而非系統 | 監聽 `liff.getContext()` 並提供手動切換 |

### 8.1 戰報 Flex Message

Flex Message 不支援 CSS 變數，需把 OKLCH 轉成 hex 常數。維護方式是在建置時由 `globals.css` 自動產生一份 `theme.flex.json`，避免兩處手動同步。

---

## 9. shadcn 設定

```json
// apps/web/components.json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "app/globals.css",
    "baseColor": "neutral",
    "cssVariables": true
  },
  "iconLibrary": "lucide",
  "aliases": {
    "components": "@/components",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

Tailwind v4 下 `tailwind.config` 為空字串（設定已移入 CSS）。`baseColor` 選 `neutral` 後再由 §2.2 的變數覆寫。

### 9.1 會用到的元件

| 元件 | 用途 |
|---|---|
| `Button` `Card` `Badge` | 全域 |
| `Dialog` `Drawer` | 購地確認、交易 offer（手機用 Drawer） |
| `Tabs` | 資產 / 股票 / 交易 / 排行 |
| `Table` | 持股、排行榜 |
| `Progress` | 回合倒數（即時配對型）、今日進度（日常型） |
| `Avatar` | 玩家頭像 |
| `Tooltip` `HoverCard` | 格子詳情 |
| `Sonner` | 事件通知 |
| `Skeleton` | LIFF 載入 |
| `Sheet` | 手機側邊選單 |
| `Slider` | 交易金額、股數 |
| `Switch` | Standing Orders 開關 |
| `Alert` | 反壟斷警告（見 [01 §7.4](01-game-rules.md#74-反壟斷保護)） |

---

## 10. 設計原則摘要

| 原則 | 說明 |
|---|---|
| **零圖檔** | 除 app icon 與 OG image 外，所有視覺由程式生成 |
| **紅漲綠跌獨立語意** | `--market-up` / `--market-down` 絕不複用 `destructive` / `success` |
| **顏色不是唯一訊息** | 漲跌必帶 ▲▼ 符號；地主必有邊框色 + 頭像 |
| **色帶承擔記憶負擔** | 棋盤每局不同，區域色與價格條取代棋盤記憶 |
| **深色模式是一等公民** | 所有變數皆有 `.dark` 對應，不是事後加的 |
| **動效可被關閉** | `prefers-reduced-motion` 下仍完整可玩 |
| **字體 subset 由建置產生** | 不手動維護字表 |
