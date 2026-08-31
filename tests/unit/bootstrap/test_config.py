import json
from pathlib import Path
from threading import Event, Thread

import pytest

from gamesave_scout.bootstrap.config import (
    AppConfig,
    BatchSaveCustomRoot,
    ConfigService,
    InvalidBatchSaveSettingsError,
    InvalidConfigError,
    InvalidLibraryScanSettingsError,
    InvalidUiScaleError,
    JsonConfigStore,
)


def test_missing_config_creates_version_six_portable_defaults(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    store = JsonConfigStore(path)

    assert store.load() == AppConfig(
        version=6,
        language="zh-CN",
        startup_quick_scan=True,
        scan_concurrency=1,
        orphan_scan_exclusions=(),
        ui_scale=1.0,
        cover_online_enabled=False,
        cover_vndb_candidate_limit=5,
        cover_local_scan_candidate_limit=10,
        cover_optimize_enabled=True,
        cover_local_scan_depth=2,
        batch_save_custom_roots=(),
        window_width=1180,
        window_height=760,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["uiScale"] == 1.0
    assert (saved["windowWidth"], saved["windowHeight"]) == (1180, 760)


def test_config_store_round_trips_utf8_and_camel_case_json(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    store = JsonConfigStore(path)
    config = AppConfig(
        orphan_scan_exclusions=("缓存", "临时目录"),
        batch_save_custom_roots=(
            BatchSaveCustomRoot(
                id="root-1",
                display_path=r"D:\Saves\同人游戏",
                enabled=True,
                max_depth=6,
            ),
        ),
    )

    store.save(config)

    assert store.load() == config
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 6,
        "language": "zh-CN",
        "startupQuickScan": True,
        "scanConcurrency": 1,
        "orphanScanExclusions": ["缓存", "临时目录"],
        "uiScale": 1.0,
        "coverOnlineEnabled": False,
        "coverVndbCandidateLimit": 5,
        "coverLocalScanCandidateLimit": 10,
        "coverOptimizeEnabled": True,
        "coverLocalScanDepth": 2,
        "batchSaveCustomRoots": [
            {
                "id": "root-1",
                "displayPath": r"D:\Saves\同人游戏",
                "enabled": True,
                "maxDepth": 6,
            }
        ],
        "windowWidth": 1180,
        "windowHeight": 760,
    }


def test_existing_version_six_config_gains_default_window_size(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 6, "uiScale": 1.2}),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert config.version == 6
    assert config.ui_scale == 1.2
    assert (config.window_width, config.window_height) == (1180, 760)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert (saved["windowWidth"], saved["windowHeight"]) == (1180, 760)


def test_invalid_window_dimensions_fall_back_independently(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 6,
                "windowWidth": 959,
                "windowHeight": 900,
            }
        ),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert (config.window_width, config.window_height) == (1180, 900)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert (saved["windowWidth"], saved["windowHeight"]) == (1180, 900)
    assert "windowWidth" in caplog.text
    assert "windowHeight" not in caplog.text


def test_config_service_saves_valid_window_size(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    service = ConfigService(JsonConfigStore(path))

    updated = service.set_window_size(1440, 900)

    assert (updated.window_width, updated.window_height) == (1440, 900)
    assert (service.current.window_width, service.current.window_height) == (1440, 900)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert (saved["windowWidth"], saved["windowHeight"]) == (1440, 900)


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (959, 760),
        (1180, 639),
        (16385, 760),
        (1180, 16385),
        (True, 760),
        (1180.0, 760),
        ("1180", 760),
    ],
)
def test_config_service_rejects_unsafe_window_sizes(
    tmp_path: Path,
    width: object,
    height: object,
) -> None:
    service = ConfigService(JsonConfigStore(tmp_path / "config.json"))

    with pytest.raises(ValueError):
        service.set_window_size(width, height)


def test_failed_window_size_write_keeps_previous_runtime_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonConfigStore(tmp_path / "config.json")
    service = ConfigService(store)

    def fail_save(config: AppConfig) -> None:
        raise OSError("read only")

    monkeypatch.setattr(store, "save", fail_save)

    with pytest.raises(OSError, match="read only"):
        service.set_window_size(1440, 900)

    assert (service.current.window_width, service.current.window_height) == (1180, 760)


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
        version=6,
        language="ja-JP",
        startup_quick_scan=False,
        scan_concurrency=1,
        orphan_scan_exclusions=("缓存",),
        ui_scale=1.0,
        cover_online_enabled=False,
        cover_vndb_candidate_limit=5,
        cover_local_scan_candidate_limit=10,
        cover_optimize_enabled=True,
        cover_local_scan_depth=2,
        batch_save_custom_roots=(),
    )
    assert json.loads(path.read_text(encoding="utf-8")) == config.to_json()


@pytest.mark.parametrize("ui_scale", [0.7, 0.95, 1.3, "1.2", None, True])
def test_invalid_ui_scale_falls_back_to_one_and_is_normalized(
    tmp_path: Path,
    ui_scale: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 3, "uiScale": ui_scale}),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert config.ui_scale == 1.0
    assert json.loads(path.read_text(encoding="utf-8"))["uiScale"] == 1.0
    assert caplog.messages[-1] == "配置中的 uiScale 无效，已在本次运行中回退到 100%。"


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

    assert config.version == 6
    assert config.ui_scale == 1.0
    assert "无法写回规范化配置" in caplog.text


def test_config_service_saves_a_valid_ui_scale_and_updates_runtime_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data" / "config.json"
    service = ConfigService(JsonConfigStore(path))

    updated = service.set_ui_scale(0.8)

    assert updated.ui_scale == 0.8
    assert service.current.ui_scale == 0.8
    assert json.loads(path.read_text(encoding="utf-8"))["uiScale"] == 0.8


def test_version_two_config_migrates_without_losing_ui_scale(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "language": "zh-CN",
                "startupQuickScan": False,
                "orphanScanExclusions": ["旧目录"],
                "uiScale": 1.2,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert config == AppConfig(
        version=6,
        language="zh-CN",
        startup_quick_scan=False,
        scan_concurrency=1,
        orphan_scan_exclusions=("旧目录",),
        ui_scale=1.2,
        cover_online_enabled=False,
        cover_vndb_candidate_limit=5,
        cover_local_scan_candidate_limit=10,
        cover_optimize_enabled=True,
        cover_local_scan_depth=2,
        batch_save_custom_roots=(),
    )
    assert json.loads(path.read_text(encoding="utf-8")) == config.to_json()


def test_invalid_cover_preferences_fall_back_independently(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 3,
                "uiScale": 1.2,
                "coverOnlineEnabled": 1,
                "coverVndbCandidateLimit": 0,
                "coverLocalScanCandidateLimit": 101,
                "coverOptimizeEnabled": "yes",
                "coverLocalScanDepth": 4,
            }
        ),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert config.ui_scale == 1.2
    assert config.cover_online_enabled is False
    assert config.cover_vndb_candidate_limit == 5
    assert config.cover_local_scan_candidate_limit == 10
    assert config.cover_optimize_enabled is True
    assert config.cover_local_scan_depth == 2
    assert "coverOnlineEnabled" in caplog.text
    assert "coverVndbCandidateLimit" in caplog.text
    assert "coverLocalScanCandidateLimit" in caplog.text
    assert "coverOptimizeEnabled" in caplog.text
    assert "coverLocalScanDepth" in caplog.text
    assert json.loads(path.read_text(encoding="utf-8")) == config.to_json()


@pytest.mark.parametrize("value", [0, 5, True, 2.0, "2"])
def test_invalid_scan_concurrency_falls_back_to_one_and_is_normalized(
    tmp_path: Path,
    value: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "data" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 3, "startupQuickScan": False, "scanConcurrency": value}),
        encoding="utf-8",
    )

    config = JsonConfigStore(path).load()

    assert config.version == 6
    assert config.startup_quick_scan is False
    assert config.scan_concurrency == 1
    assert json.loads(path.read_text(encoding="utf-8"))["scanConcurrency"] == 1
    assert "scanConcurrency" in caplog.text


def test_library_scan_settings_save_atomically_without_losing_other_preferences(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data" / "config.json"
    service = ConfigService(JsonConfigStore(path))
    service.set_ui_scale(1.2)
    service.set_cover_wizard_settings(
        online_enabled=True,
        vndb_candidate_limit=8,
        local_scan_candidate_limit=25,
        optimize_enabled=False,
        local_scan_depth=3,
    )

    updated = service.set_library_scan_settings(
        startup_quick_scan=False,
        scan_concurrency=4,
    )

    assert updated.startup_quick_scan is False
    assert updated.scan_concurrency == 4
    assert updated.ui_scale == 1.2
    assert updated.cover_online_enabled is True
    assert JsonConfigStore(path).load() == updated


@pytest.mark.parametrize(
    ("startup_quick_scan", "scan_concurrency"),
    [(1, 1), (False, True), (False, 0), (False, 5), (False, "2")],
)
def test_config_service_rejects_invalid_library_scan_settings(
    tmp_path: Path,
    startup_quick_scan: object,
    scan_concurrency: object,
) -> None:
    service = ConfigService(JsonConfigStore(tmp_path / "data" / "config.json"))

    with pytest.raises(InvalidLibraryScanSettingsError):
        service.set_library_scan_settings(
            startup_quick_scan=startup_quick_scan,
            scan_concurrency=scan_concurrency,
        )


def test_failed_library_scan_settings_write_keeps_both_previous_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonConfigStore(tmp_path / "data" / "config.json")
    service = ConfigService(store)

    def fail_save(config: AppConfig) -> None:
        raise OSError("read only")

    monkeypatch.setattr(store, "save", fail_save)

    with pytest.raises(OSError, match="read only"):
        service.set_library_scan_settings(
            startup_quick_scan=False,
            scan_concurrency=4,
        )

    assert service.current.startup_quick_scan is True
    assert service.current.scan_concurrency == 1


def test_cover_settings_save_without_losing_ui_scale(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    service = ConfigService(JsonConfigStore(path))
    service.set_ui_scale(1.2)

    updated = service.set_cover_wizard_settings(
        online_enabled=True,
        vndb_candidate_limit=8,
        local_scan_candidate_limit=25,
        optimize_enabled=False,
        local_scan_depth=3,
    )

    assert updated.ui_scale == 1.2
    assert updated.cover_online_enabled is True
    assert updated.cover_vndb_candidate_limit == 8
    assert updated.cover_local_scan_candidate_limit == 25
    assert updated.cover_optimize_enabled is False
    assert updated.cover_local_scan_depth == 3
    assert JsonConfigStore(path).load() == updated


@pytest.mark.parametrize(
    ("online_enabled", "vndb_limit", "local_limit", "optimize_enabled", "depth"),
    [
        (1, 5, 10, True, 2),
        (False, True, 10, True, 2),
        (False, 0, 10, True, 2),
        (False, 5, True, True, 2),
        (False, 5, 101, True, 2),
        (False, 5, 10, 1, 2),
        (False, 5, 10, True, True),
        (False, 5, 10, True, 0),
        (False, 5, 10, True, 4),
    ],
)
def test_config_service_rejects_invalid_cover_settings(
    tmp_path: Path,
    online_enabled: object,
    vndb_limit: object,
    local_limit: object,
    optimize_enabled: object,
    depth: object,
) -> None:
    service = ConfigService(JsonConfigStore(tmp_path / "data" / "config.json"))

    with pytest.raises(ValueError, match="封面"):
        service.set_cover_wizard_settings(
            online_enabled=online_enabled,
            vndb_candidate_limit=vndb_limit,
            local_scan_candidate_limit=local_limit,
            optimize_enabled=optimize_enabled,
            local_scan_depth=depth,
        )


@pytest.mark.parametrize("ui_scale", [0.7, 0.95, 1.3, True, "1.2"])
def test_config_service_rejects_an_invalid_ui_scale(
    tmp_path: Path,
    ui_scale: object,
) -> None:
    service = ConfigService(JsonConfigStore(tmp_path / "data" / "config.json"))

    with pytest.raises(InvalidUiScaleError):
        service.set_ui_scale(ui_scale)


def test_config_service_keeps_last_saved_state_when_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonConfigStore(tmp_path / "data" / "config.json")
    service = ConfigService(store)

    def fail_save(config: AppConfig) -> None:
        raise OSError("read only")

    monkeypatch.setattr(store, "save", fail_save)

    with pytest.raises(OSError, match="read only"):
        service.set_ui_scale(0.8)

    assert service.current.ui_scale == 1.0


def test_config_service_serializes_concurrent_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonConfigStore(tmp_path / "data" / "config.json")
    service = ConfigService(store)
    original_save = store.save
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def controlled_save(config: AppConfig) -> None:
        if config.ui_scale == 0.8:
            first_entered.set()
            assert release_first.wait(timeout=1)
        elif config.ui_scale == 1.2:
            second_entered.set()
        original_save(config)

    monkeypatch.setattr(store, "save", controlled_save)
    first = Thread(target=service.set_ui_scale, args=(0.8,))
    second = Thread(target=service.set_ui_scale, args=(1.2,))

    first.start()
    assert first_entered.wait(timeout=1)
    second.start()

    try:
        assert not second_entered.wait(timeout=0.05)
    finally:
        release_first.set()
        first.join(timeout=1)
        second.join(timeout=1)

    assert second_entered.is_set()
    assert service.current.ui_scale == 1.2


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


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_previous_config_versions_gain_empty_batch_save_roots(
    tmp_path: Path,
    version: int,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"version": version}), encoding="utf-8")

    config = JsonConfigStore(path).load()

    assert config.version == 6
    assert config.batch_save_custom_roots == ()
    assert json.loads(path.read_text(encoding="utf-8"))["batchSaveCustomRoots"] == []


@pytest.mark.parametrize(
    "roots",
    [
        "not-a-list",
        [{"id": "root-1", "displayPath": r"D:\Saves", "enabled": True, "maxDepth": True}],
        [{"id": "root-1", "displayPath": r"D:\Saves", "enabled": True, "maxDepth": 0}],
        [{"id": "root-1", "displayPath": r"D:\Saves", "enabled": True, "maxDepth": 13}],
        [{"id": "root-1", "displayPath": "D:\\\\", "enabled": True, "maxDepth": 6}],
        [
            {"id": "root-1", "displayPath": r"D:\Saves", "enabled": True, "maxDepth": 6},
            {"id": "root-2", "displayPath": "d:/saves/.", "enabled": False, "maxDepth": 2},
        ],
        [
            {
                "id": f"root-{index}",
                "displayPath": rf"D:\Saves\{index}",
                "enabled": True,
                "maxDepth": 6,
            }
            for index in range(33)
        ],
    ],
)
def test_config_store_rejects_unsafe_batch_save_roots(
    tmp_path: Path,
    roots: object,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"version": 5, "batchSaveCustomRoots": roots}),
        encoding="utf-8",
    )

    with pytest.raises(InvalidConfigError, match="批量存档"):
        JsonConfigStore(path).load()


def test_config_service_adds_updates_and_removes_batch_save_roots(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    service = ConfigService(JsonConfigStore(path))

    created = service.add_batch_save_custom_root(
        r"D:\Saves\Galgame\.",
        enabled=True,
        max_depth=6,
    )
    updated = service.update_batch_save_custom_root(
        created.id,
        enabled=False,
        max_depth=12,
    )
    removed = service.remove_batch_save_custom_root(created.id)

    assert created.display_path == r"D:\Saves\Galgame"
    assert updated == BatchSaveCustomRoot(
        id=created.id,
        display_path=r"D:\Saves\Galgame",
        enabled=False,
        max_depth=12,
    )
    assert removed is True
    assert service.current.batch_save_custom_roots == ()
    assert json.loads(path.read_text(encoding="utf-8"))["batchSaveCustomRoots"] == []


@pytest.mark.parametrize(
    ("display_path", "enabled", "max_depth"),
    [
        ("D:\\\\", True, 6),
        ("relative", True, 6),
        (r"D:\Saves", 1, 6),
        (r"D:\Saves", True, True),
        (r"D:\Saves", True, 13),
    ],
)
def test_config_service_rejects_invalid_batch_save_root_values(
    tmp_path: Path,
    display_path: object,
    enabled: object,
    max_depth: object,
) -> None:
    service = ConfigService(JsonConfigStore(tmp_path / "config.json"))

    with pytest.raises(InvalidBatchSaveSettingsError):
        service.add_batch_save_custom_root(
            display_path,
            enabled=enabled,
            max_depth=max_depth,
        )


def test_config_service_rejects_duplicate_batch_save_paths(tmp_path: Path) -> None:
    service = ConfigService(JsonConfigStore(tmp_path / "config.json"))
    service.add_batch_save_custom_root(r"D:\Saves", enabled=True, max_depth=6)

    with pytest.raises(InvalidBatchSaveSettingsError, match="重复"):
        service.add_batch_save_custom_root("d:/saves/.", enabled=True, max_depth=6)


def test_failed_batch_save_root_write_keeps_previous_runtime_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonConfigStore(tmp_path / "config.json")
    service = ConfigService(store)

    def fail_save(config: AppConfig) -> None:
        raise OSError("read only")

    monkeypatch.setattr(store, "save", fail_save)

    with pytest.raises(OSError, match="read only"):
        service.add_batch_save_custom_root(
            r"D:\Saves",
            enabled=True,
            max_depth=6,
        )

    assert service.current.batch_save_custom_roots == ()
