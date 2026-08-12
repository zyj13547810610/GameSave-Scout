# GameShelf Foundation and Desktop Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a runnable empty GameShelf desktop application with portable paths, migrated SQLite storage, serialized writes, cancellable background tasks, and a typed Vue↔Python bridge.

**Architecture:** Python is the composition root and owns all persistence. Vue renders a minimal shell and receives only JSON-safe envelopes through the pywebview whitelist; mutable database work and long-running tasks have dedicated concurrency boundaries from the first increment.

**Tech Stack:** Python 3.12, pywebview 6.2.x, SQLite, Vue 3, TypeScript, Vite, Pinia, Vitest, Vue Test Utils, pytest, Ruff, mypy, Node.js 24 LTS.

## Global Constraints

- Target Windows 10/11 x64 and PyInstaller onedir.
- Keep all application-owned persistent state beneath executable-adjacent `data/`.
- Use Python 3.12.x and Node.js 24 LTS; commit Python and npm lock results produced during this task.
- The UI receives only `ApiResult<T>` JSON envelopes from a white-listed bridge.
- SQLite writes must be serialized and foreign keys enabled.
- Do not implement scanning, covers, engines, saves, translation, injection, or backup/restore in this increment.
- Follow TDD and commit after each task.

---

### Task 1: Scaffold the Python and Vue Workspaces

**Files:**
- Create: `.editorconfig`
- Create: `.gitignore`
- Create: `README.md`
- Create: `pyproject.toml`
- Create: `src/gameshelf/__init__.py`
- Create: `tests/unit/test_package_import.py`
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/styles/base.css`
- Create: `frontend/tests/App.spec.ts`
- Generate: `frontend/package-lock.json`

**Interfaces:**
- Produces: importable package `gameshelf`.
- Produces: Vite entry `frontend/src/main.ts` and testable root component `App.vue`.
- Produces: commands `pytest`, `ruff`, `mypy`, `npm run test:unit`, `npm run type-check`, and `npm run build`.

- [ ] **Step 1: Write the failing Python and Vue smoke tests**

```python
# tests/unit/test_package_import.py
def test_package_exposes_version() -> None:
    import gameshelf

    assert gameshelf.__version__ == "0.1.0"
```

```ts
// frontend/tests/App.spec.ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import App from '../src/App.vue'

describe('App', () => {
  it('renders the product name and empty-library message', () => {
    const wrapper = mount(App)
    expect(wrapper.get('h1').text()).toBe('GameShelf')
    expect(wrapper.text()).toContain('还没有添加游戏目录')
  })
})
```

- [ ] **Step 2: Run the tests and verify that the unscaffolded project fails**

Run:

```powershell
python -m pytest tests/unit/test_package_import.py -v
npm --prefix frontend run test:unit -- --run
```

Expected: Python fails to import `gameshelf`; npm fails because `frontend/package.json` does not exist.

- [ ] **Step 3: Create the minimal workspace and root UI**

Use this Python configuration:

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=80,<81"]
build-backend = "setuptools.build_meta"

[project]
name = "gameshelf"
version = "0.1.0"
description = "Portable Windows game library and save-location manager"
requires-python = ">=3.12,<3.13"
dependencies = [
  "pywebview>=6.2,<7",
]

[project.optional-dependencies]
dev = [
  "mypy>=1.17,<2",
  "pytest>=8.4,<9",
  "pytest-cov>=6.2,<7",
  "ruff>=0.12,<1",
]

[project.scripts]
gameshelf = "gameshelf.app:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["gameshelf"]
```

Use scripts `dev`, `build`, `type-check`, and `test:unit` in `frontend/package.json`, with runtime dependencies `vue` and `pinia`, and dev dependencies `@vitejs/plugin-vue`, `@vue/test-utils`, `jsdom`, `typescript`, `vite`, `vitest`, and `vue-tsc`. Set `engines.node` to `>=24 <25` and generate the lock with `npm --prefix frontend install`.

The initial `App.vue` must render this semantic structure:

```vue
<script setup lang="ts"></script>

<template>
  <main class="app-shell">
    <header><h1>GameShelf</h1></header>
    <section class="empty-state" aria-labelledby="empty-title">
      <h2 id="empty-title">还没有添加游戏目录</h2>
      <p>添加一个或多个本地目录后，游戏会显示在这里。</p>
    </section>
  </main>
</template>
```

- [ ] **Step 4: Install dependencies and run all scaffold checks**

Run:

```powershell
python -m pip install -e ".[dev]"
npm --prefix frontend install
python -m pytest tests/unit/test_package_import.py -v
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

Expected: all commands exit `0`; Vite creates `frontend/dist/index.html`.

- [ ] **Step 5: Commit the scaffold**

```powershell
git add .editorconfig .gitignore README.md pyproject.toml src tests frontend
git commit -m "build: scaffold GameShelf workspaces"
```

### Task 2: Resolve and Create the Portable Data Layout

**Files:**
- Create: `src/gameshelf/bootstrap/__init__.py`
- Create: `src/gameshelf/bootstrap/paths.py`
- Create: `src/gameshelf/bootstrap/config.py`
- Create: `tests/unit/bootstrap/test_paths.py`
- Create: `tests/unit/bootstrap/test_config.py`

**Interfaces:**
- Produces: `AppPaths.from_root(app_root: Path) -> AppPaths`.
- Produces: `AppPaths.for_runtime() -> AppPaths`.
- Produces: `AppPaths.ensure_writable() -> None`, raising `DataDirectoryError`.
- Produces: `JsonConfigStore.load() -> AppConfig` and `save(config: AppConfig) -> None` using `data/config.json`.
- Later tasks consume every directory field from `AppPaths`; no feature may invent its own persistent root.

- [ ] **Step 1: Write failing tests for source, frozen, and unwritable layouts**

```python
from pathlib import Path

import pytest

from gameshelf.bootstrap.paths import AppPaths, DataDirectoryError, runtime_root


def test_from_root_places_every_persistent_path_under_data(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "GameShelf")
    paths.ensure_writable()

    assert paths.database_file == paths.data_dir / "library.db"
    assert paths.config_file == paths.data_dir / "config.json"
    assert paths.covers_original_dir == paths.data_dir / "covers" / "original"
    assert paths.covers_thumbs_dir == paths.data_dir / "covers" / "thumbs"
    assert paths.webview_dir == paths.data_dir / "webview"
    assert all(path.exists() for path in paths.required_directories())


def test_runtime_root_uses_executable_parent_when_frozen(tmp_path: Path) -> None:
    executable = tmp_path / "portable" / "GameShelf.exe"
    assert runtime_root(frozen=True, executable=executable) == executable.parent


def test_ensure_writable_wraps_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = AppPaths.from_root(tmp_path)

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(DataDirectoryError, match="无法写入"):
        paths.ensure_writable()


def test_config_store_recovers_invalid_json_without_overwriting_it(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{invalid", encoding="utf-8")
    store = JsonConfigStore(path)
    with pytest.raises(InvalidConfigError):
        store.load()
    assert path.read_text(encoding="utf-8") == "{invalid"
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/unit/bootstrap/test_paths.py -v`

Expected: FAIL because `gameshelf.bootstrap.paths` does not exist.

- [ ] **Step 3: Implement the immutable path model**

```python
@dataclass(frozen=True)
class AppPaths:
    app_root: Path
    data_dir: Path
    database_file: Path
    config_file: Path
    covers_original_dir: Path
    covers_thumbs_dir: Path
    manifests_dir: Path
    webview_dir: Path
    backups_dir: Path
    logs_dir: Path
    temp_dir: Path

    @classmethod
    def from_root(cls, app_root: Path) -> "AppPaths":
        root = app_root.resolve()
        data = root / "data"
        return cls(
            app_root=root,
            data_dir=data,
            database_file=data / "library.db",
            config_file=data / "config.json",
            covers_original_dir=data / "covers" / "original",
            covers_thumbs_dir=data / "covers" / "thumbs",
            manifests_dir=data / "manifests",
            webview_dir=data / "webview",
            backups_dir=data / "db_backups",
            logs_dir=data / "logs",
            temp_dir=data / "temp",
        )
```

`runtime_root` must use `Path(sys.executable).parent` when `sys.frozen` is true, and the repository root derived from `paths.py` during source development. `ensure_writable` creates every required directory, writes and removes a UUID-named probe beneath `data`, and converts `OSError` into a Chinese `DataDirectoryError` without recommending administrator mode.

`AppConfig` starts with `{version: 1, language: "zh-CN", startupQuickScan: true, orphanScanExclusions: []}`. `JsonConfigStore.save` writes UTF-8 JSON to `data/temp`, flushes/fsyncs, and atomically replaces `config.json`. Missing config returns defaults; invalid config raises `InvalidConfigError` and preserves the original for manual recovery.

- [ ] **Step 4: Run path tests and static checks**

Run:

```powershell
python -m pytest tests/unit/bootstrap/test_paths.py tests/unit/bootstrap/test_config.py -v
python -m ruff check src/gameshelf/bootstrap tests/unit/bootstrap
python -m mypy src/gameshelf/bootstrap
```

Expected: all pass.

- [ ] **Step 5: Commit portable path resolution**

```powershell
git add src/gameshelf/bootstrap tests/unit/bootstrap
git commit -m "feat: add portable application paths"
```

### Task 3: Create the Initial SQLite Schema and Migrator

**Files:**
- Create: `src/gameshelf/db/__init__.py`
- Create: `src/gameshelf/db/connection.py`
- Create: `src/gameshelf/db/migrator.py`
- Create: `src/gameshelf/db/migrations/0001_initial.sql`
- Create: `tests/unit/db/test_migrator.py`

**Interfaces:**
- Produces: `ConnectionFactory(database_file: Path).connect(*, readonly: bool = False) -> sqlite3.Connection`.
- Produces: `Migrator(factory: ConnectionFactory, backups_dir: Path).migrate() -> int` returning schema version.
- Produces: schema version `1` with the tables used by all later plans.

- [ ] **Step 1: Write failing migration tests**

```python
from pathlib import Path

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.migrator import Migrator


def test_migrator_creates_v1_schema_with_foreign_keys_and_wal(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "data" / "library.db")
    version = Migrator(factory, tmp_path / "backups").migrate()

    with factory.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert version == user_version == 1
        assert {"scan_roots", "games", "save_locations", "scan_sessions",
            "scan_observations", "save_detection_sessions", "save_discoveries",
            "settings"} <= tables
    assert foreign_keys == 1
    assert journal_mode == "wal"


def test_migrator_backs_up_existing_database_before_upgrade(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    factory.database_file.parent.mkdir(parents=True, exist_ok=True)
    with factory.connect() as connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
        connection.commit()

    Migrator(factory, tmp_path / "backups").migrate()

    assert len(list((tmp_path / "backups").glob("library-before-v1-*.db"))) == 1


def test_failed_migration_preserves_original_and_does_not_advance_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
        connection.execute("INSERT INTO legacy VALUES ('kept')")
        connection.commit()
    monkeypatch.setattr(Migrator, "migration_sql", lambda *_: "INVALID SQL")
    with pytest.raises(MigrationError):
        Migrator(factory, tmp_path / "backups").migrate()
    with factory.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT value FROM legacy").fetchone()[0] == "kept"
```

- [ ] **Step 2: Run the migration tests and verify failure**

Run: `python -m pytest tests/unit/db/test_migrator.py -v`

Expected: FAIL because database infrastructure is absent.

- [ ] **Step 3: Implement connection policy, migration discovery, backup, and V1 DDL**

Every connection must set `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`, and `PRAGMA journal_mode=WAL` for writable connections. Read-only connections use the SQLite URI `mode=ro`.

Create these V1 tables and constraints in `0001_initial.sql`:

```sql
CREATE TABLE scan_roots (
  id TEXT PRIMARY KEY,
  display_path TEXT NOT NULL,
  path_key TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  scan_mode TEXT NOT NULL CHECK (scan_mode IN ('children', 'recursive')),
  max_depth INTEGER NOT NULL DEFAULT 1 CHECK (max_depth >= 1),
  exclusions_json TEXT NOT NULL DEFAULT '[]',
  last_scanned_at TEXT,
  last_scan_status TEXT NOT NULL DEFAULT 'never',
  last_error TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE games (
  id TEXT PRIMARY KEY,
  scan_root_id TEXT REFERENCES scan_roots(id) ON DELETE SET NULL,
  relative_dir TEXT,
  install_path_key TEXT,
  title TEXT NOT NULL,
  detected_title TEXT,
  title_is_manual INTEGER NOT NULL DEFAULT 0 CHECK (title_is_manual IN (0, 1)),
  status TEXT NOT NULL CHECK (status IN ('installed', 'missing', 'save_only')),
  detected_engine_id TEXT,
  detected_engine_variant TEXT,
  engine_id TEXT,
  engine_variant TEXT,
  engine_is_manual INTEGER NOT NULL DEFAULT 0 CHECK (engine_is_manual IN (0, 1)),
  engine_confidence REAL,
  engine_evidence_json TEXT NOT NULL DEFAULT '[]',
  detected_main_exe_relpath TEXT,
  main_exe_relpath TEXT,
  main_exe_is_manual INTEGER NOT NULL DEFAULT 0 CHECK (main_exe_is_manual IN (0, 1)),
  working_dir_relpath TEXT,
  launch_args_json TEXT NOT NULL DEFAULT '[]',
  environment_json TEXT NOT NULL DEFAULT '{}',
  exe_arch TEXT NOT NULL DEFAULT 'unknown' CHECK (exe_arch IN ('x86', 'x64', 'unknown')),
  cover_original_relpath TEXT,
  cover_thumb_relpath TEXT,
  cover_revision INTEGER NOT NULL DEFAULT 0,
  engine_rules_version TEXT,
  added_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_launched_at TEXT,
  missing_since TEXT,
  CHECK (status = 'save_only' OR (scan_root_id IS NOT NULL AND relative_dir IS NOT NULL))
);

CREATE UNIQUE INDEX games_install_path_key_unique
  ON games(install_path_key) WHERE install_path_key IS NOT NULL;
CREATE UNIQUE INDEX games_root_relative_unique
  ON games(scan_root_id, relative_dir)
  WHERE scan_root_id IS NOT NULL AND relative_dir IS NOT NULL;

CREATE TABLE save_locations (
  id TEXT PRIMARY KEY,
  game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('directory', 'file', 'glob', 'registry')),
  path_template TEXT NOT NULL,
  display_path TEXT NOT NULL,
  path_key TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('manual', 'dynamic', 'ludusavi', 'engine', 'legacy_scan')),
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  evidence_json TEXT NOT NULL DEFAULT '[]',
  confirmed INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  last_verified_at TEXT,
  UNIQUE(game_id, kind, path_key)
);

CREATE TABLE scan_sessions (
  id TEXT PRIMARY KEY,
  root_id TEXT REFERENCES scan_roots(id) ON DELETE SET NULL,
  kind TEXT NOT NULL CHECK (kind IN ('library', 'orphan')),
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'cancelled', 'failed', 'unavailable')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  scope_json TEXT NOT NULL DEFAULT '{}',
  counts_json TEXT NOT NULL DEFAULT '{}',
  rules_version TEXT,
  error_summary TEXT
);

CREATE TABLE scan_observations (
  session_id TEXT NOT NULL REFERENCES scan_sessions(id) ON DELETE CASCADE,
  install_path_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(session_id, install_path_key)
);

CREATE TABLE save_detection_sessions (
  id TEXT PRIMARY KEY,
  game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (status IN ('preparing', 'monitoring', 'settling', 'completed', 'cancelled', 'failed')),
  started_at TEXT NOT NULL,
  save_marked_at TEXT,
  finished_at TEXT,
  monitored_roots_json TEXT NOT NULL DEFAULT '[]',
  overflowed INTEGER NOT NULL DEFAULT 0 CHECK (overflowed IN (0, 1)),
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  error_summary TEXT
);

CREATE TABLE save_discoveries (
  id TEXT PRIMARY KEY,
  scan_session_id TEXT REFERENCES scan_sessions(id) ON DELETE CASCADE,
  detection_session_id TEXT REFERENCES save_detection_sessions(id) ON DELETE CASCADE,
  candidate_template TEXT NOT NULL,
  display_path TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('directory', 'file', 'registry')),
  suggested_game TEXT,
  engine_id TEXT,
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  evidence_json TEXT NOT NULL DEFAULT '[]',
  review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (review_status IN ('unreviewed', 'linked', 'save_only', 'ignored')),
  linked_game_id TEXT REFERENCES games(id) ON DELETE SET NULL,
  CHECK (scan_session_id IS NOT NULL OR detection_session_id IS NOT NULL)
);

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

PRAGMA user_version = 1;
```

Before migrating a non-empty database, run `PRAGMA wal_checkpoint(TRUNCATE)` and use `sqlite3.Connection.backup` into `backups_dir`. Apply each migration in a transaction and never increase `user_version` if its SQL fails. Keep the five newest automatic DB backups and delete only older files matching GameShelf's exact `library-before-v*-*.db` naming pattern. A failed migration preserves the source DB, leaves the application in a non-writing recovery state, and reports the backup path.

- [ ] **Step 4: Run focused tests and inspect the created schema**

Run:

```powershell
python -m pytest tests/unit/db/test_migrator.py -v
python -m ruff check src/gameshelf/db tests/unit/db
python -m mypy src/gameshelf/db
```

Expected: all pass; both migration tests assert version `1`.

- [ ] **Step 5: Commit the initial database**

```powershell
git add src/gameshelf/db tests/unit/db
git commit -m "feat: add versioned SQLite storage"
```

### Task 4: Serialize SQLite Writes

**Files:**
- Create: `src/gameshelf/db/writer.py`
- Create: `tests/unit/db/test_writer.py`

**Interfaces:**
- Consumes: `ConnectionFactory.connect()` from Task 3.
- Produces: `DbWriter(factory).start()`, `submit(operation) -> Future[T]`, and `close(timeout: float = 5.0) -> None`.
- Operations receive one writer-owned `sqlite3.Connection`; callers never pass connections across threads.

- [ ] **Step 1: Write a failing serialized-write test**

```python
from concurrent.futures import Future
from pathlib import Path

from gameshelf.db.connection import ConnectionFactory
from gameshelf.db.writer import DbWriter


def test_writer_commits_operations_in_submission_order(tmp_path: Path) -> None:
    factory = ConnectionFactory(tmp_path / "library.db")
    with factory.connect() as connection:
        connection.execute("CREATE TABLE events(sequence INTEGER PRIMARY KEY, value TEXT)")
        connection.commit()

    writer = DbWriter(factory)
    writer.start()
    futures: list[Future[int]] = []
    for sequence in range(20):
        futures.append(writer.submit(lambda connection, n=sequence: connection.execute(
            "INSERT INTO events(sequence, value) VALUES (?, ?)", (n, str(n))
        ).rowcount))
    assert [future.result(timeout=2) for future in futures] == [1] * 20
    writer.close()

    with factory.connect(readonly=True) as connection:
        assert [row[0] for row in connection.execute(
            "SELECT sequence FROM events ORDER BY sequence"
        )] == list(range(20))
```

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m pytest tests/unit/db/test_writer.py -v`

Expected: FAIL because `DbWriter` does not exist.

- [ ] **Step 3: Implement one connection on one daemon thread**

Use a `queue.Queue` of `(operation, Future)` records and a unique sentinel. For each operation: begin a transaction, call `operation(connection)`, commit and resolve the future; on exception, roll back and set the exception on the future. Reject new work after closing, and join the thread with the caller-provided timeout.

```python
T = TypeVar("T")
WriteOperation = Callable[[sqlite3.Connection], T]

class DbWriter:
    def submit(self, operation: WriteOperation[T]) -> Future[T]: ...
```

Do not expose the writer connection or allow an operation to call `commit` itself.

- [ ] **Step 4: Run writer tests and the database suite**

Run: `python -m pytest tests/unit/db -v`

Expected: all pass with no locked-database errors.

- [ ] **Step 5: Commit the writer boundary**

```powershell
git add src/gameshelf/db/writer.py tests/unit/db/test_writer.py
git commit -m "feat: serialize database writes"
```

### Task 5: Add Cancellable Background Task State

**Files:**
- Create: `src/gameshelf/bridge/__init__.py`
- Create: `src/gameshelf/bridge/tasks.py`
- Create: `tests/unit/bridge/test_tasks.py`

**Interfaces:**
- Produces: `TaskRegistry.submit(kind, operation) -> UUID string`.
- Produces: `TaskContext.report(completed: int, total: int | None, message: str) -> None` and `raise_if_cancelled()`.
- Produces: immutable `TaskSnapshot` with `id`, `kind`, `status`, `progress`, `message`, `result`, and `error`.
- Status values: `queued`, `running`, `completed`, `cancelled`, `failed`.

- [ ] **Step 1: Write failing state-transition and cancellation tests**

```python
from threading import Event

from gameshelf.bridge.tasks import TaskCancelled, TaskRegistry


def test_task_reports_progress_and_result() -> None:
    registry = TaskRegistry(max_workers=1)
    task_id = registry.submit("example", lambda context: (
        context.report(1, 2, "一半"), {"answer": 42}
    )[1])
    snapshot = registry.wait(task_id, timeout=2)
    assert snapshot.status == "completed"
    assert snapshot.progress == {"completed": 1, "total": 2}
    assert snapshot.result == {"answer": 42}
    registry.close()


def test_task_can_be_cancelled_cooperatively() -> None:
    entered = Event()
    release = Event()

    def work(context: object) -> None:
        entered.set()
        release.wait(2)
        context.raise_if_cancelled()

    registry = TaskRegistry(max_workers=1)
    task_id = registry.submit("example", work)
    assert entered.wait(1)
    assert registry.cancel(task_id) is True
    release.set()
    assert registry.wait(task_id, timeout=2).status == "cancelled"
    registry.close()
```

- [ ] **Step 2: Run the task tests and verify failure**

Run: `python -m pytest tests/unit/bridge/test_tasks.py -v`

Expected: FAIL because the task registry is absent.

- [ ] **Step 3: Implement thread-safe snapshots and cooperative cancellation**

Use `ThreadPoolExecutor`, a `threading.RLock`, per-task `threading.Event`, and `dataclasses.replace` to publish immutable snapshots. Catch only the project-specific `TaskCancelled` as cancellation; convert other exceptions into `failed` with a stable error code and user-safe message while logging the traceback later through the composition root.

- [ ] **Step 4: Run focused and static checks**

Run:

```powershell
python -m pytest tests/unit/bridge/test_tasks.py -v
python -m ruff check src/gameshelf/bridge tests/unit/bridge
python -m mypy src/gameshelf/bridge
```

Expected: all pass.

- [ ] **Step 5: Commit background task infrastructure**

```powershell
git add src/gameshelf/bridge tests/unit/bridge
git commit -m "feat: add cancellable task registry"
```

### Task 6: Define the Bridge Envelope and Frontend Client

**Files:**
- Create: `src/gameshelf/bridge/contracts.py`
- Create: `src/gameshelf/bridge/api.py`
- Create: `tests/unit/bridge/test_api.py`
- Create: `frontend/src/api/contracts.ts`
- Create: `frontend/src/api/bridge.ts`
- Create: `frontend/src/api/mockBridge.ts`
- Create: `frontend/src/api/window.d.ts`
- Create: `frontend/tests/bridge.spec.ts`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: `AppPaths` and `TaskRegistry`.
- Produces Python methods: `bootstrap`, `task_snapshot`, and `cancel_task`.
- Produces TypeScript `GameShelfBridge` with the same methods and `ApiResult<T>` envelope.

- [ ] **Step 1: Write failing backend and frontend contract tests**

```python
def test_bootstrap_returns_json_safe_success(api: BridgeApi) -> None:
    assert api.bootstrap() == {
        "ok": True,
        "data": {"appName": "GameShelf", "schemaVersion": 1, "portable": True},
    }


def test_unknown_task_returns_stable_error(api: BridgeApi) -> None:
    result = api.task_snapshot("not-a-uuid")
    assert result["ok"] is False
    assert result["error"]["code"] == "task_not_found"
```

```ts
it('uses the development mock when pywebview is absent', async () => {
  const bridge = createBridge({ windowObject: {} as Window })
  const result = await bridge.bootstrap()
  expect(result).toEqual({
    ok: true,
    data: { appName: 'GameShelf', schemaVersion: 1, portable: true },
  })
})
```

- [ ] **Step 2: Run both contract suites and verify failure**

Run:

```powershell
python -m pytest tests/unit/bridge/test_api.py -v
npm --prefix frontend run test:unit -- --run tests/bridge.spec.ts
```

Expected: both fail because the contracts and clients do not exist.

- [ ] **Step 3: Implement matching Python and TypeScript contracts**

Use this exact envelope:

```ts
export type ApiError = { code: string; message: string; details?: unknown }
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError }

export type BootstrapState = {
  appName: 'GameShelf'
  schemaVersion: number
  portable: true
}

export interface GameShelfBridge {
  bootstrap(): Promise<ApiResult<BootstrapState>>
  task_snapshot(taskId: string): Promise<ApiResult<TaskSnapshot>>
  cancel_task(taskId: string): Promise<ApiResult<{ cancelled: boolean }>>
}
```

`createBridge` uses `window.pywebview.api` only after the `pywebviewready` event; development and component tests receive `createMockBridge()`. `App.vue` shows “正在连接本地数据库…” during bootstrap and the existing empty state after success. A failed bootstrap renders the error message and a retry button.

- [ ] **Step 4: Run bridge tests, frontend tests, and type checking**

Run:

```powershell
python -m pytest tests/unit/bridge -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
```

Expected: all pass.

- [ ] **Step 5: Commit the typed bridge**

```powershell
git add src/gameshelf/bridge tests/unit/bridge frontend/src frontend/tests
git commit -m "feat: add typed desktop bridge"
```

### Task 7: Compose the Desktop Application and CI Baseline

**Files:**
- Create: `src/gameshelf/bootstrap/logging.py`
- Create: `src/gameshelf/bootstrap/application.py`
- Create: `src/gameshelf/app.py`
- Create: `src/gameshelf/__main__.py`
- Create: `tests/integration/test_application_bootstrap.py`
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: all previous foundation interfaces.
- Produces: `build_application(paths: AppPaths) -> Application` with `api`, `database`, `writer`, and `tasks`.
- Produces: `python -m gameshelf --smoke-test` and `gameshelf --smoke-test`, which initialize paths/schema and exit without opening a window.
- Produces: normal `python -m gameshelf`, which opens the pywebview window.

- [ ] **Step 1: Write a failing bootstrap smoke test**

```python
from pathlib import Path

from gameshelf.bootstrap.application import build_application
from gameshelf.bootstrap.paths import AppPaths


def test_application_bootstrap_creates_only_portable_state(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "portable")
    application = build_application(paths)
    try:
        assert application.api.bootstrap()["ok"] is True
        assert paths.database_file.exists()
        assert all(paths.data_dir in path.parents or path == paths.data_dir
                   for path in paths.required_directories())
    finally:
        application.close()
```

- [ ] **Step 2: Run the integration test and verify failure**

Run: `python -m pytest tests/integration/test_application_bootstrap.py -v`

Expected: FAIL because the composition root does not exist.

- [ ] **Step 3: Implement lifecycle, logging, smoke mode, and pywebview startup**

`build_application` must:

1. call `paths.ensure_writable()`;
2. configure a rotating UTF-8 log at `data/logs/gameshelf.log`;
3. run `Migrator.migrate()`;
4. start `DbWriter` and `TaskRegistry`;
5. construct `BridgeApi`;
6. expose one idempotent `close()` that stops tasks before the writer.

Logging must never include bridge payload bytes, clipboard data, registry values, or save-file contents. Normal logs may include user-visible paths needed for local diagnosis; diagnostic export is outside V1 and therefore no external upload/export occurs.

Normal startup must build the frontend first during development, then use:

```python
window = webview.create_window(
    "GameShelf",
    str(paths.app_root / "resources" / "ui" / "index.html"),
    js_api=application.api,
    width=1180,
    height=760,
    min_size=(960, 640),
)
window.events.closed += lambda: application.close()
webview.start(
    debug=False,
    private_mode=False,
    storage_path=str(paths.webview_dir),
)
```

In source development, accept `GAMESHELF_DEV_SERVER_URL` only when the process is not frozen; otherwise always load packaged UI. `--smoke-test` prints `GameShelf bootstrap OK (schema 1)` and exits `0`.

Add a Windows CI workflow that installs Python 3.12 and Node 24, runs the roadmap integration gate, and never opens the GUI.

- [ ] **Step 4: Build UI and run the full foundation gate**

Run:

```powershell
npm --prefix frontend run build
New-Item -ItemType Directory -Force -Path resources\ui | Out-Null
Copy-Item -Recurse -Force frontend\dist\* resources\ui\
python -m gameshelf --smoke-test
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

Expected: smoke output includes schema `1`; all checks exit `0`.

- [ ] **Step 5: Commit the runnable foundation**

```powershell
git add src tests frontend README.md .github resources/ui
git commit -m "feat: boot portable GameShelf shell"
```

## Foundation Acceptance Gate

- `python -m gameshelf --smoke-test` initializes an arbitrary writable app root without touching user profile storage.
- Normal startup opens an empty GameShelf window and persists webview state under `data/webview`.
- Schema version is `1`; foreign keys and WAL are enabled.
- Background task cancellation and database serialization are covered by deterministic tests.
- Python and TypeScript bridge method names and envelopes match.
- Full backend/frontend test, lint, type-check, and build commands pass.
