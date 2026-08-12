# GameShelf V1 Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved GameShelf V1 as a portable Windows 10/11 x64 application through seven independently reviewable, working increments.

**Architecture:** A Vue 3/TypeScript frontend runs inside pywebview and calls a narrow typed Python bridge. Python owns SQLite, scanning, Windows integration, engine recognition, cover processing, and save discovery; every application-owned persistent file lives under the executable-adjacent `data` directory.

**Tech Stack:** Python 3.12, pywebview 6.2.x/WebView2, SQLite, Vue 3, TypeScript, Vite, Vitest, pytest, Pillow, watchdog, psutil, pefile, PyYAML, RapidFuzz, PyInstaller 6.21.x, Node.js 24 LTS.

## Global Constraints

- Target only Windows 10 and Windows 11 x64 for V1; development tests may run on other hosts only when the tested unit is platform-neutral.
- Ship a PyInstaller `onedir` build, never `onefile`.
- Keep configuration, database, covers, manifests, webview state, backups, logs, and temp files beneath executable-adjacent `data/`.
- Default to offline operation; only an explicit Ludusavi update action may access the network.
- Never upload game names, paths, save paths, file lists, or save content.
- Never execute an EXE while scanning; execute only the user-selected main program from an explicit launch action or save-detection session.
- Never delete, move, unpack, or modify user game/save files.
- Preserve manual title, executable, engine, and save-path choices across scans.
- Treat engine identification as optional metadata: unknown-engine Windows games must remain fully usable.
- Require user confirmation before linking orphan saves or accepting dynamically detected save locations.
- Do not implement translation, resource extraction, DLL injection, cheats, or save backup/restore in V1.
- Use TDD for behavioral changes, run focused tests before broad suites, and commit after every task.
- Use Python argument arrays with `shell=False`; never construct shell commands from UI input.
- Do not publish the repository until the user has made the final project-license decision.

---

## Why the Work Is Split

The approved specification spans seven subsystems with different failure modes. Each linked plan ends in an executable increment that a reviewer can accept or reject without obscuring failures in later work.

| Increment | Plan | Working deliverable |
|---|---|---|
| 1 | [Foundation and desktop shell](2026-08-12-gameshelf-01-foundation.md) | An empty portable GameShelf window backed by migrated SQLite and a typed bridge |
| 2 | [Library scan and launch](2026-08-12-gameshelf-02-library-scan-launch.md) | Multiple roots scan into a persistent library; games can be launched and folders opened |
| 3 | [Covers and library UX](2026-08-12-gameshelf-03-covers-library-ui.md) | Cover grid, detail drawer, search/filter, local selection, and clipboard paste |
| 4 | [Engine recognition](2026-08-12-gameshelf-04-engine-recognition.md) | Approved formal and experimental engine recognizers with evidence and manual override |
| 5 | [Static save locations](2026-08-12-gameshelf-05-static-save-locations.md) | Multiple save paths, portable templates, Ludusavi rules, and engine save hints |
| 6 | [Dynamic and orphan save discovery](2026-08-12-gameshelf-06-dynamic-orphan-saves.md) | Guided monitoring, scored candidates, expanded scan, and orphan review |
| 7 | [Portable packaging and release](2026-08-12-gameshelf-07-portable-release.md) | Reproducible onedir package with fixed WebView2 runtime and clean-machine checks |

## Dependency Order

```text
01 Foundation
  └─ 02 Library scan + launch
       ├─ 03 Covers + library UX
       └─ 04 Engine recognition
            └─ 05 Static save locations
                 └─ 06 Dynamic/orphan saves
                      └─ 07 Portable release
```

Plans 03 and 04 may be developed in either order after Plan 02, but both must be complete before Plan 05 is accepted. All other dependencies are sequential.

## Locked File Structure

```text
GameShelf/
├─ pyproject.toml
├─ README.md
├─ THIRD_PARTY_NOTICES.md
├─ frontend/
│  ├─ package.json
│  ├─ package-lock.json
│  ├─ vite.config.ts
│  ├─ vitest.config.ts
│  ├─ src/
│  │  ├─ api/                        # bridge contracts and client
│  │  ├─ app/                        # application shell and routing
│  │  ├─ features/library/
│  │  ├─ features/scan-roots/
│  │  ├─ features/covers/
│  │  ├─ features/engines/
│  │  └─ features/saves/
│  └─ tests/
├─ src/gameshelf/
│  ├─ app.py                         # composition root and desktop entry
│  ├─ bootstrap/                     # portable paths, logging, startup
│  ├─ bridge/                        # pywebview whitelist and task progress
│  ├─ db/                            # SQLite connection, migrations, writer
│  ├─ library/                       # game/root models, repositories, services
│  ├─ scanning/                      # path keys, discovery, EXE ranking
│  ├─ covers/                        # import, thumbnail, asset access
│  ├─ engines/                       # recognizer interface, rules, detectors
│  ├─ saves/                         # templates, manifests, monitor, scoring
│  ├─ platform/windows/              # process, registry, filesystem, shell
│  └─ web/                           # loopback read-only UI/cover server
├─ resources/
│  ├─ ui/                            # generated Vite production output
│  ├─ manifests/
│  └─ rules/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ scripts/
├─ packaging/
└─ docs/superpowers/
```

Focused files are preferred over large `utils.py`, `services.py`, or shared “misc” modules. A feature may import platform interfaces, database infrastructure, and shared contracts, but feature modules must not import frontend build code.

Every named pytest/Vitest harness or fixture used in a plan snippet must be implemented in the same test file or its nearest feature-specific `conftest.py`/test helper during that task. Harnesses use temporary directories, in-memory fakes, or injected adapters; they must not depend on the developer's real game library, registry, clipboard, network, or installed applications.

## Cross-Plan Interfaces

These names are stable across all plans:

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

class TaskRegistry:
    def submit(self, kind: str, operation: Callable[[TaskContext], JSONValue]) -> str: ...
    def get_snapshot(self, task_id: str) -> TaskSnapshot: ...
    def cancel(self, task_id: str) -> bool: ...

class BridgeApi:
    def bootstrap(self) -> dict[str, JSONValue]: ...
    def task_snapshot(self, task_id: str) -> dict[str, JSONValue]: ...
    def cancel_task(self, task_id: str) -> dict[str, JSONValue]: ...
```

Bridge responses always use this envelope:

```ts
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string; details?: unknown } }
```

All date/time strings crossing the bridge are UTC ISO 8601. All primary IDs are UUID strings. Filesystem paths cross the bridge only as display values for explicit user-facing operations; internal asset access uses IDs.

## Integration Gates

After every increment:

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
git status --short
```

Expected result: every command exits `0`, and `git status --short` is empty after the increment commit.

Plan 07 adds the Windows packaged smoke test to this gate.

## Specification Coverage Map

| Approved design section | Implemented by |
|---|---|
| Goals, V1 scope, offline/read-only/user-confirmation principles | Global constraints in all plans; Plans 01, 02, 05, 06 |
| First-run and cached-first daily startup | Plans 01 and 02 |
| Multiple roots, modes, depth, exclusions, overlap, missing, remap/move | Plan 02 |
| EXE recommendation, manual override, arguments, working directory, safe launch | Plan 02 |
| Formal/experimental engine coverage, confidence/evidence/manual override | Plan 04 |
| Multiple save locations and portable/absolute templates | Plan 05 |
| Ludusavi bundled/manual update/custom manifests | Plan 05 |
| Guided dynamic detection, overflow fallback, process lifetime, targeted registry | Plan 06 |
| Deleted-game/orphan scans, save-only cards, link/ignore review | Plan 06 |
| Non-destructive local/clipboard cover workflow | Plan 03 |
| Cover grid, search/filter, detail drawer, error states | Plan 03 |
| Vue/pywebview/Python/SQLite architecture and concurrency | Plan 01; extended by all feature plans |
| Executable-adjacent `data`, migrations/backups, consistency | Plans 01 and 07 |
| Security/privacy/logging/resource-serving boundaries | Plans 01, 03, 06, 07 |
| Unit/integration/VM tests and V1 acceptance criteria | Every plan; final proof in Plan 07 |
| Onedir x64, fixed WebView2, third-party notices, local artifact | Plan 07 |
| Save backup/restore and other second-stage candidates excluded | Global constraints; no V1 task implements them |
