from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from validate_config import main

from assetrush.config_bundle import load_raw_config
from assetrush.engine.config_models import ConfigValidationError, validate_config_bundle

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def test_current_config_loads_successfully() -> None:
    config = validate_config_bundle(load_raw_config(CONFIG_DIR))

    assert config.version == "2026.08.3"
    assert len(config.events.opportunity) == 22
    assert config.events.opportunity[0].effect.type == "gain"


def test_version_mismatch_fails() -> None:
    raw = _raw_config()
    raw["events"]["version"] = "bad-version"

    with pytest.raises(ConfigValidationError, match="versions"):
        validate_config_bundle(raw)


def test_opportunity_weight_total_mismatch_fails() -> None:
    raw = _raw_config()
    raw["events"]["opportunity"][0]["weight"] += 1

    with pytest.raises(ConfigValidationError, match="opportunity"):
        validate_config_bundle(raw)


def test_fate_category_weight_mismatch_fails() -> None:
    raw = _raw_config()
    raw["events"]["_fate_category_weights"]["social"] += 1

    with pytest.raises(ConfigValidationError, match="category"):
        validate_config_bundle(raw)


def test_unknown_effect_type_fails() -> None:
    raw = _raw_config()
    raw["events"]["opportunity"][0]["effect"]["type"] = "unknown_effect"

    with pytest.raises(ConfigValidationError, match="unknown effect"):
        validate_config_bundle(raw)


def test_unsafe_formula_fails() -> None:
    raw = _raw_config()
    raw["events"]["opportunity"][0]["effect"]["formula"] = "__import__('os')"

    with pytest.raises(ConfigValidationError, match="invalid formula"):
        validate_config_bundle(raw)


def test_missing_config_file_fails(tmp_path: Path) -> None:
    config_dir = _copy_config(tmp_path)
    (config_dir / "wellbeing.json").unlink()

    with pytest.raises(ConfigValidationError, match="missing config files"):
        load_raw_config(config_dir)


def test_unknown_config_file_fails(tmp_path: Path) -> None:
    config_dir = _copy_config(tmp_path)
    (config_dir / "experimental.json").write_text('{"version": "2026.08.3"}', encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="unknown config files"):
        load_raw_config(config_dir)


def test_invalid_json_fails(tmp_path: Path) -> None:
    config_dir = _copy_config(tmp_path)
    (config_dir / "events.json").write_text("{", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="invalid JSON"):
        load_raw_config(config_dir)


def test_invalid_side_job_reference_fails() -> None:
    raw = _raw_config()
    raw["events"]["opportunity"][0]["effect"]["requires_side_job"] = "missing_side_job"

    with pytest.raises(ConfigValidationError, match="requires_side_job"):
        validate_config_bundle(raw)


def test_disabled_side_job_reference_fails() -> None:
    raw = _raw_config()
    raw["events"]["opportunity"][0]["effect"]["requires_side_job"] = "mlm"

    with pytest.raises(ConfigValidationError, match="disabled"):
        validate_config_bundle(raw)


def test_duplicate_keys_fail() -> None:
    raw = _raw_config()
    raw["loans"]["products"][1]["key"] = raw["loans"]["products"][0]["key"]

    with pytest.raises(ConfigValidationError, match="duplicates"):
        validate_config_bundle(raw)


def test_invalid_board_layout_fails() -> None:
    raw = _raw_config()
    raw["board"]["function_tiles"]["layouts"]["16"][0]["fixed_index"] = 1

    with pytest.raises(ConfigValidationError, match="fixed_index"):
        validate_config_bundle(raw)


def test_non_contiguous_property_levels_fail() -> None:
    raw = _raw_config()
    raw["properties"]["levels"][-1]["level"] = 9

    with pytest.raises(ConfigValidationError, match="contiguous"):
        validate_config_bundle(raw)


def test_validate_config_cli_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_dir = _copy_config(tmp_path)

    assert main(["--config-dir", str(config_dir)]) == 0
    captured = capsys.readouterr()
    assert "OK: config validation passed" in captured.out


def test_validate_config_cli_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_dir = _copy_config(tmp_path)
    events_path = config_dir / "events.json"
    events = json.loads(events_path.read_text(encoding="utf-8"))
    events["opportunity"][0]["weight"] += 1
    events_path.write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")

    assert main(["--config-dir", str(config_dir)]) == 1
    captured = capsys.readouterr()
    assert "FAIL: config validation failed" in captured.err


def _raw_config() -> dict[str, object]:
    return deepcopy(load_raw_config(CONFIG_DIR))


def _copy_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target)
    return target
