from pathlib import Path

import pytest

from gameshelf.engines.registry import DetectorRegistry
from gameshelf.engines.rule_detector import RuleDetector
from gameshelf.engines.rule_schema import load_engine_rules


@pytest.mark.parametrize(
    ("engine_id", "filename", "content"),
    [
        ("qlie", "data.pack", b"\0" * 32 + b"FilePackVer3.0" + b"\0" * 32),
        ("majiro", "data.arc", b"MajiroArcV3.000\0"),
        ("malie", "data.lib", b"LIBP" + b"\0" * 32),
        ("shiina_rio", "data.war", b"WARC" + b"\0" * 32),
        ("softpal_amusecraft", "data.pac", b"PAC " + b"\0" * 32),
        ("entis", "data.noa", b"Entis\x1a" + b"\0" * 32),
        ("nitroplus", "data.npa", b"NPA\x01" + b"\0" * 32),
    ],
)
def test_experimental_magic(tmp_path: Path, engine_id: str, filename: str, content: bytes) -> None:
    (tmp_path / filename).write_bytes(content)
    outcome = _registry().detect(tmp_path, None)
    assert outcome.best is not None
    assert outcome.best.engine_id == engine_id
    assert outcome.best.experimental is True


@pytest.mark.parametrize(
    "filename",
    ["data.pack", "data.arc", "data.lib", "data.war", "data.pac", "data.noa", "data.npa"],
)
def test_random_content_with_same_extension_is_unknown(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_bytes(b"random bytes")
    assert _registry().detect(tmp_path, None).best is None


def _registry() -> DetectorRegistry:
    rules = load_engine_rules(Path("resources/rules/engines.yaml"))
    return DetectorRegistry(RuleDetector(rule) for rule in rules)
