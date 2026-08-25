# Repository Guidelines

## Project Structure & Module Organization

AssetRush is a monorepo with a Next.js frontend and FastAPI backend.

- `apps/frontend/` contains the Next.js 15 app. Routes are under `app/`, utilities under `lib/`, UI components under `components/`, and frontend checks under `scripts/`.
- `apps/backend/` contains the Python API package. Source is in `src/assetrush/`, tests in `tests/`, and maintenance scripts in `scripts/`.
- `config/` stores game configuration JSON files.
- `docs/` contains product, architecture, rules, and roadmap notes.

Keep pure game logic inside `apps/backend/src/assetrush/engine/`; avoid database, HTTP, or framework imports there.

## Build, Test, and Development Commands

- `make install` installs frontend dependencies with pnpm and backend dependencies with `uv sync`.
- `make dev` starts both services: frontend on `3000`, backend on `8000` by default.
- `make dev-frontend` and `make dev-backend` run one service at a time.
- `make lint` runs engine purity, Ruff/mypy, ESLint/typecheck, and secret scanning.
- `make test` runs backend pytest and frontend Vitest.
- `make build` builds backend and frontend and runs the frontend build secret check.
- `make ci` is the local pre-PR command: lint, test, then build.

Root `pnpm` scripts proxy to the frontend; for example, `pnpm test` runs frontend tests.

## Coding Style & Naming Conventions

Frontend code uses TypeScript, React 19, Next.js app routes, ESLint `next/core-web-vitals`, and the `@/*` alias. Prefer PascalCase for components, camelCase for functions and variables, and `.test.tsx` for UI tests.

Backend code targets Python 3.12. Ruff enforces 100-character lines, import sorting, pyupgrade, bugbear, and related rules. Mypy is strict for `assetrush.engine.*`; keep engine APIs typed and side-effect free.

## Testing Guidelines

Backend tests use pytest from `apps/backend/tests/` and should be named `test_*.py`. Frontend tests use Vitest with jsdom and Testing Library; name them `*.test.ts` or `*.test.tsx`. Add focused tests for changed behavior, especially engine rules, config loading, API health, and UI states.

## Commit & Pull Request Guidelines

Recent history uses short milestone or scope prefixes, such as `M0: ...`, `M1: ...`, `infra: ...`, and `ci: ...`. Keep subjects concise.

Pull requests should include a summary, linked issue or milestone when applicable, verification commands, and screenshots for visible frontend changes. Note config, environment, or Supabase changes explicitly.

## Security & Configuration Tips

Use `apps/backend/.env` for server secrets and `apps/frontend/.env.local` only for public `NEXT_PUBLIC_*` values. Never expose service role keys, passwords, or private tokens to frontend code. Run `make lint` or `pnpm --filter frontend check-secrets` before pushing environment changes.
