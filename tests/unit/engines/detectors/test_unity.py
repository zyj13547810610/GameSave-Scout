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
