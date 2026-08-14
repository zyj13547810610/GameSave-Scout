import json
from pathlib import Path

import pytest

from gameshelf.bootstrap.config import AppConfig, InvalidConfigError, JsonConfigStore


def test_missing_config_creates_version_two_portable_defaults(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    store = JsonConfigStore(path)

    assert store.load() == AppConfig(
        version=2,
        language="zh-CN",
        startup_quick_scan=True,
        orphan_scan_exclusions=(),
        ui_scale=1.0,
    )
    assert json.loads(path.read_text(encoding="utf-8"))["uiScale"] == 1.0


def test_config_store_round_trips_utf8_and_camel_case_json(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    store = JsonConfigStore(path)
    config = AppConfig(orphan_scan_exclusions=("缓存", "临时目录"))

    store.save(config)

    assert store.load() == config
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 2,
        "language": "zh-CN",
        "startupQuickScan": True,
        "orphanScanExclusions": ["缓存", "临时目录"],
        "uiScale": 1.0,
    }


def test_version_one_config_is_migrated_without_losing_existing_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "language": "ja-JP",
                "startupQuickScan": False,
                "orphanScanExclusions": ["缓存"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert config == AppConfig(
        version=2,
        language="ja-JP",
        startup_quick_scan=False,
        orphan_scan_exclusions=("缓存",),
        ui_scale=1.0,
    )
    assert json.loads(path.read_text(encoding="utf-8")) == config.to_json()


@pytest.mark.parametrize("ui_scale", [0.7, 0.95, 1.3, "1.2", None, True])
def test_invalid_ui_scale_falls_back_to_one_and_is_normalized(
    tmp_path: Path,
    ui_scale: object,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 2, "uiScale": ui_scale}),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert config.ui_scale == 1.0
    assert json.loads(path.read_text(encoding="utf-8"))["uiScale"] == 1.0


def test_failed_migration_write_still_returns_normalized_runtime_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"version": 1}', encoding="utf-8")
    store = JsonConfigStore(path)

    def fail_save(config: AppConfig) -> None:
        raise OSError("read only")

    monkeypatch.setattr(store, "save", fail_save)

    config = store.load()

    assert config.version == 2
    assert config.ui_scale == 1.0
    assert "无法写回规范化配置" in caplog.text


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
