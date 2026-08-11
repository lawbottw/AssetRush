from __future__ import annotations

import hashlib

from assetrush.engine import derive_u64, roll_d6, seed_hash


def test_roll_d6_is_deterministic_for_commit_reveal_inputs() -> None:
    assert roll_d6("m2-seed", "game-19", 1, "p1") == 6
    assert roll_d6("m2-seed", "game-19", 1, "p1") == 6


def test_seed_hash_matches_sha256_hex_digest() -> None:
    server_seed = "m2-seed"

    assert seed_hash(server_seed) == hashlib.sha256(server_seed.encode()).hexdigest()
    assert (
        seed_hash(server_seed) == "b7259079da43515a1b2d86bc6865fa2daf160fa618c800c26e310f051014ca6e"
    )


def test_derive_u64_changes_with_namespace_seq_and_subject() -> None:
    base = derive_u64("m2-seed", "game-19", "board", 1)

    assert base == 17935116953233402873
    assert derive_u64("m2-seed", "game-19", "card", 1) != base
    assert derive_u64("m2-seed", "game-19", "board", 2) != base
    assert derive_u64("m2-seed", "game-19", "board", 1, subject="p1") == 14425686578632194999
