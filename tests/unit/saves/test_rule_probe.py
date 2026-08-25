from pathlib import Path

from gamesave_scout.platform.windows.known_folders import KnownFolders
from gamesave_scout.saves.rule_probe import BoundedRuleProbe
from gamesave_scout.saves.templates import PathTemplateResolver


class _Registry:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()

    def key_exists(self, key: str) -> bool:
        return key in self.existing


def _probe(tmp_path: Path, **kwargs: object) -> BoundedRuleProbe:
    folders = _folders(tmp_path)
    return BoundedRuleProbe(
        PathTemplateResolver(folders),
        _Registry(),
        **kwargs,
    )


def test_probe_finds_literal_directory_without_reading_file_contents(tmp_path: Path) -> None:
    target = _folders(tmp_path).documents / "Game" / "Save"
    target.mkdir(parents=True)

    result = _probe(tmp_path).probe("directory", r"<winDocuments>\Game\Save", None)

    assert result.found is True
    assert result.matches == (str(target),)
    assert result.truncated is False


def test_probe_limits_glob_depth_and_rejects_reparse_points(tmp_path: Path) -> None:
    root = _folders(tmp_path).documents / "Game"
    shallow = root / "A"
    deep = shallow / "B"
    deep.mkdir(parents=True)
    (shallow / "one.sav").write_bytes(b"one")
    (deep / "two.sav").write_bytes(b"two")

    result = _probe(
        tmp_path,
        max_depth=1,
        is_reparse_point=lambda path: path == shallow,
    ).probe("glob", r"<winDocuments>\Game\**\*.sav", None)

    assert result.matches == ()
    assert result.truncated is True
    assert "reparse_point_skipped" in result.diagnostics


def test_probe_limits_visited_entries_and_matches(tmp_path: Path) -> None:
    root = _folders(tmp_path).documents / "Game"
    root.mkdir(parents=True)
    for index in range(5):
        (root / f"{index}.sav").write_bytes(b"save")

    entries = _probe(tmp_path, max_entries=2).probe(
        "glob", r"<winDocuments>\Game\*.sav", None
    )
    matches = _probe(tmp_path, max_matches=2).probe(
        "glob", r"<winDocuments>\Game\*.sav", None
    )

    assert entries.truncated is True
    assert "entry_limit_reached" in entries.diagnostics
    assert len(matches.matches) == 2
    assert matches.truncated is True
    assert "match_limit_reached" in matches.diagnostics


def test_probe_stops_at_deadline(tmp_path: Path) -> None:
    root = _folders(tmp_path).documents / "Game"
    root.mkdir(parents=True)
    (root / "one.sav").write_bytes(b"save")
    times = iter((0.0, 3.0, 3.0))

    result = _probe(tmp_path, monotonic=lambda: next(times)).probe(
        "glob", r"<winDocuments>\Game\*.sav", None
    )

    assert result.truncated is True
    assert "deadline_reached" in result.diagnostics


def test_probe_rejects_unc_or_device_roots(tmp_path: Path) -> None:
    folders = _folders(tmp_path)
    folders = KnownFolders(
        home=folders.home,
        app_data=folders.app_data,
        local_app_data=folders.local_app_data,
        local_app_data_low=folders.local_app_data_low,
        documents=Path(r"\\server\share"),
        saved_games=folders.saved_games,
        program_data=folders.program_data,
        public=folders.public,
        windows=folders.windows,
    )
    probe = BoundedRuleProbe(PathTemplateResolver(folders), _Registry())

    result = probe.probe("directory", r"<winDocuments>\Game", None)

    assert result.found is False
    assert result.diagnostics == ("network_or_device_root_rejected",)


def _folders(tmp_path: Path) -> KnownFolders:
    profile = tmp_path / "Profile"
    return KnownFolders(
        home=profile,
        app_data=profile / "AppData" / "Roaming",
        local_app_data=profile / "AppData" / "Local",
        local_app_data_low=profile / "AppData" / "LocalLow",
        documents=profile / "Documents",
        saved_games=profile / "Saved Games",
        program_data=tmp_path / "ProgramData",
        public=tmp_path / "Public",
        windows=tmp_path / "Windows",
    )
