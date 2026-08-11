"""Commit-reveal / HMAC RNG helpers."""

from __future__ import annotations

import hashlib
import hmac


def seed_hash(server_seed: str) -> str:
    """回傳局內公開的 server seed SHA-256 hex digest。"""

    return hashlib.sha256(server_seed.encode()).hexdigest()


def roll_d6(server_seed: str, game_id: str, turn_seq: int, player_id: str) -> int:
    """依 docs/01 §2.2 的公式產生 1D6 骰點。"""

    msg = f"{game_id}:{turn_seq}:{player_id}"
    value = _hmac_u64(server_seed, msg)
    return value % 6 + 1


def derive_u64(
    server_seed: str,
    game_id: str,
    namespace: str,
    seq: int,
    subject: str | None = None,
) -> int:
    """從 seed 派生穩定 u64，供棋盤抽樣、抽卡等非骰點用途使用。"""

    subject_part = "" if subject is None else f":{subject}"
    msg = f"{game_id}:{namespace}:{seq}{subject_part}"
    return _hmac_u64(server_seed, msg)


def proof_input(game_id: str, turn_seq: int, player_id: str) -> str:
    return f"{game_id}:{turn_seq}:{player_id}"


def _hmac_u64(server_seed: str, msg: str) -> int:
    digest = hmac.new(server_seed.encode(), msg.encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")
