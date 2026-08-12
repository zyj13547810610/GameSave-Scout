from pathlib import Path

import pytest

from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.rule_detector import RuleDetector
from gameshelf.engines.rule_schema import load_engine_rules


@pytest.mark.parametrize(
    ("engine_id", "files"),
    [
        ("artemis", {"data.pfs": b"pf\0\0", "movie.mja": b"MJA0"}),
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
