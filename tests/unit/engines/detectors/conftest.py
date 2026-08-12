from collections.abc import Mapping
from pathlib import Path

import pytest


@pytest.fixture
def file_tree(tmp_path: Path):
    def create(files: Mapping[str, bytes]) -> Path:
        for relative, content in files.items():
            path = tmp_path.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return tmp_path

    return create
