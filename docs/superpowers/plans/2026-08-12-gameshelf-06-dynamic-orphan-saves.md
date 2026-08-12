# GameShelf Dynamic and Orphan Save Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find unknown save locations through a guided game session and discover legacy/orphan saves through local rule-based scans, while keeping every association user-controlled.

**Architecture:** A session manager combines watchdog filesystem events, bounded fallback snapshots, process-tree lifetime, explicit “just saved” timestamps, and targeted registry snapshots. A separate orphan scanner evaluates Ludusavi paths and engine/path signatures over chosen scopes; both pipelines persist explainable discoveries for review rather than auto-linking them.

**Tech Stack:** Existing static-save stack plus watchdog, psutil, SQLite, Windows registry adapter, RapidFuzz, Vue 3/Vitest, pytest.

## Global Constraints

- Dynamic detection is an explicit guided session, never an always-on system monitor.
- Do not claim filesystem events are attributable to a particular PID; process trees control session lifetime only.
- Default monitored roots: game directory, Documents, Saved Games, AppData Roaming/Local/LocalLow, accessible ProgramData, custom roots, and confirmed-save parents.
- Skip inaccessible roots and report them; do not require administrator rights.
- Never persist raw high-volume events or registry values; persist aggregated evidence only.
- Filter common log/cache/temp/shader/telemetry/crash noise and cap candidates.
- Handle observer overflow by time-window metadata fallback and visibly mark incomplete evidence.
- Orphan discoveries require explicit link/create-save-only/ignore decisions.
- Expanded disk scans are user-selected, cancellable, bounded, and never silently scan every drive.
- Never delete, move, edit, back up, or restore save files.
- Follow TDD and commit after every task.

---

### Task 1: Model, Aggregate, Filter, and Score File Observations

**Files:**
- Modify: `pyproject.toml`
- Create: `src/gameshelf/saves/dynamic_models.py`
- Create: `src/gameshelf/saves/noise_filters.py`
- Create: `src/gameshelf/saves/scoring.py`
- Create: `tests/unit/saves/test_noise_filters.py`
- Create: `tests/unit/saves/test_scoring.py`

**Interfaces:**
- Produces: `FileObservation(path, event_kinds, first_seen, last_seen, before, after)`.
- Produces: `ObservationAggregator.record(event)`, `mark_saved(at)`, and `rank(context) -> tuple[SaveCandidate, ...]`.
- Produces: `SaveCandidate(path, kind, confidence, evidence, filtered_reason)`.
- Candidate list is capped at 200 before UI and sorted deterministically.

- [ ] **Step 1: Write failing aggregation, time-weight, repetition, and noise tests**

```python
def test_repeated_events_for_same_path_are_aggregated() -> None:
    aggregator = ObservationAggregator()
    aggregator.record(event("C:/Save/slot1.dat", "created", at=10.0))
    aggregator.record(event("C:/Save/slot1.dat", "modified", at=11.0))
    assert aggregator.observations()[0].event_kinds == frozenset({"created", "modified"})
    assert aggregator.observations()[0].last_seen == 11.0


def test_just_saved_time_and_repeated_save_raise_score() -> None:
    aggregator = ObservationAggregator()
    aggregator.record(event("C:/Save/slot1.dat", "modified", at=100.2))
    aggregator.mark_saved(100.0)
    first = aggregator.rank(score_context())[0].confidence
    aggregator.record(event("C:/Save/slot1.dat", "modified", at=110.1))
    aggregator.mark_saved(110.0)
    second = aggregator.rank(score_context())[0].confidence
    assert second > first >= 0.7


@pytest.mark.parametrize("path", [
    r"C:\Users\A\AppData\Local\Game\GPUCache\data_0",
    r"C:\Users\A\AppData\Local\Game\logs\player.log",
    r"C:\Users\A\AppData\Local\Temp\crash.dmp",
    r"C:\Users\A\AppData\Local\Game\telemetry\events.json",
])
def test_common_noise_is_filtered(path: str) -> None:
    assert classify_noise(Path(path)).is_noise is True
```

- [ ] **Step 2: Add runtime dependencies and run tests to verify failure**

Add `watchdog>=6,<7` and `psutil>=7,<8` to dependencies, reinstall, then run:

```powershell
python -m pytest tests/unit/saves/test_noise_filters.py tests/unit/saves/test_scoring.py -v
```

Expected: FAIL because dynamic models/scoring are absent.

- [ ] **Step 3: Implement explainable additive scoring with hard filters**

Use a wall-clock UTC timestamp plus a monotonic timestamp inside a session: monotonic values drive relative scoring; UTC values filter filesystem metadata and persist session times. Aggregate case-insensitive Windows path keys, moves as source+destination observations, and retain before/after size/mtime where available.

Apply these initial score contributions, then clamp to `0..1`:

```text
created/modified within ±2 seconds of a save mark     +0.40
within ±10 seconds                                     +0.25
changed near two or more save marks                    +0.20
under game/known company-product/confirmed-save parent +0.15
save-like basename/extension                           +0.10
directory contains multiple coordinated changed files +0.10
log/cache/temp/shader/telemetry/crash hard filter      excluded
browser cache or unrelated high-frequency noise        -0.40
very large (>1 GiB) transient file                      -0.20
```

File extensions alone contribute at most `0.10`. Preserve evidence codes and localized detail; do not store inferred PID. Group files in the same parent when three or more coordinated candidates change, and offer the directory as an additional candidate.

- [ ] **Step 4: Run scoring tests and static checks**

Run:

```powershell
python -m pytest tests/unit/saves/test_noise_filters.py tests/unit/saves/test_scoring.py -v
python -m ruff check src/gameshelf/saves tests/unit/saves
python -m mypy src/gameshelf/saves
```

Expected: all pass.

- [ ] **Step 5: Commit candidate scoring**

```powershell
git add pyproject.toml src/gameshelf/saves tests/unit/saves
git commit -m "feat: score dynamic save observations"
```

### Task 2: Monitor Accessible Roots and Fall Back After Overflow

**Files:**
- Create: `src/gameshelf/saves/filesystem_monitor.py`
- Create: `src/gameshelf/saves/fallback_scan.py`
- Create: `tests/unit/saves/test_filesystem_monitor.py`
- Create: `tests/unit/saves/test_fallback_scan.py`

**Interfaces:**
- Produces: `FilesystemMonitor.start(roots, callback) -> MonitorReport` and `stop() -> MonitorReport`.
- Produces: `MonitorReport(active_roots, skipped_roots, overflowed_roots)`.
- Produces: `TimeWindowScanner.scan(roots, started_at, finished_at, context) -> observations`.
- Adapter exposes `mark_overflow(root)` so platform errors/queue overflow are testable.

- [ ] **Step 1: Write failing accessible-root, event, cancellation, and fallback tests**

```python
def test_monitor_skips_inaccessible_root_and_keeps_accessible_root(fake_observer, tmp_path) -> None:
    good = tmp_path / "good"
    good.mkdir()
    bad = tmp_path / "bad"
    fake_observer.fail_schedule_for(bad, PermissionError("denied"))
    report = FilesystemMonitor(fake_observer).start([good, bad], lambda event: None)
    assert report.active_roots == (good,)
    assert report.skipped_roots[0].reason == "permission_denied"


def test_overflow_root_uses_time_window_metadata_scan(tmp_path, task_context) -> None:
    root = tmp_path / "root"
    root.mkdir()
    changed = root / "slot1.dat"
    changed.write_bytes(b"save")
    set_mtime(changed, 105.0)
    observations = TimeWindowScanner().scan([root], 100.0, 110.0, task_context)
    assert [item.path for item in observations] == [changed]
```

- [ ] **Step 2: Run monitor/fallback tests and verify failure**

Run: `python -m pytest tests/unit/saves/test_filesystem_monitor.py tests/unit/saves/test_fallback_scan.py -v`

Expected: FAIL because monitor modules are absent.

- [ ] **Step 3: Implement watchdog adaptation and bounded metadata fallback**

Use watchdog `Observer` on Windows, recursive schedules, and a dedicated bounded event queue of 50,000 normalized events. Catch scheduling `PermissionError`, `FileNotFoundError`, and `OSError` per root. Queue saturation or observer error marks only that root overflowed and continues other roots.

The fallback scanner traverses only overflowed/user-approved roots, skips links/reparse points and noise directories, checks cancellation every 64 entries, and selects files whose `mtime` or `ctime` falls within session start minus 2 seconds through finish plus 5 seconds. Cap visited entries at 500,000 per root and report truncation; never read file content during fallback.

- [ ] **Step 4: Run monitor/fallback tests and static checks**

Run: `python -m pytest tests/unit/saves/test_filesystem_monitor.py tests/unit/saves/test_fallback_scan.py -v`

Expected: all pass.

- [ ] **Step 5: Commit filesystem monitoring**

```powershell
git add src/gameshelf/saves/filesystem_monitor.py src/gameshelf/saves/fallback_scan.py tests/unit/saves
git commit -m "feat: monitor save writes with overflow fallback"
```

### Task 3: Track Game Process-Tree Lifetime Without File Attribution

**Files:**
- Create: `src/gameshelf/platform/windows/process_tree.py`
- Create: `tests/unit/platform/windows/test_process_tree.py`

**Interfaces:**
- Consumes: the safe launch configuration from Plan 02.
- Produces: `ProcessTreeTracker.start(root_pid)`, `snapshot() -> ProcessTreeSnapshot`, `wait_until_exit(cancel, timeout)`, and `stop_tracking()`.
- Snapshot contains known PIDs and alive state only; it has no file-write claims.

- [ ] **Step 1: Write failing parent-exit/child-survival and PID-reuse tests**

```python
def test_tracker_stays_alive_when_launcher_parent_exits_but_child_runs(fake_psutil) -> None:
    fake_psutil.add_process(10, create_time=1.0, children=[20], running=False)
    fake_psutil.add_process(20, create_time=2.0, children=[], running=True)
    tracker = ProcessTreeTracker(fake_psutil)
    tracker.start(10)
    assert tracker.snapshot().alive_pids == (20,)


def test_tracker_rejects_reused_pid_with_new_create_time(fake_psutil) -> None:
    fake_psutil.add_process(10, create_time=1.0, children=[], running=True)
    tracker = ProcessTreeTracker(fake_psutil)
    tracker.start(10)
    fake_psutil.replace_process(10, create_time=99.0)
    assert tracker.snapshot().alive_pids == ()
```

- [ ] **Step 2: Run process-tree tests and verify failure**

Run: `python -m pytest tests/unit/platform/windows/test_process_tree.py -v`

Expected: FAIL because tracker is absent.

- [ ] **Step 3: Implement psutil tracking with create-time identity**

Capture `(pid, create_time)` for the root and every observed descendant. Poll at 500 ms while active, retain descendants seen before their parent exits, and treat `NoSuchProcess`, `AccessDenied`, and zombie states as nonfatal evidence. `wait_until_exit` ends after no known process remains for a 2-second grace period, cancellation, or configured timeout.

Do not add methods named `writes`, `files_written`, or similar; the tracker is strictly lifecycle state.

- [ ] **Step 4: Run process tests and static checks**

Run: `python -m pytest tests/unit/platform/windows/test_process_tree.py -v`

Expected: all pass.

- [ ] **Step 5: Commit process lifecycle tracking**

```powershell
git add src/gameshelf/platform/windows/process_tree.py tests/unit/platform/windows/test_process_tree.py
git commit -m "feat: track save-session process lifetime"
```

### Task 4: Snapshot Only Targeted Registry Keys

**Files:**
- Create: `src/gameshelf/platform/windows/registry.py`
- Create: `src/gameshelf/saves/registry_snapshot.py`
- Create: `tests/unit/saves/test_registry_snapshot.py`

**Interfaces:**
- Produces: `WindowsRegistry.key_exists`, `walk_key_metadata`, and `open_key_in_regedit`.
- Produces: `RegistrySnapshot.capture(keys) -> RegistrySnapshot` and `diff(before, after) -> tuple[RegistryChange, ...]`.
- Snapshot stores key path, value name, type, and SHA-256 of serialized value—not raw value content.

- [ ] **Step 1: Write failing hash/diff/access tests**

```python
def test_registry_diff_reports_changed_value_without_retaining_content(fake_registry) -> None:
    fake_registry.set_value(r"HKCU\Software\Studio\Game", "Progress", b"secret-a")
    before = RegistrySnapshot.capture(fake_registry, [r"HKCU\Software\Studio\Game"])
    fake_registry.set_value(r"HKCU\Software\Studio\Game", "Progress", b"secret-b")
    after = RegistrySnapshot.capture(fake_registry, [r"HKCU\Software\Studio\Game"])
    changes = diff_registry(before, after)
    assert changes[0].value_name == "Progress"
    assert b"secret-a" not in repr(before).encode()
    assert b"secret-b" not in repr(after).encode()
```

- [ ] **Step 2: Run registry snapshot tests and verify failure**

Run: `python -m pytest tests/unit/saves/test_registry_snapshot.py -v`

Expected: FAIL because registry abstractions are absent.

- [ ] **Step 3: Implement targeted, bounded registry metadata traversal**

Accept only normalized HKCU/HKLM keys generated by confirmed/static hints. Traverse at most 2,000 values/subkeys per target and eight levels deep. Hash `type + length + bytes` in memory and discard raw bytes. Access denied becomes skipped-key evidence. There is no whole-registry watcher or scan.

- [ ] **Step 4: Run registry tests and static checks**

Run: `python -m pytest tests/unit/saves/test_registry_snapshot.py -v`

Expected: all pass.

- [ ] **Step 5: Commit targeted registry comparison**

```powershell
git add src/gameshelf/platform/windows/registry.py src/gameshelf/saves/registry_snapshot.py tests/unit/saves/test_registry_snapshot.py
git commit -m "feat: compare targeted save registry keys"
```

### Task 5: Orchestrate and Persist Guided Detection Sessions

**Files:**
- Create: `src/gameshelf/saves/detection_session.py`
- Create: `src/gameshelf/saves/detection_service.py`
- Create: `tests/integration/saves/test_detection_service.py`
- Modify: `src/gameshelf/bootstrap/application.py`

**Interfaces:**
- Produces: `SaveDetectionService.start(game_id, custom_roots) -> ActiveDetection`.
- Produces: `mark_saved(session_id)`, `stop(session_id)`, `snapshot(session_id)`, and `accept(session_id, candidate_ids)`.
- Produces one active session per game and a maximum of two active sessions application-wide.
- Session states: `preparing`, `monitoring`, `settling`, `completed`, `cancelled`, `failed`.

- [ ] **Step 1: Write failing state-machine and persistence tests**

```python
def test_detection_session_collects_save_and_requires_acceptance(detection_harness) -> None:
    active = detection_harness.start("game-1")
    detection_harness.write_file("appdata/Game/slot1.dat", at=100.2)
    detection_harness.mark_saved(active.session_id, at=100.0)
    result = detection_harness.stop(active.session_id)
    assert result.status == "completed"
    assert result.candidates[0].display_path.endswith("slot1.dat")
    assert detection_harness.save_locations("game-1") == []
    detection_harness.accept(active.session_id, [result.candidates[0].id])
    assert len(detection_harness.save_locations("game-1")) == 1


def test_detection_failure_does_not_remove_existing_locations(detection_harness) -> None:
    existing = detection_harness.add_manual_location("game-1")
    detection_harness.fail_monitor_start(PermissionError("denied"))
    result = detection_harness.start_and_wait("game-1")
    assert result.status == "failed"
    assert detection_harness.save_locations("game-1") == [existing]
```

Also test duplicate active session rejection, process exit automatic stop, manual stop, timeout, no candidates, skipped roots, overflow fallback, and targeted registry change.

- [ ] **Step 2: Run detection integration tests and verify failure**

Run: `python -m pytest tests/integration/saves/test_detection_service.py -v`

Expected: FAIL because orchestration is absent.

- [ ] **Step 3: Implement the full state machine and aggregate persistence**

Preparation:

1. resolve game/install/launch configuration;
2. build and deduplicate default/custom/confirmed-parent monitor roots;
3. capture targeted registry snapshot;
4. start filesystem monitors;
5. launch the game and start process tracking;
6. transition to `monitoring`.

Stop on explicit request, process-tree exit, cancellation, or a default six-hour timeout. After stop, wait a three-second quiet period, stop observers, run fallback for overflowed roots, take the after-registry snapshot, score/aggregate, persist at most 200 `save_discoveries`, and store summary only—not raw events. Run the whole session as one `TaskRegistry` operation and call `context.raise_if_cancelled()` during setup, monitoring polls, quiet period, fallback enumeration, and pre-persistence; cancellation stops observers and process tracking in `finally` and records `cancelled`.

Acceptance collapses selected paths to portable templates and inserts confirmed `dynamic` locations in one transaction. Registry candidates use kind `registry`. If there are no candidates, return actions `expanded_scan` and `manual_select` rather than a failure.

- [ ] **Step 4: Run detection, monitor, scoring, and persistence tests**

Run:

```powershell
python -m pytest tests/unit/saves tests/integration/saves/test_detection_service.py -v
python -m ruff check src tests
python -m mypy src
```

Expected: all pass.

- [ ] **Step 5: Commit guided detection service**

```powershell
git add src/gameshelf/saves src/gameshelf/bootstrap tests/integration/saves
git commit -m "feat: orchestrate guided save detection"
```

### Task 6: Build the Guided Save-Detection Wizard

**Files:**
- Modify: `src/gameshelf/bridge/api.py`
- Create: `tests/unit/bridge/test_detection_api.py`
- Modify: `frontend/src/api/contracts.ts`
- Create: `frontend/src/features/saves/SaveDetectionWizard.vue`
- Create: `frontend/src/features/saves/DetectionCandidateList.vue`
- Create: `frontend/src/features/saves/detectionStore.ts`
- Create: `frontend/tests/SaveDetectionWizard.spec.ts`
- Modify: `frontend/src/features/library/GameDetailDrawer.vue`

**Interfaces:**
- Adds bridge methods `start_save_detection`, `mark_game_saved`, `stop_save_detection`, `save_detection_snapshot`, and `accept_detection_candidates`.
- Wizard states mirror backend states and poll only while active.

- [ ] **Step 1: Write failing wizard-state tests**

```ts
it('guides prepare launch mark save stop and review without auto-accepting', async () => {
  const bridge = createDetectionBridgeFixture()
  const wrapper = mount(SaveDetectionWizard, { props: { gameId: 'game-1', bridge } })
  await wrapper.get('[data-test="start-detection"]').trigger('click')
  expect(wrapper.text()).toContain('游戏已启动，请在游戏中创建或覆盖一次存档')
  await wrapper.get('[data-test="mark-saved"]').trigger('click')
  expect(wrapper.text()).toContain('已记录保存时间')
  await wrapper.get('[data-test="stop-detection"]').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('[data-test="candidate"]')).not.toHaveLength(0)
  expect(bridge.accept_detection_candidates).not.toHaveBeenCalled()
})
```

Add tests for skipped-root summary, overflow/incomplete warning, no candidates, cancellation, game launch failure, and registry candidate warning.

- [ ] **Step 2: Run bridge/wizard tests and verify failure**

Run:

```powershell
python -m pytest tests/unit/bridge/test_detection_api.py -v
npm --prefix frontend run test:unit -- --run tests/SaveDetectionWizard.spec.ts
```

Expected: FAIL because endpoints/wizard are absent.

- [ ] **Step 3: Implement the explicit guided workflow**

Before launch, show monitored locations and permit adding custom directories. During monitoring, show elapsed time, process-running state, “我刚刚保存了,” and Stop. After completion, show ranked file/directory/registry candidates with high/medium/low confidence and evidence; default-check only high-confidence filesystem candidates, never registry candidates.

The overflow warning text must say “部分文件事件可能遗漏，已使用时间窗口补充扫描,” not imply completeness. No-candidate state offers expanded scan and manual selection. Closing an active wizard asks whether to stop detection.

- [ ] **Step 4: Run detection UI and backend suites**

Run:

```powershell
python -m pytest tests/unit/bridge/test_detection_api.py tests/integration/saves/test_detection_service.py -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
```

Expected: all pass.

- [ ] **Step 5: Commit the detection wizard**

```powershell
git add src/gameshelf/bridge frontend/src frontend/tests tests/unit/bridge
git commit -m "feat: guide users through save detection"
```

### Task 7: Implement Rule-Based and User-Selected Orphan Scans

**Files:**
- Create: `src/gameshelf/saves/orphan_models.py`
- Create: `src/gameshelf/saves/orphan_scanner.py`
- Create: `src/gameshelf/saves/legacy_patterns.py`
- Create: `tests/unit/saves/test_legacy_patterns.py`
- Create: `tests/integration/saves/test_orphan_scanner.py`

**Interfaces:**
- Produces: `OrphanScanner.scan_default(context) -> OrphanScanSummary`.
- Produces: `scan_selected(roots, max_depth, context) -> OrphanScanSummary`.
- Default scan evaluates applicable Ludusavi known-folder/registry rules plus engine legacy roots.
- Selected scan depth range is `1..12`, default `6`; max 1,000,000 visited entries per selected root.

- [ ] **Step 1: Write failing deleted-game and low-confidence tests**

```python
def test_default_scan_finds_renpy_and_unity_orphans(orphan_harness) -> None:
    orphan_harness.mkdir(r"<winAppData>\RenPy\Alice-123", files=["1-1-LT1.save"])
    orphan_harness.mkdir(r"<winLocalAppDataLow>\Studio\UnityGame", files=["save.dat"])
    summary = orphan_harness.scan_default()
    assert {item.engine_id for item in summary.discoveries} == {"renpy", "unity"}
    assert all(item.review_status == "unreviewed" for item in summary.discoveries)


def test_generic_save_file_without_context_stays_low_confidence(orphan_harness) -> None:
    orphan_harness.mkdir(r"E:\Old", files=["save01.dat"])
    result = orphan_harness.scan_selected([r"E:\Old"], max_depth=2)
    candidate = result.discoveries[0]
    assert candidate.suggested_game is None
    assert candidate.confidence < 0.5
```

Also test Ludusavi known-folder paths, ignored noise/system directories, cancellation, entry/depth truncation, duplicate discoveries, and no automatic game link.

- [ ] **Step 2: Run orphan tests and verify failure**

Run: `python -m pytest tests/unit/saves/test_legacy_patterns.py tests/integration/saves/test_orphan_scanner.py -v`

Expected: FAIL because orphan scanning is absent.

- [ ] **Step 3: Implement default database scan and bounded selected-root scan**

Default scan:

- evaluate every Ludusavi Windows file/registry rule whose leading token can expand without a store/root user ID;
- check concrete paths/globs for existence without reading save content;
- enumerate direct children of `<winAppData>\RenPy` and two levels beneath LocalLow for Unity-like company/product structure;
- inspect common engine-relative names only when the selected/default root context supports them;
- merge duplicate path keys and retain all evidence.

Selected scan skips Windows, Program Files, `$Recycle.Bin`, System Volume Information, node/browser caches, links/reparse points, and user-configured exclusions. It looks for strong directory structures and save filename groups; a single generic save extension is low confidence. Check cancellation every 64 entries and report depth/entry truncation.

Persist a `scan_sessions(kind='orphan')` and aggregated `save_discoveries`. Never set `linked_game_id` during scanning.

- [ ] **Step 4: Run orphan and static-manifest regression tests**

Run: `python -m pytest tests/unit/saves tests/integration/saves/test_orphan_scanner.py -v`

Expected: all pass.

- [ ] **Step 5: Commit orphan scanning**

```powershell
git add src/gameshelf/saves tests/unit/saves tests/integration/saves
git commit -m "feat: discover orphaned save locations"
```

### Task 8: Review, Link, Create Save-Only Cards, or Ignore Discoveries

**Files:**
- Create: `src/gameshelf/saves/orphan_review.py`
- Modify: `src/gameshelf/bridge/api.py`
- Create: `tests/integration/saves/test_orphan_review.py`
- Modify: `frontend/src/api/contracts.ts`
- Create: `frontend/src/features/saves/OrphanSavePage.vue`
- Create: `frontend/src/features/saves/OrphanSaveCard.vue`
- Create: `frontend/src/features/saves/OrphanScanDialog.vue`
- Create: `frontend/tests/OrphanSavePage.spec.ts`

**Interfaces:**
- Produces: `OrphanReviewService.link(discovery_id, game_id)`, `create_save_only(discovery_id, title)`, and `ignore(discovery_id)`.
- Adds bridge methods `start_orphan_scan`, `list_orphan_discoveries`, `link_orphan_save`, `create_save_only_game`, and `ignore_orphan_save`.
- `create_save_only` creates one `games(status='save_only')` row and one confirmed `legacy_scan` save location transactionally.

- [ ] **Step 1: Write failing transactional review tests**

```python
def test_create_save_only_card_is_atomic(review_harness) -> None:
    discovery = review_harness.discovery(path=r"<winAppData>\RenPy\Unknown")
    game = review_harness.create_save_only(discovery.id, "未知 Ren'Py 存档")
    assert game.status == "save_only"
    assert game.scan_root_id is None
    assert review_harness.locations(game.id)[0].source == "legacy_scan"
    assert review_harness.discovery(discovery.id).review_status == "save_only"


def test_link_requires_existing_game_and_does_not_move_files(review_harness) -> None:
    discovery = review_harness.discovery()
    before = review_harness.filesystem_snapshot()
    with pytest.raises(GameNotFound):
        review_harness.link(discovery.id, "missing-game")
    assert review_harness.filesystem_snapshot() == before
```

- [ ] **Step 2: Run review/UI tests and verify failure**

Run:

```powershell
python -m pytest tests/integration/saves/test_orphan_review.py -v
npm --prefix frontend run test:unit -- --run tests/OrphanSavePage.spec.ts
```

Expected: FAIL because review service/page are absent.

- [ ] **Step 3: Implement explicit review actions and evidence-first UI**

The page filters unreviewed/linked/save-only/ignored and confidence/engine. Each card shows display path, suggested game/engine, evidence, confidence, and last scan. Link opens an existing-game search; create-save-only requires a nonempty user title; ignore is reversible through the ignored filter.

Link/create transactions insert or reuse a confirmed save location and update discovery status. They do not rename, move, inspect content, or delete the discovered files. Low-confidence results never preselect an action.

- [ ] **Step 4: Run full dynamic/orphan acceptance gate**

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

- [ ] **Step 5: Commit completed orphan review**

```powershell
git add src/gameshelf/saves src/gameshelf/bridge frontend/src frontend/tests tests
git commit -m "feat: review and link orphan save discoveries"
```

### Task 9: Add a Real Process/File Integration Fixture

**Files:**
- Create: `tests/fixtures/save_writer.py`
- Create: `tests/integration/saves/test_real_save_writer_session.py`
- Modify: `README.md`

**Interfaces:**
- Test helper writes a requested file after receiving `save` on stdin and exits after `quit`.
- Exercises process lifetime plus real watchdog delivery without requiring a commercial game.

- [ ] **Step 1: Write the failing Windows-only integration test**

```python
@pytest.mark.skipif(sys.platform != "win32", reason="Windows watchdog integration")
def test_real_helper_write_is_ranked_after_save_mark(real_detection_harness, tmp_path) -> None:
    target = tmp_path / "profile" / "slot1.dat"
    session = real_detection_harness.start_helper(target)
    session.send("save\n")
    session.mark_saved()
    session.send("quit\n")
    result = session.wait(timeout=15)
    assert result.status == "completed"
    assert any(item.path == target and item.confidence >= 0.7 for item in result.candidates)
```

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m pytest tests/integration/saves/test_real_save_writer_session.py -v`

Expected: FAIL because the helper/harness path is absent.

- [ ] **Step 3: Implement the deterministic helper and integration adapter**

The helper accepts target path as one argv element, creates its parent, writes `b"gameshelf-test-save"` on `save`, flushes/fsyncs, and exits on `quit`. The harness launches `[sys.executable, helper, target]` with `shell=False` and monitors only the temporary parent. It must cleanly terminate the helper in `finally` on test failure.

- [ ] **Step 4: Run Windows integration and the entire increment**

Run:

```powershell
python -m pytest tests/integration/saves/test_real_save_writer_session.py -v
python -m pytest
```

Expected: all pass on Windows; only the explicitly marked real-watch test skips elsewhere.

- [ ] **Step 5: Commit the real integration fixture**

```powershell
git add tests/fixtures/save_writer.py tests/integration/saves/test_real_save_writer_session.py README.md
git commit -m "test: verify real guided save monitoring"
```

## Dynamic/Orphan Increment Acceptance Gate

- A guided session launches only the configured game, records one or more explicit save marks, and ranks the test save correctly.
- Process tracking controls lifetime but never appears as file-write attribution.
- Inaccessible roots are reported and do not require elevation.
- Overflow/truncation produces visible incomplete-evidence warnings and bounded fallback work.
- No raw event stream or registry value content remains in SQLite.
- No candidate becomes a save location without user acceptance.
- Default orphan scan can identify representative Ren'Py/Unity/Ludusavi leftovers.
- A generic `save01.dat` without context remains low confidence and unnamed.
- Link, save-only, and ignore actions never alter discovered files.
