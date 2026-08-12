from gameshelf.engines.base import DetectionContext
from gameshelf.engines.detectors.renpy import RenPyDetector


def test_renpy_requires_scripts_and_runtime(file_tree) -> None:
    root = file_tree({"game/script.rpyc": b"RENPY RPC2", "renpy/__init__.py": b"version"})
    match = RenPyDetector().inspect(DetectionContext(root, None))
    assert match is not None and match.engine_id == "renpy"


def test_scripts_alone_are_not_enough(file_tree) -> None:
    root = file_tree({"game/script.rpyc": b"RPC2"})
    assert RenPyDetector().inspect(DetectionContext(root, None)) is None
