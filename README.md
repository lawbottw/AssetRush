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
make dev-frontend  # 只起 Next.js
make dev-backend   # 只起 FastAPI
```

連接埠衝突時：`make dev FRONTEND_PORT=3101 BACKEND_PORT=8101`。

```bash
make ci            # lint + test + build，等同 CI 會跑的東西
make check-engine  # ★ 只跑 engine 零 I/O 邊界檢查
make help          # 列出全部 target
```

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
```

## engine 零 I/O 是硬邊界

`apps/backend/src/assetrush/engine/` 不得直接或間接依賴 DB / HTTP / web framework。
規則引擎必須能離線跑蒙地卡羅模擬，M3 的全部價值建立在這件事上。

CI 有獨立的 job 做 AST 靜態掃描（`scripts/check_engine_purity.py`），會沿著
`assetrush.*` 的 import 遞迴，`if TYPE_CHECKING:` 與函式內的延遲 import 一樣擋。
在 engine 裡加一行 `import httpx`，CI 就是紅的。

## 目前進度

M0 專案骨架。P1（純規則引擎 + 蒙地卡羅）尚未開始——**規則與數值都還沒定稿**，
細節見 [docs/10-milestones.md](docs/10-milestones.md)。
