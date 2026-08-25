# M3 Balance Report

> Status: `v1.0-validated` (2026-08-11)

## Data And Reproducibility

M3 data is generated from the pure engine and the versioned `config/*.json` snapshot. It does not
use production telemetry, a database, UI, LINE, crawler, or external stock API. Every JSONL row
contains the game seed, settings, result, player-level outcomes, bids, and event counters.

The formal report aggregates 306 completed deterministic simulations with five rotating strategies:

- Core: 300 games, three independent 100-game batches over `daily/4`, `daily/10`, `blitz/4`, and
  `blitz/8`; seeds `m3-core-v10`, `m3-core-v11`, and `m3-core-v12`.
- Crowded: 6 games of `daily/30`; seed `m3-crowded-v2`; `max_turns=9200`.

```sh
cd apps/backend
uv run python scripts/simulate.py --jsonl-in \
  ../../docs/m3-core-baseline.jsonl \
  ../../docs/m3-core-batch-v11.jsonl \
  ../../docs/m3-core-batch-v12.jsonl \
  ../../docs/m3-crowded-validated.jsonl \
  --report-out ../../docs/m3-validated-report.json \
  --fail-on-threshold
```

The runner executes legal engine commands, writes one game summary per JSONL line, and
`assetrush.sim.metrics` calculates the 13 pass/fail checks. Rerunning the command above with the
same inputs must reproduce the report.

## Validated Result

Source: `docs/m3-validated-report.json`. All 306 games completed; all 13 required checks passed.

| Metric | Result |
|---|---:|
| Starting advantage correlation | 0.1502 (< 0.35) |
| Alliance win-rate gap | 0.0303 (< 0.08) |
| Vehicle win-rate gap | 0.0286 (< 0.10) |
| Bid: high-cash success / average premium | 0.4055 / 0.0626 |
| Education vs property win-rate gap | 0.0513 (< 0.10) |
| Threshold endings, blitz / daily | 28.67% / 34.62% |
| Median first bankruptcy | 6 (> 4) |
| Turn-order fairness correlation | 0.0671 (< 0.10) |
| 30-player median duration | 14 days (> 12) |
| Maximum strategy win rate | 19.72% (<= 60%) |
| Jail / hospital per player-year | 0.1477 / 0.1792 |
| Finance bankruptcy-rate impact | 0.0050 (< 0.10) |
| Winner stock share | 0.1639 (10%-30%) |

## Final Calibration

- Daily and blitz net-worth end thresholds use independent config multipliers.
- Daily games with 21 or more players apply `crowded_game_multiplier: 1.35`; this changes only the
  30-player end threshold and moved median duration from 9.5 to 14 days.
- The `v1.0-validated` config bundle is the baseline for the next milestone. Any economic value or
  probability change requires a new simulation report before being treated as validated.
