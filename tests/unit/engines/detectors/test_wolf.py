from gameshelf.engines.base import DetectionContext
from gameshelf.engines.detectors.wolf import WolfRpgDetector


def test_wolf_plain_and_encrypted_layouts(file_tree) -> None:
    plain = file_tree({"Game.exe": b"MZ", "Data/BasicData/Game.dat": b"WOLF"})
    assert WolfRpgDetector().inspect(DetectionContext(plain, plain / "Game.exe")) is not None


def test_game_executable_alone_is_not_wolf(file_tree) -> None:
    root = file_tree({"Game.exe": b"MZ"})
    assert WolfRpgDetector().inspect(DetectionContext(root, root / "Game.exe")) is None
