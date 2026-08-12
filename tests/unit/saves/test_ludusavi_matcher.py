from pathlib import Path

from gameshelf.library.models import Game
from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.ludusavi_matcher import LudusaviMatcher
from gameshelf.saves.ludusavi_parser import parse_manifest
from gameshelf.saves.templates import PathTemplateResolver

FIXTURE = Path(__file__).parents[2] / "fixtures" / "ludusavi" / "manifest.yaml"


def test_matcher_uses_title_install_dir_and_bounded_aliases() -> None:
    matcher = _matcher()

    title_match = matcher.find(_game(title="Alice Story"), Path(r"D:\Games\Other"))
    install_match = matcher.find(_game(title="Unknown"), Path(r"D:\Games\AliceGame"))
    alias_match = matcher.find(_game(title="Bob"), Path(r"D:\Games\Other"))

    assert title_match[0].canonical_name == "Alice Story"
    assert title_match[0].confidence == 1.0
    assert install_match[0].confidence == 1.0
    assert alias_match[0].canonical_name == "Alice Story"
    assert any(item.kind == "registry" for item in title_match[0].locations)


def test_matcher_expands_windows_and_base_tokens_without_touching_filesystem() -> None:
    match = _matcher().find(_game(title="Alice Story"), Path(r"D:\Games\AliceGame"))[0]
    locations = {location.display_path: location for location in match.locations}

    assert r"C:\Users\Alice\AppData\Roaming\RenPy\Alice" in locations
    assert r"D:\Games\AliceGame\config.ini" in locations
    assert locations[r"D:\Games\AliceGame\config.ini"].category == "config"
    assert locations[r"D:\Games\AliceGame\config.ini"].preselected is False
    assert locations[r"D:\Games\AliceGame\steam-cloud\*.sav"].preselected is False
    assert "需要平台：steam" in locations[
        r"D:\Games\AliceGame\steam-cloud\*.sav"
    ].evidence


def test_matcher_returns_only_fuzzy_candidates_at_or_above_threshold() -> None:
    close = _matcher().find(_game(title="Alice Stor"), Path(r"D:\Games\Other"))
    distant = _matcher().find(_game(title="Completely Different"), Path(r"D:\Games\Other"))

    assert len(close) == 1
    assert 0.86 <= close[0].confidence < 1.0
    assert close[0].confirmed is False
    assert distant == ()


def _matcher() -> LudusaviMatcher:
    with FIXTURE.open(encoding="utf-8") as stream:
        manifest = parse_manifest(stream)
    folders = KnownFolders(
        home=Path(r"C:\Users\Alice"),
        app_data=Path(r"C:\Users\Alice\AppData\Roaming"),
        local_app_data=Path(r"C:\Users\Alice\AppData\Local"),
        local_app_data_low=Path(r"C:\Users\Alice\AppData\LocalLow"),
        documents=Path(r"C:\Users\Alice\Documents"),
        saved_games=Path(r"C:\Users\Alice\Saved Games"),
        program_data=Path(r"C:\ProgramData"),
        public=Path(r"C:\Users\Public"),
        windows=Path(r"C:\Windows"),
    )
    return LudusaviMatcher(manifest, PathTemplateResolver(folders))


def _game(*, title: str) -> Game:
    return Game(
        id="game-1",
        scan_root_id="root-1",
        relative_dir="AliceGame",
        install_path_key=r"d:\games\alicegame",
        title=title,
        detected_title=None,
        status="installed",
        detected_engine_id=None,
        detected_engine_variant=None,
        engine_id=None,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=None,
        engine_evidence=(),
        engine_rules_version=None,
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
