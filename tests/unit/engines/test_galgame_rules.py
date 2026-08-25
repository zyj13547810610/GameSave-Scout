from dataclasses import dataclass
from pathlib import Path

import pytest

from gamesave_scout.engines.registry import DetectorRegistry
from gamesave_scout.engines.rule_detector import RuleDetector
from gamesave_scout.engines.rule_schema import load_engine_rules
from gamesave_scout.scanning.pe_metadata import PeMetadata

GARBRO_COMMIT = "b09ee4570ccb1daf6ac56710ee8934dc0b8baeb0"


@dataclass(frozen=True, slots=True)
class DirectRuleFixture:
    engine_id: str
    filename: str
    content: bytes
    magic_offset: int
    magic: bytes
    supporting_files: tuple[tuple[str, bytes], ...] = ()


def _content(*parts: tuple[int, bytes]) -> bytes:
    payload = bytearray(max(offset + len(value) for offset, value in parts) + 8)
    for offset, value in parts:
        payload[offset : offset + len(value)] = value
    return bytes(payload)


DIRECT_RULE_FIXTURES = (
    DirectRuleFixture(
        "active_soft_adpack32", "data.pak", _content((0, b"ADPA"), (4, b"CK32")), 4, b"CK32"
    ),
    DirectRuleFixture(
        "advscripter", "data.pak", _content((0, b"MD002"), (0x21, b"00V")), 0x21, b"00V"
    ),
    DirectRuleFixture("advsys_t", "data.fpk", _content((0, b"MFWY")), 0, b"MFWY"),
    DirectRuleFixture(
        "alice_system4", "data.afa", _content((0, b"AFAH"), (8, b"AlicArch")), 8, b"AlicArch"
    ),
    *(
        DirectRuleFixture("aoi", "data.box", _content((0, header)), 0, header)
        for header in (
            b"AOIBX10",
            b"AOIBX12",
            b"AOIBOX7\0",
            b"AOIBOX6\0",
            b"AOIBOX5 ",
            b"AOIBOX4 ",
            b"AOIMY01\0",
            "AOIMY01\0".encode("utf-16-le"),
        )
    ),
    DirectRuleFixture(
        "dai_system", "data.pac", _content((0, b"DAI_SYSTEM_01000")), 0, b"DAI_SYSTEM_01000"
    ),
    *(
        DirectRuleFixture("ddsystem", "data.dat", _content((0, magic)), 0, magic)
        for magic in (b"DDP2", b"DDP3")
    ),
    *(
        DirectRuleFixture("densdk", "data.dat", _content((0, magic)), 0, magic)
        for magic in (b"DAF1", b"DAF2")
    ),
    DirectRuleFixture(
        "dxlib8", "data.bin", _content((0, bytes.fromhex("44580800"))), 0, bytes.fromhex("44580800")
    ),
    *(
        DirectRuleFixture("ellefin", "data.epk", _content((0, magic)), 0, magic)
        for magic in (b"EPK\x1a", b"EPK\x1e")
    ),
    *(
        DirectRuleFixture("emon_engine", filename, _content((0, b"RREDATA ")), 0, b"RREDATA ")
        for filename in ("data.eme", "data.rre")
    ),
    DirectRuleFixture(
        "eushully", "sys3ini.bin", _content((0, b"S3IC")), 0, b"S3IC", (("data.alf", b"alf"),)
    ),
    DirectRuleFixture(
        "eushully", "sys3ini.bin", _content((0, b"S3IN")), 0, b"S3IN", (("data.alf", b"alf"),)
    ),
    DirectRuleFixture(
        "eushully", "sys4ini.bin", _content((0, b"S4IC")), 0, b"S4IC", (("data.alf", b"alf"),)
    ),
    DirectRuleFixture(
        "eushully", "sys4ini.bin", _content((0, b"S4AC")), 0, b"S4AC", (("data.alf", b"alf"),)
    ),
    *(
        DirectRuleFixture("favorite_view_point", "data.bin", _content((0, magic)), 0, magic)
        for magic in (b"ACPXPK01", b"ACP_PK.1")
    ),
    DirectRuleFixture("fc_mrg", "data.mrg", _content((0, b"mrg0")), 0, b"mrg0"),
    *(
        DirectRuleFixture("ffa_system", "data.arc", _content((0, magic)), 0, magic)
        for magic in (b"M2TYPE_WAV", b"M2T_BMP", b"M2T_WORD")
    ),
    DirectRuleFixture("g2", "data.pak", _content((0, b"GCEX")), 0, b"GCEX"),
    *(
        DirectRuleFixture("glib", filename, _content((0, b"GML_ARC\0")), 0, b"GML_ARC\0")
        for filename in ("data.g", "data.xp")
    ),
    *(
        DirectRuleFixture(
            "glib2",
            filename,
            _content((0, bytes.fromhex("1033d347"))),
            0,
            bytes.fromhex("1033d347"),
        )
        for filename in ("data.g2", "data.stx")
    ),
    DirectRuleFixture(
        "gss",
        "data.bin",
        _content((0, b"LSDARC V.100")),
        0,
        b"LSDARC V.100",
        (("data.arc", b"payload"),),
    ),
    *(
        DirectRuleFixture("hsp", filename, _content((0, b"DPMX")), 0, b"DPMX")
        for filename in ("data.dpm", "data.bin", "data.dat")
    ),
    *(
        DirectRuleFixture("hypatia", filename, _content((0, b"HyPack")), 0, b"HyPack")
        for filename in ("data.pak", "data.dat")
    ),
    DirectRuleFixture("ism", "data.isa", _content((0, b"ISM ARCHIVED")), 0, b"ISM ARCHIVED"),
    *(
        DirectRuleFixture("kaguya", "data.arc", _content((0, magic)), 0, magic)
        for magic in (b"WFL1", b"LIN2", b"LINK")
    ),
    DirectRuleFixture("kscript", "data.kpc", _content((0, b"SCRPACK1")), 0, b"SCRPACK1"),
    DirectRuleFixture("lambda", "data.dat", _content((0, b"CLS_FILELINK")), 0, b"CLS_FILELINK"),
    DirectRuleFixture("lambda", "data.lax", _content((0, b"$LapH__")), 0, b"$LapH__"),
    DirectRuleFixture("littlewitch", "data.dat", _content((0, b"RepiPack")), 0, b"RepiPack"),
    DirectRuleFixture("lucifen", "SCRIPT.LPK", _content((0, b"LPK1")), 0, b"LPK1"),
    DirectRuleFixture("neko_sdk", "data.pak", _content((0, b"NEKOPACK4")), 0, b"NEKOPACK4"),
    *(
        DirectRuleFixture("pajamas", filename, _content((0, b"GAMEDAT PAC")), 0, b"GAMEDAT PAC")
        for filename in ("data.dat", "data.pak")
    ),
    DirectRuleFixture(
        "rugp", "data.rio", _content((0, bytes.fromhex("cd326e59"))), 0, bytes.fromhex("cd326e59")
    ),
    DirectRuleFixture("sas5", "data.sec5", _content((0, b"SEC5")), 0, b"SEC5"),
    DirectRuleFixture("selene", "data.pack", _content((0, b"KCAP")), 0, b"KCAP"),
    *(
        DirectRuleFixture("sh_system", "data.hxp", _content((0, magic)), 0, magic)
        for magic in (b"Him4", b"Him5", b"SHS6", b"SHS7")
    ),
    DirectRuleFixture("silky_ai6win", "data.ifl", _content((0, b"IFLS")), 0, b"IFLS"),
    *(
        DirectRuleFixture("silky_ai6win", filename, _content((0, b"ALPF")), 0, b"ALPF")
        for filename in ("data.mfg", "data.mfm", "data.mfs")
    ),
    DirectRuleFixture("slg_system", "data.szs", _content((0, b"SZS10__")), 0, b"SZS10__"),
    DirectRuleFixture("super_nekox", "data.gpc", _content((0, b"Gpc7")), 0, b"Gpc7"),
    DirectRuleFixture("sviu", "data.pkz", _content((0, b"PKZ0")), 0, b"PKZ0"),
    *(
        DirectRuleFixture(
            "tactics", filename, _content((0, b"TACTICS_ARC_FILE")), 0, b"TACTICS_ARC_FILE"
        )
        for filename in ("data.arc", "data.adf")
    ),
    DirectRuleFixture("tamasoft", "data.epk", _content((0, b"EPK ")), 0, b"EPK "),
    *(
        DirectRuleFixture(
            "tanaka", filename, _content((0, b"ARCG\x00\x00\x01\x00")), 0, b"ARCG\x00\x00\x01\x00"
        )
        for filename in ("data.arc", "data.bmx", "data.scb", "data.vpk")
    ),
    DirectRuleFixture("taskforce", "data.dat", _content((0, b"tskforce")), 0, b"tskforce"),
    DirectRuleFixture("gem_vnengine", "data.axr", _content((0, b"AXRe")), 0, b"AXRe"),
    DirectRuleFixture("vnsystem", "data.vfs", _content((0, b"VFS File")), 0, b"VFS File"),
    DirectRuleFixture(
        "wild_bug", "data.wbp", _content((0, b"ARCFORM2"), (8, b" WBUG ")), 8, b" WBUG "
    ),
    *(
        DirectRuleFixture("yuka", filename, _content((0, b"YKC0")), 0, b"YKC0")
        for filename in ("data.ykc", "data.dat")
    ),
    *(
        DirectRuleFixture("az_system", "data.arc", _content((0, magic)), 0, magic)
        for magic in (b"ARC\x1a", bytes.fromhex("eb06ea53"), bytes.fromhex("2f8ff974"))
    ),
    DirectRuleFixture(
        "advdx_ads",
        "data.ads",
        _content((0, bytes.fromhex("4e51d984"))),
        0,
        bytes.fromhex("4e51d984"),
    ),
    DirectRuleFixture("dac", "data.dpk", _content((0, b"DPK\0")), 0, b"DPK\0"),
    DirectRuleFixture("foster", "data.fa2", _content((0, b"FA2\0")), 0, b"FA2\0"),
    DirectRuleFixture(
        "liar_soft",
        "data.xfl",
        _content((0, bytes.fromhex("4c420100"))),
        0,
        bytes.fromhex("4c420100"),
    ),
    DirectRuleFixture("mnp", "data.mma", _content((0, b"ARC!")), 0, b"ARC!"),
    DirectRuleFixture("yox", "data.dat", _content((0, b"YOX\0")), 0, b"YOX\0"),
)

FORMAL_DIRECT_RULE_IDS = {
    "active_soft_adpack32",
    "advscripter",
    "advsys_t",
    "alice_system4",
    "aoi",
    "dai_system",
    "ddsystem",
    "densdk",
    "dxlib8",
    "ellefin",
    "emon_engine",
    "eushully",
    "favorite_view_point",
    "fc_mrg",
    "ffa_system",
    "g2",
    "glib",
    "glib2",
    "gss",
    "hsp",
    "hypatia",
    "ism",
    "kaguya",
    "kscript",
    "lambda",
    "littlewitch",
    "lucifen",
    "neko_sdk",
    "pajamas",
    "rugp",
    "sas5",
    "selene",
    "sh_system",
    "silky_ai6win",
    "slg_system",
    "super_nekox",
    "sviu",
    "tactics",
    "tamasoft",
    "tanaka",
    "taskforce",
    "gem_vnengine",
    "vnsystem",
    "wild_bug",
    "yuka",
}
EXPERIMENTAL_DIRECT_RULE_IDS = {
    "az_system",
    "advdx_ads",
    "dac",
    "foster",
    "liar_soft",
    "mnp",
    "yox",
}
NEGATIVE_DIRECT_RULE_FIXTURES = tuple(
    {fixture.engine_id: fixture for fixture in DIRECT_RULE_FIXTURES}.values()
)


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
    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)
    assert outcome.best is not None and outcome.best.engine_id == engine_id


@pytest.mark.parametrize("name", ["data.arc", "data.dat", "data.int", "data.pac", "Game.exe"])
def test_generic_file_alone_remains_unknown(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_bytes(b"random generic bytes")
    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)
    assert outcome.best is None


@pytest.mark.parametrize(
    "fixture",
    DIRECT_RULE_FIXTURES,
    ids=lambda fixture: f"{fixture.engine_id}-{fixture.filename}-{fixture.magic.hex()}",
)
def test_v032_direct_rule_supported_variants_match(
    tmp_path: Path,
    fixture: DirectRuleFixture,
) -> None:
    _write_direct_fixture(tmp_path, fixture, fixture.content)

    outcome = _direct_registry().detect(tmp_path, None)

    assert outcome.best is not None
    assert outcome.best.engine_id == fixture.engine_id


@pytest.mark.parametrize("mutation", ["near", "truncated"])
@pytest.mark.parametrize(
    "fixture",
    NEGATIVE_DIRECT_RULE_FIXTURES,
    ids=lambda fixture: fixture.engine_id,
)
def test_v032_direct_rules_reject_near_and_truncated_magic(
    tmp_path: Path,
    fixture: DirectRuleFixture,
    mutation: str,
) -> None:
    end = fixture.magic_offset + len(fixture.magic)
    if mutation == "near":
        content = bytearray(fixture.content)
        content[fixture.magic_offset] ^= 0x80
        changed = bytes(content)
    else:
        changed = fixture.content[: end - 1]
    _write_direct_fixture(tmp_path, fixture, changed)

    outcome = _direct_registry().detect(tmp_path, None)

    assert outcome.best is None


def test_v032_direct_rule_statuses_references_and_thresholds_are_fixed() -> None:
    rules = {
        rule.engine_id: rule
        for rule in load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    }

    assert len(FORMAL_DIRECT_RULE_IDS) == 45
    assert len(EXPERIMENTAL_DIRECT_RULE_IDS) == 7
    assert FORMAL_DIRECT_RULE_IDS.isdisjoint(EXPERIMENTAL_DIRECT_RULE_IDS)
    for engine_id in FORMAL_DIRECT_RULE_IDS:
        rule = rules[engine_id]
        assert rule.experimental is False
        assert rule.metadata.references
        assert all(
            f"/blob/{GARBRO_COMMIT}/ArcFormats/" in item for item in rule.metadata.references
        )
    for engine_id in EXPERIMENTAL_DIRECT_RULE_IDS:
        rule = rules[engine_id]
        assert rule.experimental is True
        assert rule.threshold >= 0.8
        assert rule.metadata.references
        assert all(
            f"/blob/{GARBRO_COMMIT}/ArcFormats/" in item for item in rule.metadata.references
        )


def test_v032_shared_headers_stay_scoped_by_extension(tmp_path: Path) -> None:
    (tmp_path / "data.pack").write_bytes(b"KCAP" + b"\0" * 16)
    outcome = _direct_registry().detect(tmp_path, None)
    assert outcome.best is not None and outcome.best.engine_id == "selene"

    (tmp_path / "data.pack").unlink()
    (tmp_path / "data.dat").write_bytes(b"KCAP" + b"\0" * 16)
    assert _direct_registry().detect(tmp_path, None).best is None

    (tmp_path / "data.dat").unlink()
    (tmp_path / "data.pak").write_bytes(b"NEKOPACK" + b"\0" * 16)
    assert _direct_registry().detect(tmp_path, None).best is None


@pytest.mark.parametrize(
    "fixture",
    [
        next(item for item in DIRECT_RULE_FIXTURES if item.engine_id == "eushully"),
        next(item for item in DIRECT_RULE_FIXTURES if item.engine_id == "gss"),
    ],
    ids=lambda fixture: fixture.engine_id,
)
def test_v032_composite_rules_require_their_companion_file(
    tmp_path: Path,
    fixture: DirectRuleFixture,
) -> None:
    (tmp_path / fixture.filename).write_bytes(fixture.content)

    assert _direct_registry().detect(tmp_path, None).best is None


def _write_direct_fixture(
    root: Path,
    fixture: DirectRuleFixture,
    content: bytes,
) -> None:
    for relative, supporting_content in fixture.supporting_files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(supporting_content)
    path = root / fixture.filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _direct_registry() -> DetectorRegistry:
    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    return DetectorRegistry(RuleDetector(rule) for rule in rules)


def test_artemis_pfs_extension_without_magic_remains_unknown(tmp_path: Path) -> None:
    (tmp_path / "assets_01.pfs").write_bytes(b"not pfs")
    (tmp_path / "movie.mja").write_bytes(b"MJA0")
    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))

    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)

    assert outcome.best is None


def test_artemis_reports_the_actual_variable_pfs_path(tmp_path: Path) -> None:
    (tmp_path / "assets_01.pfs").write_bytes(b"pf\0\0")
    (tmp_path / "movie.mja").write_bytes(b"MJA0")
    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))

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
        "gamesave_scout.engines.rule_detector.read_pe_metadata",
        lambda _: PeMetadata(
            product_name="Siglus",
            file_description="Siglus（VisualArt's 游戏执行引擎）",
            company_name="VisualArt's",
            architecture="x86",
        ),
    )

    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(
        tmp_path, tmp_path / "SiglusEngine.exe"
    )

    assert outcome.best is not None and outcome.best.engine_id == "siglus"
    assert outcome.best.rule_version == "2026.08.25-1"
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
        "gamesave_scout.engines.rule_detector.read_pe_metadata",
        lambda _: PeMetadata("", "", "", "unknown"),
    )

    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)

    assert outcome.best is None


def test_siglus_pe_product_with_unrelated_scene_file_remains_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "SiglusEngine.exe").write_bytes(b"MZ")
    (tmp_path / "Scene.txt").write_bytes(b"scene")
    monkeypatch.setattr(
        "gamesave_scout.engines.rule_detector.read_pe_metadata",
        lambda _: PeMetadata("Siglus", "", "VisualArt's", "x86"),
    )

    rules = load_engine_rules(Path("resources/rules/builtin/engines.yaml"))
    outcome = DetectorRegistry(RuleDetector(rule) for rule in rules).detect(tmp_path, None)

    assert outcome.best is None
