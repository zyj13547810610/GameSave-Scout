from pathlib import Path

import pytest

from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.rule_detector import RuleDetector
from gameshelf.engines.rule_schema import load_engine_rules
from gameshelf.scanning.pe_metadata import PeMetadata


@pytest.mark.parametrize(
    ("engine_id", "files"),
    [
        ("artemis", {"assets_01.pfs": b"pf\0\0", "movie.mja": b"MJA0"}),
        ("reallive", {"Gameexe.ini": b"[Window]", "seen.txt": b"PACL" + b"\0" * 32}),
        ("bgi_ethornell", {"data.arc": b"PackFile    " + b"\0" * 32}),
        ("catsystem2", {"data.dat": b"CsPack2" + b"\0" * 32, "scene.cst": b"CatScene"}),
        ("yuris", {"data.ypf": b"YPF\0" + b"\0" * 32, "script.ybn": b"YBN"}),
        ("nscripter", {"nscript.dat": b"\x84\0", "arc.nsa": b"\0" * 16}),
    ],
)
def test_galgame_signature_combinations(tmp_path: Path, engine_id: str, files) -> None:
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    rules = load_engine_rules(Path("resources/rules/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)
    assert outcome.best is not None and outcome.best.engine_id == engine_id


@pytest.mark.parametrize("name", ["data.arc", "data.dat", "data.int", "data.pac", "Game.exe"])
def test_generic_file_alone_remains_unknown(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_bytes(b"random generic bytes")
    rules = load_engine_rules(Path("resources/rules/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)
    assert outcome.best is None


def test_artemis_pfs_extension_without_magic_remains_unknown(tmp_path: Path) -> None:
    (tmp_path / "assets_01.pfs").write_bytes(b"not pfs")
    (tmp_path / "movie.mja").write_bytes(b"MJA0")
    rules = load_engine_rules(Path("resources/rules/engines.yaml"))

    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)

    assert outcome.best is None


def test_artemis_reports_the_actual_variable_pfs_path(tmp_path: Path) -> None:
    (tmp_path / "assets_01.pfs").write_bytes(b"pf\0\0")
    (tmp_path / "movie.mja").write_bytes(b"MJA0")
    rules = load_engine_rules(Path("resources/rules/engines.yaml"))

    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)

    assert outcome.best is not None and outcome.best.engine_id == "artemis"
    assert {item.path for item in outcome.best.evidence} == {
        "assets_01.pfs",
        "movie.mja",
    }


@pytest.mark.parametrize("scene_name", ["Scene.pck", "Scene.chs", "Scene.gbk"])
def test_siglus_accepts_exact_scene_file_variants(
    tmp_path: Path, monkeypatch, scene_name: str
) -> None:
    (tmp_path / "SiglusEngine.exe").write_bytes(b"MZ")
    (tmp_path / scene_name).write_bytes(b"scene")
    monkeypatch.setattr(
        "gameshelf.engines.rule_detector.read_pe_metadata",
        lambda _: PeMetadata(
            product_name="Siglus",
            file_description="Siglus（VisualArt's 游戏执行引擎）",
            company_name="VisualArt's",
            architecture="x86",
        ),
    )

    rules = load_engine_rules(Path("resources/rules/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(
        tmp_path, tmp_path / "SiglusEngine.exe"
    )

    assert outcome.best is not None and outcome.best.engine_id == "siglus"
    assert outcome.best.rule_version == "2026.08.21-1"
    assert {item.path for item in outcome.best.evidence} == {
        "SiglusEngine.exe",
        scene_name,
    }


def test_siglus_scene_without_pe_product_evidence_remains_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "SiglusEngine.exe").write_bytes(b"MZ")
    (tmp_path / "Scene.chs").write_bytes(b"scene")
    monkeypatch.setattr(
        "gameshelf.engines.rule_detector.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "unknown"),
    )

    rules = load_engine_rules(Path("resources/rules/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(
        tmp_path, None
    )

    assert outcome.best is None


def test_siglus_pe_product_with_unrelated_scene_file_remains_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "SiglusEngine.exe").write_bytes(b"MZ")
    (tmp_path / "Scene.txt").write_bytes(b"scene")
    monkeypatch.setattr(
        "gameshelf.engines.rule_detector.read_pe_metadata",
        lambda _: PeMetadata("Siglus", "", "VisualArt's", "x86"),
    )

    rules = load_engine_rules(Path("resources/rules/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(
        tmp_path, None
    )

    assert outcome.best is None
