# AssetRush — 所有操作的唯一入口。
#
# 相容性：POSIX（make + sh）與 Windows Git Bash（GnuWin32 make 3.81 + sh.exe）。
# `dev` 刻意不用 `make -j2`：GnuWin32 make 3.81 在 Windows 上不支援 -j，會靜默
# 退回 -j1，結果只有 web 起得來。改用單一 recipe 內背景執行 + trap，兩邊都準。

WEB := apps/web
API := apps/api
WEB_PORT ?= 3000
API_PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install dev dev-web dev-api build build-web build-api \
        test test-web test-api lint lint-web lint-api check-engine format clean ci

help:               ## 列出所有 target
	@echo "AssetRush make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sed -e 's/:.*## /\t/' -e 's/^/  /'

install:            ## 安裝前後端相依
	pnpm install
	cd $(API) && uv sync

dev:                ## 同時啟動 web + api（Ctrl+C 一起收掉）
	@echo "web  → http://localhost:$(WEB_PORT)"
	@echo "api  → http://localhost:$(API_PORT)/health"
	@trap 'kill $$API_PID $$WEB_PID 2>/dev/null; exit 0' INT TERM; \
	( cd $(API) && uv run uvicorn assetrush.main:app --reload --port $(API_PORT) ) & \
	API_PID=$$!; \
	( cd $(WEB) && pnpm dev --port $(WEB_PORT) ) & \
	WEB_PID=$$!; \
	wait

dev-web:            ## 只起 Next.js
	cd $(WEB) && pnpm dev --port $(WEB_PORT)

dev-api:            ## 只起 FastAPI
	cd $(API) && uv run uvicorn assetrush.main:app --reload --port $(API_PORT)

build: build-api build-web  ## 建置前後端

build-web:
	cd $(WEB) && pnpm build

build-api:
	cd $(API) && uv build

test: test-api test-web     ## 跑所有測試

test-api:
	cd $(API) && uv run pytest

test-web:
	cd $(WEB) && pnpm test

check-engine:       ## ★ 鐵律 2：engine/ 零 I/O 邊界檢查
	cd $(API) && uv run python scripts/check_engine_purity.py

lint: check-engine lint-api lint-web  ## engine 邊界 + ruff + mypy + eslint + tsc

lint-api:
	cd $(API) && uv run ruff check .
	cd $(API) && uv run ruff format --check .
	cd $(API) && uv run mypy src scripts

lint-web:
	cd $(WEB) && pnpm lint
	cd $(WEB) && pnpm typecheck

ci: lint test build ## 本地跑一遍 CI 會跑的東西

format:             ## 自動修正可修的格式問題
	cd $(API) && uv run ruff check --fix .
	cd $(API) && uv run ruff format .

clean:              ## 清掉建置產物與快取
	rm -rf $(WEB)/.next $(WEB)/out
	rm -rf $(API)/dist $(API)/.pytest_cache $(API)/.mypy_cache $(API)/.ruff_cache
