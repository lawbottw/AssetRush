# AssetRush — 所有操作的唯一入口。
#
# 相容性：POSIX（make + sh）與 Windows Git Bash（GnuWin32 make 3.81 + sh.exe）。
# `dev` 刻意不用 `make -j2`：GnuWin32 make 3.81 在 Windows 上不支援 -j，會靜默
# 退回 -j1，結果只有 frontend 起得來。改用單一 recipe 內背景執行 + trap，兩邊都準。

FRONTEND := apps/frontend
BACKEND  := apps/backend
FRONTEND_PORT ?= 3000
BACKEND_PORT  ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install dev dev-frontend dev-backend build build-frontend build-backend \
        test test-frontend test-backend lint lint-frontend lint-backend \
        check-engine check-db migrate bootstrap-test-db verify-game m4-check \
        validate-config seed-config sync-balance-doc \
        check-balance-doc play-cli play-cli-offline simulate m1-check format clean ci

help:               ## 列出所有 target
	@echo "AssetRush make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sed -e 's/:.*## /\t/' -e 's/^/  /'

install:            ## 安裝前後端相依
	pnpm install
	cd $(BACKEND) && uv sync

dev:                ## 同時啟動 frontend + backend（Ctrl+C 一起收掉）
	@echo "frontend -> http://localhost:$(FRONTEND_PORT)"
	@echo "backend  -> http://localhost:$(BACKEND_PORT)/health"
	@trap 'kill $$BACKEND_PID $$FRONTEND_PID 2>/dev/null; exit 0' INT TERM; \
	( cd $(BACKEND) && uv run uvicorn assetrush.main:app --reload --port $(BACKEND_PORT) ) & \
	BACKEND_PID=$$!; \
	( cd $(FRONTEND) && pnpm dev --port $(FRONTEND_PORT) ) & \
	FRONTEND_PID=$$!; \
	wait

dev-frontend:       ## 只起 Next.js
	cd $(FRONTEND) && pnpm dev --port $(FRONTEND_PORT)

dev-backend:        ## 只起 FastAPI
	cd $(BACKEND) && uv run uvicorn assetrush.main:app --reload --port $(BACKEND_PORT)

build: build-backend build-frontend  ## 建置前後端

build-frontend:
	cd $(FRONTEND) && pnpm build
	cd $(FRONTEND) && pnpm check-secrets:build

build-backend:
	cd $(BACKEND) && uv build

test: test-backend test-frontend     ## 跑所有測試

test-backend:
	cd $(BACKEND) && uv run pytest

test-frontend:
	cd $(FRONTEND) && pnpm test

check-engine:       ## ★ 鐵律 2：engine/ 零 I/O 邊界檢查
	cd $(BACKEND) && uv run python scripts/check_engine_purity.py

validate-config:    ## ★ M1：驗證 config/*.json schema 與跨檔不變式
	cd $(BACKEND) && uv run python scripts/validate_config.py --config-dir ../../config

seed-config:        ## ★ M1：config/*.json → game_configs（需要 DB）
	cd $(BACKEND) && uv run python scripts/seed_config.py --config-dir ../../config --activate

sync-balance-doc:   ## ★ M1：用 config/*.json 更新 docs/02 的數值摘要
	cd $(BACKEND) && uv run python scripts/sync_balance_doc.py --config-dir ../../config --doc ../../docs/02-game-balance.md --write

check-balance-doc:  ## ★ M1：檢查 docs/02 的 config 摘要是否同步
	cd $(BACKEND) && uv run python scripts/sync_balance_doc.py --config-dir ../../config --doc ../../docs/02-game-balance.md --check

check-db:           ## 驗證 Supabase 連線（需要網路，刻意不掛在 lint 下）
	cd $(BACKEND) && uv run python scripts/check_db.py

migrate:            ## ★ M4：依序套用 supabase/migrations（需要 DB）
	cd $(BACKEND) && uv run python scripts/migrate.py

bootstrap-test-db:  ## M4: create Supabase primitives; refuses non-local databases
	cd $(BACKEND) && uv run python scripts/bootstrap_test_db.py

verify-game:        ## M4: replay GAME_ID and compare DB snapshots/read models
	cd $(BACKEND) && uv run python scripts/verify_game.py --game-id $(GAME_ID)

m4-check: bootstrap-test-db migrate  ## M4: isolated DB suite, including 1,000 races
	cd $(BACKEND) && uv run pytest -q tests/test_migrations_integration.py tests/test_rls_integration.py tests/test_game_store_integration.py tests/test_games_api_integration.py tests/test_game_verifier_integration.py

lint: check-engine validate-config check-balance-doc lint-backend lint-frontend  ## engine 邊界 + config + docs 同步 + 機密外洩 + ruff + mypy + eslint + tsc

lint-backend:
	cd $(BACKEND) && uv run ruff check .
	cd $(BACKEND) && uv run ruff format --check .
	cd $(BACKEND) && uv run mypy src scripts

lint-frontend:
	cd $(FRONTEND) && pnpm lint
	cd $(FRONTEND) && pnpm typecheck
	cd $(FRONTEND) && pnpm check-secrets

m1-check: check-engine validate-config check-balance-doc  ## M1 收尾驗證（不碰 DB）
	cd $(BACKEND) && uv run pytest tests/test_engine_core_types.py tests/test_formula.py tests/test_effect_registry.py tests/test_config_loader.py tests/test_config_acceptance.py tests/test_seed_config.py tests/test_sync_balance_doc.py tests/test_m1_config_probe.py tests/test_engine_purity.py
	cd $(BACKEND) && uv run ruff check .
	cd $(BACKEND) && uv run ruff format --check .
	cd $(BACKEND) && uv run mypy src scripts

ci: lint test build ## 本地跑一遍 CI 會跑的東西

format:             ## 自動修正可修的格式問題
	cd $(BACKEND) && uv run ruff check --fix .
	cd $(BACKEND) && uv run ruff format .

clean:              ## 清掉建置產物與快取
	rm -rf $(FRONTEND)/.next $(FRONTEND)/out
	rm -rf $(BACKEND)/dist $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache

play-cli:           ## Persisted HTTP runner; set PLAYER_ARGS="--player-id UUID ..."
	cd $(BACKEND) && uv run python scripts/play_cli.py run --api-url $(or $(API_URL),http://127.0.0.1:8000) --mode $(or $(MODE),blitz) --players $(or $(PLAYERS),4) $(PLAYER_ARGS) --seed $(or $(SEED),cli-seed) --game-id $(or $(GAME_ID),cli-game) --max-turns $(or $(MAX_TURNS),1000)

play-cli-offline:   ## Pure local runner retained for simulation/debugging
	cd $(BACKEND) && uv run python scripts/play_cli.py run --offline --config-dir ../../config --mode $(or $(MODE),blitz) --players $(or $(PLAYERS),4) --seed $(or $(SEED),cli-seed) --strategy $(or $(STRATEGY),conservative) --max-turns $(or $(MAX_TURNS),1000)

simulate:           ## M3 Monte Carlo: GAMES=1000 MODE=daily PLAYERS=10 STRATEGY=mixed SCENARIO=single|m3-core|m3-crowded
	cd $(BACKEND) && uv run python scripts/simulate.py --config-dir ../../config --mode $(or $(MODE),daily) --players $(or $(PLAYERS),10) --games $(or $(GAMES),1000) --seed $(or $(SEED),m3) --strategy $(or $(STRATEGY),mixed) --scenario $(or $(SCENARIO),single) --max-turns $(or $(MAX_TURNS),5000) $(if $(JSONL_OUT),--jsonl-out $(JSONL_OUT),) $(if $(REPORT_OUT),--report-out $(REPORT_OUT),) $(if $(FAIL_ON_THRESHOLD),--fail-on-threshold,) $(if $(MAX_GAME_SECONDS),--max-game-seconds $(MAX_GAME_SECONDS),) $(if $(SKIP_REPLAY),--skip-replay,)
