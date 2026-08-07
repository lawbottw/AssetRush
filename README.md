# AssetRush 資產狂潮

多人同步大富翁．台灣真實金融版。LINE Mini App + 獨立網站雙軌。

規格與設計決策全部在 [docs/](docs/)，開發約束在 [CLAUDE.md](CLAUDE.md)。

## 需求

| 工具 | 版本 | 備註 |
|---|---|---|
| Node | ≥ 20.13 | CI 跑 22 |
| pnpm | 10.x | `corepack enable` |
| Python | 3.12 | 由 uv 自動安裝 |
| uv | ≥ 0.5 | |
| make | GNU Make | Windows 用 Git Bash |

## 起手式

```bash
make install       # pnpm install + uv sync
make dev           # frontend :3000 + backend :8000（Ctrl+C 一起收掉）
```

要連 Supabase 的話，依下方「環境變數」建立 `apps/backend/.env` 與 `apps/frontend/.env.local`。

連接埠衝突時：`make dev FRONTEND_PORT=3101 BACKEND_PORT=8101`。

```bash
make dev-frontend  # 只起 Next.js
make dev-backend   # 只起 FastAPI
make check-db      # 驗證 Supabase 連線
make ci            # lint + test + build，等同 CI 會跑的東西
make check-engine  # ★ 只跑 engine 零 I/O 邊界檢查
make help          # 列出全部 target
```

沒填 `.env` 也起得來——M0 還沒有任何端點依賴 DB，啟動時只會記一則警告。

## 環境變數

**這張表是唯一的來源。** 前後端各自一個檔案，機密只存在後端那份——用檔案邊界執行
「service_role key 絕不進前端」，比用註解提醒可靠。

| 變數 | 檔案 | 機密 | 來源 |
|---|---|---|---|
| `SUPABASE_URL` | `apps/backend/.env` | | Dashboard → Settings → API |
| `SUPABASE_ANON_KEY` | `apps/backend/.env` | | 同上 |
| `SUPABASE_SERVICE_ROLE_KEY` | `apps/backend/.env` | **★** | 同上 |
| `DATABASE_URL` | `apps/backend/.env` | **★** | Settings → Database → **Session pooler** |
| `FRONTEND_ORIGINS` | `apps/backend/.env` | | 逗號分隔 |
| `LINE_*` | `apps/backend/.env` | **★** | M5 / M10 才需要，見 [docs/09](docs/09-line-integration.md) |
| `NEXT_PUBLIC_SUPABASE_URL` | `apps/frontend/.env.local` | | 同上 |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `apps/frontend/.env.local` | | 權限由 RLS 決定 |
| `NEXT_PUBLIC_API_BASE_URL` | `apps/frontend/.env.local` | | FastAPI 位址，預設 `http://localhost:8000` |
| `NEXT_PUBLIC_LIFF_ID` | `apps/frontend/.env.local` | | M10 才需要 |

`DATABASE_URL` 有兩個會卡住的地方：

1. **要用 Session pooler（port 5432）**，不是 Direct connection（IPv6-only，家用網路多半不通），
   也不是 Transaction pooler（6543，與 asyncpg 的 prepared statement 衝突）
2. 複製下來後開頭改成 `postgresql+asyncpg://`

```
postgresql+asyncpg://postgres.<ref>:<密碼>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

**`NEXT_PUBLIC_` 前綴的值一律會進瀏覽器 bundle。** `pnpm check-secrets` 會擋下違反這條的
命名與編譯產物，CI 有跑（見下方）。

身分與驗證的完整架構見 [docs/11-auth-and-identity.md](docs/11-auth-and-identity.md)。

## 結構

```
config/              版本化遊戲數值 → game_configs 表。改這裡不改程式碼
apps/backend/        FastAPI (uv)
  src/assetrush/
    engine/          ★ 純函式規則引擎，零 I/O（鐵律 2）
    services/        engine ↔ DB 橋接，advisory lock 在這層
    routers/ jobs/ sim/
  scripts/           check_engine_purity.py 等維運腳本
apps/frontend/       Next.js 15
  app/(web)/         獨立網站：SSR + RSC
  app/(liff)/        LINE Mini App：全 CSR
  lib/supabase/      讀取路徑的 client（寫入一律經 FastAPI）
  scripts/           check-no-secrets.mjs
```

## 兩條寫成 CI 檢查的規則

慣例是：**重要的約束不寫成註解提醒，寫成會讓 CI 變紅的檢查。**

### engine 零 I/O

`apps/backend/src/assetrush/engine/` 不得直接或間接依賴 DB / HTTP / web framework。
規則引擎必須能離線跑蒙地卡羅模擬，M3 的全部價值建立在這件事上。

`scripts/check_engine_purity.py` 做 AST 靜態掃描，沿著 `assetrush.*` 的 import 遞迴，
`if TYPE_CHECKING:` 與函式內的延遲 import 一樣擋。在 engine 裡加一行 `import httpx`，CI 就紅。

### 機密不進前端 bundle

`SUPABASE_SERVICE_ROLE_KEY` 可以繞過全部 RLS，一旦進了瀏覽器 bundle 與 CDN 快取就等於永久外洩。

`apps/frontend/scripts/check-no-secrets.mjs` 兩層檢查：`NEXT_PUBLIC_*` 的**命名**不得含
`SERVICE_ROLE` / `SECRET` / `PRIVATE` / `PASSWORD`；`next build` 的**產物**不得出現
`service_role` 字樣或後端 `.env` 的機密值。兩層都在 CI 跑。

## 目前進度

M0 專案骨架。P1（純規則引擎 + 蒙地卡羅）尚未開始——**規則與數值都還沒定稿**，
細節見 [docs/10-milestones.md](docs/10-milestones.md)。
