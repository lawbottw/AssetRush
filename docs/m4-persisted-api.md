# M4 persisted game API

The M4 write path is FastAPI → `GameStore` → PostgreSQL. Authentication is intentionally deferred
to M5, so local/integration players must already exist in both `auth.users` and `public.users`.

## Endpoints

- `POST /games` creates and starts a game with a fixed config, players, mode, and seed.
- `GET /games/{game_id}` returns a safe snapshot without the active server seed or private orders.
- `POST /games/{game_id}/commands` submits a typed command with `expected_turn_seq`.
- `GET /games/{game_id}/events?after_id=0&limit=200` reads the ordered event stream.

Stale versions return HTTP 409, invalid request bodies return 422, and domain conflicts use stable
4xx error codes. All writes are delegated to the transactional service; routes do not run rules.

## CLI

Start the backend, then pass one already-registered UUID per player:

```bash
make dev-backend
make play-cli MODE=blitz PLAYERS=2 GAME_ID=demo \
  PLAYER_ARGS="--player-id <uuid-1> --player-id <uuid-2>"
```

The default runner is an HTTP client. Use `make play-cli-offline` only for a pure-engine simulation.
To test restart recovery, invoke `scripts/play_cli.py run` with `--pause-after-turns 3`, restart the
API, then invoke it again with the same `--game-id` and player IDs.
