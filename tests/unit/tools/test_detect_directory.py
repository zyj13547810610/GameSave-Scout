import json
from pathlib import Path

from gameshelf.bootstrap.resources import ResourcePaths
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
    rules_file = tmp_path / "resources" / "rules" / "engines.yaml"
    rules_file.parent.mkdir(parents=True)
    rules_file.write_text(
        """\
version: test
rules:
  - id: injected_engine
    label: Injected Engine
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
        engine_rules_file=rules_file,
        ludusavi_dir=tmp_path / "resources" / "manifests" / "ludusavi",
    )

    exit_code = main([str(game)], resources=resources)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["best"]["engineId"] == "injected_engine"
