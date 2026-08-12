# GameShelf Library Scan and Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the empty shell into a persistent multi-root game library that safely discovers folders, recommends executables, reconciles missing games, launches confirmed programs, and opens folders.

**Architecture:** Root configuration and games are repository-backed domain records. Scanning is a cancellable two-stage pipeline—enumerate deterministic candidate directories, then rank EXEs—followed by transactional reconciliation that updates missing state only after a successful scan boundary.

**Tech Stack:** Existing foundation plus Python `pefile`, pathlib/ntpath, SQLite, Vue 3/Pinia, Vitest, pytest.

## Global Constraints

- Unknown-engine games and direct child folders without an EXE remain valid library entries.
- Multiple roots have independent mode, depth, exclusions, enabled state, status, and errors.
- Do not mark games missing after root unavailability, permission error, cancellation, or failed scan.
- Preserve manual title and main-EXE choices.
- Deduplicate normalized Windows paths; for a new overlapping candidate choose the longest containing root.
- Do not follow directory junctions/symlinks during recursive scanning.
- Never execute an EXE during scanning.
- Launch with argument arrays and `shell=False` only after explicit user action.
- Follow TDD and commit after every task.

---

### Task 1: Normalize Windows Paths Without Touching the Filesystem

**Files:**
- Create: `src/gameshelf/scanning/__init__.py`
- Create: `src/gameshelf/scanning/path_keys.py`
- Create: `tests/unit/scanning/test_path_keys.py`

**Interfaces:**
- Produces: `windows_path_key(path: str | Path) -> str`.
- Produces: `is_same_or_child(path_key: str, root_key: str) -> bool`.
- Produces: `portable_relative(path: Path, root: Path) -> str` using `/` in storage.
- Produces: `expand_relative(root: Path, relative: str) -> Path` with traversal rejection.

- [ ] **Step 1: Write failing normalization and traversal tests**

```python
import pytest

from gameshelf.scanning.path_keys import (
    PathTraversalError,
    expand_relative,
    is_same_or_child,
    portable_relative,
    windows_path_key,
)


def test_windows_keys_dedupe_case_prefix_slashes_and_trailing_marks() -> None:
    assert windows_path_key(r"\\?\D:\Games\Alice\.\") == windows_path_key(
        r"d:/games/Alice"
    )
    assert windows_path_key(r"D:\Games\Alice. ") == windows_path_key(r"d:\games\alice")


def test_child_check_respects_component_boundary() -> None:
    root = windows_path_key(r"D:\Games")
    assert is_same_or_child(windows_path_key(r"D:\Games\A"), root)
    assert not is_same_or_child(windows_path_key(r"D:\GamesBackup\A"), root)


def test_relative_paths_are_portable_and_cannot_escape(tmp_path) -> None:
    root = tmp_path / "games"
    assert portable_relative(root / "group" / "game", root) == "group/game"
    with pytest.raises(PathTraversalError):
        expand_relative(root, "../outside")
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/unit/scanning/test_path_keys.py -v`

Expected: FAIL because `path_keys` does not exist.

- [ ] **Step 3: Implement lexical Windows normalization and safe expansion**

Strip a leading `\\?\`, convert `/` to `\`, apply `ntpath.normpath`, remove trailing spaces/dots from each non-root component, and `casefold()` the result. Preserve UNC server/share boundaries. Do not call `Path.resolve()` to create the deduplication key because unavailable removable drives must still normalize.

`expand_relative` must reject absolute paths, drive-qualified paths, `..` components, and a final path whose lexical Windows key is outside the root key.

- [ ] **Step 4: Run path tests and static checks**

Run:

```powershell
python -m pytest tests/unit/scanning/test_path_keys.py -v
python -m ruff check src/gameshelf/scanning tests/unit/scanning
python -m mypy src/gameshelf/scanning
```

Expected: all pass.

- [ ] **Step 5: Commit path identity rules**

```powershell
git add src/gameshelf/scanning tests/unit/scanning
git commit -m "feat: normalize portable Windows paths"
```

### Task 2: Add Scan-Root and Game Domain Repositories

**Files:**
- Create: `src/gameshelf/library/__init__.py`
- Create: `src/gameshelf/library/models.py`
- Create: `src/gameshelf/library/repository.py`
- Create: `src/gameshelf/library/service.py`
- Create: `tests/unit/library/test_repository.py`
- Create: `tests/unit/library/test_service.py`

**Interfaces:**
- Produces immutable `ScanRoot` and `Game` dataclasses matching schema columns.
- Produces `LibraryRepository` read methods using short-lived read connections.
- Produces `LibraryService.add_root`, `update_root`, `remove_root`, `remap_root`, `list_roots`, `list_games`, and `get_game`.
- All mutations submit one transaction to `DbWriter`.

- [ ] **Step 1: Write failing repository/service tests**

```python
def test_add_root_deduplicates_by_windows_key(library_service: LibraryService) -> None:
    first = library_service.add_root(r"D:\Games", "children", 1, [])
    second = library_service.add_root(r"d:/games/", "children", 1, [])
    assert first.id == second.id
    assert len(library_service.list_roots()) == 1


def test_remap_root_preserves_id_and_relative_game(library_service: LibraryService) -> None:
    root = library_service.add_root(r"D:\Games", "recursive", 2, ["tools"])
    game = library_service.create_game_for_test(root.id, "group/game", "Game")
    remapped = library_service.remap_root(root.id, r"E:\PortableGames")
    assert remapped.id == root.id
    assert library_service.get_game(game.id).relative_dir == "group/game"


def test_remove_root_preserves_games_as_missing_records(library_service: LibraryService) -> None:
    root = library_service.add_root(r"D:\Games", "children", 1, [])
    game = library_service.create_game_for_test(root.id, "GameA", "GameA")
    library_service.remove_root(root.id)
    preserved = library_service.get_game(game.id)
    assert preserved.scan_root_id is None
    assert preserved.status == "missing"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/unit/library -v`

Expected: FAIL because the library domain is absent.

- [ ] **Step 3: Implement immutable models and transactional service methods**

Use these public request/value types:

```python
ScanMode = Literal["children", "recursive"]
GameStatus = Literal["installed", "missing", "save_only"]

@dataclass(frozen=True)
class ScanRoot:
    id: str
    display_path: str
    path_key: str
    enabled: bool
    scan_mode: ScanMode
    max_depth: int
    exclusions: tuple[str, ...]
    last_scanned_at: str | None
    last_scan_status: str
    last_error: str | None
    created_at: str

@dataclass(frozen=True)
class Game:
    id: str
    scan_root_id: str | None
    relative_dir: str | None
    install_path_key: str | None
    title: str
    status: GameStatus
    main_exe_relpath: str | None
    main_exe_is_manual: bool
    working_dir_relpath: str | None
    launch_args: tuple[str, ...]
    environment: Mapping[str, str]
    exe_arch: Literal["x86", "x64", "unknown"]
    last_launched_at: str | None
    missing_since: str | None
```

Validate root mode/depth (`children` always stores depth `1`; recursive depth range is `1..8`). Normalize exclusions as relative directory names or glob patterns and reject absolute/parent-traversal entries. Removing a root updates its games to `scan_root_id=NULL`, `status='missing'`, and sets `missing_since` in the same transaction before deleting the root.

- [ ] **Step 4: Run library tests and the database suite**

Run: `python -m pytest tests/unit/library tests/unit/db -v`

Expected: all pass.

- [ ] **Step 5: Commit library persistence**

```powershell
git add src/gameshelf/library tests/unit/library
git commit -m "feat: persist game roots and library records"
```

### Task 3: Enumerate Candidate Game Directories

**Files:**
- Create: `src/gameshelf/scanning/models.py`
- Create: `src/gameshelf/scanning/discovery.py`
- Create: `tests/unit/scanning/test_discovery.py`

**Interfaces:**
- Consumes: `ScanRoot`, `windows_path_key`, `portable_relative`, and `TaskContext`.
- Produces: `DirectoryCandidate(path, relative_dir, depth, reason)`.
- Produces: `enumerate_candidates(root: ScanRoot, context: TaskContext) -> Iterator[DirectoryCandidate]`.
- `reason` is `direct_child` or `generic_executable` in this increment.

- [ ] **Step 1: Write failing direct-child, recursive, exclusion, and junction tests**

```python
def test_children_mode_keeps_every_direct_directory_even_without_exe(tmp_path, task_context) -> None:
    root_path = tmp_path / "games"
    (root_path / "NoExeYet").mkdir(parents=True)
    (root_path / "WithExe").mkdir()
    (root_path / "WithExe" / "Game.exe").write_bytes(b"MZ")
    root = make_root(root_path, mode="children", depth=1)
    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "NoExeYet", "WithExe"
    ]


def test_recursive_mode_finds_nested_exe_and_stops_below_game(tmp_path, task_context) -> None:
    root_path = tmp_path / "games"
    game = root_path / "group" / "GameC"
    (game / "tools").mkdir(parents=True)
    (game / "Game.exe").write_bytes(b"MZ")
    (game / "tools" / "helper.exe").write_bytes(b"MZ")
    root = make_root(root_path, mode="recursive", depth=2)
    assert [item.relative_dir for item in enumerate_candidates(root, task_context)] == [
        "group/GameC"
    ]
```

Also test case-insensitive exclusions, inaccessible child directories, cancellation after enumeration begins, and a mocked `DirEntry.is_symlink()` returning true.

- [ ] **Step 2: Run discovery tests and verify failure**

Run: `python -m pytest tests/unit/scanning/test_discovery.py -v`

Expected: FAIL because discovery is absent.

- [ ] **Step 3: Implement deterministic `os.scandir` traversal**

Sort entries by `name.casefold()` before yielding. In children mode, yield every accessible direct directory. In recursive mode, descend only to `max_depth`; yield a directory when it contains at least one `.exe` regular file, then do not descend below it. Skip symlinks and reparse-point directories. Convert per-child access errors into warning evidence while continuing; inability to open the root raises `RootUnavailableError` and yields nothing.

Call `context.raise_if_cancelled()` before opening each directory and every 64 entries. Do not read executable contents in this task.

- [ ] **Step 4: Run discovery tests and static checks**

Run: `python -m pytest tests/unit/scanning/test_discovery.py -v`

Expected: all pass.

- [ ] **Step 5: Commit directory discovery**

```powershell
git add src/gameshelf/scanning/models.py src/gameshelf/scanning/discovery.py tests/unit/scanning/test_discovery.py
git commit -m "feat: discover game directory candidates"
```

### Task 4: Rank Main Executables Without Launching Them

**Files:**
- Modify: `pyproject.toml`
- Create: `src/gameshelf/scanning/pe_metadata.py`
- Create: `src/gameshelf/scanning/executable_ranker.py`
- Create: `tests/unit/scanning/test_executable_ranker.py`
- Create: `tests/fixtures/pe/README.md`

**Interfaces:**
- Produces: `PeMetadata(product_name, file_description, company_name, architecture)`.
- Produces: `read_pe_metadata(path: Path) -> PeMetadata`, returning empty/unknown fields for malformed files.
- Produces: `ExecutableCandidate(relative_path, score, architecture, evidence)`.
- Produces: `rank_executables(game_dir: Path) -> tuple[ExecutableCandidate, ...]`.

- [ ] **Step 1: Write failing ranking tests with a mocked metadata reader**

```python
def test_ranker_rejects_installers_and_prefers_title_match(tmp_path, monkeypatch) -> None:
    for name in ["Alice.exe", "setup.exe", "unins000.exe", "crashreporter.exe"]:
        (tmp_path / name).write_bytes(b"MZ")
    monkeypatch.setattr(
        "gameshelf.scanning.executable_ranker.read_pe_metadata",
        lambda path: PeMetadata(
            product_name="Alice" if path.name == "Alice.exe" else "",
            file_description="",
            company_name="",
            architecture="x64",
        ),
    )
    ranked = rank_executables(tmp_path)
    assert [item.relative_path for item in ranked] == ["Alice.exe"]
    assert "product_name_matches_directory" in ranked[0].evidence


def test_malformed_pe_is_never_executed_and_remains_low_confidence(tmp_path) -> None:
    (tmp_path / "Mystery.exe").write_bytes(b"not-a-pe")
    ranked = rank_executables(tmp_path)
    assert ranked[0].relative_path == "Mystery.exe"
    assert ranked[0].architecture == "unknown"
```

- [ ] **Step 2: Add `pefile` and run tests to verify failure**

Add `pefile>=2024.8.26,<2027` to project dependencies, reinstall editable dependencies, then run: `python -m pytest tests/unit/scanning/test_executable_ranker.py -v`.

Expected: FAIL because the ranker does not exist.

- [ ] **Step 3: Implement defensive PE metadata reading and scoring**

Exclude basename patterns `unins*`, `uninstall*`, `setup*`, `install*`, `update*`, `updater*`, `crash*`, `report*`, and executables under directories named `redist`, `_commonredist`, `runtime`, `tools`, or `support`. Do not exclude `config.exe`, but give it a strong negative score and label it an auxiliary tool.

Score root-level location, normalized directory/title similarity, PE product/description similarity, and executable size. Catch `pefile.PEFormatError`, `OSError`, and invalid resource strings. Parse only PE headers/resources; never call `subprocess`, `os.startfile`, or `ShellExecute` in this module.

- [ ] **Step 4: Run ranking tests and dependency checks**

Run:

```powershell
python -m pytest tests/unit/scanning/test_executable_ranker.py -v
python -m ruff check src/gameshelf/scanning tests/unit/scanning
python -m mypy src/gameshelf/scanning
```

Expected: all pass.

- [ ] **Step 5: Commit executable ranking**

```powershell
git add pyproject.toml src/gameshelf/scanning tests/unit/scanning tests/fixtures/pe
git commit -m "feat: rank game executables safely"
```

### Task 5: Reconcile Successful, Cancelled, and Unavailable Scans

**Files:**
- Create: `src/gameshelf/scanning/reconcile.py`
- Create: `src/gameshelf/scanning/service.py`
- Create: `tests/integration/scanning/test_scan_service.py`

**Interfaces:**
- Consumes: root repository, game repository, `DbWriter`, discovery, ranker, and task context.
- Produces: `ScanService.scan_root(root_id: str, scan_kind: Literal['quick','full'], context: TaskContext) -> ScanSummary`.
- Produces: `ScanSummary(session_id, status, discovered, added, updated, missing, warnings, move_suggestions)`.
- Produces: `MoveSuggestion(existing_game_id, candidate_relative_dir, confidence, evidence)`; it never relocates automatically.

- [ ] **Step 1: Write failing end-to-end scan-state tests**

```python
def test_successful_full_scan_adds_games_and_marks_removed_game_missing(scan_harness) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA")
    first = scan_harness.scan(root.id, "full")
    game = scan_harness.games()[0]
    assert first.added == 1
    scan_harness.remove_dir("GameA")
    second = scan_harness.scan(root.id, "full")
    assert second.missing == 1
    assert scan_harness.game(game.id).status == "missing"


def test_unavailable_root_preserves_installed_status(scan_harness) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA")
    scan_harness.scan(root.id, "full")
    game = scan_harness.games()[0]
    scan_harness.make_root_unavailable()
    summary = scan_harness.scan(root.id, "full")
    assert summary.status == "unavailable"
    assert scan_harness.game(game.id).status == "installed"


def test_manual_executable_survives_new_auto_recommendation(scan_harness) -> None:
    root = scan_harness.add_root(mode="children")
    scan_harness.mkdir("GameA", exes=["A.exe", "Better.exe"])
    game = scan_harness.scan(root.id, "full").games[0]
    scan_harness.set_manual_exe(game.id, "A.exe")
    scan_harness.scan(root.id, "full")
    refreshed = scan_harness.game(game.id)
    assert refreshed.main_exe_relpath == "A.exe"
    assert refreshed.detected_main_exe_relpath is not None
```

Also cover cancellation, recursive discovery, overlapping roots choosing the longest root, and a child directory without EXE.

- [ ] **Step 2: Run integration tests and verify failure**

Run: `python -m pytest tests/integration/scanning/test_scan_service.py -v`

Expected: FAIL because scan reconciliation is absent.

- [ ] **Step 3: Implement session-bound reconciliation**

Create the `scan_sessions` record as `running` and stream candidate observations into the internal `scan_observations` table in batches of 200 through `DbWriter`; this avoids holding a large library in memory without changing visible game state early. When discovery completes, apply one reconciliation transaction that:

1. upsert candidates by `install_path_key`;
2. update detected title and detected EXE while preserving manual fields;
3. set observed records to `installed` and clear `missing_since`;
4. for a successful full scan, mark unobserved records assigned to that root `missing`;
5. for quick recursive scans, verify known records but do not claim discovery completeness for new nested games;
6. update root/session success metadata last.

Delete that session's staged observations after successful reconciliation. On failure/cancellation/unavailability, delete staged observations and preserve visible games; keep only the session/error summary.

On `RootUnavailableError`, cancellation, or any exception, update only session/root status and error; do not reconcile missing states.

Generate move suggestions when a newly observed candidate resembles a missing record by EXE basename, file size, PE product name, and directory-title similarity. Confidence below `0.75` is not returned.

- [ ] **Step 4: Run integration and regression tests**

Run:

```powershell
python -m pytest tests/integration/scanning tests/unit/library tests/unit/scanning -v
python -m ruff check src tests
python -m mypy src
```

Expected: all pass.

- [ ] **Step 5: Commit transactional scanning**

```powershell
git add src/gameshelf/scanning tests/integration/scanning
git commit -m "feat: reconcile cancellable library scans"
```

### Task 6: Launch Games and Open Folders Safely

**Files:**
- Create: `src/gameshelf/platform/__init__.py`
- Create: `src/gameshelf/platform/windows/__init__.py`
- Create: `src/gameshelf/platform/windows/shell.py`
- Create: `src/gameshelf/platform/windows/processes.py`
- Create: `src/gameshelf/library/launcher.py`
- Create: `tests/unit/library/test_launcher.py`

**Interfaces:**
- Produces: `WindowsShell.open_directory(path: Path) -> None`.
- Produces: `WindowsProcessLauncher.launch(executable, arguments, cwd, environment) -> LaunchedProcess(pid)`.
- Produces: `GameLauncher.launch(game_id) -> LaunchReceipt` and `open_install_directory(game_id) -> None`.

- [ ] **Step 1: Write failing safety tests against fakes**

```python
def test_launch_uses_array_cwd_and_shell_false(game_launcher, fake_process_launcher) -> None:
    game = game_launcher.fixture_game(
        install_dir=r"D:\Games\Alice",
        exe="bin/Alice.exe",
        args=["--profile", "A B"],
        working_dir="bin",
    )
    game_launcher.launch(game.id)
    call = fake_process_launcher.calls[0]
    assert call.executable == Path(r"D:\Games\Alice\bin\Alice.exe")
    assert call.arguments == ("--profile", "A B")
    assert call.cwd == Path(r"D:\Games\Alice\bin")
    assert call.shell is False


def test_launch_rejects_relative_exe_that_escapes_install_dir(game_launcher) -> None:
    game = game_launcher.fixture_game(exe="../outside.exe")
    with pytest.raises(InvalidLaunchConfiguration):
        game_launcher.launch(game.id)
```

- [ ] **Step 2: Run launch tests and verify failure**

Run: `python -m pytest tests/unit/library/test_launcher.py -v`

Expected: FAIL because launcher adapters do not exist.

- [ ] **Step 3: Implement safe resolution and Windows adapters**

Resolve install, executable, and working directory with `expand_relative`; require the EXE to exist and end in `.exe`. Merge only validated string environment entries over `os.environ`. Use:

```python
subprocess.Popen(
    [str(executable), *arguments],
    cwd=str(cwd),
    env=environment,
    shell=False,
    close_fds=True,
)
```

Use `os.startfile(path)` only in `WindowsShell.open_directory`, after checking the path is an existing directory. Update `last_launched_at` only after `Popen` returns a PID.

- [ ] **Step 4: Run launcher and static checks**

Run: `python -m pytest tests/unit/library/test_launcher.py -v`

Expected: all pass without starting a real external process.

- [ ] **Step 5: Commit launch/open behavior**

```powershell
git add src/gameshelf/platform src/gameshelf/library/launcher.py tests/unit/library/test_launcher.py
git commit -m "feat: launch games and open folders safely"
```

### Task 7: Expose Library Commands Through the Typed Bridge

**Files:**
- Modify: `src/gameshelf/bridge/api.py`
- Modify: `src/gameshelf/bootstrap/application.py`
- Create: `tests/unit/bridge/test_library_api.py`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/api/bridge.ts`
- Modify: `frontend/src/api/mockBridge.ts`
- Create: `frontend/src/features/library/libraryStore.ts`
- Create: `frontend/src/features/scan-roots/ScanRootDialog.vue`
- Create: `frontend/src/features/scan-roots/ScanRootList.vue`
- Create: `frontend/src/features/library/GamePlaceholderGrid.vue`
- Create: `frontend/src/features/library/GameSettingsPanel.vue`
- Create: `frontend/tests/libraryStore.spec.ts`
- Create: `frontend/tests/ScanRootDialog.spec.ts`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Adds bridge methods `list_roots`, `add_root`, `update_root`, `remove_root`, `remap_root`, `list_games`, `start_scan`, `confirm_move`, `launch_game`, and `open_install_directory`.
- Adds bridge methods `choose_game_executable`, `set_game_executable`, `set_game_title`, and `update_launch_configuration`.
- `start_scan` returns `{ taskId: string }`; progress uses the foundation task endpoint.
- Produces Pinia `useLibraryStore()` with `load`, `scan`, and root mutation actions.

- [ ] **Step 1: Write failing bridge and component tests**

```python
def test_start_scan_returns_task_id(library_api: BridgeApi) -> None:
    root = library_api.add_root({
        "displayPath": r"D:\Games", "scanMode": "children",
        "maxDepth": 1, "exclusions": []
    })["data"]
    result = library_api.start_scan({"rootId": root["id"], "kind": "full"})
    assert result["ok"] is True
    assert isinstance(result["data"]["taskId"], str)


def test_manual_executable_must_remain_inside_game_directory(library_api: BridgeApi) -> None:
    result = library_api.set_game_executable({
        "gameId": "game-1", "selectedPath": r"D:\Other\tool.exe"
    })
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_executable"
```

```ts
it('validates recursive depth before calling the bridge', async () => {
  const bridge = createMockBridge()
  const wrapper = mount(ScanRootDialog, { props: { bridge } })
  await wrapper.get('[data-test="mode-recursive"]').setValue(true)
  await wrapper.get('[data-test="max-depth"]').setValue(9)
  await wrapper.get('form').trigger('submit')
  expect(wrapper.text()).toContain('扫描深度必须在 1 到 8 之间')
  expect(bridge.add_root).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run bridge and frontend tests and verify failure**

Run:

```powershell
python -m pytest tests/unit/bridge/test_library_api.py -v
npm --prefix frontend run test:unit -- --run tests/libraryStore.spec.ts tests/ScanRootDialog.spec.ts
```

Expected: failures for missing methods/components.

- [ ] **Step 3: Implement validated commands and a usable placeholder library UI**

All Python bridge methods accept one JSON object, validate required keys/types, call a service, and return camelCase DTOs. Do not expose repository objects directly.

The UI must provide:

- “添加游戏目录” action;
- root list with enable state, mode/depth, last status, rescan, remap, and remove;
- scan progress with cancel;
- placeholder cards showing title and installed/missing/no-main-program state;
- details actions for launch and open folder;
- title editing; an EXE picker rooted at the game's installation directory; advanced working-directory, argument-array, and environment key/value editing;
- a move-suggestion confirmation panel.

Use native pywebview folder selection through a white-listed `choose_directory` method; the backend returns a selected display path or `null`. Do not accept arbitrary JavaScript browsing of the filesystem.

`confirm_move` must require a still-missing existing game, an observed candidate from the referenced scan session, and an unclaimed target path. In one transaction it reassigns root/relative/install key, sets installed, clears missing state, and preserves title, cover, saves, manual EXE/engine, and launch configuration.

- [ ] **Step 4: Run all bridge/frontend checks**

Run:

```powershell
python -m pytest tests/unit/bridge tests/integration/scanning -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

Expected: all pass.

- [ ] **Step 5: Commit the interactive library**

```powershell
git add src frontend tests
git commit -m "feat: manage and scan game roots from the UI"
```

### Task 8: Add Startup Quick Scan and Complete the Increment

**Files:**
- Modify: `frontend/src/features/library/libraryStore.ts`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/startupScan.spec.ts`
- Create: `tests/integration/scanning/test_overlap_and_startup.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `start_scan(kind='quick')`.
- Produces: one startup quick-scan request after cached library rendering, never before.
- Quick behavior: children roots enumerate direct children; recursive roots verify known game paths only.

- [ ] **Step 1: Write failing cached-first startup tests**

```ts
it('renders cached games before requesting quick scans', async () => {
  const order: string[] = []
  const bridge = createMockBridge({
    list_games: async () => {
      order.push('games')
      return ok([fixtureGame({ title: 'Alice' })])
    },
    start_scan: async () => {
      order.push('scan')
      return ok({ taskId: 'task-1' })
    },
  })
  const wrapper = mount(App, { global: { provide: { bridge } } })
  await flushPromises()
  expect(wrapper.text()).toContain('Alice')
  expect(order).toEqual(['games', 'scan'])
})
```

- [ ] **Step 2: Run startup tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run tests/startupScan.spec.ts`

Expected: FAIL because startup scanning is not orchestrated.

- [ ] **Step 3: Implement cached-first startup and non-blocking errors**

After `bootstrap`, load roots/games, render, then start quick scans for enabled roots. Do not clear existing cards while scanning. An unavailable root displays “根目录暂时无法访问，已有游戏状态未改变” and preserves cards. Scan errors appear in a dismissible status area and root detail, not a fatal application screen.

- [ ] **Step 4: Run the increment acceptance gate**

Run:

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

Expected: all pass.

- [ ] **Step 5: Commit the completed library increment**

```powershell
git add frontend tests README.md
git commit -m "feat: refresh cached library in the background"
```

## Library Increment Acceptance Gate

- Configure `D:\文件夹a` recursive depth 2 and `D:\文件夹b` children mode; discover games a, b, c, and d.
- A direct child without an EXE is visible with “尚未选择主程序”.
- Overlapping roots never create duplicate installed-path records.
- Unavailable/cancelled roots preserve prior installed status.
- Manual EXE and title choices survive rescans.
- Scanning never executes an EXE.
- Explicit launch uses the selected EXE, exact argument array, configured working directory, and `shell=False`.
- Cached cards render before startup quick scanning begins.
