# GameShelf WebView2 手动安装引导实施计划

> 实施状态：已完成。轻量版已改为验证 Bootstrapper 后打开安装目录并正常退出，双版本产物重建、Windows Sandbox 手动安装闭环和关键故障路径均已验证。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本计划在当前会话内顺序执行，不使用子代理或额外 worktree。

**Goal:** 将轻量联网版从“GameShelf 静默运行并同步等待 WebView2 Bootstrapper”改为“验证安装器后打开其所在文件夹并正常退出，由用户手动安装并重新启动 GameShelf”。

**Architecture:** 保留现有 Evergreen 官方 API 检测、发布清单和 Bootstrapper 完整性校验，把 `EvergreenRuntimeInstaller` 收敛为不执行外部安装器的 `EvergreenRuntimeGuide`。缺失 Runtime 时先验证安装器，再通过原生确认框征得同意；确认后仅调用 Windows Shell 打开 Explorer 并选中文件，以专用正常控制流结束本次启动。GameShelf 不跟踪微软安装器状态，用户完成安装后重新启动，下一次检测成功才创建主窗口。

**Tech Stack:** Python 3.12、pytest、PyInstaller onedir、pywebview 6.2.1、Windows `MessageBoxW`、Windows `ShellExecuteW`、PowerShell 发布脚本、Microsoft Evergreen WebView2 Bootstrapper 1.3.257.13。

## Global Constraints

- 仓库设计和开发文档使用中文；需求变化和缺陷事实更新到 `docs/superpowers/plans` 下对应固定文档。
- 本文件是一次性详细实施计划，固定放在 `docs/历史归档/2026-08`；不得再为本修复新增永久设计文档。
- 当前工作直接位于 `main`，已有未提交的双版本发布改动；必须原地增量修改，不创建分支、子代理或 worktree。
- 不执行 `git add`、`git commit`、`git push`；每个任务只做只读 Git 检查，等用户明确要求后再处理 Git 边界。
- 不得修改或纳入用户的未跟踪文件 `后续优化-备忘录.md`。
- GameShelf 不得直接执行 `MicrosoftEdgeWebview2Setup.exe`，不得传递 `/silent /install`，不得等待或轮询微软安装器，也不得自动启动第二个 GameShelf 进程。
- 轻量版缺失 Evergreen 时必须先验证 Bootstrapper 绝对路径、普通文件属性和发布清单 SHA-256，再显示手动安装提示。
- 用户取消和成功打开安装位置均为正常退出：退出码 `0`，不写 `startup-error.log`，不创建应用主窗口。
- Bootstrapper 缺失或哈希错误、Evergreen 检测失败、Explorer 启动失败均为真实启动故障：退出码 `1`，由现有冻结启动报告器显示中文错误并写日志。
- 冻结 smoke 不得显示提示、打开 Explorer 或启动安装器；仍需校验系统 Evergreen 和随包 Bootstrapper 完整性。
- 真实受控输入固定为仓库内被 `.gitignore` 排除的 `webview安装包/Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab` 与 `webview安装包/MicrosoftEdgeWebview2Setup.exe`。
- 正式重建继续一次性原子发布完整版目录/ZIP/SHA-256 和轻量版目录/ZIP/SHA-256，共六个产物。

---

## 文件职责与改动边界

- `src/gameshelf/bootstrap/webview_bootstrapper.py`：检测 Evergreen、验证 Bootstrapper、提示后打开安装位置；不再执行安装器。
- `src/gameshelf/bootstrap/webview_runtime.py`：把 `evergreen` 模式委托给手动引导组件，向上暴露 `allow_manual_guide` 语义。
- `src/gameshelf/platform/windows/startup_reporter.py`：提供准确的中文手动安装确认文案。
- `src/gameshelf/app.py`：区分“用户取消/已打开安装位置”的正常退出和真实启动故障。
- `release/README-lite.txt`：面向最终用户说明手动安装和重新启动流程。
- `tests/unit/bootstrap/test_webview_bootstrapper.py`：覆盖验证顺序、Explorer 打开、取消、smoke 和 Windows Shell 错误。
- `tests/unit/bootstrap/test_webview_runtime.py`：覆盖 `WebViewRuntime` 到手动引导组件的委托。
- `tests/unit/platform/windows/test_startup_reporter.py`：锁定确认框文案和默认否按钮。
- `tests/unit/test_app_startup.py`：覆盖正常退出、无主窗口、无错误报告、已有 Runtime 正常启动和真实错误报告。
- `docs/superpowers/plans/2026-08-12-GameShelf-07-便携版打包与发布.md`、`docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md`：设计已经批准；只有真实重建和 Sandbox 复验取得新证据后才更新完成状态、体积和哈希。
- `scripts/build_release.ps1`：本修复不改变发布架构，只作为真实重建入口执行；若必须改脚本，应停止并先说明与本计划不一致的原因。

---

### Task 1: 用手动安装引导替换安装器执行与等待

**Files:**
- Modify: `src/gameshelf/bootstrap/webview_bootstrapper.py:1-180`
- Modify: `tests/unit/bootstrap/test_webview_bootstrapper.py:1-245`

**Interfaces:**
- Consumes: `ReleaseRuntimeConfig.bootstrapper_path`、`ReleaseRuntimeConfig.bootstrapper_sha256`、`detect_evergreen_version()`、`FrozenRuntimeInstallPrompt.confirm()`。
- Produces: `EvergreenRuntimeGuide.ensure_available(config: ReleaseRuntimeConfig, *, allow_manual_guide: bool) -> str`；`WebViewManualInstallRequired` 表示 Explorer 已成功打开；`WebViewInstallCancelled` 表示用户拒绝；`_open_bootstrapper_location(path: Path) -> None` 只打开 Explorer。

- [x] **Step 1: 写成功打开安装位置和验证顺序的失败测试**

在 `tests/unit/bootstrap/test_webview_bootstrapper.py` 用下面的行为替换旧的“安装并重检成功”测试：

```python
def test_missing_evergreen_opens_verified_bootstrapper_location(
    tmp_path: Path,
) -> None:
    config = _evergreen_config(tmp_path, payload=b"official bootstrapper")
    opened: list[Path] = []
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: True,
        opener=opened.append,
    )

    with pytest.raises(WebViewManualInstallRequired):
        guide.ensure_available(config, allow_manual_guide=True)

    assert opened == [config.bootstrapper_path]


def test_invalid_bootstrapper_is_rejected_before_prompt(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path, payload=b"tampered")
    config = ReleaseRuntimeConfig(
        config.mode,
        config.bootstrapper_path,
        hashlib.sha256(b"official").hexdigest(),
    )
    guide = EvergreenRuntimeGuide(
        detector=lambda: None,
        prompt=lambda: pytest.fail("prompt must not run"),
        opener=lambda _path: pytest.fail("Explorer must not open"),
    )

    with pytest.raises(WebViewBootstrapperError, match="SHA-256 不匹配"):
        guide.ensure_available(config, allow_manual_guide=True)
```

- [x] **Step 2: 运行新增测试并确认接口缺失**

Run:

```powershell
.\.venv\python.exe -m pytest tests/unit/bootstrap/test_webview_bootstrapper.py `
  -k "opens_verified or rejected_before_prompt" -vv
```

Expected: FAIL，错误指向 `EvergreenRuntimeGuide`、`WebViewManualInstallRequired` 或 `allow_manual_guide` 尚不存在。

- [x] **Step 3: 定义手动引导并删除安装器状态机**

在 `src/gameshelf/bootstrap/webview_bootstrapper.py` 删除 `time`、`Sequence`、`CompletedProcess`、`CommandRunner`、`Clock`、`Sleeper`、`_require_success()`、`_run_bootstrapper()`、`_wait_for_runtime()` 和 `timeout_seconds`，保留检测、文件验证和 SHA-256。引入 `stat`，并让 `_validate_bootstrapper()` 在 `path.is_file()` 之外调用 `_is_reparse_point(path)`，拒绝符号链接、目录联接和其他重解析点。实现：

```python
type VersionDetector = Callable[[], str | None]
type ConsentPrompt = Callable[[], bool]
type LocationOpener = Callable[[Path], None]


class WebViewManualInstallRequired(Exception):
    """Explorer opened successfully; the user must install and restart."""


class WebViewInstallCancelled(Exception):
    """The user declined to open the manual installer location."""


@dataclass
class EvergreenRuntimeGuide:
    detector: VersionDetector = field(default_factory=lambda: detect_evergreen_version)
    prompt: ConsentPrompt = field(
        default_factory=lambda: FrozenRuntimeInstallPrompt().confirm
    )
    opener: LocationOpener = field(
        default_factory=lambda: _open_bootstrapper_location
    )

    def ensure_available(
        self,
        config: ReleaseRuntimeConfig,
        *,
        allow_manual_guide: bool,
    ) -> str:
        version = self.detector()
        if not allow_manual_guide:
            _validate_bootstrapper(config)
            if version is not None:
                return version
            raise WebViewBootstrapperError(
                "系统未安装 Evergreen WebView2；smoke 不会打开安装位置。"
            )
        if version is not None:
            return version

        _validate_bootstrapper(config)
        if not self.prompt():
            raise WebViewInstallCancelled
        path = config.bootstrapper_path
        if path is None:
            raise WebViewBootstrapperError("发布配置缺少 WebView2 Bootstrapper 路径。")
        self.opener(path)
        raise WebViewManualInstallRequired
```

验证必须发生在 `prompt()` 之前；只有已经安装 Evergreen 时，正常启动才允许跳过 Bootstrapper 校验。

`_is_reparse_point()` 使用 `path.lstat()` 读取 `st_file_attributes` 并检查 `stat.FILE_ATTRIBUTE_REPARSE_POINT`；`lstat()` 失败必须转成包含目标路径的 `WebViewBootstrapperError`。新增测试时通过 monkeypatch 令 `_is_reparse_point()` 返回 `True`，断言提示框与 Explorer 均不调用，避免依赖测试机是否允许创建 Windows 符号链接。

- [x] **Step 4: 用 Windows Shell 打开 Explorer**

在同一文件引入 `ctypes`、`Path`、`Any` 并增加：

```python
def _open_bootstrapper_location(path: Path) -> None:
    windows_directory = os.environ.get("WINDIR")
    if not windows_directory:
        raise WebViewBootstrapperError("无法确定 Windows 目录，不能打开安装位置。")
    explorer = Path(windows_directory) / "explorer.exe"
    if not explorer.is_absolute() or not explorer.is_file():
        raise WebViewBootstrapperError(f"找不到 Windows Explorer：{explorer}")
    result = _shell_execute_explorer(explorer, path)
    if result <= 32:
        raise WebViewBootstrapperError(
            f"无法打开 WebView2 安装位置，ShellExecuteW 返回 {result}。"
        )


def _shell_execute_explorer(explorer: Path, selected_file: Path) -> int:
    shell32: Any = ctypes.WinDLL("shell32", use_last_error=True)
    shell_execute = shell32.ShellExecuteW
    shell_execute.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    shell_execute.restype = ctypes.c_void_p
    result = shell_execute(
        None,
        "open",
        str(explorer),
        f'/select,"{selected_file}"',
        str(selected_file.parent),
        1,
    )
    return int(result or 0)
```

`lpFile` 必须是受系统目录约束的 `explorer.exe`，Bootstrapper 只能出现在 `/select` 参数中。

- [x] **Step 5: 写 Explorer 成功和失败测试**

```python
def test_location_opener_selects_bootstrapper_with_system_explorer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = tmp_path / "Windows"
    windows.mkdir()
    explorer = windows / "explorer.exe"
    explorer.write_bytes(b"explorer")
    bootstrapper = tmp_path / "GameShelf" / "prerequisites" / "MicrosoftEdgeWebview2Setup.exe"
    bootstrapper.parent.mkdir(parents=True)
    bootstrapper.write_bytes(b"official")
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setenv("WINDIR", str(windows))
    monkeypatch.setattr(
        bootstrapper_module,
        "_shell_execute_explorer",
        lambda executable, selected: calls.append((executable, selected)) or 33,
    )

    _open_bootstrapper_location(bootstrapper)

    assert calls == [(explorer, bootstrapper)]


def test_location_opener_reports_shell_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = tmp_path / "Windows"
    windows.mkdir()
    (windows / "explorer.exe").write_bytes(b"explorer")
    bootstrapper = tmp_path / "MicrosoftEdgeWebview2Setup.exe"
    bootstrapper.write_bytes(b"official")
    monkeypatch.setenv("WINDIR", str(windows))
    monkeypatch.setattr(
        bootstrapper_module,
        "_shell_execute_explorer",
        lambda _executable, _selected: 31,
    )

    with pytest.raises(WebViewBootstrapperError, match="ShellExecuteW 返回 31"):
        _open_bootstrapper_location(bootstrapper)
```

保留并改写已有 Evergreen 已安装、smoke 禁止交互、用户取消、安装器缺失、哈希错误和检测组件异常测试。删除安装器退出码、安装后轮询超时和 `subprocess.run` 参数测试。

- [x] **Step 6: 运行 Task 1 测试与静态检查**

Run:

```powershell
.\.venv\python.exe -m pytest tests/unit/bootstrap/test_webview_bootstrapper.py -q
.\.venv\python.exe -m ruff check src/gameshelf/bootstrap/webview_bootstrapper.py tests/unit/bootstrap/test_webview_bootstrapper.py
.\.venv\python.exe -m mypy src/gameshelf/bootstrap/webview_bootstrapper.py
git diff --check
```

Expected: 全部命令退出码为 `0`；生产代码不再运行安装器。只执行 `git status --short` 记录检查点，不暂存或提交。

---

### Task 2: 把正常退出语义接入 WebViewRuntime 和应用入口

**Files:**
- Modify: `src/gameshelf/bootstrap/webview_runtime.py:1-207`
- Modify: `src/gameshelf/app.py:1-229`
- Modify: `tests/unit/bootstrap/test_webview_runtime.py:1-245`
- Modify: `tests/unit/test_app_startup.py:1-425`

**Interfaces:**
- Consumes: Task 1 的 `EvergreenRuntimeGuide`、`WebViewManualInstallRequired`、`WebViewInstallCancelled`。
- Produces: `WebViewRuntime.ensure_available(*, allow_manual_guide: bool) -> str | None`；`main()` 对两种正常中止返回 `0`，真实 `WebViewBootstrapperError` 继续进入冻结错误报告器。

- [x] **Step 1: 写 Explorer 已打开后不构建应用的失败测试**

在 `tests/unit/test_app_startup.py` 用下面测试替换旧的“安装成功同进程继续”测试：

```python
def test_manual_install_location_opened_exits_without_building_application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "_internal"
    app_root = tmp_path / "GameShelf"
    _create_required_resources(bundle_root / "resources")
    _write_release_manifest(app_root, mode="evergreen")
    reporter = RecordingReporter()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(app_module, "_validate_desktop_dependencies", lambda: None)
    monkeypatch.setattr(
        WebViewRuntime,
        "ensure_available",
        lambda _self, *, allow_manual_guide: (_ for _ in ()).throw(
            WebViewManualInstallRequired
        ),
    )
    monkeypatch.setattr(
        app_module,
        "build_application",
        lambda *_args, **_kwargs: pytest.fail("application must not build"),
    )

    exit_code = main(["--app-root", str(app_root)], reporter=reporter)

    assert exit_code == 0
    assert reporter.calls == []
    assert not (app_root / "data" / "logs" / "startup-error.log").exists()
```

同步把用户取消测试改为 `allow_manual_guide`，保留真实 `WebViewBootstrapperError` 进入报告器的测试。

- [x] **Step 2: 写 WebViewRuntime 委托标志的失败测试**

使用记录桩锁定 `allow_manual_guide=True` 会原样传给引导组件：

```python
from typing import cast


class RecordingGuide:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def ensure_available(
        self,
        _config: ReleaseRuntimeConfig,
        *,
        allow_manual_guide: bool,
    ) -> str:
        self.calls.append(allow_manual_guide)
        return "151.0.4129.86"


guide = RecordingGuide()
runtime = WebViewRuntime.for_runtime(
    tmp_path,
    frozen=True,
    release_config=config,
    evergreen_guide=cast(EvergreenRuntimeGuide, guide),
)
assert runtime.ensure_available(allow_manual_guide=True) == "151.0.4129.86"
assert guide.calls == [True]
```

- [x] **Step 3: 运行新接口测试并确认旧命名失败**

Run:

```powershell
.\.venv\python.exe -m pytest `
  tests/unit/bootstrap/test_webview_runtime.py `
  tests/unit/test_app_startup.py `
  -k "manual_guide or manual_install_location or cancelled_webview" -vv
```

Expected: FAIL，旧 `allow_install`、`evergreen_installer` 或旧异常导入导致测试失败。

- [x] **Step 4: 一致重命名 WebViewRuntime 委托**

在 `src/gameshelf/bootstrap/webview_runtime.py` 使用：

```python
from gameshelf.bootstrap.webview_bootstrapper import EvergreenRuntimeGuide

_evergreen_guide: EvergreenRuntimeGuide = field(repr=False)

# for_runtime 的注入参数
evergreen_guide: EvergreenRuntimeGuide | None = None

guide = evergreen_guide or EvergreenRuntimeGuide()

def ensure_available(self, *, allow_manual_guide: bool) -> str | None:
    if self.release_config.mode is RuntimeMode.FIXED:
        self.validate()
        return None
    if self.release_config.mode is RuntimeMode.EVERGREEN:
        return self._evergreen_guide.ensure_available(
            self.release_config,
            allow_manual_guide=allow_manual_guide,
        )
    return None
```

两个 `cls(...)` 构造分支都传 `_evergreen_guide=guide`。不得保留 `allow_install` 或 `_evergreen_installer` 兼容别名。

- [x] **Step 5: 让 app.py 正常结束手动引导**

```python
from gameshelf.bootstrap.webview_bootstrapper import (
    WebViewInstallCancelled,
    WebViewManualInstallRequired,
)

runtime_version = webview_runtime.ensure_available(
    allow_manual_guide=not args.smoke_test
)

except (WebViewInstallCancelled, WebViewManualInstallRequired):
    if application is not None:
        application.close()
    return 0
```

该 `except` 必须位于通用 `Exception` 之前。同步把所有测试桩和 smoke 记录从 `allow_install` 改为 `allow_manual_guide`；smoke 仍断言收到 `[False]`。

- [x] **Step 6: 运行 Task 2 测试与静态检查**

Run:

```powershell
.\.venv\python.exe -m pytest tests/unit/bootstrap/test_webview_runtime.py tests/unit/test_app_startup.py -q
.\.venv\python.exe -m ruff check src/gameshelf/bootstrap/webview_runtime.py src/gameshelf/app.py tests/unit/bootstrap/test_webview_runtime.py tests/unit/test_app_startup.py
.\.venv\python.exe -m mypy src/gameshelf/bootstrap/webview_runtime.py src/gameshelf/app.py
git diff --check
git status --short
```

Expected: 全部命令退出码为 `0`；正常引导和取消均没有错误报告；不暂存或提交。

---

### Task 3: 更新原生提示、轻量版 README 并跑完整回归

**Files:**
- Modify: `src/gameshelf/platform/windows/startup_reporter.py:1-78`
- Modify: `tests/unit/platform/windows/test_startup_reporter.py:1-76`
- Modify: `release/README-lite.txt:1-46`
- Verify: `docs/superpowers/plans/2026-08-12-GameShelf-07-便携版打包与发布.md`
- Verify: `docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md`

**Interfaces:**
- Consumes: `FrozenRuntimeInstallPrompt.confirm() -> bool` 和 Windows Yes/No、warning、default-No 标志。
- Produces: 明确告知“打开安装位置—手动双击—安装后重新启动”的中文提示与 README；不改变 `FrozenStartupReporter.show()`。

- [x] **Step 1: 写新提示文案的失败测试**

```python
def test_runtime_prompt_explains_manual_install_and_restart() -> None:
    calls: list[tuple[str, str, int]] = []
    prompt = FrozenRuntimeInstallPrompt(
        message_box=lambda message, title, flags: calls.append(
            (message, title, flags)
        ) or 6
    )

    assert prompt.confirm() is True
    message, title, flags = calls[0]
    assert "打开安装器所在文件夹" in message
    assert "双击 MicrosoftEdgeWebview2Setup.exe" in message
    assert "安装完成后重新启动 GameShelf" in message
    assert "联网" in message
    assert title == "GameShelf 需要 WebView2"
    assert flags & 0x00000100
```

Run:

```powershell
.\.venv\python.exe -m pytest tests/unit/platform/windows/test_startup_reporter.py -k manual_install_and_restart -vv
```

Expected: FAIL，旧文案缺少打开文件夹、手动双击和重新启动动作。

- [x] **Step 2: 更新确认框文案**

保持消息框 flags 不变，把 docstring 改为询问是否打开已验证安装器位置，并使用：

```python
result = self.message_box(
    "系统未检测到 Microsoft WebView2 Runtime。\n\n"
    "GameShelf 将打开安装器所在文件夹。\n"
    "请双击 MicrosoftEdgeWebview2Setup.exe 联网完成安装，\n"
    "安装完成后重新启动 GameShelf。\n\n"
    "是否打开安装位置？",
    "GameShelf 需要 WebView2",
    _INSTALL_PROMPT_FLAGS,
)
```

返回非 `IDYES` 或消息框异常仍等价于取消。

- [x] **Step 3: 重写轻量版 README Runtime 段落**

`release/README-lite.txt` 必须包含：

```text
系统缺失 Evergreen 时，GameShelf 会先校验随包的微软官方安装器，并询问是否
打开安装位置。选择“是”后，程序只会打开 prerequisites 文件夹并选中
MicrosoftEdgeWebview2Setup.exe，随后正常退出。请手动双击该安装器联网完成安装，
然后重新启动 GameShelf。

GameShelf 不会静默运行或等待安装器，也不会自动重新启动自身。
```

“取消与安装失败”说明：取消不写错误堆栈；微软安装器断网或失败由安装器自身提示；重新启动后 Runtime 仍缺失会再次引导；安装器缺失、哈希错误或无法打开目录才写 `data\logs\startup-error.log`。

- [x] **Step 4: 验证生产文件没有旧行为文字或命令**

Run:

```powershell
Select-String -LiteralPath `
  'src/gameshelf/bootstrap/webview_bootstrapper.py', `
  'src/gameshelf/bootstrap/webview_runtime.py', `
  'src/gameshelf/app.py', `
  'release/README-lite.txt' `
  -Pattern '/silent /install','同进程继续','自动继续启动'
```

Expected: 无输出。固定文档中的 `/silent /install` 只能出现在“不得执行”的当前规则或历史记录中。

- [x] **Step 5: 运行全部质量门**

Run:

```powershell
$repoPath = (Get-Location).Path
$env:PATH = "$repoPath\.venv;$repoPath\.venv\Scripts;$env:PATH"
.\.venv\python.exe -m pytest -q
.\.venv\python.exe -m ruff check src tests scripts
.\.venv\python.exe -m mypy src scripts
.\.venv\npm.cmd --prefix frontend run test:unit -- --run
.\.venv\npm.cmd --prefix frontend run type-check
.\.venv\npm.cmd --prefix frontend run build
.\.venv\python.exe -m gameshelf --smoke-test
git diff --check
```

Expected: 全部命令退出码为 `0`；前端仍为 25 个文件、86 项测试通过；Python 数量记录本次实际输出，不沿用旧的 550 项。

---

### Task 4: 真实重建、Sandbox 闭环和固定文档收尾

**Files:**
- Execute: `scripts/build_release.ps1`
- Generate ignored outputs: `dist/GameShelf-0.1.0-win-x64*`
- Modify after evidence: `docs/superpowers/plans/2026-08-12-GameShelf-07-便携版打包与发布.md`
- Modify after evidence: `docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md`

**Interfaces:**
- Consumes: Tasks 1–3 的源码、测试、README 和两个受控输入。
- Produces: 六个一致的新候选产物、完整性/签名/体积证据，以及全新 Sandbox 的手动安装闭环结果。

- [x] **Step 1: 正式重建两版六个产物**

Run:

```powershell
.\scripts\build_release.ps1 `
  -WebView2Archive (Join-Path (Get-Location).Path 'webview安装包\Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab') `
  -WebView2Bootstrapper (Join-Path (Get-Location).Path 'webview安装包\MicrosoftEdgeWebview2Setup.exe')
```

Expected: 只构建一次 PyInstaller 核心，并原子生成：

```text
dist\GameShelf-0.1.0-win-x64
dist\GameShelf-0.1.0-win-x64.zip
dist\GameShelf-0.1.0-win-x64.zip.sha256
dist\GameShelf-0.1.0-win-x64-lite
dist\GameShelf-0.1.0-win-x64-lite.zip
dist\GameShelf-0.1.0-win-x64-lite.zip.sha256
```

- [x] **Step 2: 独立复核目录、ZIP、校验文件和签名**

Run:

```powershell
$repoPath = (Get-Location).Path
$verifyCode = "from pathlib import Path; from scripts.release_tools import ReleaseMode, ReleaseVersions, verify_release_tree, verify_release_zip, verify_zip_sha256; root=Path(r'$repoPath'); versions=ReleaseVersions.load(root); [(verify_release_tree(root/'dist'/versions.name_for(mode), versions, mode), verify_release_zip(root/'dist'/(versions.name_for(mode)+'.zip'), versions, mode), verify_zip_sha256(root/'dist'/(versions.name_for(mode)+'.zip'), root/'dist'/(versions.name_for(mode)+'.zip.sha256'))) for mode in ReleaseMode]; print('DUAL-RELEASE-INTEGRITY=OK')"
.\.venv\python.exe -c $verifyCode

Get-FileHash -Algorithm SHA256 -LiteralPath `
  'dist\GameShelf-0.1.0-win-x64.zip', `
  'dist\GameShelf-0.1.0-win-x64-lite.zip'

Get-AuthenticodeSignature -LiteralPath `
  'dist\GameShelf-0.1.0-win-x64\runtime\msedgewebview2.exe', `
  'dist\GameShelf-0.1.0-win-x64-lite\prerequisites\MicrosoftEdgeWebview2Setup.exe' |
  Select-Object Status,@{Name='Signer';Expression={$_.SignerCertificate.Subject}}
```

Expected: 输出 `DUAL-RELEASE-INTEGRITY=OK`；两份 Microsoft 文件均为 `Valid` 且签名者包含 `Microsoft Corporation`；记录两份新 ZIP 的实际 SHA-256，不复用旧候选哈希。正式目录没有 `data`，完整版只有 `runtime`，轻量版只有 `prerequisites`。

- [x] **Step 3: 在全新 Windows Sandbox 验证只打开目录并退出**

1. 关闭存在残留安装器进程的旧 Sandbox，启动全新 Sandbox。
2. 完整解压新的轻量版 ZIP 并双击 `GameShelf.exe`。
3. 确认提示包含手动双击和重新启动说明。
4. 选择“是”，确认 Explorer 打开 `prerequisites` 并选中安装器。
5. 在任务管理器确认 `GameShelf.exe` 已退出，而且 GameShelf 没有自动创建 `MicrosoftEdgeWebview2Setup` 进程。
6. 确认不存在 `data\logs\startup-error.log`。

Expected: GameShelf 不再等待外部安装器。

- [x] **Step 4: 完成手动安装和重新启动闭环**

1. 用户在 Explorer 中双击已选中的 `MicrosoftEdgeWebview2Setup.exe`。
2. 微软安装器联网完成安装；GameShelf 不参与安装进度或错误处理。
3. 再次双击 `GameShelf.exe`，确认主窗口出现并保持至少 8 秒。
4. 正常关闭，确认没有 `startup-error.log`。

Expected: 第二次启动检测到系统 Evergreen 后直接进入主窗口。

- [x] **Step 5: 验证取消、完整性错误和完整版离线启动**

- 轻量版选择“否”：GameShelf 退出，Explorer 不打开，不写日志。
- 在 Sandbox 测试副本中改名 Bootstrapper：不显示普通引导，显示缺失文件错误并写日志。
- 在另一个测试副本中修改 Bootstrapper 一个字节：不显示普通引导，显示 SHA-256 错误并写日志。
- 在无系统 WebView2、断网的全新 Sandbox 中启动完整版，窗口保持至少 8 秒并正常关闭，不显示轻量版提示且不写日志。

不得修改正式 `dist` 目录，只操作 Sandbox 内副本。

- [x] **Step 6: 用新证据更新两份固定中文文档**

只有 Steps 1–5 全部通过后：

- 模块 07 状态改为“手动引导已实现并通过 Sandbox”，同时保留 Windows 11、路径、SmartScreen 和模块 06 尚未完成的人工验收。
- 路线图移除“手动引导待实现/原候选作废”，记录新的 Python 测试数量、两版体积、两份 ZIP SHA-256 和 Sandbox 结果。
- 两份变更记录新增“删除静默执行/等待，采用 Explorer 手动安装和用户重启”的事实。
- 旧候选记录继续作为历史事实保留，不能用新结果覆盖旧哈希。

- [x] **Step 7: 最终回归、文档自审和 Git 边界检查**

Run:

```powershell
.\.venv\python.exe -m pytest -q
.\.venv\python.exe -m ruff check src tests scripts
.\.venv\python.exe -m mypy src scripts
.\.venv\npm.cmd --prefix frontend run test:unit -- --run
.\.venv\npm.cmd --prefix frontend run type-check
.\.venv\npm.cmd --prefix frontend run build
git diff --check

$docs = @(
  'docs/superpowers/plans/2026-08-12-GameShelf-07-便携版打包与发布.md',
  'docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md'
)
$placeholders = Select-String -LiteralPath $docs -Pattern @(('T'+'BD'),('TO'+'DO'))
if ($placeholders) { throw '固定文档仍含占位符' }

git status --short
git diff --stat
```

Expected: 全部命令退出码为 `0`，固定文档无占位符；`后续优化-备忘录.md` 仍是用户未跟踪文件。不得执行暂存、提交或推送，等待用户明确决定。

---

## 完成判定

- 生产代码不再执行或等待 `MicrosoftEdgeWebview2Setup.exe`。
- 缺失 Runtime 时先验证受控文件，再由用户确认打开 Explorer；GameShelf 正常退出。
- 用户取消、Explorer 已打开、真实故障三种结果在退出码、日志和原生提示上严格区分。
- smoke 不提示、不打开 Explorer、不修改系统。
- Python/前端测试、Ruff、mypy、类型检查和生产构建全部通过。
- 六个正式发布产物重新生成并通过清单、ZIP、SHA-256、签名和布局复核。
- 全新 Windows Sandbox 完成“提示—打开目录—GameShelf 退出—手动安装—重新启动”闭环。
- 固定中文文档记录新候选证据，同时保留尚未完成的首发验收项。
- 没有暂存、提交、推送或修改 `后续优化-备忘录.md`。
