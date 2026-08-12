import json
from pathlib import Path

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
