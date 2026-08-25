"""Replay and compare one persisted game against its snapshots and read models."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from assetrush.console import force_utf8_output
from assetrush.db import get_sessionmaker
from assetrush.services import GameVerificationError, verify_game


async def _run(game_id: UUID) -> int:
    try:
        report = await verify_game(get_sessionmaker(), game_id)
    except GameVerificationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "game_id": str(report.game_id),
                "event_count": report.event_count,
                "final_event_seq": report.final_event_seq,
                "digest_sha256": report.digest_sha256,
                "verified": True,
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", type=UUID, required=True)
    return asyncio.run(_run(parser.parse_args(argv).game_id))


if __name__ == "__main__":
    raise SystemExit(main())
