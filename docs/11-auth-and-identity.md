# 11 — 身分與驗證

> 文件版本 v0.1｜2026-08-07
> 對應 milestone：設定在 **M0**（issue #5），實作在 **M5**

---

## 1. 結論先講

| 決定 | 選擇 |
|---|---|
| 驗證機制 | **Supabase Auth**（沒有實質選擇餘地，見 §2） |
| 身分來源 | LINE ID token · Email/Google · **匿名（訪客）** |
| 訪客可玩範圍 | **兩種模式都能玩**（含 21 天日常型） |
| Supabase 專案 | **1 個**，不分 dev/staging |
| 本機開發 | 直連雲端專案（不跑本地 Docker stack） |

---

## 2. 為什麼是 Supabase Auth（而不是自建）

這不太算是一個「選擇」——現有設計已經把它寫死了：

| 依據 | 位置 |
|---|---|
| `users.id uuid primary key references auth.users(id)` | [05 §8](05-data-model.md#8-使用者與帳號) |
| 全部 RLS policy 都用 `auth.uid()` | [05 §6](05-data-model.md#6-rls-策略) |
| 讀取路徑是「前端直連 Supabase，RLS 保護」 | [CLAUDE.md](../CLAUDE.md) 職責邊界 |

`auth.uid()` 讀的是 Supabase Auth 簽發的 JWT claim。**不用 Supabase Auth，就得自己簽一份 Supabase 認得的 JWT**——那是「重新實作 Supabase Auth」，不是「避開它」。

真正剩下的問題不是「用不用」，而是「LINE 這個非內建 provider 怎麼接進來」（§5）。

---

## 3. 三種身分來源

| 來源 | 進入點 | Supabase 對應 | Milestone |
|---|---|---|---|
| **LINE ID token** | LINE Mini App | 自訂流程（LINE 非內建 provider） | M5 |
| **Email / Google** | 獨立網站 | 內建 provider | M5 |
| **匿名** | 獨立網站訪客 | `signInAnonymously()` | M5 |

三者最後都落到同一個 `auth.users` 列，因此同一個 `users` 列、同一份遊戲紀錄。

### 為什麼 Mini App 裡不需要匿名

`liff.getIDToken()` 在 Mini App 裡**本來就免費給你身分**——玩家點進來的那一刻已經是登入狀態（LIFF 的 `Bot link feature` 開 Aggressive 時甚至已經是好友）。在那裡再蓋一層匿名登入是多餘的，只會讓帳號合併多一種組合要處理。

**匿名的實際適用面只有獨立網站的訪客。**

---

## 4. 訪客（匿名登入）

### 4.1 為什麼用 Supabase 的匿名登入，而不是自己發一個「訪客 ID」

因為 RLS 全靠 `auth.uid()`。自訂的訪客 ID 沒有 `auth.uid()`，訪客就讀不到任何東西，得為他們另開一條「後端代讀」路徑——那等於**維護兩套資料存取**，而且兩套的可見性規則必須手動保持一致。可見性規則寫錯的後果是洩漏底牌（`standing_orders`、`holdings.avg_cost`）。

Supabase 的匿名使用者有**真的 `auth.users` 列與真的 `auth.uid()`**，`is_in_game()` 等既有 helper 照常運作，`users.id references auth.users(id)` 的外鍵也成立。零額外分支。

需要區分匿名與正式帳號時，讀 JWT 裡的 `is_anonymous` claim：

```sql
-- 例：限制匿名使用者不能建立日常型的局（若日後決定要限制）
create policy "..." on games
  for select using (
    is_in_game(id)
    and (auth.jwt()->>'is_anonymous')::boolean is not true
  );
```

### 4.2 訪客能玩 21 天的日常型 — 風險與對策

**已定案：兩種模式都能玩。** 這裡記錄風險的實際形狀，以及 M5 必須做的對策。

**局不會卡住。** 日常型本來就有 Standing Orders 託管（[01 §13](01-game-rules.md#13-standing-orders預設指令)）與 `daily_settlement` 的自動推進（[08 P4](08-roadmap.md#p4--日常型--主打模式)）。玩家消失時系統會託管他的決策，其他 29 人不受影響。這是非同步設計本來就要處理的情況，不是訪客獨有的問題。

**真正的風險是玩家自己回不來。** 匿名帳號沒有 email、沒有密碼，session 掉了就永久失聯——而 [06 風險 5](06-architecture.md#風險-5--ios-line-webview-的-session-掉失) 已經記載 iOS WebView 的儲存策略不可預期。這是**留存問題，不是遊戲完整性問題**。

**M5 必須實作的對策：**

| 情境 | 處理 |
|---|---|
| 匿名玩家加入**日常型**局 | **強制**先取得恢復手段：綁 email，或產生一組恢復碼並要求確認已保存 |
| 匿名玩家加入**即時配對型**局 | 不強制（單局 20–45 分鐘，掉了就掉了，成本可接受） |
| 局結束時 | 引導升級為正式帳號，強調「保留戰績與稱號」 |

### 4.3 匿名 → 正式帳號的升級

Supabase 支援把匿名使用者綁定到一個 identity，**保留同一個 `auth.users.id`**：

```ts
// 綁 email
await supabase.auth.updateUser({ email: "player@example.com" });
// 綁 OAuth
await supabase.auth.linkIdentity({ provider: "google" });
```

`auth.users.id` 不變 → `users` 列不變 → **遊戲紀錄完整保留**。這是選 Supabase 匿名登入而非自訂訪客 ID 的第二個理由。

⚠️ **匿名 → LINE 的升級是例外**，因為 LINE 不是內建 provider，`linkIdentity` 用不上。這條路徑要走後端仲介，見 §5。

---

## 5. LINE 登入怎麼接（M5 待決）

LINE 不是 Supabase 內建的 OAuth provider。[09 §4.1](09-line-integration.md#41-流程) 的流程前 7 步沒有爭議：

```
1. LIFF 初始化（client-side）
2. liff.isLoggedIn() → 否則 liff.login()
3. liff.getIDToken()
4. 送到 Next.js BFF
5. 後端向 LINE 驗證 ID token（POST https://api.line.me/oauth2/v2.1/verify）★ 不可省略
6. 取出 sub（= LINE userId）
7. 對照 users.line_user_id → 找到或建立帳號
8. 簽發 Supabase JWT   ← 這一步有兩種做法
```

**第 5 步的伺服器端驗證不可省略。** 前端傳來的 ID token 必須向 LINE 驗證簽章與 audience，否則任何人都能偽造身分。

### 第 8 步的兩條路

| | (a) Auth Admin API | (b) 自簽 JWT |
|---|---|---|
| 做法 | 後端用 service_role 呼叫 Admin API 建立/取得 user，再產生 session | 用專案的 JWT secret 自行簽一份 Supabase 格式的 JWT |
| 優點 | 走官方路徑，refresh token 由 Supabase 管理 | 不依賴 Admin API 的行為 |
| 風險 | Admin API 的介面可能變動 | **Supabase 已在推非對稱簽章金鑰，對稱 secret 的長期可用性未定** |

[09 §4.1](09-line-integration.md#41-流程) 目前寫的是 (b)。

> ⚠️ **這是待驗證項，不是已定案。** M5 開始時要用當下的 Supabase dashboard 實際確認 JWT secret 是否仍可取得、是否仍被 GoTrue 接受。若非對稱金鑰已成為預設，(a) 是唯一可行路徑。**不要在 M5 之前假設任一條路可行。**

### 匿名 → LINE 的升級

`linkIdentity` 用不上，要走後端仲介：後端同時持有**匿名使用者的 JWT**（證明呼叫者是誰）與**已驗證的 LINE sub**，然後合併兩者。合併規則沿用 [09 §4.2](09-line-integration.md#42-雙軌帳號合併)：

- LINE userId 未被使用 → 綁到匿名那一列
- LINE userId 已屬於別的帳號 → **要求使用者選擇保留哪一個**，不自動合併
- **有進行中的局時不允許合併**，提示等該局結束

---

## 6. Session 與 Cookie

沿用 [06 風險 5](06-architecture.md#風險-5--ios-line-webview-的-session-掉失)：

| 項目 | 設定 |
|---|---|
| Cookie | `SameSite=None; Secure; HttpOnly` |
| 網域 | Next.js 與 API 走同一個 apex domain |
| 備援 | session 掉失時用 `liff.getIDToken()` 靜默重新交換，不要求重登 |
| 儲存 | 不用 `localStorage` 存 auth，只做 UI 偏好 |

**匿名使用者沒有「靜默重新交換」這條備援**——這正是 §4.2 要強制恢復手段的原因。

---

## 7. 寫入路徑的授權（M4/M5）

RLS 只保護**讀取**。所有寫入經 FastAPI，FastAPI 以 service_role 執行（[05 §6.3](05-data-model.md#63-寫入一律走-fastapi)）——service_role 繞過全部 RLS，因此**授權判斷完全是 FastAPI 的責任**：

1. 驗證請求帶的 Supabase JWT（簽章 + 過期）
2. 取出 `sub` → `users.id`
3. 確認該使用者是這局的參與者，且輪到他行動
4. 才進 services 層（advisory lock → engine → 寫入）

第 3 步不能靠 RLS，因為 service_role 看不到 RLS。這個中介層是 M5 的交付。

---

## 8. 環境變數與機密邊界

| 變數 | 放哪 | 機密 |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `apps/frontend/.env.local` | 否 |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `apps/frontend/.env.local` | 否（權限由 RLS 決定） |
| `SUPABASE_SERVICE_ROLE_KEY` | `apps/backend/.env` | **★ 是——可繞過全部 RLS** |
| `DATABASE_URL` | `apps/backend/.env` | ★ 是 |
| `LINE_CHANNEL_SECRET` | `apps/backend/.env` | ★ 是 |

前後端各自一個環境檔，**機密只存在後端那份**——用檔案邊界執行「service_role key 絕不進前端」，比用註解提醒可靠。變數清單見 [README](../README.md#環境變數)。

`apps/frontend/scripts/check-no-secrets.mjs`（`pnpm check-secrets`）是第二道防線，CI 會跑：

1. `NEXT_PUBLIC_*` 的名稱不得含 `SERVICE_ROLE` / `SECRET` / `PRIVATE` / `PASSWORD`
2. `next build` 的產物不得出現 `service_role` 字樣或後端 `.env` 的機密值

---

## 9. Supabase 專案設定

**只開一個專案**，不分 dev/staging。理由：staging 的價值來自「有 prod 可以對照，驗證 migration 在同構環境跑得過」；現在沒有 prod、沒有真實使用者、也還沒有任何 migration，staging 只是第二個一模一樣的空資料庫。而免費方案每個組織只有 2 個 active project，現在用滿，M10 要上 prod 時就得付費或砍掉 staging。

M10 上線前再開 prod，屆時現有專案自然轉為 staging 的角色。

| Dashboard 設定 | 值 | 時機 |
|---|---|---|
| Region | Northeast Asia (Tokyo) | 建專案時 |
| Auth → Anonymous sign-ins | **啟用** | 建專案時 |
| Auth → Email | 啟用 | 建專案時 |
| Auth → Google | 啟用 | M5 |
| Auth → CAPTCHA | 啟用 | **M10**（見 §10） |

---

## 10. M10 上線前的防濫用

**現在刻意不做**——這些設定在開發期只會擋住自己。列在這裡是為了上線前不會漏掉。

| 項目 | 為什麼需要 |
|---|---|
| 匿名登入的 CAPTCHA | 匿名登入是無限開帳號的入口 |
| 匿名登入的 rate limit | 同上 |
| 廢棄匿名帳號回收 | N 天無活動且未加入任何局的匿名帳號應清除，否則 `auth.users` 無限成長 |

---

## 11. 待辦

| 項目 | Milestone |
|---|---|
| 建立 Supabase 專案、開啟匿名登入 | **M0**（issue #5） |
| `users` 表 migration + RLS | M4 |
| FastAPI 的 JWT 驗證中介層（§7） | M5 |
| LINE ID token 驗證 + 第 8 步選路（§5） | M5 |
| 匿名 → 正式帳號的升級流程 | M5 |
| 日常型的匿名恢復手段強制流程（§4.2） | M5 |
| 帳號合併（LINE ↔ email） | M5 |
| Onboarding 11 步的畫面與狀態機 | M5，見 [10 §5 M5](10-milestones.md#m5--身分與-onboarding) |
| 防濫用（§10） | M10 |
