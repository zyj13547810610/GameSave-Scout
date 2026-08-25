from io import StringIO
from pathlib import Path

import pytest

from gamesave_scout.saves.ludusavi_parser import InvalidLudusaviManifest, parse_manifest

FIXTURE = Path(__file__).parents[2] / "fixtures" / "ludusavi" / "manifest.yaml"


def test_parser_keeps_save_and_unspecified_entries_but_marks_config_only() -> None:
    with FIXTURE.open(encoding="utf-8") as stream:
        manifest = parse_manifest(stream)

    alice = manifest.games["Alice Story"]
    assert alice.files[0].tags == frozenset({"save"})
    assert alice.files[1].tags == frozenset({"config"})
    assert [entry.path for entry in alice.files] == [
        "<winAppData>/RenPy/Alice",
        "<base>/config.ini",
        "<base>/steam-cloud/*.sav",
    ]
    assert alice.files[2].conditions[0].store == "steam"
    assert alice.install_dirs == ("AliceGame",)
    assert manifest.games["Bob"].alias == "Alice Story"


def test_parser_ignores_future_fields_instead_of_rejecting_manifest() -> None:
    manifest = parse_manifest(
        StringIO(
            """
Alice:
  files:
    <base>/save: {tags: [save], future: true}
  futureField: {anything: true}
"""
        )
    )

    assert manifest.games["Alice"].files[0].path == "<base>/save"


@pytest.mark.parametrize(
    "document",
    [
        "- not\n- a\n- mapping\n",
        "Alice: []\n",
        "Alice:\n  files: []\n",
        "Alice:\n  files:\n    C:/raw/save: {}\n",
        "Alice:\n  files:\n    <base>/save:\n      tags: save\n",
    ],
)
def test_parser_rejects_wrong_types_and_unrecognized_path_roots(document: str) -> None:
    with pytest.raises(InvalidLudusaviManifest):
        parse_manifest(StringIO(document))


def test_parser_rejects_alias_cycles_and_more_than_eight_hops() -> None:
    cyclic = "A: {alias: B}\nB: {alias: A}\n"
    long_chain = "\n".join(
        f"Alias{index}: {{alias: Alias{index + 1}}}" for index in range(9)
    ) + "\nAlias9: {files: {'<base>/save': {}}}\n"

    with pytest.raises(InvalidLudusaviManifest, match="别名"):
        parse_manifest(StringIO(cyclic))
    with pytest.raises(InvalidLudusaviManifest, match="8"):
        parse_manifest(StringIO(long_chain))


def test_upstream_mode_skips_pcgw_free_text_and_legacy_linux_variables() -> None:
    manifest = parse_manifest(
        StringIO(
            """
Alice:
  files:
    <winAppData>/Alice: {tags: [save]}
    $XDG_DATA_HOME/alice: {tags: [save]}
    No local save games: {tags: [save]}
  registry:
    HKEY_CURRENT_USERSoftware/Studio/Alice: {tags: [save]}
"""
        ),
        skip_invalid_paths=True,
    )

    assert [item.path for item in manifest.games["Alice"].files] == [
        "<winAppData>/Alice"
    ]
    assert manifest.games["Alice"].registry == ()
