import json
from pathlib import Path

import pytest

from gameshelf.bootstrap.config import AppConfig, InvalidConfigError, JsonConfigStore


def test_missing_config_returns_portable_defaults(tmp_path: Path) -> None:
    store = JsonConfigStore(tmp_path / "data" / "config.json")

    assert store.load() == AppConfig(
        version=1,
        language="zh-CN",
        startup_quick_scan=True,
        orphan_scan_exclusions=(),
    )


def test_config_store_round_trips_utf8_and_camel_case_json(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    store = JsonConfigStore(path)
    config = AppConfig(orphan_scan_exclusions=("缓存", "临时目录"))

    store.save(config)

    assert store.load() == config
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "language": "zh-CN",
        "startupQuickScan": True,
        "orphanScanExclusions": ["缓存", "临时目录"],
    }


def test_config_store_preserves_invalid_json_for_manual_recovery(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{invalid", encoding="utf-8")
    store = JsonConfigStore(path)

    with pytest.raises(InvalidConfigError, match="配置文件无效"):
        store.load()

    assert path.read_text(encoding="utf-8") == "{invalid"


def test_config_store_rejects_wrong_field_types(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"version": 1, "startupQuickScan": "yes"}', encoding="utf-8")

    with pytest.raises(InvalidConfigError, match="配置文件无效"):
        JsonConfigStore(path).load()
