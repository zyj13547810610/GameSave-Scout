from pathlib import Path

import pytest

from gameshelf.platform.windows.known_folders import KnownFolders
from gameshelf.saves.templates import InvalidPathTemplate, PathTemplateResolver


@pytest.fixture
def known_folders() -> KnownFolders:
    return KnownFolders(
        home=Path(r"C:\Users\Alice"),
        app_data=Path(r"C:\Users\Alice\AppData\Roaming"),
        local_app_data=Path(r"C:\Users\Alice\AppData\Local"),
        local_app_data_low=Path(r"C:\Users\Alice\AppData\LocalLow"),
        documents=Path(r"C:\Users\Alice\Documents"),
        saved_games=Path(r"C:\Users\Alice\Saved Games"),
        program_data=Path(r"C:\ProgramData"),
        public=Path(r"C:\Users\Public"),
        windows=Path(r"C:\Windows"),
    )


@pytest.fixture
def resolver(known_folders: KnownFolders) -> PathTemplateResolver:
    return PathTemplateResolver(known_folders)


def test_collapse_uses_longest_known_prefix(resolver: PathTemplateResolver) -> None:
    path = Path(r"C:\Users\Alice\AppData\LocalLow\Studio\作品")

    assert resolver.collapse(path, None) == r"<winLocalAppDataLow>\Studio\作品"


def test_game_relative_path_round_trips(resolver: PathTemplateResolver) -> None:
    game = Path(r"D:\Games\Alice")

    template = resolver.collapse(game / "save" / "slot1.dat", game)

    assert template == r"<game>\save\slot1.dat"
    assert resolver.expand(template, game) == game / "save" / "slot1.dat"


@pytest.mark.parametrize(
    "template",
    [
        r"<game>\..\OtherGame",
        r"<unknown>\x",
        r"C:\absolute\path",
        r"\\server\share\save",
        r"<home>\folder\<winDir>",
    ],
)
def test_expand_rejects_escape_unknown_token_and_non_template_paths(
    template: str,
    resolver: PathTemplateResolver,
) -> None:
    with pytest.raises(InvalidPathTemplate):
        resolver.expand(template, Path(r"D:\Games\Alice"))


def test_expand_requires_game_directory_for_game_token(resolver: PathTemplateResolver) -> None:
    with pytest.raises(InvalidPathTemplate, match="game"):
        resolver.expand(r"<game>\save", None)


def test_collapse_rejects_path_outside_portable_roots(resolver: PathTemplateResolver) -> None:
    with pytest.raises(InvalidPathTemplate, match="便携"):
        resolver.collapse(Path(r"E:\Unmapped\save.dat"), None)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (r"<home>\save", Path(r"C:\Users\Alice\save")),
        (r"<winAppData>\save", Path(r"C:\Users\Alice\AppData\Roaming\save")),
        (r"<winLocalAppData>\save", Path(r"C:\Users\Alice\AppData\Local\save")),
        (r"<winLocalAppDataLow>\save", Path(r"C:\Users\Alice\AppData\LocalLow\save")),
        (r"<winDocuments>\save", Path(r"C:\Users\Alice\Documents\save")),
        (r"<winSavedGames>\save", Path(r"C:\Users\Alice\Saved Games\save")),
        (r"<winProgramData>\save", Path(r"C:\ProgramData\save")),
        (r"<winPublic>\save", Path(r"C:\Users\Public\save")),
        (r"<winDir>\save", Path(r"C:\Windows\save")),
    ],
)
def test_expand_supports_each_known_folder_token(
    template: str,
    expected: Path,
    resolver: PathTemplateResolver,
) -> None:
    assert resolver.expand(template, None) == expected
