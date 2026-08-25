from pathlib import Path

import pytest

from gamesave_scout.engines.registry import DetectorRegistry
from gamesave_scout.engines.rule_detector import RuleDetector
from gamesave_scout.engines.rule_schema import load_engine_rules

QLIE_SIGNATURE = b"FilePackVer3.0"
MAJIRO_SIGNATURE = b"MajiroArcV3.000\0"
MALIE_SIGNATURE = b"LIB\0"
SHIINA_RIO_SIGNATURE = b"WARC 1.7"
SOFTPAL_SIGNATURE = b"PAC "
ENTIS_SIGNATURE = b"Entis\x1a\0\0\x00\x04\x00\x02"
NITROPLUS_SIGNATURE = b"NPA\x01"


@pytest.mark.parametrize(
    ("engine_id", "filename", "content", "experimental"),
    [
        ("qlie", "data.pack", b"payload" + QLIE_SIGNATURE + b"\0" * 14, False),
        ("majiro", "data.arc", MAJIRO_SIGNATURE + b"\0" * 32, False),
        ("malie", "data.lib", MALIE_SIGNATURE + b"\0" * 32, False),
        ("shiina_rio", "data.war", SHIINA_RIO_SIGNATURE + b"\0" * 32, False),
        (
            "softpal_amusecraft",
            "data.pac",
            SOFTPAL_SIGNATURE + b"\0" * 32,
            True,
        ),
        ("entis", "data.noa", ENTIS_SIGNATURE + b"\0" * 32, False),
        ("nitroplus", "data.npa", NITROPLUS_SIGNATURE + b"\0" * 40, False),
    ],
)
def test_calibrated_archive_signature(
    tmp_path: Path,
    engine_id: str,
    filename: str,
    content: bytes,
    experimental: bool,
) -> None:
    (tmp_path / filename).write_bytes(content)

    outcome = _registry().detect(tmp_path, None)

    assert outcome.best is not None
    assert outcome.best.engine_id == engine_id
    assert outcome.best.experimental is experimental


@pytest.mark.parametrize(
    "filename",
    ["data.pack", "data.arc", "data.lib", "data.war", "data.pac", "data.noa", "data.npa"],
)
def test_random_content_with_same_filename_is_unknown(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_bytes(b"random bytes")
    assert _registry().detect(tmp_path, None).best is None


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("data.pack", b"payload" + QLIE_SIGNATURE + b"\0" * 13),
        ("data.arc", b"\0" + MAJIRO_SIGNATURE),
        ("data.lib", b"\0" + MALIE_SIGNATURE),
        ("data.war", b"\0" + SHIINA_RIO_SIGNATURE),
        ("data.pac", b"\0" + SOFTPAL_SIGNATURE),
        ("data.noa", b"\0" + ENTIS_SIGNATURE),
        ("data.npa", b"\0" + NITROPLUS_SIGNATURE),
    ],
)
def test_shifted_signature_is_unknown(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    (tmp_path / filename).write_bytes(content)
    assert _registry().detect(tmp_path, None).best is None


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("data.pack", QLIE_SIGNATURE[:-1] + b"\0" * 14),
        ("data.arc", MAJIRO_SIGNATURE[:-1]),
        ("data.lib", MALIE_SIGNATURE[:-1]),
        ("data.war", b"WAR"),
        ("data.pac", b"PAC"),
        ("data.noa", b"Entis"),
        ("data.npa", b"NPA"),
    ],
)
def test_truncated_signature_is_unknown(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    (tmp_path / filename).write_bytes(content)
    assert _registry().detect(tmp_path, None).best is None


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("data.lib", b"LIBP" + b"\0" * 32),
        ("data.war", b"WARCxxxx" + b"\0" * 32),
        ("data.noa", b"Entis\x1a\0\0\0\0\0\0" + b"\0" * 32),
    ],
)
def test_format_header_without_required_structure_is_unknown(
    tmp_path: Path, filename: str, content: bytes
) -> None:
    (tmp_path / filename).write_bytes(content)
    assert _registry().detect(tmp_path, None).best is None


def test_v032_short_or_encrypted_headers_remain_experimental() -> None:
    expected = {
        "az_system",
        "advdx_ads",
        "dac",
        "foster",
        "liar_soft",
        "mnp",
        "yox",
    }
    rules = {
        rule.engine_id: rule
        for rule in load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    }

    assert len(expected) == 7
    assert all(rules[engine_id].experimental for engine_id in expected)
    assert all(rules[engine_id].threshold >= 0.8 for engine_id in expected)


def _registry() -> DetectorRegistry:
    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    return DetectorRegistry(RuleDetector(rule) for rule in rules)
