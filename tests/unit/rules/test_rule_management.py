from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from gamesave_scout.library.models import Game
from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.rules.catalog import RuleCatalogService
from gamesave_scout.rules.management import (
    RuleCapabilities,
    RuleListFilters,
    RuleManagementError,
    RuleManagementService,
)
from gamesave_scout.rules.repository import UserRuleRepository
from gamesave_scout.rules.settings import RuleSettingsStore
from gamesave_scout.saves.models import SaveLocation
from gamesave_scout.saves.templates import PathTemplateResolver
from gamesave_scout.scanning.path_keys import windows_path_key


@dataclass
class _Library:
    game: Game
    install_dir: Path

    def get_game(self, game_id: str) -> Game | None:
        return self.game if game_id == self.game.id else None

    def install_directory(self, game_id: str) -> Path:
        if game_id != self.game.id:
            raise LookupError(game_id)
        return self.install_dir


@dataclass
class _SaveRepository:
    locations: tuple[SaveLocation, ...] = ()

    def list_for_game(self, _game_id: str) -> tuple[SaveLocation, ...]:
        return self.locations


@dataclass
class _Registry:
    existing: set[str]
    write_calls: list[str]

    def key_exists(self, key: str) -> bool:
        return key in self.existing


def test_rule_list_detail_and_validation_are_normalized_and_path_safe(
    tmp_path: Path,
) -> None:
    service, _, _, _ = _service(tmp_path)

    page = service.list_rules(
        RuleListFilters(kind="all", source="all", query="SHARED", limit=20)
    )
    detail = service.get_rule("builtin:declared_engine")
    save_detail = service.get_rule("builtin:declared_save")
    invalid = service.validate_draft({"version": "1", "id": "UPPER"})

    assert [item.qualified_id for item in page.items] == [
        "builtin:declared_engine",
        "builtin:declared_save",
    ]
    assert detail.capabilities == RuleCapabilities(
        edit=False,
        copy=True,
        test=True,
        toggle=True,
        delete=False,
        export=True,
    )
    assert detail.source_file == "builtin/engines.yaml"
    assert save_detail.draft["product_ids"] == []
    assert save_detail.draft["locations"][0]["require_existing"] is False
    assert "product_ids" not in save_detail.yaml_preview
    assert str(tmp_path) not in detail.yaml_preview
    assert invalid.valid is False
    assert invalid.error_code == "invalid_rule_draft"


def test_user_rule_crud_is_transactional_and_ids_cannot_change(
    tmp_path: Path,
) -> None:
    service, catalog, repository, _ = _service(tmp_path)
    before_generation = catalog.snapshot().generation

    created = service.save_rule(None, _engine_draft("mine"), None)
    copied = service.copy_rule("user:mine")
    copied_builtin = service.copy_rule("builtin:declared_engine")
    disabled = service.set_enabled("builtin:declared_engine", False)
    disabled_user = service.set_enabled("user:mine", False)

    assert created.detail.qualified_id == "user:mine"
    assert copied.detail.qualified_id == "user:mine_copy"
    assert copied_builtin.detail.qualified_id == "user:declared_engine_copy"
    assert copied.detail.status == "experimental"
    assert disabled.detail.enabled is False
    assert disabled_user.detail.enabled is False
    assert catalog.snapshot().generation == before_generation + 5
    assert (repository.engine_dir / "mine.yaml").is_file()
    assert (repository.engine_dir / "mine_copy.yaml").is_file()
    assert "enabled: false" in (repository.engine_dir / "mine.yaml").read_text(
        encoding="utf-8"
    )

    with pytest.raises(RuleManagementError) as changing:
        service.save_rule("user:mine", _engine_draft("renamed"), None)
    assert changing.value.code == "rule_id_change_requires_copy"

    deleted = service.delete_user_rule("user:mine_copy")
    assert deleted.qualified_id == "user:mine_copy"
    assert not (repository.engine_dir / "mine_copy.yaml").exists()
    with pytest.raises(RuleManagementError) as builtin_delete:
        service.delete_user_rule("builtin:declared_engine")
    assert builtin_delete.value.code == "builtin_rule_readonly"


def test_new_engine_rule_requires_category_but_legacy_draft_stays_valid(
    tmp_path: Path,
) -> None:
    service, catalog, repository, _ = _service(tmp_path)
    service.save_rule(None, _engine_draft("legacy"), None)
    legacy_file = repository.engine_dir / "legacy.yaml"
    legacy_file.write_text(
        "\n".join(
            line
            for line in legacy_file.read_text(encoding="utf-8").splitlines()
            if "category:" not in line
        )
        + "\n",
        encoding="utf-8",
    )
    assert catalog.refresh().applied is True
    legacy_draft = {**_engine_draft("legacy")}
    legacy_draft.pop("category")

    validation = service.validate_draft(legacy_draft)
    updated = service.save_rule("user:legacy", legacy_draft, None)

    assert validation.valid is True
    assert validation.normalized_draft is not None
    assert "category" not in validation.normalized_draft
    assert updated.detail.qualified_id == "user:legacy"

    unclassified_new = {**legacy_draft, "id": "unclassified_new"}
    with pytest.raises(RuleManagementError) as missing_category:
        service.save_rule(None, unclassified_new, None)
    assert missing_category.value.code == "engine_category_required"


def test_formal_user_rule_requires_bound_test_and_matching_changes_downgrade(
    tmp_path: Path,
) -> None:
    service, _, _, install_dir = _service(tmp_path)
    (install_dir / "marker.dat").write_bytes(b"marker")
    formal = _engine_draft("verified", status="formal")

    with pytest.raises(RuleManagementError) as unverified:
        service.save_rule(None, formal, None)
    assert unverified.value.code == "rule_verification_required"

    test_result = service.test_draft(formal, "game-1")
    assert test_result.matched is True
    assert test_result.verification_token
    created = service.save_rule(None, formal, test_result.verification_token)
    assert created.detail.status == "formal"

    metadata_only = {**formal, "label": "Renamed", "notes": "new note"}
    kept = service.save_rule("user:verified", metadata_only, None)
    assert kept.detail.status == "formal"

    changed = {
        **metadata_only,
        "all": [{"op": "path_exists", "path": "other.dat", "weight": 1.0}],
    }
    downgraded = service.save_rule("user:verified", changed, None)
    assert downgraded.detail.status == "experimental"


def test_game_save_prefill_uses_exact_identity_and_confirmed_templates_only(
    tmp_path: Path,
) -> None:
    service, _, _, _ = _service(tmp_path, with_recorded_location=True)

    prefill = service.prefill_game_save_rule("game-1")

    assert prefill.title == "Alice RJ012345"
    assert prefill.aliases == ("Alice Detected",)
    assert prefill.product_ids == ("dlsite:RJ012345",)
    assert tuple(
        (location.kind, location.path_template)
        for location in prefill.locations
    ) == (("directory", r"<winDocuments>\Alice"),)
    assert prefill.engine_id == "unity"
    assert all(
        "Profile" not in location.path_template
        for location in prefill.locations
    )


def _service(
    tmp_path: Path,
    *,
    with_recorded_location: bool = False,
) -> tuple[RuleManagementService, RuleCatalogService, UserRuleRepository, Path]:
    builtin = tmp_path / "resources" / "rules" / "builtin"
    builtin.mkdir(parents=True)
    engine_file = builtin / "engines.yaml"
    engine_file.write_text(
        """\
version: test
rules:
  - id: declared_engine
    label: Shared Engine
    type: engine
    references: [https://example.com/engine]
    all: [{op: path_exists, path: marker.dat, weight: 1.0}]
""",
        encoding="utf-8",
    )
    save_file = builtin / "saves.yaml"
    save_file.write_text(
        r"""version: test
rules:
  - id: declared_save
    label: Shared Save
    type: save_game
    references: [https://example.com/save]
    titles: [Alice]
    locations:
      - {kind: directory, path: '<winDocuments>\Alice', category: save, confidence: 0.9}
""",
        encoding="utf-8",
    )
    user = tmp_path / "data" / "rules" / "user"
    repository = UserRuleRepository(
        user / "engines",
        user / "saves",
        tmp_path / "data" / "temp",
    )
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    home = tmp_path / "Profile"
    folders = KnownFolders(
        home=home,
        app_data=home / "AppData" / "Roaming",
        local_app_data=home / "AppData" / "Local",
        local_app_data_low=home / "AppData" / "LocalLow",
        documents=home / "Documents",
        saved_games=home / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
    resolver = PathTemplateResolver(folders)
    settings = RuleSettingsStore(tmp_path / "data" / "rules" / "settings.json")
    catalog = RuleCatalogService(
        builtin_engine_file=engine_file,
        builtin_save_file=save_file,
        repository=repository,
        settings_store=settings,
        resolver=resolver,
        legacy_manifest_dir=tmp_path / "data" / "manifests",
    )
    install_dir = tmp_path / "Games" / "Alice"
    install_dir.mkdir(parents=True)
    game = _game()
    recorded = (
        SaveLocation(
            id="location-1",
            game_id=game.id,
            kind="directory",
            path_template=r"<winDocuments>\Alice",
            display_path=str(folders.documents / "Alice"),
            path_key=windows_path_key(folders.documents / "Alice"),
            source="manual",
            confidence=1.0,
            evidence=(),
            confirmed=True,
            enabled=True,
            last_verified_at=None,
        ),
    ) if with_recorded_location else ()
    service = RuleManagementService(
        catalog=catalog,
        repository=repository,
        resolver=resolver,
        library=_Library(game, install_dir),
        save_repository=_SaveRepository(recorded),
        registry=_Registry(set(), []),
    )
    return service, catalog, repository, install_dir


def _engine_draft(rule_id: str, *, status: str = "experimental") -> dict[str, object]:
    return {
        "version": "user-test",
        "id": rule_id,
        "label": "Mine",
        "type": "engine",
        "category": "general",
        "status": status,
        "priority": 0,
        "enabled": True,
        "notes": None,
        "references": [],
        "threshold": 0.8,
        "all": [{"op": "path_exists", "path": "marker.dat", "weight": 1.0}],
        "any": [],
        "negative": [],
    }


def _game() -> Game:
    return Game(
        id="game-1",
        scan_root_id="root-1",
        relative_dir="Alice RJ012345",
        install_path_key=windows_path_key(r"D:\Games\Alice"),
        title="Alice RJ012345",
        detected_title="Alice Detected",
        status="installed",
        detected_engine_id="unity",
        detected_engine_variant=None,
        engine_id="unity",
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=0.9,
        engine_evidence=(),
        engine_rules_version="test",
        main_exe_relpath="Alice.exe",
        main_exe_is_manual=False,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="unknown",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        last_launched_at=None,
        missing_since=None,
    )
