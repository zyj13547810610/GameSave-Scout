# GameShelf 便携打包与发布实施计划

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 产出可复现的 Windows 10/11 x64 PyInstaller onedir 安装包；完整版本内含固定版 WebView2 运行时，并确保应用自身的持久化写入都位于 `data` 下。

**架构：** 构建脚本生成 Vue 生产包、暂存 Python 资源、运行经过审核的 PyInstaller spec，然后加入从官方获取的固定版 WebView2 运行时。启动时明确选择暂存运行时和便携用户数据目录；自动化及干净虚拟机检查验证启动、迁移、目录复制、Unicode 路径和缺少预装依赖的情况。

**技术栈：** 现有完整应用、Vite、Node.js 24 LTS、Python 3.12、pywebview 6.2.x、PyInstaller 6.21.x、固定版 Microsoft Edge WebView2 Runtime x64、PowerShell。

## 全局约束

- 构建 x64 `onedir`；绝不构建 `onefile`。
- 完整便携包必须能够在受支持的 Windows 10/11 系统上启动，无需预装 WebView2 运行时。
- 固定版 WebView2 超过 250 MiB；不得将其二进制文件提交到 Git。
- 固定版 WebView2 无法从 UNC/网络路径运行；必须检测这种情况，并使用已安装的 Evergreen 运行时或显示可操作的错误。
- 在 Windows 10 上使用 Fixed Version 120+ 时，按照 Microsoft 文档确保运行时文件夹向 `ALL APPLICATION PACKAGES` 和 `ALL RESTRICTED APPLICATION PACKAGES` 授予读取/执行权限。
- WebView 状态写入 `data/webview`；数据库、封面、清单、备份、日志和临时文件都位于 `data` 下。
- 构建/发布脚本只有在解析并确认精确路径位于仓库下之后，才可替换 `dist/GameShelf`。
- 未经用户明确批准，不得公开发布、创建 release 或选择项目许可证。
- 本地产物中包含所有必需的第三方许可证/声明。
- 遵循 TDD，并在每个任务完成后提交。

---

### 任务 1：让资源定位同时支持源码与冻结模式

**文件：**
- 新建：`src/gameshelf/bootstrap/resources.py`
- 新建：`tests/unit/bootstrap/test_resources.py`
- 修改：`src/gameshelf/bootstrap/application.py`
- 修改：`src/gameshelf/app.py`

**接口：**
- 产出：`ResourcePaths.for_runtime(app_paths: AppPaths) -> ResourcePaths`。
- 字段：`ui_dir`、`engine_rules`、`bundled_ludusavi_dir` 和 `runtime_dir`。
- 冻结模式下，内置资源位于 `sys._MEIPASS/resources`；固定运行时仍位于 `GameShelf.exe` 旁的 `runtime/` 下。

- [ ] **步骤 1：编写会失败的源码/冻结资源测试**

```python
def test_source_resources_use_repository_resources(tmp_path, monkeypatch) -> None:
    module = tmp_path / "repo" / "src" / "gameshelf" / "bootstrap" / "resources.py"
    paths = resource_paths(frozen=False, module_file=module, executable=tmp_path / "python.exe")
    assert paths.ui_dir == tmp_path / "repo" / "resources" / "ui"


def test_frozen_resources_split_meipass_and_external_runtime(tmp_path) -> None:
    exe = tmp_path / "GameShelf" / "GameShelf.exe"
    meipass = tmp_path / "GameShelf" / "_internal"
    paths = resource_paths(frozen=True, executable=exe, meipass=meipass)
    assert paths.ui_dir == meipass / "resources" / "ui"
    assert paths.runtime_dir == exe.parent / "runtime"
```

- [ ] **步骤 2：运行资源测试并确认失败**

运行：`python -m pytest tests/unit/bootstrap/test_resources.py -v`

预期：失败，因为资源解析尚不存在。

- [ ] **步骤 3：实现明确的源码/冻结资源解析**

绝不使用当前工作目录。冻结模式下，不可变内置资源使用 `sys._MEIPASS`，应用根目录/运行时/data 使用 `Path(sys.executable).parent`。源码模式下根据 `resources.py` 推导仓库根目录。引导时验证 UI/规则/清单是否存在；缺失时抛出本地化 `MissingResourceError`，列出缺少的逻辑资源，而不是 traceback。

- [ ] **步骤 4：运行引导/资源测试**

运行：`python -m pytest tests/unit/bootstrap tests/integration/test_application_bootstrap.py -v`

预期：全部通过。

- [ ] **步骤 5：提交冻结资源解析**

```powershell
git add src/gameshelf/bootstrap src/gameshelf/app.py tests/unit/bootstrap
git commit -m "feat: resolve packaged GameShelf resources"
```

### 任务 2：自动化前端与 Python 构建暂存

**文件：**
- 新建：`scripts/build_ui.ps1`
- 新建：`scripts/verify_build_inputs.py`
- 新建：`tests/unit/scripts/test_verify_build_inputs.py`
- 修改：`.gitignore`
- 修改：`README.md`

**接口：**
- `scripts/build_ui.ps1` 运行锁定版本的 npm 安装/检查/构建，只替换 `resources/ui`。
- `verify_build_inputs.py` 检查 Python/Node 架构与版本、UI、规则、内置清单、软件包锁文件及干净的必需路径。

- [ ] **步骤 1：编写会失败的输入校验器测试**

```python
def test_verifier_rejects_missing_ui_and_wrong_architecture(tmp_path) -> None:
    result = verify_inputs(repo=tmp_path, python_bits=32, node_major=24)
    assert "Python must be 64-bit" in result.errors
    assert "resources/ui/index.html is missing" in result.errors


def test_verifier_accepts_complete_locked_inputs(complete_build_repo) -> None:
    result = verify_inputs(repo=complete_build_repo, python_bits=64, node_major=24)
    assert result.errors == ()
```

- [ ] **步骤 2：运行校验器测试并确认失败**

运行：`python -m pytest tests/unit/scripts/test_verify_build_inputs.py -v`

预期：失败，因为脚本/校验器尚不存在。

- [ ] **步骤 3：实现安全 UI 替换与精确构建检查**

`build_ui.ps1` 必须根据 `$PSScriptRoot` 解析仓库根目录，断言目标等于 `<repo>\resources\ui`，并运行：

```powershell
npm --prefix "$repo\frontend" ci
npm --prefix "$repo\frontend" run test:unit -- --run
npm --prefix "$repo\frontend" run type-check
npm --prefix "$repo\frontend" run build
```

然后只删除已验证的 `resources/ui` 目录，并将 `frontend/dist` 复制到其中。校验器要求 Python `3.12`、64 位解释器、Node 主版本 `24`、`frontend/package-lock.json`、`pyproject.toml` 及所有不可变资源输入。

- [ ] **步骤 4：运行暂存与输入校验**

运行：

```powershell
.\scripts\build_ui.ps1
python scripts\verify_build_inputs.py
python -m pytest tests/unit/scripts/test_verify_build_inputs.py -v
```

预期：所有命令均以 `0` 退出。

- [ ] **步骤 5：提交构建暂存功能**

```powershell
git add scripts tests/unit/scripts .gitignore README.md resources/ui
git commit -m "build: automate locked UI staging"
```

### 任务 3：定义并测试 PyInstaller Onedir 构建

**文件：**
- 修改：`pyproject.toml`
- 新建：`packaging/GameShelf.spec`
- 新建：`packaging/version_info.txt`
- 新建：`scripts/build_portable.ps1`
- 新建：`tests/integration/packaging/test_frozen_smoke.py`
- 修改：`.gitignore`

**接口：**
- 产出：`dist/GameShelf/GameShelf.exe` 及 `_internal`，不内嵌可写 `data`。
- `GameShelf.exe --smoke-test --json` 输出 JSON，包含应用版本、架构版本、应用根目录、data 目录、冻结状态、运行时选择及成功状态。
- 构建脚本接受 `-SkipRuntime`，但只用于较小的开发产物。

- [ ] **步骤 1：编写会失败的冻结产物冒烟测试**

```python
@pytest.mark.skipif(sys.platform != "win32", reason="Windows packaging")
def test_frozen_smoke_uses_executable_adjacent_data(built_app: Path, tmp_path: Path) -> None:
    copied = tmp_path / "复制后的 GameShelf"
    shutil.copytree(built_app, copied)
    result = subprocess.run(
        [copied / "GameShelf.exe", "--smoke-test", "--json"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    payload = json.loads(result.stdout)
    assert payload["frozen"] is True
    assert Path(payload["dataDir"]) == copied / "data"
    assert (copied / "data" / "library.db").exists()
```

- [ ] **步骤 2：添加 PyInstaller 并运行测试以确认产物缺失**

将 `PyInstaller>=6.21,<7` 添加到开发依赖，重新安装，然后运行：

```powershell
python -m pytest tests/integration/packaging/test_frozen_smoke.py -v
```

预期：因为不存在打包产物，测试失败或跳过夹具设置。

- [ ] **步骤 3：实现 spec 与带保护的构建脚本**

spec 必须使用 `console=False`、单个 EXE、`COLLECT` onedir、图标/版本元数据、通过 PyInstaller hook 收集的 pywebview 隐藏导入，以及以下不可变数据树：

```python
datas = [
    (str(repo / "resources" / "ui"), "resources/ui"),
    (str(repo / "resources" / "rules"), "resources/rules"),
    (str(repo / "resources" / "manifests"), "resources/manifests"),
]
```

不要包含源码/开发用 `data` 目录。`build_portable.ps1` 在删除构建输出前解析并验证 `<repo>\build` 和 `<repo>\dist\GameShelf`，然后运行 UI 暂存/输入校验/后端测试，之后：

```powershell
python -m PyInstaller --noconfirm --clean packaging\GameShelf.spec
```

添加不打开 pywebview 的 JSON 冒烟模式。

- [ ] **步骤 4：构建开发用 onedir 并运行冻结冒烟测试**

运行：

```powershell
.\scripts\build_portable.ps1 -SkipRuntime
python -m pytest tests/integration/packaging/test_frozen_smoke.py -v --built-app dist\GameShelf
```

预期：安装包构建成功，复制到 Unicode 路径后的冒烟测试通过。

- [ ] **步骤 5：提交 onedir 打包功能**

```powershell
git add pyproject.toml packaging scripts/build_portable.ps1 src/gameshelf/app.py tests/integration/packaging .gitignore
git commit -m "build: package GameShelf as Windows onedir"
```

### 任务 4：暂存并选择固定版 WebView2 运行时

**文件：**
- 新建：`scripts/stage_webview2_runtime.ps1`
- 新建：`packaging/runtime/README.md`
- 新建：`src/gameshelf/bootstrap/webview2.py`
- 新建：`tests/unit/bootstrap/test_webview2.py`
- 修改：`src/gameshelf/app.py`
- 修改：`scripts/build_portable.ps1`
- 修改：`.gitignore`

**接口：**
- 暂存脚本接受必需参数 `-ArchivePath`、`-Version` 和 `-SourceUrl`；产出 `packaging/runtime/staged/` 和 `runtime-manifest.json`。
- 产出：`select_webview2_runtime(resources, platform) -> RuntimeSelection`。
- 产出：`ensure_windows10_runtime_acl(runtime_dir) -> AclResult`。
- 完整构建将暂存运行时复制到 `dist/GameShelf/runtime`。

- [ ] **步骤 1：编写会失败的运行时选择、UNC 与 ACL 命令测试**

```python
def test_local_fixed_runtime_is_selected_when_manifest_and_exe_exist(tmp_path) -> None:
    runtime = make_fixed_runtime(tmp_path, version="150.0.1.0")
    selection = select_webview2_runtime(runtime, windows_version="10")
    assert selection.mode == "fixed"
    assert selection.browser_executable_folder == runtime


def test_unc_app_path_does_not_select_fixed_runtime(tmp_path) -> None:
    selection = select_webview2_runtime(
        Path(r"\\server\share\GameShelf\runtime"), windows_version="10"
    )
    assert selection.mode == "evergreen_required"
    assert selection.reason == "fixed_runtime_unsupported_on_unc"


def test_windows10_acl_uses_well_known_sids(fake_command_runner, runtime_dir) -> None:
    ensure_windows10_runtime_acl(runtime_dir, fake_command_runner)
    assert fake_command_runner.commands == [
        ("icacls", str(runtime_dir), "/grant", "*S-1-15-2-2:(OI)(CI)(RX)"),
        ("icacls", str(runtime_dir), "/grant", "*S-1-15-2-1:(OI)(CI)(RX)"),
    ]
```

- [ ] **步骤 2：运行运行时测试并确认失败**

运行：`python -m pytest tests/unit/bootstrap/test_webview2.py -v`

预期：失败，因为运行时选择/暂存尚不存在。

- [ ] **步骤 3：实现官方归档暂存、清单校验、ACL 与 pywebview 选择**

PowerShell 暂存脚本必须：

1. 要求维护者提供本地官方 x64 Fixed Version `.cab`/归档；
2. 解析输入/输出路径，并验证输出仍位于 `packaging/runtime/staged`；
3. 使用 Windows `expand.exe` 或文档规定的归档格式展开；
4. 在解压根目录下查找 `msedgewebview2.exe`；
5. 写入清单字段 `version`、`architecture: x64`、`archiveSha256`、`sourceUrl` 和 `stagedAt`；
6. 绝不下载或执行运行时。

启动时校验清单/版本/可执行文件，并配置：

```python
webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(selection.browser_executable_folder)
```

在 Windows 10 上，使用命令参数数组、隐藏窗口、30 秒超时且不使用 shell，应用文档规定的两个 SID 授权。ACL 设置失败时尝试使用有效的已安装 Evergreen 运行时；否则显示可操作的启动错误。Windows 11 无需调用 ACL。绝不从 UNC 路径运行固定版运行时。

- [ ] **步骤 4：暂存官方运行时并构建完整产物**

从 Microsoft 官方 WebView2 下载页面下载当前 x64 Fixed Version 软件包后运行：

```powershell
.\scripts\stage_webview2_runtime.ps1 `
  -ArchivePath 'C:\Downloads\Microsoft.WebView2.FixedVersionRuntime.150.0.4078.44.x64.cab' `
  -Version '150.0.4078.44' `
  -SourceUrl 'https://developer.microsoft.com/microsoft-edge/webview2/'
.\scripts\build_portable.ps1
```

预期：版本参数与解压出的运行时不匹配时暂存失败；完整构建包含 `dist/GameShelf/runtime/msedgewebview2.exe` 和匹配的清单。本计划编写时，版本 `150.0.4078.44` 是当前稳定 Release-SDK 运行时基线。如果执行前 Microsoft 已替换可下载的 Fixed Version，则在两个参数中使用精确的新稳定版本，并让生成的清单记录它；不要将版本写入应用源代码。

- [ ] **步骤 5：提交运行时工具，但不提交运行时二进制文件**

```powershell
git add scripts/stage_webview2_runtime.ps1 packaging/runtime/README.md src/gameshelf/bootstrap/webview2.py src/gameshelf/app.py scripts/build_portable.ps1 tests/unit/bootstrap/test_webview2.py .gitignore
git commit -m "build: support bundled fixed WebView2 runtime"
```

### 任务 5：审计便携写入与数据库复制一致性

**文件：**
- 新建：`src/gameshelf/bootstrap/portable_audit.py`
- 新建：`scripts/test_portable_copy.ps1`
- 新建：`tests/integration/packaging/test_portable_writes.py`
- 新建：`tests/integration/packaging/test_database_copy.py`

**接口：**
- `GameShelf.exe --portable-audit --json` 初始化应用服务，创建有代表性的受管理文件，对 SQLite 执行 checkpoint，报告结果，清理测试记录，并在不打开 GUI 的情况下退出。
- 复制脚本只针对 `dist/GameShelf` 的临时副本运行，并验证报告的所有应用自有路径均位于复制后的 `data` 下。

- [ ] **步骤 1：编写会失败的便携审计测试**

```python
def test_audit_rejects_owned_path_outside_data(tmp_path) -> None:
    data = tmp_path / "GameShelf" / "data"
    report = audit_owned_paths(data, [data / "library.db", tmp_path / "AppData" / "state"])
    assert report.ok is False
    assert report.violations == (tmp_path / "AppData" / "state",)


def test_checkpointed_database_copy_opens_without_wal(tmp_path, migrated_database) -> None:
    checkpoint_and_close(migrated_database)
    copied = tmp_path / "copy.db"
    shutil.copy2(migrated_database, copied)
    with sqlite3.connect(copied) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
```

- [ ] **步骤 2：运行审计/复制测试并确认失败**

运行：`python -m pytest tests/integration/packaging/test_portable_writes.py tests/integration/packaging/test_database_copy.py -v`

预期：失败，因为审计/checkpoint 辅助功能尚不存在。

- [ ] **步骤 3：实现应用自有路径注册表与安全复制测试**

集中登记应用自有路径类别：数据库/WAL/SHM、配置、封面、清单、WebView、备份、日志和临时文件。审计报告解析后的路径，并拒绝任何位于 data 之外的路径。不得声称审计 GameShelf 不拥有的操作系统日志/运行时缓存。

`test_portable_copy.ps1` 创建唯一临时目录，复制完整 onedir，运行冒烟测试和审计，关闭后再次复制到第二个带 Unicode/空格的本地路径，重新运行冒烟测试，并断言数据库架构/封面夹具仍然存在。它在 `finally` 中只删除自己解析后的临时目录。

- [ ] **步骤 4：运行源码与打包产物的便携复制测试**

运行：

```powershell
python -m pytest tests/integration/packaging/test_portable_writes.py tests/integration/packaging/test_database_copy.py -v
.\scripts\test_portable_copy.ps1 -BuiltApp .\dist\GameShelf
```

预期：全部通过；第二次复制的应用仍保留审计夹具和架构。

- [ ] **步骤 5：提交便携性审计**

```powershell
git add src/gameshelf/bootstrap/portable_audit.py scripts/test_portable_copy.ps1 tests/integration/packaging
git commit -m "test: audit portable data and directory copies"
```

### 任务 6：添加第三方声明、发布元数据与干净虚拟机检查清单

**文件：**
- 修改：`THIRD_PARTY_NOTICES.md`
- 新建：`packaging/release-manifest.json`
- 新建：`docs/release/windows-clean-vm-checklist.md`
- 新建：`scripts/create_release_archive.ps1`
- 新建：`scripts/write_release_manifest.py`
- 新建：`tests/unit/scripts/test_release_manifest.py`
- 修改：`README.md`

**接口：**
- 内嵌发布清单记录应用版本、架构版本、引擎规则版本、Ludusavi SHA-256/源提交、WebView2 版本/哈希、Python/Node 版本和构建时间。同目录 `.sha256` 文件及外部发布记录存储最终 ZIP 哈希。
- 归档脚本产出 `artifacts/GameShelf-<version>-windows-x64-portable.zip`，但绝不上传。

- [ ] **步骤 1：编写会失败的发布清单完整性测试**

```python
def test_release_manifest_contains_reproducibility_fields(release_manifest) -> None:
    required = {
        "appVersion", "schemaVersion", "engineRulesVersion", "ludusaviSha256",
        "ludusaviCommit", "webview2Version", "webview2ArchiveSha256",
        "pythonVersion", "nodeVersion", "builtAt",
    }
    assert required <= release_manifest.keys()


def test_external_release_record_contains_final_archive_hash(release_record) -> None:
    assert len(release_record["artifactSha256"]) == 64
```

- [ ] **步骤 2：运行清单测试并确认失败**

运行：`python -m pytest tests/unit/scripts/test_release_manifest.py -v`

预期：失败，因为发布元数据不完整或不存在。

- [ ] **步骤 3：实现声明、本地归档创建与手动干净虚拟机流程**

`THIRD_PARTY_NOTICES.md` 必须列出直接运行时/构建依赖及其许可证，包括 pywebview BSD-3-Clause、Vue/Pinia/Vite MIT、Pillow HPND、watchdog Apache-2.0、psutil BSD-3-Clause、pefile MIT、PyYAML MIT、RapidFuzz MIT、Ludusavi manifest MIT、PyInstaller GPL exception，以及 Microsoft WebView2 再分发条款/链接。再分发要求附带许可证正文时，复制上游许可证文本。

干净虚拟机检查清单必须验证：

```text
Windows 10 x64 with no installed Evergreen WebView2 -> complete package starts
Windows 11 x64 -> complete package starts
standard non-admin user -> starts and writes data only beside app
Chinese/Japanese/spaced local path -> starts
copied complete directory -> retains database/covers/settings
root drive offline -> cached library remains and root error is scoped
UNC path -> fixed runtime is not selected; actionable fallback/error appears
first migration + interrupted/invalid migration recovery -> old DB preserved
```

`write_release_manifest.py` 收集依赖/运行时/规则/源字段，将省略 `artifactSha256` 的 `packaging/release-manifest.json` 写入暂存应用；归档脚本随后创建 ZIP，并写入同目录的 `artifacts/GameShelf-<version>-windows-x64-portable.zip.sha256`，以及包含归档哈希的外部发布记录。这样避免了将 ZIP 最终哈希嵌入同一 ZIP 的不可能自引用要求。脚本检查干净的 Git 工作树，运行全部自动化门禁，对测试数据库执行 checkpoint，创建 ZIP、计算哈希并验证内容。它不打标签、不推送、不上传，也不创建 GitHub release。

- [ ] **步骤 4：运行发布检查并创建本地候选归档**

运行：

```powershell
python -m pytest tests/unit/scripts/test_release_manifest.py -v
.\scripts\create_release_archive.ps1 -BuiltApp .\dist\GameShelf -Version '0.1.0'
```

预期：在 `artifacts` 下创建本地 ZIP 和 SHA-256；不上传任何内容。

- [ ] **步骤 5：提交发布文档/工具**

```powershell
git add THIRD_PARTY_NOTICES.md packaging/release-manifest.json docs/release scripts/create_release_archive.ps1 scripts/write_release_manifest.py tests/unit/scripts README.md
git commit -m "build: prepare verified portable release artifacts"
```

### 任务 7：在宣告 V1 完成前运行最终验证

**文件：**
- 只修改为修复验证过程中发现的失败所必需的文件。
- 记录：`docs/release/v0.1.0-verification.md`

**接口：**
- 产出：包含命令、时间戳、退出状态和干净虚拟机检查结果的证据记录。
- 不发布产物。

- [ ] **步骤 1：从干净工作树运行每个自动化后端/前端/构建门禁**

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend ci
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
.\scripts\build_portable.ps1
.\scripts\test_portable_copy.ps1 -BuiltApp .\dist\GameShelf
```

预期：每条命令均以 `0` 退出。任何命令失败时，先诊断并修复再继续；不得写入成功记录。

- [ ] **步骤 2：在 Windows 10 和 Windows 11 上执行干净虚拟机检查清单**

使用全新的 x64 虚拟机和标准用户。记录操作系统构建号、测试前是否存在 Evergreen、软件包哈希、选中的运行时及每个检查项结果。不得用开发机器代替无运行时的 Windows 10 用例。

- [ ] **步骤 3：运行有代表性的手动验收场景**

使用合成/免费测试夹具，不得再分发商业资源：

```text
multiple roots with nested game c
unknown-engine EXE launch
formal and experimental engine evidence
local and pasted cover
multiple manual/static save locations
real guided save-writer session
Ren'Py/Unity orphan fixtures
copy complete app directory and reopen
```

预期：所有已确认的 V1 验收条件均得到验证。

- [ ] **步骤 4：编写并验证证据记录**

记录必须列出精确提交、依赖锁文件哈希、产物哈希、命令/结果、虚拟机结果、已知限制（包括固定运行时大小和 UNC 行为），并明确说明不包含存档备份/恢复和翻译功能。

- [ ] **步骤 5：仅在全部门禁通过后提交验证证据**

```powershell
git add docs/release/v0.1.0-verification.md
git commit -m "docs: record GameShelf v0.1.0 verification"
```

## 便携发布验收门禁

- 完整 onedir 可在干净的 Windows 10/11 x64 上启动，无需安装 WebView2。
- Windows 10 固定运行时 ACL 要求得到处理，无需让用户长期以管理员身份运行 GameShelf。
- 复制已关闭的应用目录后，数据库、封面、清单、设置和 WebView 状态均保留。
- 应用自有持久化路径审计均位于 `data` 下；明确不支持在应用运行期间复制。
- 产物包含已校验 UI、规则、Ludusavi 元数据/许可证、运行时清单和第三方声明。
- UNC 情况会被检测并解释，而不是出现原因不明的空白窗口。
- 创建本地归档不会发布、打标签、推送或选择项目许可证。
- 只有自动化门禁和两份干净虚拟机记录都通过后，才能宣告完成。
