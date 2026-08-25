# GameSave Scout WebView2 双版本发布实施计划

> 实施状态：已完成。完整离线版与轻量联网版的运行时配置、单入口构建、六产物原子发布、冻结 smoke 和本机候选验证均已落地；轻量版安装行为随后由手动安装引导计划替代。

> **面向执行代理：** 必须使用 `superpowers:executing-plans` 按任务顺序实施；本计划禁止使用子代理、Git worktree 和自动提交/推送。每个步骤使用复选框跟踪。

**目标：** 从同一份 GameSave Scout PyInstaller 核心原子生成完整离线版和 `-lite` 轻量联网版；轻量版优先使用系统 Evergreen WebView2，缺失时经用户同意运行随包官方 Bootstrapper，并在安装成功后由同一 GameSave Scout 进程继续启动。

**架构：** 启动侧以格式版本 2 的发布清单确定 `fixed` 或 `evergreen`，不根据目录偶然存在进行回退；发布清单解析、Evergreen 安装状态机和 pywebview 配置各自保持独立。构建侧只运行一次质量门和 PyInstaller，再派生两种严格布局，分别验证清单、smoke、ZIP 和 SHA-256，最后把六个产物作为一个事务发布。

**技术栈：** Python 3.12、Conda、pywebview 6.2.1、pythonnet、PyInstaller 6.22.1、PowerShell、pytest、Ruff、mypy、Windows WebView2 Evergreen Bootstrapper。

## 全局约束

- 目标平台仅为 Windows 10/11 x64；Python 必须来自仓库 `.venv` Conda 前缀，Node.js 主版本必须为 24。
- 完整离线版名称保持 `GameShelf-0.1.0-win-x64`；轻量联网版名称为 `GameShelf-0.1.0-win-x64-lite`。
- 完整版必须只使用随包 Fixed Runtime，损坏时不得回退系统 Evergreen；轻量版不得包含 Fixed Runtime。
- 轻量版只有在官方 API 检测不到 Evergreen 且用户明确同意后，才能以固定参数执行随包 Bootstrapper；安装成功后同一进程继续，不创建第二个 GameSave Scout 进程。
- 构建脚本不得联网下载外部输入；Fixed Runtime CAB 和 Evergreen Bootstrapper 均由构建者手动提供并通过版本、SHA-256 与 Microsoft Corporation 有效签名校验。
- 构建、测试和 smoke 不得自动安装 WebView2 或修改构建机系统状态。
- 发布目录不得包含 `data`、CAB、Python 源码、`__pycache__`、用户游戏、封面或存档。
- 轻量版解压体积必须小于 100 MiB；完整版不得以删除 Fixed Runtime 文件的方式精简。
- 所有实现采用测试驱动：先观察目标测试失败，再写最小实现，再运行相关测试。
- 仓库设计与开发文档使用中文；需求和缺陷直接维护 `docs/superpowers/plans` 中的固定文档；本文件是位于 `docs/历史归档` 的一次性计划。
- 保留工作区已有修改；禁止自动提交、推送、创建分支、创建 worktree 或调度子代理。

---

## 文件结构与职责

**新增文件**

- `src/gamesave_scout/bootstrap/release_runtime.py`：只负责读取冻结发布清单并产出强类型运行时配置。
- `src/gamesave_scout/bootstrap/webview_bootstrapper.py`：只负责 Evergreen 检测、用户同意后的 Bootstrapper 校验/执行和有限重检。
- `tests/unit/bootstrap/test_release_runtime.py`：覆盖格式版本 2、模式字段和两种包布局配置。
- `tests/unit/bootstrap/test_webview_bootstrapper.py`：覆盖检测、取消、哈希、安装进程和超时状态机。
- `release/webview2-bootstrapper.json`：在取得真实微软官方 Bootstrapper 后记录唯一文件名、文件版本、SHA-256 和来源 URL。
- `release/README-lite.txt`：轻量联网版运行、联网安装、取消和失败说明。

**修改文件**

- `src/gamesave_scout/bootstrap/webview_runtime.py`：消费发布运行时配置，分别准备 Fixed 或 Evergreen。
- `src/gamesave_scout/platform/windows/startup_reporter.py`：增加独立的原生安装确认接口，保留现有错误报告行为。
- `src/gamesave_scout/bootstrap/smoke.py`：报告 `runtimeMode` 和分模式检查结果。
- `src/gamesave_scout/app.py`：在构建应用前完成运行时准备，并把用户取消与真实错误分开。
- `scripts/release_tools.py`：增加 Bootstrapper 受控配置、双模式布局、格式版本 2 清单、双 ZIP 和六产物原子发布。
- `scripts/build_release.ps1`：接收两个外部输入，一次构建核心，派生并验证两个发布包。
- `release/README.txt`：继续作为完整离线版说明，并明确与 `-lite` 的区别。
- `THIRD_PARTY_NOTICES.md`：记录 Evergreen Bootstrapper 官方来源和再分发说明。
- 现有相关测试：扩展启动、smoke、发布工具、入口脚本和真实 PyInstaller 回归测试。
- `docs/superpowers/plans/2026-08-12-GameSave-Scout-07-便携版打包与发布.md`、`docs/superpowers/plans/2026-08-12-GameSave-Scout-开发路线图.md`：实施完成后只更新实际状态和验证证据。

---

### 任务 1：冻结发布清单运行时配置

**文件：**

- 新增：`src/gamesave_scout/bootstrap/release_runtime.py`
- 新增：`tests/unit/bootstrap/test_release_runtime.py`

**接口：**

- 产出：`RuntimeMode(StrEnum)`，值为 `source`、`fixed`、`evergreen`。
- 产出：`ReleaseRuntimeError(RuntimeError)`，用于清单缺失、损坏或模式矛盾。
- 产出：`ReleaseRuntimeConfig.for_runtime(app_root: Path, *, frozen: bool | None = None) -> ReleaseRuntimeConfig`。
- 产出字段：`mode`、`bootstrapper_path`、`bootstrapper_sha256`。
- 后续任务只通过该对象读取发布模式，不自行解析 JSON。

- [x] **步骤 1：写入格式版本 2 和双模式失败测试**

```python
def test_fixed_release_runtime_reads_manifest_without_bootstrapper(tmp_path: Path) -> None:
    _write_manifest(tmp_path, runtime_mode="fixed", fixed_runtime=True)
    config = ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)
    assert config.mode is RuntimeMode.FIXED
    assert config.bootstrapper_path is None
    assert config.bootstrapper_sha256 is None


def test_evergreen_release_runtime_requires_bootstrapper_digest(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        runtime_mode="evergreen",
        fixed_runtime=False,
        webview2_bootstrapper_sha256=None,
    )
    with pytest.raises(ReleaseRuntimeError, match="Bootstrapper SHA-256"):
        ReleaseRuntimeConfig.for_runtime(tmp_path, frozen=True)
```

测试文件中的 `_write_manifest(root, *, runtime_mode, fixed_runtime, webview2_bootstrapper_sha256="a" * 64)` 必须写入包含 `formatVersion: 2` 的最小真实 JSON；传入 `None` 时保留 JSON `null`，不能省略被测字段。

同时覆盖：源码模式不读清单、冻结版清单缺失、JSON 损坏、`formatVersion != 2`、未知模式、`fixedRuntime` 与模式矛盾、无效 64 位小写十六进制摘要。

- [x] **步骤 2：运行测试并确认因模块不存在而失败**

```powershell
./.venv/python.exe -m pytest tests/unit/bootstrap/test_release_runtime.py -q
```

预期：收集阶段因 `gamesave_scout.bootstrap.release_runtime` 不存在而失败。

- [x] **步骤 3：实现最小强类型解析器**

```python
class RuntimeMode(StrEnum):
    SOURCE = "source"
    FIXED = "fixed"
    EVERGREEN = "evergreen"


@dataclass(frozen=True)
class ReleaseRuntimeConfig:
    mode: RuntimeMode
    bootstrapper_path: Path | None = None
    bootstrapper_sha256: str | None = None

    @classmethod
    def for_runtime(
        cls,
        app_root: Path,
        *,
        frozen: bool | None = None,
    ) -> ReleaseRuntimeConfig:
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        if not is_frozen:
            return cls(RuntimeMode.SOURCE)
        manifest = _read_manifest(app_root / "release-manifest.json")
        return _parse_runtime_config(app_root, manifest)
```

`_parse_runtime_config` 必须要求完整清单格式版本为 2；`fixed` 要求 `fixedRuntime is True`，`evergreen` 要求 `fixedRuntime is False`、有效的 `webview2BootstrapperSha256`，并固定返回 `app_root / "prerequisites" / "MicrosoftEdgeWebview2Setup.exe"`。

- [x] **步骤 4：运行单元测试和静态检查**

```powershell
./.venv/python.exe -m pytest tests/unit/bootstrap/test_release_runtime.py -q
./.venv/python.exe -m ruff check src/gamesave_scout/bootstrap/release_runtime.py tests/unit/bootstrap/test_release_runtime.py
./.venv/python.exe -m mypy src/gamesave_scout/bootstrap/release_runtime.py
```

预期：全部通过。

- [x] **步骤 5：人工检查点**

确认解析器不验证整个发布树、不执行安装器、不访问注册表或 CLR；它只把发布清单转换为后续组件可消费的不可变配置。


### 任务 2：原生确认框与 Evergreen 安装状态机

**文件：**

- 新增：`src/gamesave_scout/bootstrap/webview_bootstrapper.py`
- 新增：`tests/unit/bootstrap/test_webview_bootstrapper.py`
- 修改：`src/gamesave_scout/platform/windows/startup_reporter.py`
- 修改：`tests/unit/platform/windows/test_startup_reporter.py`

**接口：**

- 产出：`WebViewInstallCancelled(Exception)`，只表示用户主动取消。
- 产出：`WebViewBootstrapperError(RuntimeError)`，用于检测、文件、哈希、进程和重检失败。
- 产出：`EvergreenRuntimeInstaller.ensure_available(config: ReleaseRuntimeConfig, *, allow_install: bool) -> str`。
- 产出：`FrozenRuntimeInstallPrompt.confirm() -> bool`。
- 消费：任务 1 的 `ReleaseRuntimeConfig`。

- [x] **步骤 1：写入原生确认框测试**

```python
def test_runtime_prompt_uses_yes_no_and_defaults_to_no() -> None:
    calls: list[tuple[str, str, int]] = []
    prompt = FrozenRuntimeInstallPrompt(
        message_box=lambda message, title, flags: calls.append(
            (message, title, flags)
        ) or 6
    )
    assert prompt.confirm() is True
    message, title, flags = calls[0]
    assert "联网" in message
    assert "Microsoft WebView2 Runtime" in message
    assert title == "GameSave Scout 需要 WebView2"
    assert flags & 0x00000004
    assert flags & 0x00000100
```

另加返回 `IDNO` 和消息框异常时返回 `False` 的测试。现有 `FrozenStartupReporter` 两项测试必须保持不变。

- [x] **步骤 2：运行确认框测试并观察失败**

```powershell
./.venv/python.exe -m pytest tests/unit/platform/windows/test_startup_reporter.py -q
```

预期：因 `FrozenRuntimeInstallPrompt` 尚未定义而失败。

- [x] **步骤 3：实现确认接口**

```python
_IDYES = 6
_INSTALL_PROMPT_FLAGS = 0x00000004 | 0x00000020 | 0x00000100 | 0x00002000


@dataclass
class FrozenRuntimeInstallPrompt:
    message_box: MessageBox = _native_message_box

    def confirm(self) -> bool:
        try:
            result = self.message_box(
                "系统未检测到 Microsoft WebView2 Runtime。\\n\\n"
                "是否现在联网安装微软官方运行时？",
                "GameSave Scout 需要 WebView2",
                _INSTALL_PROMPT_FLAGS,
            )
        except Exception:
            return False
        return result == _IDYES
```

- [x] **步骤 4：写入安装状态机测试**

```python
def test_existing_evergreen_skips_prompt_and_installer(tmp_path: Path) -> None:
    installer = EvergreenRuntimeInstaller(
        detector=lambda: "151.0.4129.86",
        prompt=lambda: pytest.fail("prompt must not run"),
        runner=lambda _command: pytest.fail("installer must not run"),
    )
    version = installer.ensure_available(_evergreen_config(tmp_path), allow_install=True)
    assert version == "151.0.4129.86"


def test_missing_evergreen_installs_and_rechecks_in_same_call(tmp_path: Path) -> None:
    config = _evergreen_config(tmp_path, payload=b"official bootstrapper")
    detected = iter((None, None, "151.0.4129.86"))
    commands: list[tuple[str, ...]] = []
    installer = EvergreenRuntimeInstaller(
        detector=lambda: next(detected),
        prompt=lambda: True,
        runner=lambda command: commands.append(tuple(command))
        or subprocess.CompletedProcess(command, 0, "", ""),
        monotonic=_monotonic(0.0, 0.1, 0.2),
        sleeper=lambda _seconds: None,
        timeout_seconds=1.0,
    )
    version = installer.ensure_available(config, allow_install=True)
    assert version == "151.0.4129.86"
    assert commands == [
        (str(config.bootstrapper_path), "/silent", "/install")
    ]
```

测试文件中的 `_evergreen_config(tmp_path, payload=b"official bootstrapper")` 必须创建真实临时文件并以其 SHA-256 构造 `ReleaseRuntimeConfig`；`_monotonic(*values)` 必须返回按参数顺序取值的可调用时钟，取尽时报测试失败。

同时覆盖：smoke 下 `allow_install=False` 不弹框不运行、用户取消抛 `WebViewInstallCancelled`、文件缺失、SHA-256 不匹配、非零退出码保留 stderr/stdout、安装后超时仍缺失、命令 `shell=False`。

- [x] **步骤 5：运行状态机测试并观察失败**

```powershell
./.venv/python.exe -m pytest tests/unit/bootstrap/test_webview_bootstrapper.py -q
```

预期：因安装状态机模块不存在而失败。

- [x] **步骤 6：实现检测、校验、执行和有限重检**

```python
@dataclass
class EvergreenRuntimeInstaller:
    detector: VersionDetector = detect_evergreen_version
    prompt: ConsentPrompt = field(
        default_factory=lambda: FrozenRuntimeInstallPrompt().confirm
    )
    runner: CommandRunner = _run_bootstrapper
    monotonic: Clock = time.monotonic
    sleeper: Sleeper = time.sleep
    timeout_seconds: float = 15.0

    def ensure_available(
        self,
        config: ReleaseRuntimeConfig,
        *,
        allow_install: bool,
    ) -> str:
        version = self.detector()
        if version is not None:
            return version
        if not allow_install:
            raise WebViewBootstrapperError(
                "系统未安装 Evergreen WebView2；smoke 不会运行安装器。"
            )
        if not self.prompt():
            raise WebViewInstallCancelled()
        _validate_bootstrapper(config)
        result = self.runner(
            (str(config.bootstrapper_path), "/silent", "/install")
        )
        _require_success(result)
        return self._wait_for_runtime()
```

`detect_evergreen_version` 必须调用 `Microsoft.Web.WebView2.Core.CoreWebView2Environment.GetAvailableBrowserVersionString()`；只有 WebView2 Runtime 未找到异常转换为 `None`，其他 CLR 异常保留为中文启动错误。重检使用 `time.monotonic()` 截止时间和短间隔 `sleep`，禁止无界等待。

- [x] **步骤 7：运行相关测试和静态检查**

```powershell
./.venv/python.exe -m pytest tests/unit/bootstrap/test_webview_bootstrapper.py tests/unit/platform/windows/test_startup_reporter.py -q
./.venv/python.exe -m ruff check src/gamesave_scout/bootstrap/webview_bootstrapper.py src/gamesave_scout/platform/windows/startup_reporter.py tests/unit/bootstrap/test_webview_bootstrapper.py tests/unit/platform/windows/test_startup_reporter.py
./.venv/python.exe -m mypy src/gamesave_scout/bootstrap/webview_bootstrapper.py src/gamesave_scout/platform/windows/startup_reporter.py
```

预期：全部通过。

---

### 任务 3：运行时模式接入应用启动与 smoke

**文件：**

- 修改：`src/gamesave_scout/bootstrap/webview_runtime.py`
- 修改：`src/gamesave_scout/bootstrap/smoke.py`
- 修改：`src/gamesave_scout/app.py`
- 修改：`tests/unit/bootstrap/test_webview_runtime.py`
- 修改：`tests/unit/bootstrap/test_smoke.py`
- 修改：`tests/unit/test_app_startup.py`
- 修改：`tests/unit/test_app_close.py`

**接口：**

- `WebViewRuntime.for_runtime(..., release_config: ReleaseRuntimeConfig | None = None, evergreen_installer: EvergreenRuntimeInstaller | None = None) -> WebViewRuntime`。
- `WebViewRuntime.ensure_available(*, allow_install: bool) -> str | None`。
- `SmokeReport` 增加 `runtime_mode: str`，JSON 键为 `runtimeMode`。
- 消费任务 1 和任务 2 的接口。

- [x] **步骤 1：扩展 WebViewRuntime 的模式测试**

```python
def test_fixed_runtime_configures_bundled_path(tmp_path: Path) -> None:
    config = ReleaseRuntimeConfig(RuntimeMode.FIXED)
    runtime = _runtime(tmp_path, config=config)
    assert runtime.ensure_available(allow_install=False) is None
    runtime.configure(webview)
    assert webview.settings["WEBVIEW2_RUNTIME_PATH"] == str(tmp_path / "runtime")


def test_evergreen_runtime_uses_system_and_never_sets_fixed_path(tmp_path: Path) -> None:
    installer = _recording_installer("151.0.4129.86")
    config = ReleaseRuntimeConfig(
        RuntimeMode.EVERGREEN,
        tmp_path / "prerequisites" / "MicrosoftEdgeWebview2Setup.exe",
        "a" * 64,
    )
    runtime = _runtime(tmp_path, config=config, installer=installer)
    assert runtime.ensure_available(allow_install=True) == "151.0.4129.86"
    runtime.configure(webview)
    assert webview.settings["WEBVIEW2_RUNTIME_PATH"] is None
```

增加：Fixed 保留 UNC/本地固定磁盘/Windows 10 ACL 测试；Evergreen 不运行 ACL；源码模式不读清单。

- [x] **步骤 2：运行 WebViewRuntime 测试并观察旧实现失败**

```powershell
./.venv/python.exe -m pytest tests/unit/bootstrap/test_webview_runtime.py -q
```

预期：新接口参数或 `ensure_available` 不存在而失败。

- [x] **步骤 3：实现模式化 WebViewRuntime**

```python
def ensure_available(self, *, allow_install: bool) -> str | None:
    if self.release_config.mode is RuntimeMode.FIXED:
        self._validate_fixed_runtime()
        return None
    if self.release_config.mode is RuntimeMode.EVERGREEN:
        return self._evergreen_installer.ensure_available(
            self.release_config,
            allow_install=allow_install,
        )
    return None
```

`prepare_windows10_permissions` 和固定路径 `configure` 只在 `FIXED` 执行；`SOURCE`、`EVERGREEN` 必须确保 `WEBVIEW2_RUNTIME_PATH` 为 `None`。

- [x] **步骤 4：先写应用取消和同进程继续测试**

```python
def test_user_cancelled_webview_install_exits_without_error_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporter = RecordingReporter()
    monkeypatch.setattr(
        WebViewRuntime,
        "ensure_available",
        lambda _self, *, allow_install: (_ for _ in ()).throw(
            WebViewInstallCancelled()
        ),
    )
    exit_code = main(["--app-root", str(tmp_path)], reporter=reporter)
    assert exit_code == 0
    assert reporter.calls == []
    assert not (tmp_path / "data" / "logs" / "startup-error.log").exists()
```

另加安装成功后 `build_application` 和 `_run_desktop` 各调用一次、smoke 传入 `allow_install=False`、真实安装失败仍调用现有 reporter 一次。

- [x] **步骤 5：扩展 SmokeReport 契约测试并观察失败**

```python
assert report.as_dict()["runtimeMode"] == "evergreen"
```

```powershell
./.venv/python.exe -m pytest tests/unit/bootstrap/test_smoke.py tests/unit/test_app_startup.py tests/unit/test_app_close.py -q
```

预期：旧报告缺少 `runtimeMode`，旧 `main` 不区分取消。

- [x] **步骤 6：接入启动顺序和取消分支**

```python
release_config = ReleaseRuntimeConfig.for_runtime(paths.app_root)
webview_runtime = WebViewRuntime.for_runtime(
    paths.app_root,
    release_config=release_config,
)
checks["webviewRuntime"] = False
webview_runtime.ensure_available(allow_install=not args.smoke_test)
checks["webviewRuntime"] = True
```

在通用 `except Exception` 之前增加 `except WebViewInstallCancelled`：关闭已创建资源并返回 0，不调用 `FrozenStartupReporter`。smoke 报告写入 `release_config.mode.value`；Evergreen 时 `webviewRuntime` 路径为 `null`。

- [x] **步骤 7：运行启动相关测试和静态检查**

```powershell
./.venv/python.exe -m pytest tests/unit/bootstrap/test_webview_runtime.py tests/unit/bootstrap/test_smoke.py tests/unit/test_app_startup.py tests/unit/test_app_close.py -q
./.venv/python.exe -m ruff check src/gamesave_scout/app.py src/gamesave_scout/bootstrap tests/unit/bootstrap tests/unit/test_app_startup.py tests/unit/test_app_close.py
./.venv/python.exe -m mypy src/gamesave_scout/app.py src/gamesave_scout/bootstrap
```

预期：全部通过。

---

### 任务 4：Bootstrapper 受控配置与双模式发布清单

**文件：**

- 修改：`scripts/release_tools.py`
- 修改：`tests/unit/scripts/test_release_tools.py`

**接口：**

- 产出：`ReleaseMode(StrEnum)`，值为 `fixed`、`evergreen`。
- 产出：`WebViewBootstrapperConfig.load(path: Path) -> WebViewBootstrapperConfig`。
- 产出：`validate_webview_bootstrapper(path: Path, config: WebViewBootstrapperConfig) -> Path`。
- 修改：`write_release_manifest(release_root, metadata, mode, bootstrapper_config=None) -> Path`。
- 清单格式固定为 2。

- [x] **步骤 1：写入 Bootstrapper 配置严格模式测试**

```python
def test_bootstrapper_config_accepts_only_controlled_schema(tmp_path: Path) -> None:
    config_file = tmp_path / "webview2-bootstrapper.json"
    config_file.write_text(
        json.dumps(
            {
                "formatVersion": 1,
                "fileName": "MicrosoftEdgeWebview2Setup.exe",
                "fileVersion": "1.3.205.0",
                "sha256": "a" * 64,
                "sourceUrl": "https://developer.microsoft.com/microsoft-edge/webview2/",
            }
        ),
        encoding="utf-8",
    )
    config = WebViewBootstrapperConfig.load(config_file)
    assert config.file_name == "MicrosoftEdgeWebview2Setup.exe"
```

另加未知字段、缺字段、非 HTTPS、文件名含目录、无效版本和摘要测试；测试值只用于单元测试，不进入真实配置。

- [x] **步骤 2：写入输入路径和哈希失败测试**

```python
def test_validate_bootstrapper_requires_absolute_matching_regular_file(
    tmp_path: Path,
) -> None:
    config = _bootstrapper_config(sha256=hashlib.sha256(b"official").hexdigest())
    installer = tmp_path / config.file_name
    installer.write_bytes(b"official")
    assert validate_webview_bootstrapper(installer, config) == installer
    with pytest.raises(ReleaseToolError, match="绝对路径"):
        validate_webview_bootstrapper(Path(config.file_name), config)
```

- [x] **步骤 3：运行配置测试并观察失败**

```powershell
./.venv/python.exe -m pytest tests/unit/scripts/test_release_tools.py -k "bootstrapper" -q
```

预期：新配置类型和验证函数未定义。

- [x] **步骤 4：实现配置和输入验证**

实现与现有 `WebViewArchiveConfig` 同等严格的字段集合、HTTPS URL、普通绝对文件、文件名和 SHA-256 检查。Authenticode 签名由任务 6 的 PowerShell 入口在清理输出前完成。

- [x] **步骤 5：写入两种布局和格式版本 2 清单测试**

```python
@pytest.mark.parametrize(
    ("mode", "release_name", "required", "forbidden"),
    [
        (ReleaseMode.FIXED, "GameShelf-0.1.0-win-x64", "runtime", "prerequisites"),
        (
            ReleaseMode.EVERGREEN,
            "GameShelf-0.1.0-win-x64-lite",
            "prerequisites",
            "runtime",
        ),
    ],
)
def test_release_layout_is_strictly_mode_specific(
    mode: ReleaseMode,
    release_name: str,
    required: str,
    forbidden: str,
    tmp_path: Path,
) -> None:
    release_root = _minimal_release_tree(tmp_path, mode)
    manifest = build_release_manifest(
        release_root,
        _release_metadata(),
        mode,
        bootstrapper_config=_bootstrapper_config(),
    )
    assert release_root.name == release_name
    assert manifest["formatVersion"] == 2
    assert manifest["runtimeMode"] == mode.value
    assert (release_root / required).exists()
    assert not (release_root / forbidden).exists()
```

完整版必须记录 `fixedRuntime: true`、Fixed 版本和 CAB SHA-256，且 Bootstrapper 字段为 `null`；轻量版必须记录 `fixedRuntime: false`、Bootstrapper 文件版本/SHA-256/签名有效标记，且 Fixed 输入字段为 `null`。

- [x] **步骤 6：运行清单测试并观察旧格式失败**

```powershell
./.venv/python.exe -m pytest tests/unit/scripts/test_release_tools.py -k "manifest or layout" -q
```

预期：旧实现仍输出格式 1 并强制要求 `runtime`。

- [x] **步骤 7：实现 `ReleaseMode`、命名和模式布局**

```python
class ReleaseMode(StrEnum):
    FIXED = "fixed"
    EVERGREEN = "evergreen"


def name_for(self, mode: ReleaseMode) -> str:
    base = f"GameShelf-{self.version}-win-x64"
    return base if mode is ReleaseMode.FIXED else f"{base}-lite"
```

更新布局校验、清单生成和清单复核，要求根目录名称、`runtimeMode`、`fixedRuntime` 和模式专属文件完全一致。继续拒绝 `data`、CAB、重解析点和意外顶层文件。

- [x] **步骤 8：运行发布工具单元测试和静态检查**

```powershell
./.venv/python.exe -m pytest tests/unit/scripts/test_release_tools.py -q
./.venv/python.exe -m ruff check scripts/release_tools.py tests/unit/scripts/test_release_tools.py
./.venv/python.exe -m mypy scripts/release_tools.py
```

预期：全部通过。

### 任务 5：双 ZIP 与六产物原子发布

**文件：**

- 修改：`scripts/release_tools.py`
- 修改：`tests/unit/scripts/test_release_tools.py`

**接口：**

- 产出：`StagedRelease(mode, directory, archive, checksum)`。
- 产出：`publish_releases(repository_root, staged_releases, versions) -> tuple[Path, ...]`。
- `staged_releases` 必须恰好包含一份 `fixed` 和一份 `evergreen`。

- [x] **步骤 1：参数化两个 ZIP 根目录测试**

```python
@pytest.mark.parametrize("mode", tuple(ReleaseMode))
def test_release_zip_has_mode_specific_single_root(
    mode: ReleaseMode,
    tmp_path: Path,
) -> None:
    release_root = _minimal_release_tree(tmp_path, mode)
    versions = ReleaseVersions("0.1.0")
    write_release_manifest(
        release_root,
        _release_metadata(),
        mode,
        bootstrapper_config=_bootstrapper_config(),
    )
    archive = tmp_path / f"{versions.name_for(mode)}.zip"
    create_release_zip(release_root, archive, versions, mode)
    verify_release_zip(archive, versions, mode)
    with zipfile.ZipFile(archive) as bundle:
        assert all(
            name.startswith(f"{versions.name_for(mode)}/")
            for name in bundle.namelist()
        )
```

- [x] **步骤 2：运行 ZIP 测试并观察旧命名失败**

```powershell
./.venv/python.exe -m pytest tests/unit/scripts/test_release_tools.py -k "release_zip" -q
```

预期：旧 ZIP 函数只接受完整版根目录。

- [x] **步骤 3：实现模式参数并保持归档安全检查**

更新 `create_release_zip`、`verify_release_zip` 和校验文件逻辑，使用 `versions.name_for(mode)`，继续要求稳定排序、单根目录、安全相对路径、无 `data`、无重复项，逐项复核清单中的大小和 SHA-256。

- [x] **步骤 4：写入六产物成功和中途失败回滚测试**

```python
def test_publish_releases_replaces_both_modes_as_one_transaction(
    tmp_path: Path,
) -> None:
    versions = ReleaseVersions("0.1.0")
    staged = tuple(_staged_release(tmp_path, versions, mode) for mode in ReleaseMode)
    published = publish_releases(tmp_path, staged, versions)
    assert len(published) == 6
    for mode in ReleaseMode:
        final = tmp_path / "dist" / versions.name_for(mode)
        verify_release_tree(final, versions, mode)


def test_publish_releases_rolls_back_all_six_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = ReleaseVersions("0.1.0")
    staged = tuple(_staged_release(tmp_path, versions, mode) for mode in ReleaseMode)
    old_markers = _write_six_old_outputs(tmp_path, versions)
    _fail_fourth_replace(monkeypatch)
    with pytest.raises(ReleaseToolError, match="simulated publish failure"):
        publish_releases(tmp_path, staged, versions)
    assert all(path.read_bytes() == payload for path, payload in old_markers.items())
    assert not list((tmp_path / "dist").glob(".*.backup-*"))
```

辅助函数签名固定为 `_write_six_old_outputs(tmp_path: Path, versions: ReleaseVersions) -> dict[Path, bytes]` 和 `_fail_fourth_replace(monkeypatch: pytest.MonkeyPatch) -> None`；前者创建六个内容互异的旧标记，后者包装真实 `os.replace` 并只在第四次调用抛 `PermissionError("simulated publish failure")`。测试必须逐项断言内容，不能只检查数量。

- [x] **步骤 5：运行原子发布测试并观察失败**

```powershell
./.venv/python.exe -m pytest tests/unit/scripts/test_release_tools.py -k "publish_releases" -q
```

预期：`StagedRelease` 和 `publish_releases` 尚未定义。

- [x] **步骤 6：实现可回滚的六产物事务**

先完整验证两个 staged bundle，再为六个最终路径分别建立受控备份；随后按稳定顺序 `os.replace`。任一步失败时，删除本轮已移动的新目标并逆序恢复全部旧备份；成功后才清理备份。目标验证必须复用现有绝对路径、仓库 `dist` 子代、精确版本名和重解析点拒绝逻辑。

- [x] **步骤 7：运行发布工具全量测试**

```powershell
./.venv/python.exe -m pytest tests/unit/scripts/test_release_tools.py -q
./.venv/python.exe -m ruff check scripts/release_tools.py tests/unit/scripts/test_release_tools.py
./.venv/python.exe -m mypy scripts/release_tools.py
```

预期：全部通过。

---

### 任务 6：单入口双包构建流水线

**文件：**

- 修改：`scripts/build_release.ps1`
- 修改：`scripts/release_tools.py`
- 修改：`tests/integration/test_release_entrypoint.py`
- 修改：`release/README.txt`
- 新增：`release/README-lite.txt`
- 修改：`THIRD_PARTY_NOTICES.md`

**接口：**

- PowerShell 新增强制参数 `-WebView2Bootstrapper <绝对路径>`。
- `verify-context` 同时接收 CAB 和 Bootstrapper，输出两个发布名与两种受控输入信息。
- `write-manifest`、`verify-release`、`build-archive` 增加必填 `--runtime-mode fixed|evergreen`。
- `publish` 一次接收两套 staged directory/archive/checksum。

- [x] **步骤 1：扩展入口最早失败测试**

```python
def test_release_entrypoint_rejects_relative_bootstrapper_before_cleanup(
    tmp_path: Path,
) -> None:
    repository = _copy_entrypoint(tmp_path)
    build_marker, dist_marker = _write_keep_markers(repository)
    result = _run_entrypoint(
        repository,
        archive=str(repository / "runtime.cab"),
        bootstrapper="relative-bootstrapper.exe",
    )
    assert result.returncode != 0
    assert "absolute path" in f"{result.stdout}\\n{result.stderr}"
    assert build_marker.read_text(encoding="utf-8") == "keep build"
    assert dist_marker.read_text(encoding="utf-8") == "keep dist"
```

同时更新 bypass 参数测试，确保不存在 `-SkipLite`、`-SkipSignature`、`-Download` 或只构建其中一版的旁路。

- [x] **步骤 2：运行入口测试并观察参数失败**

```powershell
./.venv/python.exe -m pytest tests/integration/test_release_entrypoint.py -q
```

预期：旧脚本不识别或不要求 Bootstrapper。

- [x] **步骤 3：在任何清理前校验两个路径和微软签名**

```powershell
$bootstrapperSignature = Get-AuthenticodeSignature -LiteralPath $bootstrapperPath
if ($bootstrapperSignature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "WebView2 Bootstrapper Authenticode signature is not valid."
}
if ($null -eq $bootstrapperSignature.SignerCertificate -or
    $bootstrapperSignature.SignerCertificate.Subject -notmatch '(^|, )O=Microsoft Corporation(,|$)') {
    throw "WebView2 Bootstrapper signer is not Microsoft Corporation."
}
```

CAB、内部 `msedgewebview2.exe` 和 Bootstrapper 的签名状态都必须在发布前验证；Bootstrapper 文件版本还必须等于受控配置。

- [x] **步骤 4：扩展受控 smoke 副本清理边界**

只允许删除 `build/release/smoke-copy-fixed` 和 `build/release/smoke-copy-evergreen` 两个精确绝对目录；保持父目录、重解析点和名称检查，禁止接受通配符或任意名称。

- [x] **步骤 5：实现一次核心构建、两次派生**

```powershell
$fixedReleaseName = [string]$releaseContext.fixedReleaseName
$evergreenReleaseName = [string]$releaseContext.evergreenReleaseName
$fixedDirectory = Join-Path $stagingRoot $fixedReleaseName
$evergreenDirectory = Join-Path $stagingRoot $evergreenReleaseName
Copy-Item -LiteralPath $frozenDirectory -Destination $fixedDirectory -Recurse
Copy-Item -LiteralPath $frozenDirectory -Destination $evergreenDirectory -Recurse
Copy-Item -LiteralPath $runtimeRoot -Destination (Join-Path $fixedDirectory "runtime") -Recurse
$prerequisites = Join-Path $evergreenDirectory "prerequisites"
New-Item -ItemType Directory -Path $prerequisites | Out-Null
Copy-Item -LiteralPath $bootstrapperPath -Destination (
    Join-Path $prerequisites "MicrosoftEdgeWebview2Setup.exe"
)
```

前端门禁、Python 门禁、源码 smoke 和 PyInstaller 命令在脚本中只能出现一次。完整版复制 `release/README.txt`，轻量版复制 `release/README-lite.txt`。

- [x] **步骤 6：实现两次无安装副作用的冻结 smoke**

两个 smoke 都用 `--smoke-test --json-output`。固定版要求 `runtimeMode == "fixed"` 和 Fixed 检查全真；轻量版要求 `runtimeMode == "evergreen"`、`webviewRuntime is null`、系统 Evergreen 检测和 Bootstrapper 结构检查全真。若构建机没有 Evergreen，轻量版 smoke 必须失败并提示先安装构建机运行时，不得运行随包 Bootstrapper。

- [x] **步骤 7：实现两个 README 和第三方说明**

`release/README-lite.txt` 必须明确：

- 已安装 Evergreen 时可断网启动。
- 缺失时会先询问，再联网运行微软官方安装器。
- 安装成功后 GameSave Scout 同进程继续。
- 取消不写错误堆栈；断网或安装失败写 `data/logs/startup-error.log`。
- 删除整个 GameSave Scout 目录不会卸载系统共享 Evergreen。

完整 README 明确自身包含 Fixed Runtime，并指向轻量版作为小体积选择。第三方声明记录 Bootstrapper 官方来源，不把它描述为 GameSave Scout 自有二进制。

- [x] **步骤 8：接入两套清单、ZIP、SHA-256 和一次发布**

构建脚本先分别调用 `write-manifest`、`verify-release`、`build-archive`，六项都通过后只调用一次 `publish`。任一步失败时保持 `dist` 现有两组产物不变。

- [x] **步骤 9：运行入口、发布工具和静态检查**

```powershell
./.venv/python.exe -m pytest tests/integration/test_release_entrypoint.py tests/unit/scripts/test_release_tools.py -q
./.venv/python.exe -m ruff check scripts tests/integration/test_release_entrypoint.py
./.venv/python.exe -m mypy scripts
```

预期：全部通过。

---

### 任务 7：固定真实 Bootstrapper 输入并生成两个候选包

**文件：**

- 新增：`release/webview2-bootstrapper.json`
- 验证：`dist/GameShelf-0.1.0-win-x64*`

**执行门槛：**

官方 Evergreen Bootstrapper 和 Fixed Runtime CAB 已放入仓库根目录下被 `.gitignore` 排除的 `webview安装包`。执行本任务时必须使用该目录中的真实 Microsoft 文件；若文件缺失，停止本任务并请求用户补充，禁止用测试文件、第三方镜像或虚构哈希继续。

- [x] **步骤 1：核对真实文件、签名、版本和 SHA-256**

```powershell
$bootstrapper = "D:/MyProgrammingSoftware/GameSave-Scout/webview安装包/MicrosoftEdgeWebview2Setup.exe"
Get-Item -LiteralPath $bootstrapper |
    Select-Object FullName, Length, @{Name="FileVersion";Expression={$_.VersionInfo.FileVersion}}
Get-FileHash -LiteralPath $bootstrapper -Algorithm SHA256
Get-AuthenticodeSignature -LiteralPath $bootstrapper |
    Select-Object Status, @{Name="Signer";Expression={$_.SignerCertificate.Subject}}
```

预期：普通文件、非零长度、有效文件版本、SHA-256 为 64 位十六进制、签名状态 `Valid`、签名者组织为 Microsoft Corporation。若用户提供了其他绝对路径，只替换第一行路径，不改变发布文件名。

- [x] **步骤 2：用刚核对的真实值写入受控配置**

使用 `apply_patch` 新建 `release/webview2-bootstrapper.json`，字段严格为 `formatVersion`、`fileName`、`fileVersion`、`sha256`、`sourceUrl`；前四项分别写入整数 1、固定文件名、步骤 1 的真实文件版本、步骤 1 的真实小写 SHA-256，`sourceUrl` 写入 `https://developer.microsoft.com/en-us/microsoft-edge/webview2/#download-section`。禁止在文件中落入示例值或描述性占位文本。写入后立即调用 `WebViewBootstrapperConfig.load` 和 `validate_webview_bootstrapper` 复核。

- [x] **步骤 3：运行完整自动质量门**

```powershell
$repo = "D:/MyProgrammingSoftware/GameSave-Scout"
$env:PATH = "$repo/.venv;$repo/.venv/Scripts;$env:PATH"
./.venv/python.exe -m pytest -q
./.venv/python.exe -m ruff check src tests scripts
./.venv/python.exe -m mypy src scripts
./.venv/npm.cmd --prefix frontend run test:unit -- --run
./.venv/npm.cmd --prefix frontend run type-check
./.venv/npm.cmd --prefix frontend run build
```

预期：所有测试和静态检查通过；记录准确测试数量。

- [x] **步骤 4：运行唯一正式构建入口**

```powershell
./scripts/build_release.ps1 `
  -WebView2Archive "D:/MyProgrammingSoftware/GameSave-Scout/webview安装包/Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab" `
  -WebView2Bootstrapper "D:/MyProgrammingSoftware/GameSave-Scout/webview安装包/MicrosoftEdgeWebview2Setup.exe"
```

预期：生成两组目录、ZIP、SHA-256，共六项；完整流程内部再次运行全部门禁，不使用跳过参数。

- [x] **步骤 5：独立验证两个发布树和归档**

```powershell
./.venv/python.exe -c "from pathlib import Path; from scripts.release_tools import ReleaseMode, ReleaseVersions, verify_release_tree, verify_release_zip, verify_zip_sha256; root=Path(r'D:/MyProgrammingSoftware/GameSave-Scout'); versions=ReleaseVersions.load(root); [(verify_release_tree(root/'dist'/versions.name_for(mode), versions, mode), verify_release_zip(root/'dist'/f'{versions.name_for(mode)}.zip', versions, mode), verify_zip_sha256(root/'dist'/f'{versions.name_for(mode)}.zip', root/'dist'/f'{versions.name_for(mode)}.zip.sha256')) for mode in ReleaseMode]; print('dual-release=OK')"
```

另用 PowerShell 确认两个正式目录都没有 `data`、CAB、`.py`、`.pyc` 或 `__pycache__`；完整版有 `runtime` 且无 `prerequisites`，轻量版相反。

- [x] **步骤 6：验证体积和签名**

```powershell
$fixed = Get-ChildItem -LiteralPath "dist/GameShelf-0.1.0-win-x64" -Recurse -File
$lite = Get-ChildItem -LiteralPath "dist/GameShelf-0.1.0-win-x64-lite" -Recurse -File
[pscustomobject]@{
    FixedMiB = [math]::Round(($fixed | Measure-Object Length -Sum).Sum / 1MB, 2)
    LiteMiB = [math]::Round(($lite | Measure-Object Length -Sum).Sum / 1MB, 2)
}
Get-AuthenticodeSignature -LiteralPath "dist/GameShelf-0.1.0-win-x64-lite/prerequisites/MicrosoftEdgeWebview2Setup.exe"
```

预期：轻量版小于 100 MiB；Bootstrapper 签名仍为 `Valid`；GameSave Scout 本体仍按 V0.1 设计未签名。

- [x] **步骤 7：在发布副本中做真实窗口验证**

分别把两个正式目录复制到 `build/release` 下不同验证副本。完整版执行冻结 JSON smoke、启动窗口至少 8 秒并正常关闭；轻量版在本机已有 Evergreen 的条件下执行相同步骤，并确认未启动 Bootstrapper、退出码为 0、没有 `startup-error.log`。不得直接运行正式 `dist` 目录以免生成 `data`。

---

### 任务 8：完成状态文档与交付检查

**文件：**

- 修改：`docs/superpowers/plans/2026-08-12-GameSave-Scout-07-便携版打包与发布.md`
- 修改：`docs/superpowers/plans/2026-08-12-GameSave-Scout-开发路线图.md`

**接口：**

- 不新增长期设计文档。
- 只把已经观察到的实现和验证事实写入固定文档。

- [x] **步骤 1：更新当前状态和变更记录**

模块 07 文档记录实际生成的两个目录/ZIP 大小、真实 Bootstrapper 版本/SHA-256、自动测试数量、本机 fixed/evergreen smoke 和窗口结果。路线图把下一项改为四种干净 Windows 10/11 场景，不得提前标记虚拟机验收完成。

- [x] **步骤 2：运行文档与工作树自检**

```powershell
git diff --check
git status --short
Select-String -LiteralPath `
  "docs/superpowers/plans/2026-08-12-GameSave-Scout-07-便携版打包与发布.md", `
  "docs/superpowers/plans/2026-08-12-GameSave-Scout-开发路线图.md" `
  -Pattern @(("T" + "BD"), ("TO" + "DO"))
```

预期：`git diff --check` 无错误；固定文档没有未解决占位符；历史变更记录中的旧格式事实保留日期语境，不被误写为当前要求。

- [x] **步骤 3：最终回归证据**

```powershell
./.venv/python.exe -m pytest -q
./.venv/python.exe -m ruff check src tests scripts
./.venv/python.exe -m mypy src scripts
./.venv/npm.cmd --prefix frontend run test:unit -- --run
./.venv/npm.cmd --prefix frontend run type-check
./.venv/npm.cmd --prefix frontend run build
```

预期：全部通过。最终报告列出六个产物、两个 ZIP SHA-256、两种解压体积、GameSave Scout/Bootstrapper/Fixed Runtime 签名状态，并明确 Windows Sandbox 四场景仍需用户复验。

- [x] **步骤 4：停止在未授权的 Git 边界之前**

不执行 `git add`、`git commit`、`git push`、分支创建或 worktree 操作。向用户报告工作区修改和验证证据，由用户另行决定提交方式。

---

---

## 执行检查点

1. 任务 1～3 完成后：源码启动层具备双运行时状态机，运行针对性测试和一次源码 smoke。
2. 任务 4～6 完成后：发布工具和构建入口具备双包能力，运行发布工具/入口全量测试。
3. 任务 7 完成后：必须已有真实微软 Bootstrapper 输入，生成并验证六个候选产物。
4. 任务 8 完成后：固定文档只记录已证实事实，停止在 Git 提交边界前。
