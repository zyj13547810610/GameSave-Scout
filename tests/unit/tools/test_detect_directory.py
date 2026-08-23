import json
from pathlib import Path

from gameshelf.bootstrap.resources import ResourcePaths
from gameshelf.scanning.pe_metadata import PeMetadata
from gameshelf.tools import detect_directory
from gameshelf.tools.detect_directory import main


def test_detect_directory_outputs_json_without_creating_data(
    tmp_path: Path, capsys
) -> None:
    game = tmp_path / "Sample"
    (game / "game").mkdir(parents=True)
    (game / "game" / "script.rpyc").write_bytes(b"synthetic")
    (game / "renpy").mkdir()

    exit_code = main([str(game)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["directory"] == str(game.resolve())
    assert payload["best"]["engineId"] == "renpy"
    assert payload["best"]["confidence"] == 0.96
    assert not (tmp_path / "data").exists()


def test_detect_directory_rejects_missing_directory(
    tmp_path: Path, capsys
) -> None:
    exit_code = main([str(tmp_path / "missing")])

    payload = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert payload["error"] == "directory_not_found"


def test_detect_directory_rejects_unreadable_directory(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    game = tmp_path / "unreadable"
    game.mkdir()

    def fail_iterdir(_path: Path):
        raise PermissionError("denied")

    monkeypatch.setattr(type(game), "iterdir", fail_iterdir)

    exit_code = main([str(game)])

    payload = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert payload["error"] == "directory_unreadable"


def test_detect_directory_uses_injected_engine_rules(tmp_path: Path, capsys) -> None:
    game = tmp_path / "Sample"
    game.mkdir()
    (game / "injected.marker").write_text("marker", encoding="utf-8")
    rules_file = tmp_path / "resources" / "rules" / "builtin" / "engines.yaml"
    rules_file.parent.mkdir(parents=True)
    rules_file.write_text(
        """\
version: test
rules:
  - id: injected_engine
    label: Injected Engine
    references: [https://example.com/injected-engine]
    all:
      - op: path_exists
        path: injected.marker
        weight: 1.0
""",
        encoding="utf-8",
    )
    resources = ResourcePaths(
        root=tmp_path / "resources",
        ui_dir=tmp_path / "resources" / "ui",
        builtin_engine_rules_file=rules_file,
        builtin_save_rules_file=(
            tmp_path / "resources" / "rules" / "builtin" / "saves.yaml"
        ),
        rule_schemas_dir=tmp_path / "resources" / "rules" / "schemas",
        ludusavi_dir=tmp_path / "resources" / "rules" / "ludusavi",
    )

    exit_code = main([str(game)], resources=resources)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["best"]["engineId"] == "injected_engine"


def test_sanitized_report_is_bounded_relative_and_contains_no_file_body(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    game = tmp_path / "Users" / "PrivateUser" / "SecretGame"
    (game / "game").mkdir(parents=True)
    (game / "game" / "script.rpyc").write_bytes(b"synthetic")
    (game / "renpy").mkdir()
    executable = game / "Game.exe"
    executable.write_bytes(b"MZ" + b"\0" * 30)
    archive = game / "archive.pac"
    archive.write_bytes(b"PAC " + b"\0" * 12 + b"DO_NOT_EXPORT_PRIVATE_BODY")
    (game / "private-note.txt").write_text(
        "DO_NOT_EXPORT_TEXT_BODY",
        encoding="utf-8",
    )
    too_deep = game / "one" / "two" / "three" / "too-deep.bin"
    too_deep.parent.mkdir(parents=True)
    too_deep.write_bytes(b"DO_NOT_EXPORT_DEEP_BODY")
    reparse = game / "junction"
    reparse.mkdir()
    (reparse / "outside-secret.bin").write_bytes(b"DO_NOT_CROSS_REPARSE")

    real_reparse_check = getattr(detect_directory, "_is_link_or_reparse", None)

    def fake_reparse(path: Path) -> bool:
        if path == reparse:
            return True
        return bool(real_reparse_check and real_reparse_check(path))

    monkeypatch.setattr(
        detect_directory,
        "_is_link_or_reparse",
        fake_reparse,
        raising=False,
    )
    monkeypatch.setattr(
        detect_directory,
        "read_pe_metadata",
        lambda _path: PeMetadata("Sample Product", "Sample Game", "Studio", "x64"),
        raising=False,
    )

    exit_code = main([str(game), "--sanitized"])

    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert exit_code == 0
    assert payload["sanitized"] is True
    assert "directory" not in payload
    assert str(game) not in serialized
    assert "PrivateUser" not in serialized
    assert "DO_NOT_EXPORT" not in serialized
    assert "DO_NOT_CROSS_REPARSE" not in serialized
    assert payload["best"]["engineId"] == "renpy"
    assert payload["best"]["ruleVersion"]
    entries = {
        entry["relativePath"]: entry for entry in payload["fileOverview"]["entries"]
    }
    assert entries["archive.pac"]["headerHex"] == archive.read_bytes()[:16].hex()
    assert "headerHex" not in entries["private-note.txt"]
    assert entries["Game.exe"]["pe"]["productName"] == "Sample Product"
    assert "one/two/three/too-deep.bin" not in entries
    assert "junction/outside-secret.bin" not in entries
    assert payload["fileOverview"]["limits"] == {
        "maxEntries": 256,
        "maxDepth": 3,
        "headerBytes": 16,
    }


def test_sanitized_report_limits_inventory_and_degrades_read_failures(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    game = tmp_path / "Large"
    game.mkdir()
    for index in range(300):
        (game / f"file-{index:03}.bin").write_bytes(b"\x00" * 32)

    def fail_one(path: Path) -> str | None:
        if path.name == "file-000.bin":
            raise PermissionError("private absolute path must not escape")
        return "00" * 16

    monkeypatch.setattr(
        detect_directory,
        "_read_magic_header",
        fail_one,
        raising=False,
    )

    exit_code = main([str(game), "--sanitized"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(payload["fileOverview"]["entries"]) == 256
    assert payload["fileOverview"]["truncated"] is True
    assert payload["fileOverview"]["errors"] == [
        {
            "relativePath": "file-000.bin",
            "operation": "read_header",
            "errorType": "PermissionError",
        }
    ]


def test_sanitized_unknown_engine_keeps_bounded_root_exe_metadata(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    game = tmp_path / "Unknown"
    game.mkdir()
    (game / "Mystery.exe").write_bytes(b"MZ" + b"\0" * 30)
    monkeypatch.setattr(
        detect_directory,
        "read_pe_metadata",
        lambda _path: PeMetadata("Mystery Product", "", "Circle", "x86"),
    )

    exit_code = main([str(game), "--sanitized"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["best"] is None
    assert payload["fileOverview"]["entries"] == [
        {
            "relativePath": "Mystery.exe",
            "kind": "file",
            "size": 32,
            "headerHex": (b"MZ" + b"\0" * 14).hex(),
            "pe": {
                "productName": "Mystery Product",
                "fileDescription": "",
                "companyName": "Circle",
                "architecture": "x86",
            },
        }
    ]


def test_sanitized_missing_directory_error_does_not_echo_absolute_path(
    tmp_path: Path,
    capsys,
) -> None:
    missing = tmp_path / "Users" / "PrivateUser" / "missing"

    exit_code = main([str(missing), "--sanitized"])

    payload = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert payload == {"error": "directory_not_found", "sanitized": True}
