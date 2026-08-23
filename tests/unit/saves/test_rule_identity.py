from pathlib import Path

from gameshelf.library.models import Game
from gameshelf.saves.models import SaveLocation
from gameshelf.saves.rule_identity import collect_rule_identity


def test_identity_uses_exact_titles_and_normalizes_supported_product_ids() -> None:
    game = _game(
        title="千恋＊万花",
        detected_title="Senren Banka RJ012345",
        relative_dir="Senren_Banka_VJ000777_v1.0",
        main_exe="steam:1144400",
    )
    location = SaveLocation(
        id="location-1",
        game_id=game.id,
        kind="directory",
        path_template=r"<winDocuments>\RJ012345\Save",
        display_path=r"D:\Saves\RJ012345\Save",
        path_key=r"d:\saves\rj012345\save",
        source="manual",
        confidence=1.0,
        evidence=("来源 dlsite:RJ012345；镜像 gog:game_1",),
        confirmed=True,
        enabled=True,
        last_verified_at=None,
    )

    identity = collect_rule_identity(game, (location,))

    assert identity.exact_titles == ("千恋＊万花", "Senren Banka RJ012345")
    assert identity.product_ids == (
        "dlsite:RJ012345",
        "dlsite:VJ000777",
        "steam:1144400",
        "gog:game_1",
    )


def test_identity_ignores_game_version_and_unconfirmed_or_disabled_locations() -> None:
    game = _game(
        title="Game",
        detected_title="Game",
        relative_dir="Game",
        main_exe="Game.exe",
        version="RJ999999",
    )
    locations = (
        _location("RJ000001", confirmed=False, enabled=True),
        _location("VJ000002", confirmed=True, enabled=False),
    )

    identity = collect_rule_identity(game, locations)

    assert identity.exact_titles == ("Game",)
    assert identity.product_ids == ()


def _game(
    *,
    title: str,
    detected_title: str | None,
    relative_dir: str,
    main_exe: str,
    version: str | None = None,
) -> Game:
    return Game(
        id="game-1",
        scan_root_id="root-1",
        relative_dir=relative_dir,
        install_path_key=r"d:\games\game",
        title=title,
        detected_title=detected_title,
        status="installed",
        detected_engine_id=None,
        detected_engine_variant=None,
        engine_id=None,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=None,
        engine_evidence=(),
        engine_rules_version=None,
        main_exe_relpath=main_exe,
        main_exe_is_manual=False,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="unknown",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        version=version,
        last_launched_at=None,
        missing_since=None,
    )


def _location(value: str, *, confirmed: bool, enabled: bool) -> SaveLocation:
    path = Path("D:/Saves") / value
    return SaveLocation(
        id=value,
        game_id="game-1",
        kind="directory",
        path_template=rf"<winDocuments>\{value}",
        display_path=str(path),
        path_key=str(path).casefold(),
        source="manual",
        confidence=1.0,
        evidence=(),
        confirmed=confirmed,
        enabled=enabled,
        last_verified_at=None,
    )
