from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from gameshelf.bootstrap.config import AppConfig, ConfigService, JsonConfigStore
from gameshelf.bootstrap.paths import AppPaths
from gameshelf.bridge.api import BridgeApi
from gameshelf.bridge.tasks import TaskRegistry
from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator
from gameshelf.db.writer import DbWriter
from gameshelf.library.group_repository import GroupRepository
from gameshelf.library.group_service import GroupService
from gameshelf.library.repository import LibraryRepository
from gameshelf.library.service import LibraryService
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.batch_candidates import candidate_path_key
from gameshelf.saves.batch_models import RawBatchCandidate, RepresentativeFile
from gameshelf.saves.batch_repository import BatchSaveRepository
from gameshelf.saves.batch_review import BatchSaveReviewService
from gameshelf.saves.batch_rules import (
    BatchRuleCatalog,
    BatchRuleContext,
    RuleIdentity,
)
from gameshelf.saves.batch_scanner import BatchFilesystemScanner
from gameshelf.saves.batch_scope import BatchScopeBuilder
from gameshelf.saves.batch_service import BatchSaveDiscoveryService
from gameshelf.saves.repository import SaveLocationRepository
from gameshelf.saves.service import SaveLocationService
from gameshelf.saves.templates import PathTemplateResolver
from gameshelf.scanning.path_keys import windows_path_key


@dataclass(frozen=True)
class _RuleProvider:
    catalog: BatchRuleCatalog

    def collect(self, _context: BatchRuleContext) -> BatchRuleCatalog:
        return self.catalog


class _Shell:
    def open_directory(self, _path: Path) -> None:
        return None

    def reveal_file(self, _path: Path) -> None:
        return None


class _Registry:
    def key_exists(self, _key: str) -> bool:
        return True

    def open_key(self, _key: str) -> None:
        return None


@dataclass
class _Harness:
    paths: AppPaths
    factory: ConnectionFactory
    writer: DbWriter
    tasks: TaskRegistry
    api: BridgeApi
    repository: BatchSaveRepository
    save_repository: SaveLocationRepository

    def close(self) -> None:
        self.tasks.close()
        self.writer.close()


def test_scan_review_detail_and_rescan_complete_one_real_bridge_loop(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    try:
        first = _run_scan(harness)
        assert first["status"] == "completed"
        assert first["newCount"] == 8

        candidates = _candidate_map(harness)
        assert candidates["InstalledOne"]["classification"] == "installed"
        assert candidates["InstalledOne"]["confidence"] == "high"
        assert candidates["AlreadyRecorded"]["reviewStatus"] == "recorded"
        assert candidates["MissingGame"]["classification"] == "missing"
        assert candidates["RJ123456"]["suggestedTitle"] == "Library External"
        assert candidates["UnknownDojin"]["classification"] == "unknown"
        assert candidates["UnknownDojin"]["confidence"] == "low"
        assert candidates["SharedA"]["strongGroupKey"] == "game:game-installed"
        assert candidates["SharedB"]["strongGroupKey"] == "game:game-installed"

        accepted_ids = [
            candidates[name]["id"]
            for name in ("InstalledOne", "SharedA", "SharedB")
        ]
        accepted = harness.api.accept_batch_save_candidates(
            {"candidateIds": accepted_ids, "confirmRegistry": False}
        )
        assert accepted["ok"] is True
        assert accepted["data"]["recordedCount"] == 3
        installed_locations = harness.api.list_save_locations(
            {"gameId": "game-installed"}
        )
        assert installed_locations["ok"] is True
        assert len(installed_locations["data"]) == 3

        group = harness.api.create_game_group({"name": "存档归档"})
        save_only = harness.api.create_batch_save_only_game(
            {
                "title": "Library External Archive",
                "version": "v1.0",
                "engineId": "renpy",
                "groupIds": [group["data"]["id"]],
                "candidateIds": [candidates["RJ123456"]["id"]],
                "confirmRegistry": False,
            }
        )
        assert save_only["ok"] is True
        archive_id = save_only["data"]["id"]
        assert save_only["data"]["status"] == "save_only"
        assert save_only["data"]["groupIds"] == [group["data"]["id"]]
        archive_locations = harness.api.list_save_locations({"gameId": archive_id})
        assert len(archive_locations["data"]) == 1

        registry_id = candidates["RegistryProduct"]["id"]
        assert harness.api.reassociate_batch_save_candidates(
            {"candidateIds": [registry_id], "gameId": "game-missing"}
        )["ok"] is True
        rejected_registry = harness.api.accept_batch_save_candidates(
            {"candidateIds": [registry_id], "confirmRegistry": False}
        )
        assert rejected_registry["error"]["code"] == "registry_confirmation_required"
        assert harness.api.accept_batch_save_candidates(
            {"candidateIds": [registry_id], "confirmRegistry": True}
        )["ok"] is True

        second = _run_scan(harness)
        assert second["status"] == "completed"
        assert second["newCount"] == 0
        rescanned = _candidate_map(harness)
        assert rescanned["InstalledOne"]["reviewStatus"] == "recorded"
        assert rescanned["RJ123456"]["reviewStatus"] == "save_only"
        assert rescanned["RegistryProduct"]["reviewStatus"] == "recorded"
        assert len(harness.api.list_games()["data"]) == 4
    finally:
        harness.close()


def _build_harness(tmp_path: Path) -> _Harness:
    portable_root = tmp_path / "portable"
    paths = AppPaths.from_root(portable_root)
    paths.ensure_writable()
    known = _known_folders(tmp_path / "profile")
    for folder in known.__slots__:
        Path(getattr(known, folder)).mkdir(parents=True, exist_ok=True)
    candidate_paths = _create_save_tree(known.documents)

    factory = ConnectionFactory(paths.database_file)
    assert Migrator(factory, paths.backups_dir).migrate() == 4
    writer = DbWriter(factory)
    writer.start()
    _insert_library_rows(factory, candidate_paths["AlreadyRecorded"])

    library_repository = LibraryRepository(factory)
    library = LibraryService(library_repository, writer)
    save_repository = SaveLocationRepository(factory)
    resolver = PathTemplateResolver(known)
    batch_repository = BatchSaveRepository(factory, writer)
    batch_review = BatchSaveReviewService(
        factory,
        writer,
        batch_repository,
        engine_ids=("renpy", "unity"),
    )
    catalog = _catalog(candidate_paths, known.documents)
    config = ConfigService(JsonConfigStore(paths.config_file))
    discovery = BatchSaveDiscoveryService(
        repository=batch_repository,
        rule_provider=_RuleProvider(catalog),
        scope_builder=BatchScopeBuilder(known, AppConfig()),
        scanner=BatchFilesystemScanner(progress_interval=1),
        library=library,
        save_repository=save_repository,
    )
    save_locations = SaveLocationService(
        save_repository,
        writer,
        resolver,
        library,
        _Shell(),
        _Registry(),
    )
    groups = GroupService(
        connection_factory=factory,
        writer=writer,
        repository=GroupRepository(factory),
    )
    tasks = TaskRegistry(max_workers=1)
    api = BridgeApi(
        paths,
        tasks,
        schema_version=4,
        config=config,
        library=library,
        groups=groups,
        save_locations=save_locations,
        batch_repository=batch_repository,
        batch_saves=discovery,
        batch_review=batch_review,
    )
    return _Harness(paths, factory, writer, tasks, api, batch_repository, save_repository)


def _known_folders(root: Path) -> KnownFolders:
    return KnownFolders(
        home=root,
        app_data=root / "AppData" / "Roaming",
        local_app_data=root / "AppData" / "Local",
        local_app_data_low=root / "AppData" / "LocalLow",
        documents=root / "Documents",
        saved_games=root / "Saved Games",
        program_data=root / "ProgramData",
        public=root / "Public",
        windows=root / "Windows",
    )


def _create_save_tree(documents: Path) -> dict[str, Path]:
    relative_paths = {
        "InstalledOne": Path("InstalledOne") / "SaveData",
        "AlreadyRecorded": Path("AlreadyRecorded") / "SaveData",
        "MissingGame": Path("MissingGame") / "SaveData",
        "RJ123456": Path("LibraryExternal") / "RJ123456",
        "UnknownDojin": Path("UnknownDojin") / "SaveData",
        "SharedA": Path("SharedGame") / "ProfileA" / "SaveData",
        "SharedB": Path("SharedGame") / "ProfileB" / "SaveData",
    }
    result: dict[str, Path] = {}
    for name, relative in relative_paths.items():
        directory = documents / relative
        directory.mkdir(parents=True)
        directory.joinpath(f"save-{name}.sav").write_bytes(name.encode("utf-8"))
        result[name] = directory
    return result


def _insert_library_rows(factory: ConnectionFactory, recorded_path: Path) -> None:
    with factory.connect() as connection:
        connection.execute(
            """
            INSERT INTO scan_roots(
                id, display_path, path_key, scan_mode, max_depth, created_at
            ) VALUES ('root', 'D:\\Games', 'd:\\games', 'children', 1, 'now')
            """
        )
        connection.executemany(
            """
            INSERT INTO games(
                id, scan_root_id, relative_dir, install_path_key,
                title, status, engine_id, added_at, updated_at
            ) VALUES (?, 'root', ?, ?, ?, ?, ?, 'now', 'now')
            """,
            (
                (
                    "game-installed",
                    "Installed One",
                    r"d:\games\installed one",
                    "Installed One",
                    "installed",
                    "unity",
                ),
                (
                    "game-recorded",
                    "Already Recorded",
                    r"d:\games\already recorded",
                    "Already Recorded",
                    "installed",
                    None,
                ),
                (
                    "game-missing",
                    "Missing Game",
                    r"d:\games\missing game",
                    "Missing Game",
                    "missing",
                    None,
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO save_locations(
                id, game_id, kind, path_template, display_path, path_key,
                source, confidence, evidence_json, confirmed, enabled
            ) VALUES (
                'recorded-location', 'game-recorded', 'directory', ?, ?, ?,
                'manual', 1, '[]', 1, 1
            )
            """,
            (
                r"<winDocuments>\AlreadyRecorded\SaveData",
                str(recorded_path),
                windows_path_key(recorded_path),
            ),
        )
        connection.commit()


def _catalog(paths: dict[str, Path], documents: Path) -> BatchRuleCatalog:
    candidates: list[RawBatchCandidate] = []
    identities: dict[tuple[str, str], tuple[RuleIdentity, ...]] = {}

    def add(
        name: str,
        identity: RuleIdentity | None,
        *,
        source: str,
    ) -> None:
        path = paths[name]
        relative = str(path.relative_to(documents)).replace("/", "\\")
        raw = RawBatchCandidate(
            scope_key="documents",
            kind="directory",
            path_template=rf"<winDocuments>\{relative}",
            display_path=str(path),
            path_key=windows_path_key(path),
            sources=(source,),  # type: ignore[arg-type]
            evidence=(f"{source} 测试规则",),
            representative_files=(RepresentativeFile("save01.sav", 10, 100),),
            matched_file_count=1,
            representatives_truncated=False,
        )
        candidates.append(raw)
        if identity is not None:
            identities[("directory", candidate_path_key("directory", raw.path_key))] = (
                identity,
            )

    add("AlreadyRecorded", None, source="recorded")
    add("InstalledOne", _identity("game-installed", "Installed One"), source="custom")
    add("MissingGame", _identity("game-missing", "Missing Game"), source="custom")
    add("SharedA", _identity("game-installed", "Installed One"), source="ludusavi")
    add("SharedB", _identity("game-installed", "Installed One"), source="ludusavi")
    add(
        "RJ123456",
        RuleIdentity(
            source="ludusavi",
            game_id=None,
            external_title="Library External",
            external_product_id="RJ123456",
            engine_id="renpy",
            confidence="high",
            strong_group_key="product:rj123456",
            evidence=("Ludusavi 库外规则",),
        ),
        source="ludusavi",
    )

    registry_path = r"HKEY_CURRENT_USER\Software\Studio\RegistryProduct"
    registry = RawBatchCandidate(
        scope_key="registry",
        kind="registry",
        path_template=registry_path,
        display_path=registry_path,
        path_key=candidate_path_key("registry", registry_path),
        sources=("registry",),
        evidence=("显式注册表规则",),
        representative_files=(),
        matched_file_count=0,
        representatives_truncated=False,
    )
    candidates.append(registry)
    identities[("registry", registry.path_key)] = (
        RuleIdentity(
            source="custom",
            game_id=None,
            external_title="RegistryProduct",
            external_product_id=None,
            engine_id=None,
            confidence="high",
            strong_group_key="registry:studio/registryproduct",
            evidence=("自定义注册表规则",),
        ),
    )
    return BatchRuleCatalog(
        candidates=tuple(candidates),
        identities_by_path=MappingProxyType(identities),
        reverse_path_rules=(),
        warnings=(),
        rules_version="integration-rules-v1",
    )


def _identity(game_id: str, title: str) -> RuleIdentity:
    return RuleIdentity(
        source="custom",
        game_id=game_id,
        external_title=title,
        external_product_id=None,
        engine_id=None,
        confidence="high",
        strong_group_key=f"game:{game_id}",
        evidence=("已关联本地游戏",),
    )


def _run_scan(harness: _Harness) -> dict[str, object]:
    started = harness.api.start_batch_save_scan(
        {"standardScopeIds": ["documents"], "customRootIds": []}
    )
    assert started["ok"] is True
    snapshot = harness.tasks.wait(started["data"]["taskId"], timeout=5)
    assert snapshot.status == "completed"
    assert isinstance(snapshot.result, dict)
    return snapshot.result


def _candidate_map(harness: _Harness) -> dict[str, dict[str, object]]:
    response = harness.api.list_batch_save_candidates({"offset": 0, "limit": 100})
    assert response["ok"] is True
    items = response["data"]["items"]
    by_marker: dict[str, dict[str, object]] = {}
    for item in items:
        display_path = str(item["displayPath"])
        marker = next(
            (
                name
                for name, fragment in (
                    ("InstalledOne", "InstalledOne"),
                    ("AlreadyRecorded", "AlreadyRecorded"),
                    ("MissingGame", "MissingGame"),
                    ("RJ123456", "RJ123456"),
                    ("UnknownDojin", "UnknownDojin"),
                    ("SharedA", "ProfileA"),
                    ("SharedB", "ProfileB"),
                    ("RegistryProduct", "RegistryProduct"),
                )
                if fragment in display_path
            ),
            None,
        )
        if marker is not None:
            by_marker[marker] = item
    assert set(by_marker) == {
        "InstalledOne",
        "AlreadyRecorded",
        "MissingGame",
        "RJ123456",
        "UnknownDojin",
        "SharedA",
        "SharedB",
        "RegistryProduct",
    }
    return by_marker
