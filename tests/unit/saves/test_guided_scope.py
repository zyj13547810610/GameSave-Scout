from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from gamesave_scout.db.connection import ConnectionFactory
from gamesave_scout.db.migrator import Migrator
from gamesave_scout.db.writer import DbWriter
from gamesave_scout.library.repository import LibraryRepository
from gamesave_scout.library.service import LibraryService
from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.saves.guided_scope import GuidedSaveScopeBuilder, InvalidGuidedScope
from gamesave_scout.saves.repository import SaveLocationRepository
from gamesave_scout.saves.templates import PathTemplateResolver
from gamesave_scout.scanning.path_keys import windows_path_key


@dataclass
class FakeRegistryTargets:
    calls: int = 0

    def registry_targets_for_game(
        self, game_id: str
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        self.calls += 1
        assert game_id
        return (
            (
                r"HKEY_CURRENT_USER\Software\Studio\Alice",
                ("Ludusavi 官方清单",),
            ),
        )


@dataclass(frozen=True)
class ScopeHarness:
    builder: GuidedSaveScopeBuilder
    library: LibraryService
    writer: DbWriter
    game_id: str
    game_dir: Path
    folders: KnownFolders
    registry_targets: FakeRegistryTargets


@pytest.fixture
def scope_harness(tmp_path: Path) -> Iterator[ScopeHarness]:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    Migrator(factory, tmp_path / "backups").migrate()
    writer = DbWriter(factory)
    writer.start()
    library = LibraryService(LibraryRepository(factory), writer)
    game_root = tmp_path / "Games"
    game_dir = game_root / "Alice"
    game_dir.mkdir(parents=True)
    executable = game_dir / "Alice.exe"
    executable.write_bytes(b"MZ")
    root = library.add_root(str(game_root), "children", 1, [])
    game = library.create_game_for_test(root.id, "Alice", "Alice")
    writer.submit(
        lambda connection: connection.execute(
            "UPDATE games SET main_exe_relpath = 'Alice.exe' WHERE id = ?", (game.id,)
        ).rowcount
    ).result()

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
    for directory in (
        folders.app_data,
        folders.local_app_data,
        folders.local_app_data_low,
        folders.documents,
        folders.saved_games,
        folders.program_data,
        folders.public,
        folders.windows,
        folders.home / "Vendor" / "Alice",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    resolver = PathTemplateResolver(folders)
    save_repository = SaveLocationRepository(factory)
    with factory.connect() as connection:
        _insert_confirmed_location(
            connection,
            game.id,
            folders.home / "Vendor" / "Alice",
            r"<home>\Vendor\Alice",
        )
        connection.commit()
    registry_targets = FakeRegistryTargets()
    builder = GuidedSaveScopeBuilder(
        library=library,
        save_repository=save_repository,
        resolver=resolver,
        known_folders=folders,
        static_discovery=registry_targets,
    )
    try:
        yield ScopeHarness(
            builder,
            library,
            writer,
            game.id,
            game_dir,
            folders,
            registry_targets,
        )
    finally:
        writer.close()


def test_preview_marks_defaults_and_program_data_without_starting_monitoring(
    scope_harness: ScopeHarness,
) -> None:
    preview = scope_harness.builder.preview(scope_harness.game_id)
    by_source = {scope.source: scope for scope in preview.scopes}

    assert preview.game_title == "Alice"
    assert preview.executable == str(scope_harness.game_dir / "Alice.exe")
    assert by_source["game"].default_selected is True
    assert by_source["documents"].default_selected is True
    assert by_source["saved_games"].default_selected is True
    assert by_source["app_data"].default_selected is True
    assert by_source["local_app_data"].default_selected is True
    assert by_source["local_app_data_low"].default_selected is True
    assert by_source["program_data"].default_selected is False
    assert by_source["confirmed"].path_template == r"<home>\Vendor"
    assert len({scope.path_template.casefold() for scope in preview.scopes}) == len(
        preview.scopes
    )
    assert preview.registry_targets[0].key.endswith(r"Studio\Alice")
    assert scope_harness.registry_targets.calls == 1


def test_preview_includes_an_existing_confirmed_registry_location(
    scope_harness: ScopeHarness,
) -> None:
    key = r"HKEY_CURRENT_USER\Software\Studio\ConfirmedAlice"
    scope_harness.writer.submit(
        lambda connection: connection.execute(
            """
            INSERT INTO save_locations(
                id, game_id, kind, path_template, display_path, path_key,
                source, confidence, evidence_json, confirmed, enabled
            ) VALUES (
                'confirmed-registry', ?, 'registry', ?, ?, ?,
                'manual', 1.0, '[]', 1, 1
            )
            """,
            (scope_harness.game_id, key, key, key.casefold()),
        ).rowcount
    ).result()

    preview = scope_harness.builder.preview(scope_harness.game_id)

    assert any(target.key == key for target in preview.registry_targets)


def test_preview_keeps_an_unavailable_default_visible_and_disabled(
    scope_harness: ScopeHarness,
) -> None:
    scope_harness.folders.saved_games.rmdir()

    preview = scope_harness.builder.preview(scope_harness.game_id)
    saved_games = next(
        scope for scope in preview.scopes if scope.id == "default:saved-games"
    )

    assert saved_games.available is False
    assert saved_games.unavailable_reason == "目录不存在或无法访问。"


def test_resolve_selected_revalidates_a_directory_that_disappeared(
    scope_harness: ScopeHarness,
) -> None:
    preview = scope_harness.builder.preview(scope_harness.game_id)
    documents = next(scope for scope in preview.scopes if scope.id == "default:documents")
    scope_harness.folders.documents.rmdir()

    with pytest.raises(InvalidGuidedScope, match="确认后已不可用"):
        scope_harness.builder.resolve_selected(
            scope_harness.game_id, (documents.id,), ()
        )


def test_resolve_selected_rejects_unc_unknown_and_unportable_directories(
    scope_harness: ScopeHarness, tmp_path: Path
) -> None:
    outside = tmp_path / "Outside"
    outside.mkdir()

    with pytest.raises(InvalidGuidedScope, match="未知的监控范围"):
        scope_harness.builder.resolve_selected(
            scope_harness.game_id, ("default:unknown",), ()
        )
    with pytest.raises(InvalidGuidedScope, match="不支持网络目录"):
        scope_harness.builder.resolve_selected(
            scope_harness.game_id, ("default:game",), (r"\\server\share",)
        )
    with pytest.raises(InvalidGuidedScope, match="无法表示为便携存档路径"):
        scope_harness.builder.resolve_selected(
            scope_harness.game_id, ("default:game",), (str(outside),)
        )


def test_resolve_selected_collapses_nested_extra_directory_to_outer_scope(
    scope_harness: ScopeHarness,
) -> None:
    nested = scope_harness.game_dir / "Saves"
    nested.mkdir()

    resolved = scope_harness.builder.resolve_selected(
        scope_harness.game_id,
        ("default:game",),
        (str(nested),),
    )

    assert [scope.id for scope in resolved] == ["default:game"]


def test_preview_rejects_a_game_without_a_launchable_executable(
    scope_harness: ScopeHarness,
) -> None:
    scope_harness.writer.submit(
        lambda connection: connection.execute(
            "UPDATE games SET main_exe_relpath = NULL WHERE id = ?",
            (scope_harness.game_id,),
        ).rowcount
    ).result()

    with pytest.raises(InvalidGuidedScope, match="尚未配置可启动的主程序"):
        scope_harness.builder.preview(scope_harness.game_id)


def _insert_confirmed_location(
    connection: sqlite3.Connection,
    game_id: str,
    display_path: Path,
    path_template: str,
) -> None:
    connection.execute(
        """
        INSERT INTO save_locations(
            id, game_id, kind, path_template, display_path, path_key,
            source, confidence, confirmed, enabled
        ) VALUES (
            'save-1', ?, 'directory', ?, ?, ?, 'manual', 1.0, 1, 1
        )
        """,
        (game_id, path_template, str(display_path), windows_path_key(display_path)),
    )
