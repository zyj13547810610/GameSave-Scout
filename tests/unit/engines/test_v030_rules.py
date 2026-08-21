from pathlib import Path

import pytest

from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.rule_detector import RuleDetector
from gameshelf.engines.rule_schema import load_engine_rules
from gameshelf.engines.service import EngineDetectionService

RULES_FILE = Path("resources/rules/engines.yaml")


def test_livemaker_vff_archive_is_detected(tmp_path: Path) -> None:
    (tmp_path / "game.dat").write_bytes(b"vff\0" + b"\0" * 32)

    match = _detect(tmp_path)

    assert match is not None
    assert match.engine_id == "livemaker"
    assert match.experimental is False


@pytest.mark.parametrize("version", [b"5", b"6", b"7"])
def test_cmvs_cpz_with_start_script_is_detected(
    tmp_path: Path, version: bytes
) -> None:
    pack_dir = tmp_path / "data" / "pack"
    pack_dir.mkdir(parents=True)
    (pack_dir / "start.ps3").write_bytes(b"PS3 script")
    (pack_dir / "script.cpz").write_bytes(b"CPZ" + version + b"\0" * 32)

    match = _detect(tmp_path)

    assert match is not None
    assert match.engine_id == "cmvs"
    assert match.experimental is False


def test_godot_standalone_pck_is_detected(tmp_path: Path) -> None:
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    (tmp_path / "game.pck").write_bytes(b"GDPC" + b"\x04\0\0\0" + b"\0" * 32)

    match = _detect(tmp_path)

    assert match is not None
    assert match.engine_id == "godot"
    assert match.experimental is False


def test_godot_project_configuration_is_detected(tmp_path: Path) -> None:
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    (tmp_path / "project.godot").write_text(
        "config_version=5\n[application]\nconfig/name=\"Sample\"\n", encoding="utf-8"
    )

    match = _detect(tmp_path)

    assert match is not None
    assert match.engine_id == "godot"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("game.dat", b"random dat"),
        ("script.cpz", b"random cpz"),
        ("game.pck", b"random pck"),
    ],
)
def test_new_engine_extensions_with_random_content_are_unknown(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    (tmp_path / filename).write_bytes(content)
    assert _detect(tmp_path) is None


def test_livemaker_gal_image_alone_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "image.gal").write_bytes(b"GaleX200" + b"\0" * 32)
    assert _detect(tmp_path) is None


@pytest.mark.parametrize("version", [b"5", b"6", b"7"])
def test_cmvs_cpz_without_start_script_is_unknown(
    tmp_path: Path, version: bytes
) -> None:
    (tmp_path / "script.cpz").write_bytes(b"CPZ" + version + b"\0" * 32)
    assert _detect(tmp_path) is None


def test_cmvs_start_script_without_cpz_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "start.ps3").write_bytes(b"PS3 script")
    assert _detect(tmp_path) is None


def test_cmvs_unsupported_cpz_version_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "start.ps3").write_bytes(b"PS3 script")
    (tmp_path / "script.cpz").write_bytes(b"CPZ4" + b"\0" * 32)
    assert _detect(tmp_path) is None


def test_godot_magic_at_the_wrong_offset_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    (tmp_path / "game.pck").write_bytes(b"\0GDPC" + b"\0" * 32)
    assert _detect(tmp_path) is None


def test_project_godot_without_config_header_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    (tmp_path / "project.godot").write_text("ordinary text", encoding="utf-8")
    assert _detect(tmp_path) is None


def test_new_rules_are_exposed_as_formal_engine_options() -> None:
    service = EngineDetectionService.from_rules_file(RULES_FILE)

    options = {option.id: option for option in service.list_options()}

    assert options["livemaker"].experimental is False
    assert options["cmvs"].experimental is False
    assert options["godot"].experimental is False


def _detect(game_dir: Path):
    rules = load_engine_rules(RULES_FILE)
    return DetectorRegistry(RuleDetector(rule) for rule in rules).detect(
        game_dir, None
    ).best
