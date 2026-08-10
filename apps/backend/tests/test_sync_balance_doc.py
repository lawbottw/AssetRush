from __future__ import annotations

from pathlib import Path

import pytest
from sync_balance_doc import (
    BEGIN_MARKER,
    END_MARKER,
    generate_summary,
    main,
    replace_generated_block,
)

from assetrush.config_bundle import load_config_bundle

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def test_generate_summary_contains_m1_config_surface() -> None:
    summary = generate_summary(load_config_bundle(CONFIG_DIR))

    assert BEGIN_MARKER in summary
    assert END_MARKER in summary
    assert "Config version" in summary
    assert "Effect types" in summary
    assert "發票" not in summary
    assert "有效進修 50%" in summary
    assert "打水飄 50%" in summary


def test_replace_generated_block_replaces_existing_block() -> None:
    document = f"before\n{BEGIN_MARKER}\nstale\n{END_MARKER}\nafter\n"

    updated = replace_generated_block(document, f"{BEGIN_MARKER}\nfresh\n{END_MARKER}")

    assert "stale" not in updated
    assert "fresh" in updated
    assert updated.startswith("before\n")
    assert updated.endswith("\nafter\n")


def test_check_mode_detects_stale_doc(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = tmp_path / "02.md"
    doc.write_text(f"{BEGIN_MARKER}\nstale\n{END_MARKER}\n", encoding="utf-8")

    assert main(["--config-dir", str(CONFIG_DIR), "--doc", str(doc), "--check"]) == 1
    captured = capsys.readouterr()
    assert "stale" in captured.err


def test_write_then_check_passes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    doc = tmp_path / "02.md"
    doc.write_text("# Balance\n", encoding="utf-8")

    assert main(["--config-dir", str(CONFIG_DIR), "--doc", str(doc), "--write"]) == 0
    assert main(["--config-dir", str(CONFIG_DIR), "--doc", str(doc), "--check"]) == 0
    captured = capsys.readouterr()
    assert "up to date" in captured.out
