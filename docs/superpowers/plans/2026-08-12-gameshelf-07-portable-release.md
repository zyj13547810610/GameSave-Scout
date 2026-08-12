# GameShelf Portable Packaging and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible Windows 10/11 x64 PyInstaller onedir package whose complete variant includes a fixed WebView2 runtime and whose application-owned persistent writes remain under `data`.

**Architecture:** A build script creates the Vue production bundle, stages Python resources, runs a reviewed PyInstaller spec, then appends an officially downloaded fixed WebView2 runtime. Startup explicitly selects the staged runtime and portable user-data directory; automated and clean-VM checks validate startup, migration, copying, Unicode paths, and dependency absence.

**Tech Stack:** Existing full application, Vite, Node.js 24 LTS, Python 3.12, pywebview 6.2.x, PyInstaller 6.21.x, fixed Microsoft Edge WebView2 Runtime x64, PowerShell.

## Global Constraints

- Build x64 `onedir`; never build `onefile`.
- The complete portable package must start on supported Windows 10/11 systems without requiring a preinstalled WebView2 runtime.
- Fixed WebView2 is over 250 MiB; do not commit its binaries to Git.
- Fixed WebView2 cannot run from UNC/network paths; detect that case and use an installed Evergreen runtime or show an actionable error.
- On Windows 10 with Fixed Version 120+, ensure the runtime folder grants read/execute to `ALL APPLICATION PACKAGES` and `ALL RESTRICTED APPLICATION PACKAGES` as Microsoft documents.
- Route webview state to `data/webview`; DB, covers, manifests, backups, logs, and temp stay below `data`.
- Build/release scripts may replace `dist/GameShelf` only after resolving and verifying that exact path beneath the repository.
- Do not publish, create a release, or choose the project license without explicit user approval.
- Include all required third-party licenses/notices in the local artifact.
- Follow TDD and commit after every task.

---

### Task 1: Make Resource Location Work in Source and Frozen Modes

**Files:**
- Create: `src/gameshelf/bootstrap/resources.py`
- Create: `tests/unit/bootstrap/test_resources.py`
- Modify: `src/gameshelf/bootstrap/application.py`
- Modify: `src/gameshelf/app.py`

**Interfaces:**
- Produces: `ResourcePaths.for_runtime(app_paths: AppPaths) -> ResourcePaths`.
- Fields: `ui_dir`, `engine_rules`, `bundled_ludusavi_dir`, and `runtime_dir`.
- In frozen mode bundled resources live under `sys._MEIPASS/resources`; fixed runtime remains beside `GameShelf.exe` under `runtime/`.

- [ ] **Step 1: Write failing source/frozen resource tests**

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

- [ ] **Step 2: Run resource tests and verify failure**

Run: `python -m pytest tests/unit/bootstrap/test_resources.py -v`

Expected: FAIL because resource resolution is absent.

- [ ] **Step 3: Implement explicit source/frozen resource resolution**

Never use the current working directory. In frozen mode require `sys._MEIPASS` for immutable bundled resources and `Path(sys.executable).parent` for app root/runtime/data. In source mode derive repository root from `resources.py`. Validate UI/rules/manifest presence during bootstrap and raise a localized `MissingResourceError` listing the missing logical resource, not a traceback.

- [ ] **Step 4: Run bootstrap/resource tests**

Run: `python -m pytest tests/unit/bootstrap tests/integration/test_application_bootstrap.py -v`

Expected: all pass.

- [ ] **Step 5: Commit frozen resource resolution**

```powershell
git add src/gameshelf/bootstrap src/gameshelf/app.py tests/unit/bootstrap
git commit -m "feat: resolve packaged GameShelf resources"
```

### Task 2: Automate Frontend and Python Build Staging

**Files:**
- Create: `scripts/build_ui.ps1`
- Create: `scripts/verify_build_inputs.py`
- Create: `tests/unit/scripts/test_verify_build_inputs.py`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- `scripts/build_ui.ps1` runs locked npm install/check/build and replaces only `resources/ui`.
- `verify_build_inputs.py` checks Python/Node architecture/version, UI, rules, bundled manifest, package locks, and clean required paths.

- [ ] **Step 1: Write failing input-verifier tests**

```python
def test_verifier_rejects_missing_ui_and_wrong_architecture(tmp_path) -> None:
    result = verify_inputs(repo=tmp_path, python_bits=32, node_major=24)
    assert "Python must be 64-bit" in result.errors
    assert "resources/ui/index.html is missing" in result.errors


def test_verifier_accepts_complete_locked_inputs(complete_build_repo) -> None:
    result = verify_inputs(repo=complete_build_repo, python_bits=64, node_major=24)
    assert result.errors == ()
```

- [ ] **Step 2: Run verifier tests and verify failure**

Run: `python -m pytest tests/unit/scripts/test_verify_build_inputs.py -v`

Expected: FAIL because scripts/verifier are absent.

- [ ] **Step 3: Implement safe UI replacement and exact build checks**

`build_ui.ps1` must resolve repository root from `$PSScriptRoot`, assert the destination equals `<repo>\resources\ui`, run:

```powershell
npm --prefix "$repo\frontend" ci
npm --prefix "$repo\frontend" run test:unit -- --run
npm --prefix "$repo\frontend" run type-check
npm --prefix "$repo\frontend" run build
```

Then remove only the verified `resources/ui` directory and copy `frontend/dist` into it. The verifier requires Python `3.12`, 64-bit interpreter, Node major `24`, `frontend/package-lock.json`, `pyproject.toml`, and all immutable resource inputs.

- [ ] **Step 4: Run staging and input verification**

Run:

```powershell
.\scripts\build_ui.ps1
python scripts\verify_build_inputs.py
python -m pytest tests/unit/scripts/test_verify_build_inputs.py -v
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit build staging**

```powershell
git add scripts tests/unit/scripts .gitignore README.md resources/ui
git commit -m "build: automate locked UI staging"
```

### Task 3: Define and Test the PyInstaller Onedir Build

**Files:**
- Modify: `pyproject.toml`
- Create: `packaging/GameShelf.spec`
- Create: `packaging/version_info.txt`
- Create: `scripts/build_portable.ps1`
- Create: `tests/integration/packaging/test_frozen_smoke.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `dist/GameShelf/GameShelf.exe` plus `_internal` and no embedded writable `data`.
- `GameShelf.exe --smoke-test --json` emits JSON with app version, schema version, app root, data dir, frozen state, runtime selection, and success.
- Build script accepts `-SkipRuntime` for the smaller development artifact only.

- [ ] **Step 1: Write a failing frozen-smoke artifact test**

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

- [ ] **Step 2: Add PyInstaller and run the test to verify missing artifact**

Add `PyInstaller>=6.21,<7` to dev dependencies, reinstall, then run:

```powershell
python -m pytest tests/integration/packaging/test_frozen_smoke.py -v
```

Expected: FAIL/skip fixture setup because no packaged artifact exists.

- [ ] **Step 3: Implement spec and guarded build script**

The spec must use `console=False`, one EXE, `COLLECT` onedir, icon/version metadata, pywebview hidden imports collected through PyInstaller hooks, and immutable data trees:

```python
datas = [
    (str(repo / "resources" / "ui"), "resources/ui"),
    (str(repo / "resources" / "rules"), "resources/rules"),
    (str(repo / "resources" / "manifests"), "resources/manifests"),
]
```

Do not include a source/development `data` directory. `build_portable.ps1` resolves and validates `<repo>\build` and `<repo>\dist\GameShelf` before removing those build outputs, runs UI staging/input verification/backend tests, then:

```powershell
python -m PyInstaller --noconfirm --clean packaging\GameShelf.spec
```

Add JSON smoke mode without opening pywebview.

- [ ] **Step 4: Build the development onedir and run frozen smoke**

Run:

```powershell
.\scripts\build_portable.ps1 -SkipRuntime
python -m pytest tests/integration/packaging/test_frozen_smoke.py -v --built-app dist\GameShelf
```

Expected: package builds and the copied Unicode-path smoke test passes.

- [ ] **Step 5: Commit onedir packaging**

```powershell
git add pyproject.toml packaging scripts/build_portable.ps1 src/gameshelf/app.py tests/integration/packaging .gitignore
git commit -m "build: package GameShelf as Windows onedir"
```

### Task 4: Stage and Select a Fixed WebView2 Runtime

**Files:**
- Create: `scripts/stage_webview2_runtime.ps1`
- Create: `packaging/runtime/README.md`
- Create: `src/gameshelf/bootstrap/webview2.py`
- Create: `tests/unit/bootstrap/test_webview2.py`
- Modify: `src/gameshelf/app.py`
- Modify: `scripts/build_portable.ps1`
- Modify: `.gitignore`

**Interfaces:**
- Staging script accepts mandatory `-ArchivePath`, `-Version`, and `-SourceUrl`; produces `packaging/runtime/staged/` and `runtime-manifest.json`.
- Produces: `select_webview2_runtime(resources, platform) -> RuntimeSelection`.
- Produces: `ensure_windows10_runtime_acl(runtime_dir) -> AclResult`.
- Complete build copies staged runtime to `dist/GameShelf/runtime`.

- [ ] **Step 1: Write failing runtime selection, UNC, and ACL-command tests**

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

- [ ] **Step 2: Run runtime tests and verify failure**

Run: `python -m pytest tests/unit/bootstrap/test_webview2.py -v`

Expected: FAIL because runtime selection/staging are absent.

- [ ] **Step 3: Implement official archive staging, manifest verification, ACL, and pywebview selection**

The PowerShell staging script must:

1. require a local official x64 Fixed Version `.cab`/archive supplied by the maintainer;
2. resolve input/output paths and verify output remains `packaging/runtime/staged`;
3. expand with Windows `expand.exe` or the documented archive format;
4. find `msedgewebview2.exe` beneath the extracted root;
5. write manifest fields `version`, `architecture: x64`, `archiveSha256`, `sourceUrl`, and `stagedAt`;
6. never download or execute the runtime.

At startup, validate the manifest/version/executable and configure:

```python
webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(selection.browser_executable_folder)
```

On Windows 10, apply the documented two SID grants using a command argument array, hidden window, timeout 30 seconds, and no shell. If ACL setup fails, try a valid installed Evergreen runtime; otherwise show an actionable startup error. On Windows 11 the ACL call is unnecessary. Never run from UNC with Fixed Runtime.

- [ ] **Step 4: Stage an official runtime and build the complete artifact**

Run after downloading the current x64 Fixed Version package from Microsoft's official WebView2 download page:

```powershell
.\scripts\stage_webview2_runtime.ps1 `
  -ArchivePath 'C:\Downloads\Microsoft.WebView2.FixedVersionRuntime.150.0.4078.44.x64.cab' `
  -Version '150.0.4078.44' `
  -SourceUrl 'https://developer.microsoft.com/microsoft-edge/webview2/'
.\scripts\build_portable.ps1
```

Expected: staging fails if the version argument does not match the extracted runtime; complete build contains `dist/GameShelf/runtime/msedgewebview2.exe` and a matching manifest. Version `150.0.4078.44` is the current stable Release-SDK runtime baseline when this plan was written. If Microsoft has replaced the downloadable Fixed Version before execution, use the exact new stable version in both arguments and let the generated manifest record it; do not add the version to application source code.

- [ ] **Step 5: Commit runtime tooling, not runtime binaries**

```powershell
git add scripts/stage_webview2_runtime.ps1 packaging/runtime/README.md src/gameshelf/bootstrap/webview2.py src/gameshelf/app.py scripts/build_portable.ps1 tests/unit/bootstrap/test_webview2.py .gitignore
git commit -m "build: support bundled fixed WebView2 runtime"
```

### Task 5: Audit Portable Writes and Database Copy Consistency

**Files:**
- Create: `src/gameshelf/bootstrap/portable_audit.py`
- Create: `scripts/test_portable_copy.ps1`
- Create: `tests/integration/packaging/test_portable_writes.py`
- Create: `tests/integration/packaging/test_database_copy.py`

**Interfaces:**
- `GameShelf.exe --portable-audit --json` initializes application services, creates representative managed files, checkpoints SQLite, reports them, cleans test records, and exits without GUI.
- Copy script runs only against a temporary copy of `dist/GameShelf` and verifies all reported owned paths lie below copied `data`.

- [ ] **Step 1: Write failing portable audit tests**

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

- [ ] **Step 2: Run audit/copy tests and verify failure**

Run: `python -m pytest tests/integration/packaging/test_portable_writes.py tests/integration/packaging/test_database_copy.py -v`

Expected: FAIL because audit/checkpoint helpers are absent.

- [ ] **Step 3: Implement application-owned path registry and safe copy test**

Register owned path categories centrally: database/WAL/SHM, config, covers, manifests, webview, backups, logs, and temp. The audit reports resolved paths and refuses anything outside data. It must not claim to audit operating-system logs/runtime caches that GameShelf does not own.

`test_portable_copy.ps1` creates a unique temp directory, copies the complete onedir, runs smoke and audit, shuts down, copies it again to a second Unicode/spaced local path, reruns smoke, and asserts the database schema/cover fixture survive. It removes only its resolved temp directory in `finally`.

- [ ] **Step 4: Run source and packaged portable-copy tests**

Run:

```powershell
python -m pytest tests/integration/packaging/test_portable_writes.py tests/integration/packaging/test_database_copy.py -v
.\scripts\test_portable_copy.ps1 -BuiltApp .\dist\GameShelf
```

Expected: all pass; second copied app retains the audit fixture and schema.

- [ ] **Step 5: Commit portability auditing**

```powershell
git add src/gameshelf/bootstrap/portable_audit.py scripts/test_portable_copy.ps1 tests/integration/packaging
git commit -m "test: audit portable data and directory copies"
```

### Task 6: Add Third-Party Notices, Release Metadata, and Clean-VM Checklist

**Files:**
- Modify: `THIRD_PARTY_NOTICES.md`
- Create: `packaging/release-manifest.json`
- Create: `docs/release/windows-clean-vm-checklist.md`
- Create: `scripts/create_release_archive.ps1`
- Create: `scripts/write_release_manifest.py`
- Create: `tests/unit/scripts/test_release_manifest.py`
- Modify: `README.md`

**Interfaces:**
- Embedded release manifest records app version, schema version, engine-rule version, Ludusavi SHA-256/source commit, WebView2 version/hash, Python/Node versions, and build time. A sibling `.sha256` and external release record store the final ZIP hash.
- Archive script produces `artifacts/GameShelf-<version>-windows-x64-portable.zip` but never uploads it.

- [ ] **Step 1: Write failing release-manifest completeness test**

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

- [ ] **Step 2: Run manifest tests and verify failure**

Run: `python -m pytest tests/unit/scripts/test_release_manifest.py -v`

Expected: FAIL because release metadata is incomplete/absent.

- [ ] **Step 3: Implement notices, local archive creation, and manual clean-VM procedure**

`THIRD_PARTY_NOTICES.md` must enumerate direct runtime/build dependencies and licenses, including pywebview BSD-3-Clause, Vue/Pinia/Vite MIT, Pillow HPND, watchdog Apache-2.0, psutil BSD-3-Clause, pefile MIT, PyYAML MIT, RapidFuzz MIT, Ludusavi manifest MIT, PyInstaller GPL exception, and Microsoft WebView2 redistribution terms/link. Copy upstream license texts where redistribution requires them.

The clean-VM checklist must verify:

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

`write_release_manifest.py` gathers dependency/runtime/rule/source fields and writes `packaging/release-manifest.json` into the staged app with `artifactSha256` omitted; the archive script then creates the ZIP and writes a sibling `artifacts/GameShelf-<version>-windows-x64-portable.zip.sha256` plus an external release record containing the archive hash. This avoids the impossible self-referential requirement of embedding a ZIP's final hash inside the same ZIP. The script checks a clean Git worktree, runs all automated gates, checkpoints test DBs, creates and hashes the ZIP, and verifies its contents. It does not tag, push, upload, or create a GitHub release.

- [ ] **Step 4: Run release checks and create a local candidate archive**

Run:

```powershell
python -m pytest tests/unit/scripts/test_release_manifest.py -v
.\scripts\create_release_archive.ps1 -BuiltApp .\dist\GameShelf -Version '0.1.0'
```

Expected: local ZIP and SHA-256 are created under `artifacts`; nothing is uploaded.

- [ ] **Step 5: Commit release documentation/tooling**

```powershell
git add THIRD_PARTY_NOTICES.md packaging/release-manifest.json docs/release scripts/create_release_archive.ps1 scripts/write_release_manifest.py tests/unit/scripts README.md
git commit -m "build: prepare verified portable release artifacts"
```

### Task 7: Run Final Verification Before Claiming V1 Complete

**Files:**
- Modify only files required by failures found during verification.
- Record: `docs/release/v0.1.0-verification.md`

**Interfaces:**
- Produces an evidence record with command, timestamp, exit status, and clean-VM checklist results.
- Does not publish the artifact.

- [ ] **Step 1: Run every automated backend/frontend/build gate from a clean worktree**

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

Expected: every command exits `0`. If any command fails, diagnose and fix it before proceeding; do not write a success record.

- [ ] **Step 2: Execute the clean-VM checklist on Windows 10 and Windows 11**

Use fresh x64 VMs and a standard user. Record OS build, whether Evergreen was present before the test, package hash, runtime selected, and result for every checklist item. Do not use developer machines as a substitute for the no-runtime Windows 10 case.

- [ ] **Step 3: Run representative manual acceptance scenarios**

Use synthetic/free test fixtures, not redistributed commercial assets:

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

Expected: all approved V1 acceptance criteria are observed.

- [ ] **Step 4: Write and verify the evidence record**

The record must list exact commits, dependency-lock hashes, artifact hash, commands/results, VM results, known limitations (including fixed-runtime size and UNC behavior), and explicitly state that save backup/restore and translation are not included.

- [ ] **Step 5: Commit verification evidence only after all gates pass**

```powershell
git add docs/release/v0.1.0-verification.md
git commit -m "docs: record GameShelf v0.1.0 verification"
```

## Portable Release Acceptance Gate

- Complete onedir starts on clean Windows 10/11 x64 without requiring a WebView2 installation.
- Windows 10 fixed-runtime ACL requirement is handled without asking users to run GameShelf permanently as administrator.
- A copied, closed application directory retains database, covers, manifests, settings, and webview state.
- Application-owned persistent paths audit below `data`; run-in-progress copying is explicitly unsupported.
- Artifact includes validated UI, rules, Ludusavi metadata/license, runtime manifest, and third-party notices.
- UNC behavior is detected and explained rather than failing as an unexplained blank window.
- Local archive creation does not publish, tag, push, or choose the project license.
- Completion is claimed only after automated gates and both clean-VM records pass.
