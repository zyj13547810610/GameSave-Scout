# GameShelf 游戏库扫描与启动实施计划

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 将空白外壳变为持久化的多根目录游戏库，能够安全发现文件夹、推荐可执行文件、核对失效游戏、启动已确认的程序以及打开文件夹。

**架构：** 根目录配置和游戏都是由仓储支持的领域记录。扫描采用可取消的两阶段流水线——先以确定性方式枚举候选目录，再对 EXE 排名——之后执行事务化核对，只有成功到达扫描边界后才更新失效状态。

**技术栈：** 现有基础设施，加上 Python `pefile`、pathlib/ntpath、SQLite、Vue 3/Pinia、Vitest、pytest。

## 全局约束

- 引擎未知的游戏，以及没有 EXE 的直接子文件夹，仍然是有效的游戏库条目。
- 多个根目录分别拥有独立的模式、深度、排除规则、启用状态、运行状态和错误。
- 根目录不可用、发生权限错误、取消或扫描失败后，不得将游戏标记为失效。
- 保留用户手动设置的标题和主 EXE。
- 按规范化的 Windows 路径去重；新候选项处于多个重叠根目录时，选择包含它且路径最长的根目录。
- 递归扫描时不跟随目录联接点或符号链接。
- 扫描期间绝不执行 EXE。
- 只有用户明确操作后，才以参数数组和 `shell=False` 启动程序。
- 遵循 TDD，并在每个任务完成后提交。

---

### 任务 1：在不访问文件系统的情况下规范化 Windows 路径

**文件：**
- 新建：`src/gameshelf/scanning/__init__.py`
- 新建：`src/gameshelf/scanning/path_keys.py`
- 新建：`tests/unit/scanning/test_path_keys.py`

**接口：**
- 产出：`windows_path_key(path: str | Path) -> str`。
- 产出：`is_same_or_child(path_key: str, root_key: str) -> bool`。
- 产出：`portable_relative(path: Path, root: Path) -> str`，存储时使用 `/`。
- 产出：拒绝路径穿越的 `expand_relative(root: Path, relative: str) -> Path`。

- [ ] **步骤 1：编写会失败的规范化与路径穿越测试**

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

- [ ] **步骤 2：运行针对性测试并确认失败**

运行：`python -m pytest tests/unit/scanning/test_path_keys.py -v`

预期：失败，因为 `path_keys` 尚不存在。

- [ ] **步骤 3：实现按字面处理的 Windows 路径规范化与安全展开**

移除开头的 `\\?\`，将 `/` 转为 `\`，应用 `ntpath.normpath`，去掉每个非根路径分段末尾的空格/句点，并对结果执行 `casefold()`。保留 UNC 服务器/共享边界。生成去重键时不要调用 `Path.resolve()`，因为暂时不可用的可移动驱动器仍需能够规范化。

`expand_relative` 必须拒绝绝对路径、带驱动器限定的路径、`..` 分段，以及按字面生成的 Windows 键位于根目录键之外的最终路径。

- [ ] **步骤 4：运行路径测试与静态检查**

运行：

```powershell
python -m pytest tests/unit/scanning/test_path_keys.py -v
python -m ruff check src/gameshelf/scanning tests/unit/scanning
python -m mypy src/gameshelf/scanning
```

预期：全部通过。

- [ ] **步骤 5：提交路径标识规则**

```powershell
git add src/gameshelf/scanning tests/unit/scanning
git commit -m "feat: normalize portable Windows paths"
```

### 任务 2：添加扫描根目录与游戏领域仓储

**文件：**
- 新建：`src/gameshelf/library/__init__.py`
- 新建：`src/gameshelf/library/models.py`
- 新建：`src/gameshelf/library/repository.py`
- 新建：`src/gameshelf/library/service.py`
- 新建：`tests/unit/library/test_repository.py`
- 新建：`tests/unit/library/test_service.py`

**接口：**
- 产出：与架构列对应的不可变 `ScanRoot` 和 `Game` 数据类。
- 产出：使用短生命周期只读连接的 `LibraryRepository` 读取方法。
- 产出：`LibraryService.add_root`、`update_root`、`remove_root`、`remap_root`、`list_roots`、`list_games` 和 `get_game`。
- 所有变更都向 `DbWriter` 提交一个事务。

- [ ] **步骤 1：编写会失败的仓储/服务测试**

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

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/unit/library -v`

预期：失败，因为游戏库领域尚不存在。

- [ ] **步骤 3：实现不可变模型与事务化服务方法**

使用以下公开请求/值类型：

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

校验根目录模式/深度（`children` 始终存储深度 `1`；递归深度范围为 `1..8`）。将排除项规范化为相对目录名或 glob 模式，并拒绝绝对路径或向父级穿越的条目。删除根目录时，必须先在同一事务内将其游戏更新为 `scan_root_id=NULL`、`status='missing'` 并设置 `missing_since`，然后再删除根目录。

- [ ] **步骤 4：运行游戏库测试与数据库测试套件**

运行：`python -m pytest tests/unit/library tests/unit/db -v`

预期：全部通过。

- [ ] **步骤 5：提交游戏库持久化**

```powershell
git add src/gameshelf/library tests/unit/library
git commit -m "feat: persist game roots and library records"
```

### 任务 3：枚举候选游戏目录

**文件：**
- 新建：`src/gameshelf/scanning/models.py`
- 新建：`src/gameshelf/scanning/discovery.py`
- 新建：`tests/unit/scanning/test_discovery.py`

**接口：**
- 使用：`ScanRoot`、`windows_path_key`、`portable_relative` 和 `TaskContext`。
- 产出：`DirectoryCandidate(path, relative_dir, depth, reason)`。
- 产出：`enumerate_candidates(root: ScanRoot, context: TaskContext) -> Iterator[DirectoryCandidate]`。
- 本增量中 `reason` 为 `direct_child` 或 `generic_executable`。

- [ ] **步骤 1：编写会失败的直接子目录、递归、排除和联接点测试**

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

还要测试不区分大小写的排除项、不可访问的子目录、枚举开始后的取消，以及模拟 `DirEntry.is_symlink()` 返回 true 的情况。

- [ ] **步骤 2：运行发现测试并确认失败**

运行：`python -m pytest tests/unit/scanning/test_discovery.py -v`

预期：失败，因为发现功能尚不存在。

- [ ] **步骤 3：实现确定性的 `os.scandir` 遍历**

产出条目前先按 `name.casefold()` 排序。子目录模式下，产出每个可访问的直接子目录。递归模式下只深入到 `max_depth`；目录中至少包含一个 `.exe` 普通文件时就产出该目录，并停止向其下层继续深入。跳过符号链接和重解析点目录。单个子项的访问错误转为警告证据并继续扫描；无法打开根目录时抛出 `RootUnavailableError`，且不产出任何内容。

打开每个目录前以及每处理 64 个条目时调用 `context.raise_if_cancelled()`。本任务不读取可执行文件内容。

- [ ] **步骤 4：运行发现测试与静态检查**

运行：`python -m pytest tests/unit/scanning/test_discovery.py -v`

预期：全部通过。

- [ ] **步骤 5：提交目录发现功能**

```powershell
git add src/gameshelf/scanning/models.py src/gameshelf/scanning/discovery.py tests/unit/scanning/test_discovery.py
git commit -m "feat: discover game directory candidates"
```

### 任务 4：在不启动程序的情况下为主可执行文件排名

**文件：**
- 修改：`pyproject.toml`
- 新建：`src/gameshelf/scanning/pe_metadata.py`
- 新建：`src/gameshelf/scanning/executable_ranker.py`
- 新建：`tests/unit/scanning/test_executable_ranker.py`
- 新建：`tests/fixtures/pe/README.md`

**接口：**
- 产出：`PeMetadata(product_name, file_description, company_name, architecture)`。
- 产出：`read_pe_metadata(path: Path) -> PeMetadata`，文件格式错误时返回空字段或未知字段。
- 产出：`ExecutableCandidate(relative_path, score, architecture, evidence)`。
- 产出：`rank_executables(game_dir: Path) -> tuple[ExecutableCandidate, ...]`。

- [ ] **步骤 1：使用模拟元数据读取器编写会失败的排名测试**

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

- [ ] **步骤 2：添加 `pefile` 并运行测试以确认失败**

将 `pefile>=2024.8.26,<2027` 添加到项目依赖，重新安装可编辑依赖，然后运行：`python -m pytest tests/unit/scanning/test_executable_ranker.py -v`。

预期：失败，因为排名器尚不存在。

- [ ] **步骤 3：实现防御性的 PE 元数据读取与评分**

排除基本文件名匹配 `unins*`、`uninstall*`、`setup*`、`install*`、`update*`、`updater*`、`crash*`、`report*` 的程序，以及位于名为 `redist`、`_commonredist`、`runtime`、`tools` 或 `support` 目录下的可执行文件。不要排除 `config.exe`，但要给予较大的负分，并将其标记为辅助工具。

根据是否位于根层级、规范化后的目录/标题相似度、PE 产品/描述相似度以及可执行文件大小进行评分。捕获 `pefile.PEFormatError`、`OSError` 和无效资源字符串。只解析 PE 标头/资源；本模块绝不调用 `subprocess`、`os.startfile` 或 `ShellExecute`。

- [ ] **步骤 4：运行排名测试与依赖检查**

运行：

```powershell
python -m pytest tests/unit/scanning/test_executable_ranker.py -v
python -m ruff check src/gameshelf/scanning tests/unit/scanning
python -m mypy src/gameshelf/scanning
```

预期：全部通过。

- [ ] **步骤 5：提交可执行文件排名功能**

```powershell
git add pyproject.toml src/gameshelf/scanning tests/unit/scanning tests/fixtures/pe
git commit -m "feat: rank game executables safely"
```

### 任务 5：核对成功、已取消及不可用的扫描

**文件：**
- 新建：`src/gameshelf/scanning/reconcile.py`
- 新建：`src/gameshelf/scanning/service.py`
- 新建：`tests/integration/scanning/test_scan_service.py`

**接口：**
- 使用：根目录仓储、游戏仓储、`DbWriter`、发现器、排名器和任务上下文。
- 产出：`ScanService.scan_root(root_id: str, scan_kind: Literal['quick','full'], context: TaskContext) -> ScanSummary`。
- 产出：`ScanSummary(session_id, status, discovered, added, updated, missing, warnings, move_suggestions)`。
- 产出：`MoveSuggestion(existing_game_id, candidate_relative_dir, confidence, evidence)`；绝不自动执行迁移。

- [ ] **步骤 1：编写会失败的端到端扫描状态测试**

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

还要覆盖取消、递归发现、根目录重叠时选择最长根目录，以及不含 EXE 的子目录。

- [ ] **步骤 2：运行集成测试并确认失败**

运行：`python -m pytest tests/integration/scanning/test_scan_service.py -v`

预期：失败，因为扫描核对功能尚不存在。

- [ ] **步骤 3：实现以会话为边界的核对**

以 `running` 状态创建 `scan_sessions` 记录，并通过 `DbWriter` 每批 200 条地将候选观察结果流式写入内部 `scan_observations` 表；这样无需将大型游戏库全部保留在内存中，也不会过早改变可见游戏状态。发现完成后，执行一个核对事务：

1. 按 `install_path_key` 插入或更新候选项；
2. 更新检测到的标题和 EXE，同时保留手动字段；
3. 将已观察记录设为 `installed` 并清除 `missing_since`；
4. 完整扫描成功时，将分配给该根目录但未观察到的记录标记为 `missing`；
5. 快速递归扫描时，只核验已知记录，不声称已完整发现新的嵌套游戏；
6. 最后更新根目录/会话的成功元数据。

成功核对后删除该会话的暂存观察记录。失败、取消或不可用时，删除暂存观察记录并保留可见游戏，只留下会话/错误摘要。

发生 `RootUnavailableError`、取消或任意异常时，只更新会话/根目录状态与错误；不得核对失效状态。

当新观察到的候选项在 EXE 基本文件名、文件大小、PE 产品名及目录-标题相似度上接近某条失效记录时，生成移动建议。置信度低于 `0.75` 的建议不返回。

- [ ] **步骤 4：运行集成测试与回归测试**

运行：

```powershell
python -m pytest tests/integration/scanning tests/unit/library tests/unit/scanning -v
python -m ruff check src tests
python -m mypy src
```

预期：全部通过。

- [ ] **步骤 5：提交事务化扫描功能**

```powershell
git add src/gameshelf/scanning tests/integration/scanning
git commit -m "feat: reconcile cancellable library scans"
```

### 任务 6：安全启动游戏并打开文件夹

**文件：**
- 新建：`src/gameshelf/platform/__init__.py`
- 新建：`src/gameshelf/platform/windows/__init__.py`
- 新建：`src/gameshelf/platform/windows/shell.py`
- 新建：`src/gameshelf/platform/windows/processes.py`
- 新建：`src/gameshelf/library/launcher.py`
- 新建：`tests/unit/library/test_launcher.py`

**接口：**
- 产出：`WindowsShell.open_directory(path: Path) -> None`。
- 产出：`WindowsProcessLauncher.launch(executable, arguments, cwd, environment) -> LaunchedProcess(pid)`。
- 产出：`GameLauncher.launch(game_id) -> LaunchReceipt` 和 `open_install_directory(game_id) -> None`。

- [ ] **步骤 1：使用假对象编写会失败的安全测试**

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

- [ ] **步骤 2：运行启动测试并确认失败**

运行：`python -m pytest tests/unit/library/test_launcher.py -v`

预期：失败，因为启动器适配器尚不存在。

- [ ] **步骤 3：实现安全路径解析与 Windows 适配器**

使用 `expand_relative` 解析安装目录、可执行文件和工作目录；要求 EXE 存在且以 `.exe` 结尾。只将校验过的字符串环境变量条目合并到 `os.environ`。使用：

```python
subprocess.Popen(
    [str(executable), *arguments],
    cwd=str(cwd),
    env=environment,
    shell=False,
    close_fds=True,
)
```

只有 `WindowsShell.open_directory` 可以使用 `os.startfile(path)`，而且要先检查路径是已存在的目录。仅在 `Popen` 返回 PID 后更新 `last_launched_at`。

- [ ] **步骤 4：运行启动器测试与静态检查**

运行：`python -m pytest tests/unit/library/test_launcher.py -v`

预期：全部通过，且不启动真实外部进程。

- [ ] **步骤 5：提交启动/打开行为**

```powershell
git add src/gameshelf/platform src/gameshelf/library/launcher.py tests/unit/library/test_launcher.py
git commit -m "feat: launch games and open folders safely"
```

### 任务 7：通过类型化桥接层公开游戏库命令

**文件：**
- 修改：`src/gameshelf/bridge/api.py`
- 修改：`src/gameshelf/bootstrap/application.py`
- 新建：`tests/unit/bridge/test_library_api.py`
- 修改：`frontend/src/api/contracts.ts`
- 修改：`frontend/src/api/bridge.ts`
- 修改：`frontend/src/api/mockBridge.ts`
- 新建：`frontend/src/features/library/libraryStore.ts`
- 新建：`frontend/src/features/scan-roots/ScanRootDialog.vue`
- 新建：`frontend/src/features/scan-roots/ScanRootList.vue`
- 新建：`frontend/src/features/library/GamePlaceholderGrid.vue`
- 新建：`frontend/src/features/library/GameSettingsPanel.vue`
- 新建：`frontend/tests/libraryStore.spec.ts`
- 新建：`frontend/tests/ScanRootDialog.spec.ts`
- 修改：`frontend/src/App.vue`

**接口：**
- 添加桥接方法 `list_roots`、`add_root`、`update_root`、`remove_root`、`remap_root`、`list_games`、`start_scan`、`confirm_move`、`launch_game` 和 `open_install_directory`。
- 添加桥接方法 `choose_game_executable`、`set_game_executable`、`set_game_title` 和 `update_launch_configuration`。
- `start_scan` 返回 `{ taskId: string }`；进度通过基础设施的任务端点获取。
- 产出 Pinia `useLibraryStore()`，包含 `load`、`scan` 及根目录变更操作。

- [ ] **步骤 1：编写会失败的桥接与组件测试**

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

- [ ] **步骤 2：运行桥接与前端测试并确认失败**

运行：

```powershell
python -m pytest tests/unit/bridge/test_library_api.py -v
npm --prefix frontend run test:unit -- --run tests/libraryStore.spec.ts tests/ScanRootDialog.spec.ts
```

预期：因方法/组件缺失而失败。

- [ ] **步骤 3：实现经过校验的命令和可用的占位游戏库 UI**

所有 Python 桥接方法都接收一个 JSON 对象，校验必需的键/类型，调用服务，并返回 camelCase DTO。不得直接暴露仓储对象。

UI 必须提供：

- “添加游戏目录”操作；
- 根目录列表，显示启用状态、模式/深度、最近状态，并提供重新扫描、重映射和删除；
- 可取消的扫描进度；
- 显示标题及已安装/失效/无主程序状态的占位卡片；
- 详情中的启动和打开文件夹操作；
- 标题编辑；以游戏安装目录为根的 EXE 选择器；高级工作目录、参数数组和环境变量键值编辑；
- 移动建议确认面板。

通过白名单 `choose_directory` 方法使用 pywebview 原生文件夹选择；后端返回选中的显示路径或 `null`。不得允许 JavaScript 任意浏览文件系统。

`confirm_move` 必须要求：现有游戏仍处于失效状态、候选项确实来自所引用扫描会话的观察结果，并且目标路径未被占用。它在一个事务中重新分配根目录/相对路径/安装路径键，设为已安装、清除失效状态，同时保留标题、封面、存档、手动 EXE/引擎和启动配置。

- [ ] **步骤 4：运行全部桥接/前端检查**

运行：

```powershell
python -m pytest tests/unit/bridge tests/integration/scanning -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

预期：全部通过。

- [ ] **步骤 5：提交可交互游戏库**

```powershell
git add src frontend tests
git commit -m "feat: manage and scan game roots from the UI"
```

### 任务 8：添加启动快速扫描并完成本增量

**文件：**
- 修改：`frontend/src/features/library/libraryStore.ts`
- 修改：`frontend/src/App.vue`
- 新建：`frontend/tests/startupScan.spec.ts`
- 新建：`tests/integration/scanning/test_overlap_and_startup.py`
- 修改：`README.md`

**接口：**
- 使用：`start_scan(kind='quick')`。
- 产出：缓存游戏库渲染完成后发起一次启动快速扫描请求，绝不提前发起。
- 快速扫描行为：子目录模式的根目录枚举直接子目录；递归模式的根目录只核验已知游戏路径。

- [ ] **步骤 1：编写会失败的缓存优先启动测试**

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

- [ ] **步骤 2：运行启动测试并确认失败**

运行：`npm --prefix frontend run test:unit -- --run tests/startupScan.spec.ts`

预期：失败，因为尚未编排启动扫描。

- [ ] **步骤 3：实现缓存优先启动与非阻塞错误**

`bootstrap` 后先加载根目录/游戏并完成渲染，再为已启用根目录启动快速扫描。扫描期间不得清除现有卡片。根目录不可用时显示“根目录暂时无法访问，已有游戏状态未改变”并保留卡片。扫描错误显示在可关闭的状态区域及根目录详情中，而不是显示致命应用错误页面。

- [ ] **步骤 4：运行本增量验收门禁**

运行：

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

预期：全部通过。

- [ ] **步骤 5：提交完整的游戏库增量**

```powershell
git add frontend tests README.md
git commit -m "feat: refresh cached library in the background"
```

## 游戏库增量验收门禁

- 将 `D:\文件夹a` 配置为递归深度 2，将 `D:\文件夹b` 配置为子目录模式；能够发现游戏 a、b、c、d。
- 不含 EXE 的直接子目录仍可见，并显示“尚未选择主程序”。
- 重叠根目录绝不会生成重复的安装路径记录。
- 不可用/已取消的根目录保留原有已安装状态。
- 手动 EXE 和标题设置在重新扫描后仍保留。
- 扫描绝不执行 EXE。
- 明确启动时使用已选择 EXE、精确参数数组、已配置工作目录和 `shell=False`。
- 启动快速扫描开始前先渲染缓存卡片。
