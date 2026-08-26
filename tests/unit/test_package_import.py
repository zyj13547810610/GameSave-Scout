import importlib

import pytest


def test_package_exposes_version_without_legacy_import_alias() -> None:
    import gamesave_scout

    assert gamesave_scout.__version__ == "0.3.4"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("game" + "shelf")
