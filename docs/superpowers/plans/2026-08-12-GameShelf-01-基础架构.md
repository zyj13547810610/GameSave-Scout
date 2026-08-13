# GameShelf 基础设施与桌面外壳实施计划

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 产出一个可运行的空白 GameShelf 桌面应用，具备便携路径、已迁移的 SQLite 存储、串行化写入、可取消的后台任务，以及类型化的 Vue↔Python 桥接层。

**架构：** Python 作为组合根并负责全部持久化。Vue 渲染最小应用外壳，只通过 pywebview 白名单接收可安全序列化为 JSON 的响应封装；从第一个增量起，可变数据库操作和长时间任务就拥有各自独立的并发边界。

**技术栈：** Python 3.12、pywebview 6.2.x、SQLite、Vue 3、TypeScript、Vite、Pinia、Vitest、Vue Test Utils、pytest、Ruff、mypy、Node.js 24 LTS。

## 全局约束

- 目标平台为 Windows 10/11 x64，使用 PyInstaller onedir 打包。
- 应用自身的所有持久化状态都必须位于可执行文件旁的 `data/` 下。
- 使用 Python 3.12.x 和 Node.js 24 LTS；提交本任务生成的 Python 与 npm 锁定结果。
- UI 只能从白名单桥接层接收 `ApiResult<T>` JSON 响应封装。
- SQLite 写入必须串行化，并启用外键。
- 本增量不实现扫描、封面、引擎、存档、翻译、注入或备份/恢复。
- 遵循 TDD，并在每个任务完成后提交。

---

### 任务 1：搭建 Python 与 Vue 工作区

**文件：**
- 新建：`.editorconfig`
- 新建：`.gitignore`
- 新建：`README.md`
- 新建：`pyproject.toml`
- 新建：`src/gameshelf/__init__.py`
- 新建：`tests/unit/test_package_import.py`
- 新建：`frontend/package.json`
- 新建：`frontend/tsconfig.json`
- 新建：`frontend/tsconfig.app.json`
- 新建：`frontend/vite.config.ts`
- 新建：`frontend/vitest.config.ts`
- 新建：`frontend/index.html`
- 新建：`frontend/src/main.ts`
- 新建：`frontend/src/App.vue`
- 新建：`frontend/src/styles/base.css`
- 新建：`frontend/tests/App.spec.ts`
- 生成：`frontend/package-lock.json`

**接口：**
- 产出：可导入的软件包 `gameshelf`。
- 产出：Vite 入口 `frontend/src/main.ts` 和可测试的根组件 `App.vue`。
- 产出：`pytest`、`ruff`、`mypy`、`npm run test:unit`、`npm run type-check` 及 `npm run build` 命令。

- [ ] **步骤 1：编写会失败的 Python 与 Vue 冒烟测试**

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

- [ ] **步骤 2：运行测试，确认尚未搭建的项目会失败**

运行：

```powershell
python -m pytest tests/unit/test_package_import.py -v
npm --prefix frontend run test:unit -- --run
```

预期：Python 因无法导入 `gameshelf` 而失败；npm 因 `frontend/package.json` 不存在而失败。

- [ ] **步骤 3：创建最小工作区与根 UI**

使用以下 Python 配置：

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

在 `frontend/package.json` 中配置 `dev`、`build`、`type-check` 和 `test:unit` 脚本；运行时依赖为 `vue` 与 `pinia`，开发依赖为 `@vitejs/plugin-vue`、`@vue/test-utils`、`jsdom`、`typescript`、`vite`、`vitest` 和 `vue-tsc`。将 `engines.node` 设为 `>=24 <25`，并通过 `npm --prefix frontend install` 生成锁文件。

初始 `App.vue` 必须渲染以下语义结构：

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

- [ ] **步骤 4：安装依赖并运行全部脚手架检查**

运行：

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

预期：所有命令均以 `0` 退出；Vite 创建 `frontend/dist/index.html`。

- [ ] **步骤 5：提交脚手架**

```powershell
git add .editorconfig .gitignore README.md pyproject.toml src tests frontend
git commit -m "build: scaffold GameShelf workspaces"
```

### 任务 2：解析并创建便携数据目录结构

**文件：**
- 新建：`src/gameshelf/bootstrap/__init__.py`
- 新建：`src/gameshelf/bootstrap/paths.py`
- 新建：`src/gameshelf/bootstrap/config.py`
- 新建：`tests/unit/bootstrap/test_paths.py`
- 新建：`tests/unit/bootstrap/test_config.py`

**接口：**
- 产出：`AppPaths.from_root(app_root: Path) -> AppPaths`。
- 产出：`AppPaths.for_runtime() -> AppPaths`。
- 产出：`AppPaths.ensure_writable() -> None`，失败时抛出 `DataDirectoryError`。
- 产出：使用 `data/config.json` 的 `JsonConfigStore.load() -> AppConfig` 和 `save(config: AppConfig) -> None`。
- 后续任务使用 `AppPaths` 中的每个目录字段；任何功能都不得自行另设持久化根目录。

- [ ] **步骤 1：为源码、冻结构建和不可写目录结构编写失败测试**

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

- [ ] **步骤 2：运行针对性测试并确认失败**

运行：`python -m pytest tests/unit/bootstrap/test_paths.py -v`

预期：失败，因为 `gameshelf.bootstrap.paths` 尚不存在。

- [ ] **步骤 3：实现不可变路径模型**

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

当 `sys.frozen` 为 true 时，`runtime_root` 必须使用 `Path(sys.executable).parent`；源码开发时则使用根据 `paths.py` 推导出的仓库根目录。`ensure_writable` 创建所有必需目录，在 `data` 下写入并删除一个以 UUID 命名的探测文件，并将 `OSError` 转换为中文 `DataDirectoryError`，且不得建议用户以管理员模式运行。

`AppConfig` 的初始值为 `{version: 1, language: "zh-CN", startupQuickScan: true, orphanScanExclusions: []}`。`JsonConfigStore.save` 先将 UTF-8 JSON 写入 `data/temp`，执行 flush/fsync，再原子替换 `config.json`。配置不存在时返回默认值；配置无效时抛出 `InvalidConfigError`，并保留原文件供手动恢复。

- [ ] **步骤 4：运行路径测试与静态检查**

运行：

```powershell
python -m pytest tests/unit/bootstrap/test_paths.py tests/unit/bootstrap/test_config.py -v
python -m ruff check src/gameshelf/bootstrap tests/unit/bootstrap
python -m mypy src/gameshelf/bootstrap
```

预期：全部通过。

- [ ] **步骤 5：提交便携路径解析功能**

```powershell
git add src/gameshelf/bootstrap tests/unit/bootstrap
git commit -m "feat: add portable application paths"
```

### 任务 3：创建初始 SQLite 架构与迁移器

**文件：**
- 新建：`src/gameshelf/db/__init__.py`
- 新建：`src/gameshelf/db/connection.py`
- 新建：`src/gameshelf/db/migrator.py`
- 新建：`src/gameshelf/db/migrations/0001_initial.sql`
- 新建：`tests/unit/db/test_migrator.py`

**接口：**
- 产出：`ConnectionFactory(database_file: Path).connect(*, readonly: bool = False) -> sqlite3.Connection`。
- 产出：返回架构版本的 `Migrator(factory: ConnectionFactory, backups_dir: Path).migrate() -> int`。
- 产出：架构版本 `1`，包含后续所有计划使用的表。

- [ ] **步骤 1：编写会失败的迁移测试**

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

- [ ] **步骤 2：运行迁移测试并确认失败**

运行：`python -m pytest tests/unit/db/test_migrator.py -v`

预期：失败，因为数据库基础设施尚不存在。

- [ ] **步骤 3：实现连接策略、迁移发现、备份和 V1 DDL**

每个连接都必须设置 `row_factory=sqlite3.Row`、`PRAGMA foreign_keys=ON` 和 `PRAGMA busy_timeout=5000`；可写连接还要设置 `PRAGMA journal_mode=WAL`。只读连接使用 SQLite URI `mode=ro`。

在 `0001_initial.sql` 中创建以下 V1 数据表及约束：

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

迁移非空数据库前，运行 `PRAGMA wal_checkpoint(TRUNCATE)`，并使用 `sqlite3.Connection.backup` 将数据库备份到 `backups_dir`。每个迁移都在事务中执行；SQL 失败时绝不能提高 `user_version`。保留最新五个自动数据库备份，只删除严格匹配 GameShelf `library-before-v*-*.db` 命名模式的更早文件。迁移失败时保留源数据库，使应用进入禁止写入的恢复状态，并报告备份路径。

- [ ] **步骤 4：运行针对性测试并检查生成的架构**

运行：

```powershell
python -m pytest tests/unit/db/test_migrator.py -v
python -m ruff check src/gameshelf/db tests/unit/db
python -m mypy src/gameshelf/db
```

预期：全部通过；两个迁移测试均断言版本为 `1`。

- [ ] **步骤 5：提交初始数据库**

```powershell
git add src/gameshelf/db tests/unit/db
git commit -m "feat: add versioned SQLite storage"
```

### 任务 4：串行化 SQLite 写入

**文件：**
- 新建：`src/gameshelf/db/writer.py`
- 新建：`tests/unit/db/test_writer.py`

**接口：**
- 使用：任务 3 的 `ConnectionFactory.connect()`。
- 产出：`DbWriter(factory).start()`、`submit(operation) -> Future[T]` 和 `close(timeout: float = 5.0) -> None`。
- 操作接收由写入器持有的单个 `sqlite3.Connection`；调用方绝不在线程之间传递连接。

- [ ] **步骤 1：编写会失败的串行写入测试**

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

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/unit/db/test_writer.py -v`

预期：失败，因为 `DbWriter` 尚不存在。

- [ ] **步骤 3：在单个守护线程上实现单一连接**

使用保存 `(operation, Future)` 记录的 `queue.Queue` 和唯一的哨兵对象。对每项操作：开启事务、调用 `operation(connection)`、提交并完成 future；发生异常时回滚，并将异常设置到 future。关闭后拒绝新任务，并按调用方提供的超时时间等待线程结束。

```python
T = TypeVar("T")
WriteOperation = Callable[[sqlite3.Connection], T]

class DbWriter:
    def submit(self, operation: WriteOperation[T]) -> Future[T]: ...
```

不得暴露写入器连接，也不得允许操作自行调用 `commit`。

- [ ] **步骤 4：运行写入器测试与数据库测试套件**

运行：`python -m pytest tests/unit/db -v`

预期：全部通过，不出现数据库锁定错误。

- [ ] **步骤 5：提交写入边界**

```powershell
git add src/gameshelf/db/writer.py tests/unit/db/test_writer.py
git commit -m "feat: serialize database writes"
```

### 任务 5：添加可取消的后台任务状态

**文件：**
- 新建：`src/gameshelf/bridge/__init__.py`
- 新建：`src/gameshelf/bridge/tasks.py`
- 新建：`tests/unit/bridge/test_tasks.py`

**接口：**
- 产出：`TaskRegistry.submit(kind, operation) -> UUID string`。
- 产出：`TaskContext.report(completed: int, total: int | None, message: str) -> None` 和 `raise_if_cancelled()`。
- 产出：不可变的 `TaskSnapshot`，包含 `id`、`kind`、`status`、`progress`、`message`、`result` 和 `error`。
- 状态值：`queued`、`running`、`completed`、`cancelled`、`failed`。

- [ ] **步骤 1：编写会失败的状态转换与取消测试**

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

- [ ] **步骤 2：运行任务测试并确认失败**

运行：`python -m pytest tests/unit/bridge/test_tasks.py -v`

预期：失败，因为任务注册表尚不存在。

- [ ] **步骤 3：实现线程安全的快照与协作式取消**

使用 `ThreadPoolExecutor`、一个 `threading.RLock`、每任务一个 `threading.Event` 以及 `dataclasses.replace` 发布不可变快照。只有项目专用的 `TaskCancelled` 才按取消处理；其他异常转为 `failed`，包含稳定的错误码和对用户安全的消息，之后再由组合根记录 traceback。

- [ ] **步骤 4：运行针对性测试与静态检查**

运行：

```powershell
python -m pytest tests/unit/bridge/test_tasks.py -v
python -m ruff check src/gameshelf/bridge tests/unit/bridge
python -m mypy src/gameshelf/bridge
```

预期：全部通过。

- [ ] **步骤 5：提交后台任务基础设施**

```powershell
git add src/gameshelf/bridge tests/unit/bridge
git commit -m "feat: add cancellable task registry"
```

### 任务 6：定义桥接响应封装与前端客户端

**文件：**
- 新建：`src/gameshelf/bridge/contracts.py`
- 新建：`src/gameshelf/bridge/api.py`
- 新建：`tests/unit/bridge/test_api.py`
- 新建：`frontend/src/api/contracts.ts`
- 新建：`frontend/src/api/bridge.ts`
- 新建：`frontend/src/api/mockBridge.ts`
- 新建：`frontend/src/api/window.d.ts`
- 新建：`frontend/tests/bridge.spec.ts`
- 修改：`frontend/src/App.vue`

**接口：**
- 使用：`AppPaths` 和 `TaskRegistry`。
- 产出 Python 方法：`bootstrap`、`task_snapshot` 和 `cancel_task`。
- 产出：具有相同方法和 `ApiResult<T>` 响应封装的 TypeScript `GameShelfBridge`。

- [ ] **步骤 1：编写会失败的后端与前端契约测试**

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

- [ ] **步骤 2：运行两组契约测试并确认失败**

运行：

```powershell
python -m pytest tests/unit/bridge/test_api.py -v
npm --prefix frontend run test:unit -- --run tests/bridge.spec.ts
```

预期：两者都失败，因为契约和客户端尚不存在。

- [ ] **步骤 3：实现相互匹配的 Python 与 TypeScript 契约**

使用以下精确的响应封装：

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

`createBridge` 只能在 `pywebviewready` 事件之后使用 `window.pywebview.api`；开发和组件测试使用 `createMockBridge()`。`App.vue` 在引导期间显示“正在连接本地数据库…”，成功后显示现有空状态。引导失败时渲染错误消息和重试按钮。

- [ ] **步骤 4：运行桥接测试、前端测试和类型检查**

运行：

```powershell
python -m pytest tests/unit/bridge -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
```

预期：全部通过。

- [ ] **步骤 5：提交类型化桥接层**

```powershell
git add src/gameshelf/bridge tests/unit/bridge frontend/src frontend/tests
git commit -m "feat: add typed desktop bridge"
```

### 任务 7：组装桌面应用与 CI 基线

**文件：**
- 新建：`src/gameshelf/bootstrap/logging.py`
- 新建：`src/gameshelf/bootstrap/application.py`
- 新建：`src/gameshelf/app.py`
- 新建：`src/gameshelf/__main__.py`
- 新建：`tests/integration/test_application_bootstrap.py`
- 新建：`.github/workflows/ci.yml`
- 修改：`README.md`

**接口：**
- 使用：此前所有基础设施接口。
- 产出：具有 `api`、`database`、`writer` 和 `tasks` 的 `build_application(paths: AppPaths) -> Application`。
- 产出：`python -m gameshelf --smoke-test` 和 `gameshelf --smoke-test`，用于初始化路径/架构并在不打开窗口的情况下退出。
- 产出：正常的 `python -m gameshelf`，用于打开 pywebview 窗口。

- [ ] **步骤 1：编写会失败的引导冒烟测试**

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

- [ ] **步骤 2：运行集成测试并确认失败**

运行：`python -m pytest tests/integration/test_application_bootstrap.py -v`

预期：失败，因为组合根尚不存在。

- [ ] **步骤 3：实现生命周期、日志、冒烟模式与 pywebview 启动**

`build_application` 必须：

1. 调用 `paths.ensure_writable()`；
2. 在 `data/logs/gameshelf.log` 配置滚动 UTF-8 日志；
3. 运行 `Migrator.migrate()`；
4. 启动 `DbWriter` 和 `TaskRegistry`；
5. 构造 `BridgeApi`；
6. 提供幂等的 `close()`，先停止任务，再停止写入器。

日志绝不能包含桥接载荷字节、剪贴板数据、注册表值或存档文件内容。普通日志可以包含本地诊断所需的用户可见路径；诊断导出不属于 V1，因此不会发生任何外部上传或导出。

开发期间正常启动前必须先构建前端，然后使用：

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

源码开发时，只有进程未被冻结打包时才接受 `GAMESHELF_DEV_SERVER_URL`；否则始终加载已打包 UI。`--smoke-test` 输出 `GameShelf bootstrap OK (schema 1)` 并以 `0` 退出。

添加 Windows CI 工作流：安装 Python 3.12 与 Node 24，运行路线图中的集成门禁，并且绝不打开 GUI。

- [ ] **步骤 4：构建 UI 并运行完整基础设施门禁**

运行：

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

预期：冒烟输出包含架构版本 `1`；所有检查均以 `0` 退出。

- [ ] **步骤 5：提交可运行的基础设施**

```powershell
git add src tests frontend README.md .github resources/ui
git commit -m "feat: boot portable GameShelf shell"
```

## 基础设施验收门禁

- `python -m gameshelf --smoke-test` 能初始化任意可写的应用根目录，且不接触用户配置文件存储位置。
- 正常启动会打开一个空的 GameShelf 窗口，并将 WebView 状态持久化到 `data/webview` 下。
- 架构版本为 `1`；外键和 WAL 已启用。
- 后台任务取消和数据库串行化均由确定性测试覆盖。
- Python 与 TypeScript 桥接方法名称及响应封装相互匹配。
- 完整的后端/前端测试、lint、类型检查及构建命令全部通过。
