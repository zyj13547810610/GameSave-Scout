from gameshelf.engines.base import DetectionContext
from gameshelf.engines.detectors.unity import UnityDetector


def test_unity_requires_player_named_data_and_manager(file_tree) -> None:
    root = file_tree({
        "Alice.exe": b"MZ",
        "UnityPlayer.dll": b"MZ",
        "Alice_Data/globalgamemanagers": b"UnityFS",
    })
    match = UnityDetector().inspect(DetectionContext(root, root / "Alice.exe"))
    assert match is not None and match.engine_id == "unity"


def test_unity_player_alone_is_not_enough(file_tree) -> None:
    root = file_tree({"UnityPlayer.dll": b"MZ"})
    assert UnityDetector().inspect(DetectionContext(root, None)) is None


def test_unity_uses_the_selected_executable_nested_runtime(file_tree) -> None:
    root = file_tree(
        {
            "Build/Mortal.exe": b"MZ",
            "Build/UnityPlayer.dll": b"MZ",
            "Build/Mortal_Data/globalgamemanagers": b"UnityFS",
        }
    )
    context = DetectionContext(root, root / "Build" / "Mortal.exe")

    detector = UnityDetector()
    match = detector.inspect(context)

    assert detector.cheap_probe(context) is True
    assert match is not None and match.engine_id == "unity"
    assert {item.code: item.path for item in match.evidence} == {
        "unity_player": "Build/UnityPlayer.dll",
        "unity_data": "Build/Mortal_Data/globalgamemanagers",
    }


def test_unity_does_not_substitute_a_different_executable(file_tree) -> None:
    root = file_tree(
        {
            "Alice.exe": b"MZ",
            "WrongTool.exe": b"MZ",
            "UnityPlayer.dll": b"MZ",
            "Alice_Data/globalgamemanagers": b"UnityFS",
        }
    )
    context = DetectionContext(root, root / "WrongTool.exe")

    assert UnityDetector().inspect(context) is None


def test_unity_rejects_an_executable_outside_the_game_directory(
    tmp_path,
) -> None:
    root = tmp_path / "Game"
    outside = tmp_path / "Outside"
    root.mkdir()
    (outside / "Outside_Data").mkdir(parents=True)
    executable = outside / "Outside.exe"
    executable.write_bytes(b"MZ")
    (outside / "UnityPlayer.dll").write_bytes(b"MZ")
    (outside / "Outside_Data" / "globalgamemanagers").write_bytes(b"UnityFS")
    context = DetectionContext(root, executable)

    detector = UnityDetector()

    assert detector.cheap_probe(context) is False
    assert detector.inspect(context) is None
