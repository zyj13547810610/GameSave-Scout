from pathlib import Path

import pytest

from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.rules.catalog import RuleCatalogError, RuleCatalogService
from gamesave_scout.rules.repository import UserRuleRepository
from gamesave_scout.rules.settings import RuleSettings, RuleSettingsStore
from gamesave_scout.saves.templates import PathTemplateResolver

ENGINE_DOCUMENT = b"""\
version: test
rules:
  - id: declared_engine
    label: Shared label
    type: engine
    references: [https://example.com/engine]
    all:
      - op: path_exists
        path: marker.dat
        weight: 1.0
"""

SAVE_DOCUMENT = b"""\
version: test
rules:
  - id: declared_save
    label: Shared label
    type: save_engine
    references: [https://example.com/save]
    engine_ids: [declared_engine]
    locations:
      - kind: directory
        path: <winAppData>/Example
        category: save
        confidence: 0.8
"""


def _user_engine(rule_id: str, *, label: str = "User engine") -> bytes:
    return f"""\
version: user-test
rules:
  - id: {rule_id}
    label: {label}
    type: engine
    all:
      - op: path_exists
        path: user.marker
        weight: 1.0
""".encode()


def _user_save(rule_id: str, *, label: str = "User save") -> bytes:
    return f"""\
version: user-test
rules:
  - id: {rule_id}
    label: {label}
    type: save_game
    titles: [Example]
    locations:
      - kind: directory
        path: <winDocuments>/Example
        category: save
        confidence: 0.7
""".encode()


def _catalog(tmp_path: Path) -> tuple[RuleCatalogService, UserRuleRepository]:
    resource_dir = tmp_path / "resources" / "rules" / "builtin"
    resource_dir.mkdir(parents=True)
    engine_file = resource_dir / "engines.yaml"
    save_file = resource_dir / "saves.yaml"
    engine_file.write_bytes(ENGINE_DOCUMENT)
    save_file.write_bytes(SAVE_DOCUMENT)
    user_root = tmp_path / "data" / "rules" / "user"
    repository = UserRuleRepository(
        user_root / "engines",
        user_root / "saves",
        tmp_path / "data" / "temp",
    )
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    folders = KnownFolders(
        home=tmp_path / "home",
        app_data=tmp_path / "appdata",
        local_app_data=tmp_path / "local",
        local_app_data_low=tmp_path / "locallow",
        documents=tmp_path / "documents",
        saved_games=tmp_path / "saved",
        program_data=tmp_path / "programdata",
        public=tmp_path / "public",
        windows=tmp_path / "windows",
    )
    catalog = RuleCatalogService(
        builtin_engine_file=engine_file,
        builtin_save_file=save_file,
        repository=repository,
        settings_store=RuleSettingsStore(tmp_path / "data" / "rules" / "settings.json"),
        resolver=PathTemplateResolver(folders),
        legacy_manifest_dir=tmp_path / "data" / "manifests",
    )
    return catalog, repository


def test_catalog_allows_duplicate_labels_across_rule_types(tmp_path: Path) -> None:
    catalog, _ = _catalog(tmp_path)

    snapshot = catalog.snapshot()

    assert [item.rule.label for item in snapshot.rules] == ["Shared label", "Shared label"]
    assert snapshot.generation == 1
    assert snapshot.engine_detection.has_option("declared_engine")
    assert len(snapshot.save_rules.rules) == 1


@pytest.mark.parametrize("conflicting_id", ("declared_engine", "unity"))
def test_user_rule_cannot_shadow_declarative_or_dedicated_builtin_ids(
    tmp_path: Path,
    conflicting_id: str,
) -> None:
    catalog, repository = _catalog(tmp_path)
    path = repository.save_dir / "conflict.yaml"
    path.write_bytes(_user_save(conflicting_id))

    before = catalog.snapshot()
    result = catalog.refresh()

    assert result.applied is False
    assert catalog.snapshot() is before
    assert any(item.code == "rule_id_conflict" for item in result.diagnostics)


def test_rule_ids_are_globally_unique_across_engine_and_save_user_files(
    tmp_path: Path,
) -> None:
    catalog, repository = _catalog(tmp_path)
    (repository.engine_dir / "one.yaml").write_bytes(_user_engine("duplicate"))
    (repository.save_dir / "two.yaml").write_bytes(_user_save("duplicate"))

    result = catalog.refresh()

    assert result.applied is False
    assert any(item.code == "rule_id_conflict" for item in result.diagnostics)


def test_one_broken_user_yaml_is_isolated_and_other_rules_are_published(
    tmp_path: Path,
) -> None:
    catalog, repository = _catalog(tmp_path)
    (repository.engine_dir / "broken.yaml").write_bytes(b"version: [")
    (repository.save_dir / "working.yaml").write_bytes(_user_save("working"))

    result = catalog.refresh()

    assert result.applied is True
    assert catalog.snapshot() is result.snapshot
    assert any(item.rule.metadata.rule_id == "working" for item in result.snapshot.rules)
    assert any(item.code == "invalid_user_rule" for item in result.snapshot.diagnostics)


def test_broken_settings_are_ignored_without_blocking_user_rules(tmp_path: Path) -> None:
    catalog, repository = _catalog(tmp_path)
    (repository.save_dir / "working.yaml").write_bytes(_user_save("working"))
    settings_path = tmp_path / "data" / "rules" / "settings.json"
    settings_path.write_text("{", encoding="utf-8")

    result = catalog.refresh()

    assert result.applied is True
    assert any(item.rule.metadata.rule_id == "working" for item in result.snapshot.rules)
    assert any(item.code == "invalid_rule_settings" for item in result.snapshot.diagnostics)


def test_invalid_builtin_engine_rules_fall_back_to_dedicated_detectors(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog(tmp_path)
    catalog.builtin_engine_file.write_bytes(b"version: [")

    result = catalog.refresh()

    assert result.applied is True
    assert result.snapshot.engine_detection.has_option("unity")
    assert not result.snapshot.engine_detection.has_option("declared_engine")
    assert any(item.code == "invalid_builtin_engine_rules" for item in result.snapshot.diagnostics)
    assert len(result.snapshot.save_rules.rules) == 1


def test_invalid_builtin_save_rules_disable_only_that_source(tmp_path: Path) -> None:
    catalog, _ = _catalog(tmp_path)
    catalog.builtin_save_file.write_bytes(b"version: test\nrules: nope\n")

    result = catalog.refresh()

    assert result.applied is True
    assert result.snapshot.engine_detection.has_option("declared_engine")
    assert result.snapshot.save_rules.rules == ()
    assert any(item.code == "invalid_builtin_save_rules" for item in result.snapshot.diagnostics)


def test_disabled_builtin_setting_is_applied_to_snapshot_and_runtime(
    tmp_path: Path,
) -> None:
    catalog, repository = _catalog(tmp_path)
    files = repository.read_all()

    candidate = catalog.compile_candidate(
        files,
        RuleSettings(
            disabled_builtin_rule_ids=frozenset({"builtin:declared_engine"})
        ),
    )

    rule = next(
        item.rule
        for item in candidate.rules
        if item.rule.metadata.rule_id == "declared_engine"
    )
    assert rule.metadata.enabled is False
    assert not candidate.engine_detection.has_option("declared_engine")


def test_legacy_manifest_directory_only_adds_diagnostic(tmp_path: Path) -> None:
    catalog, _ = _catalog(tmp_path)
    catalog.legacy_manifest_dir.mkdir(parents=True)

    result = catalog.refresh()

    assert result.applied is True
    assert any(item.code == "legacy_manifest_detected" for item in result.snapshot.diagnostics)


def test_failed_refresh_keeps_identity_and_success_increments_generation(
    tmp_path: Path,
) -> None:
    catalog, repository = _catalog(tmp_path)
    before = catalog.snapshot()
    (repository.engine_dir / "conflict.yaml").write_bytes(
        _user_engine("declared_save")
    )

    failed = catalog.refresh()

    assert failed.applied is False
    assert catalog.snapshot() is before

    (repository.engine_dir / "conflict.yaml").write_bytes(_user_engine("new_engine"))
    succeeded = catalog.refresh()

    assert succeeded.applied is True
    assert catalog.snapshot() is succeeded.snapshot
    assert succeeded.snapshot is not before
    assert succeeded.snapshot.generation == before.generation + 1


def test_compile_candidate_rejects_global_conflict_without_publishing(
    tmp_path: Path,
) -> None:
    catalog, repository = _catalog(tmp_path)
    files = {repository.engine_dir / "conflict.yaml": _user_engine("declared_save")}

    with pytest.raises(RuleCatalogError):
        catalog.compile_candidate(files, RuleSettings())


def test_apply_user_changes_writes_files_and_publishes_compiled_snapshot(
    tmp_path: Path,
) -> None:
    catalog, repository = _catalog(tmp_path)
    before = catalog.snapshot()
    target = repository.engine_dir / "new_engine.yaml"

    published = catalog.apply_user_changes(
        {target: _user_engine("new_engine")},
        RuleSettings(
            disabled_builtin_rule_ids=frozenset({"builtin:declared_save"})
        ),
    )

    assert target.is_file()
    assert catalog.snapshot() is published
    assert published.generation == before.generation + 1
    disabled = next(
        item.rule
        for item in published.rules
        if item.rule.metadata.rule_id == "declared_save"
    )
    assert disabled.metadata.enabled is False
    assert (tmp_path / "data" / "rules" / "settings.json").is_file()


def test_apply_user_changes_failure_keeps_files_and_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog, repository = _catalog(tmp_path)
    before = catalog.snapshot()
    target = repository.engine_dir / "new_engine.yaml"

    def fail(_changes: object) -> None:
        raise OSError("injected write failure")

    monkeypatch.setattr(repository, "apply_batch", fail)

    with pytest.raises(OSError, match="injected"):
        catalog.apply_user_changes(
            {target: _user_engine("new_engine")},
            RuleSettings(),
        )

    assert catalog.snapshot() is before
    assert not target.exists()
