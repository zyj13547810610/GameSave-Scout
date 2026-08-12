# GameShelf 动态与孤立存档发现实施计划

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 通过引导式游戏会话寻找未知存档位置，并通过本地规则扫描发现旧存档/孤立存档，同时确保每项关联都由用户控制。

**架构：** 会话管理器结合 watchdog 文件系统事件、受限的降级快照、进程树生命周期、用户明确标记的“刚刚保存”时间点及定向注册表快照。独立的孤立存档扫描器在选定范围内评估 Ludusavi 路径和引擎/路径特征；两条流水线都持久化可解释的发现结果供用户审核，而不自动关联。

**技术栈：** 现有静态存档技术栈，加上 watchdog、psutil、SQLite、Windows 注册表适配器、RapidFuzz、Vue 3/Vitest、pytest。

## 全局约束

- 动态检测是用户明确启动的引导式会话，绝不是常驻系统监控器。
- 不得声称文件系统事件可归因于某个特定 PID；进程树只用于控制会话生命周期。
- 默认监控根目录：游戏目录、文档、保存的游戏、AppData Roaming/Local/LocalLow、可访问的 ProgramData、自定义根目录，以及已确认存档位置的父目录。
- 跳过并报告不可访问的根目录；不要求管理员权限。
- 绝不持久化高容量原始事件或注册表值；只持久化聚合证据。
- 过滤常见日志/缓存/临时/着色器/遥测/崩溃噪声，并限制候选项数量。
- 监视器溢出时，使用时间窗口元数据降级扫描，并明显标记证据不完整。
- 孤立存档发现必须由用户明确选择关联/创建仅存档卡片/忽略。
- 扩展磁盘扫描由用户选择、可取消、有明确边界，绝不静默扫描所有驱动器。
- 绝不删除、移动、编辑、备份或恢复存档文件。
- 遵循 TDD，并在每个任务完成后提交。

---

### 任务 1：对文件观察结果进行建模、聚合、过滤与评分

**文件：**
- 修改：`pyproject.toml`
- 新建：`src/gameshelf/saves/dynamic_models.py`
- 新建：`src/gameshelf/saves/noise_filters.py`
- 新建：`src/gameshelf/saves/scoring.py`
- 新建：`tests/unit/saves/test_noise_filters.py`
- 新建：`tests/unit/saves/test_scoring.py`

**接口：**
- 产出：`FileObservation(path, event_kinds, first_seen, last_seen, before, after)`。
- 产出：`ObservationAggregator.record(event)`、`mark_saved(at)` 和 `rank(context) -> tuple[SaveCandidate, ...]`。
- 产出：`SaveCandidate(path, kind, confidence, evidence, filtered_reason)`。
- 送到 UI 前，候选列表最多保留 200 项，并以确定性方式排序。

- [ ] **步骤 1：编写会失败的聚合、时间权重、重复与噪声测试**

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

- [ ] **步骤 2：添加运行时依赖并运行测试以确认失败**

将 `watchdog>=6,<7` 和 `psutil>=7,<8` 添加到依赖，重新安装，然后运行：

```powershell
python -m pytest tests/unit/saves/test_noise_filters.py tests/unit/saves/test_scoring.py -v
```

预期：失败，因为动态模型/评分尚不存在。

- [ ] **步骤 3：实现带硬过滤器且可解释的加法评分**

会话内同时使用墙上时钟 UTC 时间戳和单调时间戳：单调值用于相对评分；UTC 值用于筛选文件系统元数据及持久化会话时间。按不区分大小写的 Windows 路径键聚合；移动操作记录为源和目标两个观察项；可用时保留变更前后的大小/mtime。

应用以下初始评分贡献，再将结果限制在 `0..1`：

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

单靠文件扩展名最多贡献 `0.10`。保留证据代码和本地化详情；不存储推断出的 PID。同一父目录中有三个或更多协同变化候选文件时，将它们分组，并额外将该目录作为候选项。

- [ ] **步骤 4：运行评分测试与静态检查**

运行：

```powershell
python -m pytest tests/unit/saves/test_noise_filters.py tests/unit/saves/test_scoring.py -v
python -m ruff check src/gameshelf/saves tests/unit/saves
python -m mypy src/gameshelf/saves
```

预期：全部通过。

- [ ] **步骤 5：提交候选项评分**

```powershell
git add pyproject.toml src/gameshelf/saves tests/unit/saves
git commit -m "feat: score dynamic save observations"
```

### 任务 2：监控可访问根目录并在溢出后降级处理

**文件：**
- 新建：`src/gameshelf/saves/filesystem_monitor.py`
- 新建：`src/gameshelf/saves/fallback_scan.py`
- 新建：`tests/unit/saves/test_filesystem_monitor.py`
- 新建：`tests/unit/saves/test_fallback_scan.py`

**接口：**
- 产出：`FilesystemMonitor.start(roots, callback) -> MonitorReport` 和 `stop() -> MonitorReport`。
- 产出：`MonitorReport(active_roots, skipped_roots, overflowed_roots)`。
- 产出：`TimeWindowScanner.scan(roots, started_at, finished_at, context) -> observations`。
- 适配器公开 `mark_overflow(root)`，使平台错误/队列溢出可测试。

- [ ] **步骤 1：编写会失败的可访问根目录、事件、取消与降级测试**

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

- [ ] **步骤 2：运行监控/降级测试并确认失败**

运行：`python -m pytest tests/unit/saves/test_filesystem_monitor.py tests/unit/saves/test_fallback_scan.py -v`

预期：失败，因为监控模块尚不存在。

- [ ] **步骤 3：实现 watchdog 适配与受限元数据降级扫描**

在 Windows 上使用 watchdog `Observer`、递归调度及容量为 50,000 个规范化事件的专用有界事件队列。按根目录捕获调度时的 `PermissionError`、`FileNotFoundError` 和 `OSError`。队列饱和或监视器错误只将对应根目录标记为溢出，并继续处理其他根目录。

降级扫描器只遍历溢出或用户批准的根目录，跳过链接/重解析点和噪声目录，每处理 64 个条目检查一次取消，并选择 `mtime` 或 `ctime` 位于“会话开始前 2 秒至结束后 5 秒”范围内的文件。每个根目录最多访问 500,000 个条目，截断时要报告；降级期间绝不读取文件内容。

- [ ] **步骤 4：运行监控/降级测试与静态检查**

运行：`python -m pytest tests/unit/saves/test_filesystem_monitor.py tests/unit/saves/test_fallback_scan.py -v`

预期：全部通过。

- [ ] **步骤 5：提交文件系统监控**

```powershell
git add src/gameshelf/saves/filesystem_monitor.py src/gameshelf/saves/fallback_scan.py tests/unit/saves
git commit -m "feat: monitor save writes with overflow fallback"
```

### 任务 3：跟踪游戏进程树生命周期，但不归因文件操作

**文件：**
- 新建：`src/gameshelf/platform/windows/process_tree.py`
- 新建：`tests/unit/platform/windows/test_process_tree.py`

**接口：**
- 使用：计划 02 的安全启动配置。
- 产出：`ProcessTreeTracker.start(root_pid)`、`snapshot() -> ProcessTreeSnapshot`、`wait_until_exit(cancel, timeout)` 和 `stop_tracking()`。
- 快照只包含已知 PID 和存活状态；不声称任何文件写入归属。

- [ ] **步骤 1：编写会失败的父进程退出/子进程存活及 PID 重用测试**

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

- [ ] **步骤 2：运行进程树测试并确认失败**

运行：`python -m pytest tests/unit/platform/windows/test_process_tree.py -v`

预期：失败，因为跟踪器尚不存在。

- [ ] **步骤 3：使用创建时间标识实现 psutil 跟踪**

记录根进程和每个已观察后代的 `(pid, create_time)`。活动期间每 500 ms 轮询；保留父进程退出前已看到的后代；将 `NoSuchProcess`、`AccessDenied` 和僵尸状态作为非致命证据。没有任何已知进程存活并经过 2 秒宽限期、发生取消或达到配置超时后，`wait_until_exit` 结束。

不得添加名为 `writes`、`files_written` 或类似的方法；跟踪器严格只表示生命周期状态。

- [ ] **步骤 4：运行进程测试与静态检查**

运行：`python -m pytest tests/unit/platform/windows/test_process_tree.py -v`

预期：全部通过。

- [ ] **步骤 5：提交进程生命周期跟踪**

```powershell
git add src/gameshelf/platform/windows/process_tree.py tests/unit/platform/windows/test_process_tree.py
git commit -m "feat: track save-session process lifetime"
```

### 任务 4：仅快照定向注册表键

**文件：**
- 新建：`src/gameshelf/platform/windows/registry.py`
- 新建：`src/gameshelf/saves/registry_snapshot.py`
- 新建：`tests/unit/saves/test_registry_snapshot.py`

**接口：**
- 产出：`WindowsRegistry.key_exists`、`walk_key_metadata` 和 `open_key_in_regedit`。
- 产出：`RegistrySnapshot.capture(keys) -> RegistrySnapshot` 和 `diff(before, after) -> tuple[RegistryChange, ...]`。
- 快照存储键路径、值名称、类型以及序列化值的 SHA-256，不存储原始值内容。

- [ ] **步骤 1：编写会失败的哈希/差异/访问测试**

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

- [ ] **步骤 2：运行注册表快照测试并确认失败**

运行：`python -m pytest tests/unit/saves/test_registry_snapshot.py -v`

预期：失败，因为注册表抽象尚不存在。

- [ ] **步骤 3：实现定向且受限的注册表元数据遍历**

只接受由已确认位置/静态提示生成的规范化 HKCU/HKLM 键。每个目标最多遍历 2,000 个值/子键，深度最多八层。在内存中对 `type + length + bytes` 计算哈希，随后丢弃原始字节。访问被拒绝转为跳过键的证据。不实现全注册表监视或扫描。

- [ ] **步骤 4：运行注册表测试与静态检查**

运行：`python -m pytest tests/unit/saves/test_registry_snapshot.py -v`

预期：全部通过。

- [ ] **步骤 5：提交定向注册表比较**

```powershell
git add src/gameshelf/platform/windows/registry.py src/gameshelf/saves/registry_snapshot.py tests/unit/saves/test_registry_snapshot.py
git commit -m "feat: compare targeted save registry keys"
```

### 任务 5：编排并持久化引导式检测会话

**文件：**
- 新建：`src/gameshelf/saves/detection_session.py`
- 新建：`src/gameshelf/saves/detection_service.py`
- 新建：`tests/integration/saves/test_detection_service.py`
- 修改：`src/gameshelf/bootstrap/application.py`

**接口：**
- 产出：`SaveDetectionService.start(game_id, custom_roots) -> ActiveDetection`。
- 产出：`mark_saved(session_id)`、`stop(session_id)`、`snapshot(session_id)` 和 `accept(session_id, candidate_ids)`。
- 每个游戏最多有一个活动会话，整个应用最多同时有两个活动会话。
- 会话状态：`preparing`、`monitoring`、`settling`、`completed`、`cancelled`、`failed`。

- [ ] **步骤 1：编写会失败的状态机与持久化测试**

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

还要测试拒绝重复活动会话、进程退出时自动停止、手动停止、超时、无候选项、跳过根目录、溢出降级和定向注册表变化。

- [ ] **步骤 2：运行检测集成测试并确认失败**

运行：`python -m pytest tests/integration/saves/test_detection_service.py -v`

预期：失败，因为编排功能尚不存在。

- [ ] **步骤 3：实现完整状态机与聚合持久化**

准备阶段：

1. 解析游戏/安装/启动配置；
2. 构建默认/自定义/已确认位置父目录的监控根目录并去重；
3. 捕获定向注册表快照；
4. 启动文件系统监控器；
5. 启动游戏并开始进程跟踪；
6. 转入 `monitoring`。

在明确请求、进程树退出、取消或默认六小时超时时停止。停止后等待三秒静默期，停止监视器，对溢出根目录运行降级扫描，获取事后注册表快照，评分/聚合，最多持久化 200 条 `save_discoveries`，并且只存摘要，不存原始事件。整个会话作为一项 `TaskRegistry` 操作运行；在设置、监控轮询、静默期、降级枚举和持久化前调用 `context.raise_if_cancelled()`；取消时在 `finally` 中停止监视器与进程跟踪，并记录为 `cancelled`。

接受操作将选中路径折叠为便携模板，并在一个事务中插入已确认的 `dynamic` 位置。注册表候选项使用类型 `registry`。没有候选项时，返回 `expanded_scan` 和 `manual_select` 操作，而不是报错。

- [ ] **步骤 4：运行检测、监控、评分与持久化测试**

运行：

```powershell
python -m pytest tests/unit/saves tests/integration/saves/test_detection_service.py -v
python -m ruff check src tests
python -m mypy src
```

预期：全部通过。

- [ ] **步骤 5：提交引导式检测服务**

```powershell
git add src/gameshelf/saves src/gameshelf/bootstrap tests/integration/saves
git commit -m "feat: orchestrate guided save detection"
```

### 任务 6：构建引导式存档检测向导

**文件：**
- 修改：`src/gameshelf/bridge/api.py`
- 新建：`tests/unit/bridge/test_detection_api.py`
- 修改：`frontend/src/api/contracts.ts`
- 新建：`frontend/src/features/saves/SaveDetectionWizard.vue`
- 新建：`frontend/src/features/saves/DetectionCandidateList.vue`
- 新建：`frontend/src/features/saves/detectionStore.ts`
- 新建：`frontend/tests/SaveDetectionWizard.spec.ts`
- 修改：`frontend/src/features/library/GameDetailDrawer.vue`

**接口：**
- 添加桥接方法 `start_save_detection`、`mark_game_saved`、`stop_save_detection`、`save_detection_snapshot` 和 `accept_detection_candidates`。
- 向导状态与后端状态一致，仅在活动期间轮询。

- [ ] **步骤 1：编写会失败的向导状态测试**

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

添加跳过根目录摘要、溢出/不完整警告、无候选项、取消、游戏启动失败及注册表候选警告测试。

- [ ] **步骤 2：运行桥接/向导测试并确认失败**

运行：

```powershell
python -m pytest tests/unit/bridge/test_detection_api.py -v
npm --prefix frontend run test:unit -- --run tests/SaveDetectionWizard.spec.ts
```

预期：失败，因为端点/向导尚不存在。

- [ ] **步骤 3：实现明确的引导式流程**

启动前显示监控位置，并允许添加自定义目录。监控期间显示已用时间、进程运行状态、“我刚刚保存了”和停止按钮。完成后显示按排名排列的文件/目录/注册表候选项及高/中/低置信度和证据；默认只勾选高置信度文件系统候选项，绝不默认勾选注册表候选项。

溢出警告必须写明“部分文件事件可能遗漏，已使用时间窗口补充扫描”，不得暗示结果完整。无候选项状态提供扩展扫描和手动选择。关闭活动中的向导时，询问是否停止检测。

- [ ] **步骤 4：运行检测 UI 与后端测试套件**

运行：

```powershell
python -m pytest tests/unit/bridge/test_detection_api.py tests/integration/saves/test_detection_service.py -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
```

预期：全部通过。

- [ ] **步骤 5：提交检测向导**

```powershell
git add src/gameshelf/bridge frontend/src frontend/tests tests/unit/bridge
git commit -m "feat: guide users through save detection"
```

### 任务 7：实现基于规则及用户选择的孤立存档扫描

**文件：**
- 新建：`src/gameshelf/saves/orphan_models.py`
- 新建：`src/gameshelf/saves/orphan_scanner.py`
- 新建：`src/gameshelf/saves/legacy_patterns.py`
- 新建：`tests/unit/saves/test_legacy_patterns.py`
- 新建：`tests/integration/saves/test_orphan_scanner.py`

**接口：**
- 产出：`OrphanScanner.scan_default(context) -> OrphanScanSummary`。
- 产出：`scan_selected(roots, max_depth, context) -> OrphanScanSummary`。
- 默认扫描评估适用的 Ludusavi 已知文件夹/注册表规则及引擎旧式根目录。
- 选择扫描的深度范围为 `1..12`，默认 `6`；每个选中根目录最多访问 1,000,000 个条目。

- [ ] **步骤 1：编写会失败的已删除游戏与低置信度测试**

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

还要测试 Ludusavi 已知文件夹路径、忽略的噪声/系统目录、取消、条目/深度截断、重复发现及不自动关联游戏。

- [ ] **步骤 2：运行孤立存档测试并确认失败**

运行：`python -m pytest tests/unit/saves/test_legacy_patterns.py tests/integration/saves/test_orphan_scanner.py -v`

预期：失败，因为孤立存档扫描尚不存在。

- [ ] **步骤 3：实现默认数据库扫描与受限的选定根目录扫描**

默认扫描：

- 评估所有开头令牌无需平台商店/root 用户 ID 即可展开的 Ludusavi Windows 文件/注册表规则；
- 检查具体路径/glob 是否存在，但不读取存档内容；
- 枚举 `<winAppData>\RenPy` 的直接子目录，并检查 LocalLow 下两层深度的 Unity 式公司/产品结构；
- 只有选定/默认根目录上下文支持时，才检查常见引擎相对名称；
- 合并重复路径键并保留全部证据。

选定扫描跳过 Windows、Program Files、`$Recycle.Bin`、System Volume Information、node/浏览器缓存、链接/重解析点和用户配置的排除项。它寻找强目录结构和存档文件名组；单独一个通用存档扩展名只具有低置信度。每处理 64 个条目检查一次取消，并报告深度/条目截断。

持久化一条 `scan_sessions(kind='orphan')` 和聚合后的 `save_discoveries`。扫描期间绝不设置 `linked_game_id`。

- [ ] **步骤 4：运行孤立存档与静态清单回归测试**

运行：`python -m pytest tests/unit/saves tests/integration/saves/test_orphan_scanner.py -v`

预期：全部通过。

- [ ] **步骤 5：提交孤立存档扫描**

```powershell
git add src/gameshelf/saves tests/unit/saves tests/integration/saves
git commit -m "feat: discover orphaned save locations"
```

### 任务 8：审核、关联、创建仅存档卡片或忽略发现结果

**文件：**
- 新建：`src/gameshelf/saves/orphan_review.py`
- 修改：`src/gameshelf/bridge/api.py`
- 新建：`tests/integration/saves/test_orphan_review.py`
- 修改：`frontend/src/api/contracts.ts`
- 新建：`frontend/src/features/saves/OrphanSavePage.vue`
- 新建：`frontend/src/features/saves/OrphanSaveCard.vue`
- 新建：`frontend/src/features/saves/OrphanScanDialog.vue`
- 新建：`frontend/tests/OrphanSavePage.spec.ts`

**接口：**
- 产出：`OrphanReviewService.link(discovery_id, game_id)`、`create_save_only(discovery_id, title)` 和 `ignore(discovery_id)`。
- 添加桥接方法 `start_orphan_scan`、`list_orphan_discoveries`、`link_orphan_save`、`create_save_only_game` 和 `ignore_orphan_save`。
- `create_save_only` 在事务中创建一条 `games(status='save_only')` 记录和一个已确认的 `legacy_scan` 存档位置。

- [ ] **步骤 1：编写会失败的事务化审核测试**

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

- [ ] **步骤 2：运行审核/UI 测试并确认失败**

运行：

```powershell
python -m pytest tests/integration/saves/test_orphan_review.py -v
npm --prefix frontend run test:unit -- --run tests/OrphanSavePage.spec.ts
```

预期：失败，因为审核服务/页面尚不存在。

- [ ] **步骤 3：实现明确的审核操作与证据优先 UI**

页面可按未审核/已关联/仅存档/已忽略以及置信度/引擎筛选。每张卡片显示路径、建议游戏/引擎、证据、置信度和最近扫描时间。关联操作打开现有游戏搜索；创建仅存档卡片要求用户输入非空标题；忽略操作可通过“已忽略”筛选撤销。

关联/创建事务插入或复用已确认的存档位置，并更新发现状态。它们不会重命名、移动、检查内容或删除已发现文件。低置信度结果绝不预选任何操作。

- [ ] **步骤 4：运行完整动态/孤立存档验收门禁**

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

- [ ] **步骤 5：提交完整的孤立存档审核**

```powershell
git add src/gameshelf/saves src/gameshelf/bridge frontend/src frontend/tests tests
git commit -m "feat: review and link orphan save discoveries"
```

### 任务 9：添加真实进程/文件集成夹具

**文件：**
- 新建：`tests/fixtures/save_writer.py`
- 新建：`tests/integration/saves/test_real_save_writer_session.py`
- 修改：`README.md`

**接口：**
- 测试辅助程序从 stdin 收到 `save` 后写入指定文件，收到 `quit` 后退出。
- 无需商业游戏即可测试进程生命周期和真实 watchdog 事件传递。

- [ ] **步骤 1：编写会失败的 Windows 专用集成测试**

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

- [ ] **步骤 2：运行测试并确认失败**

运行：`python -m pytest tests/integration/saves/test_real_save_writer_session.py -v`

预期：失败，因为辅助程序/测试工具路径尚不存在。

- [ ] **步骤 3：实现确定性的辅助程序与集成适配器**

辅助程序将目标路径作为一个 argv 元素接收，创建其父目录，在收到 `save` 时写入 `b"gameshelf-test-save"` 并执行 flush/fsync，在收到 `quit` 时退出。测试工具以 `shell=False` 启动 `[sys.executable, helper, target]`，并且只监控临时父目录。测试失败时必须在 `finally` 中干净终止辅助程序。

- [ ] **步骤 4：运行 Windows 集成测试与完整增量测试**

运行：

```powershell
python -m pytest tests/integration/saves/test_real_save_writer_session.py -v
python -m pytest
```

预期：在 Windows 上全部通过；其他平台只跳过明确标记的真实监控测试。

- [ ] **步骤 5：提交真实集成夹具**

```powershell
git add tests/fixtures/save_writer.py tests/integration/saves/test_real_save_writer_session.py README.md
git commit -m "test: verify real guided save monitoring"
```

## 动态/孤立存档增量验收门禁

- 引导式会话只启动已配置游戏，记录一次或多次明确的保存标记，并正确排列测试存档。
- 进程跟踪控制生命周期，但绝不表现为文件写入归因。
- 不可访问的根目录会被报告，且无需提升权限。
- 溢出/截断会产生清晰可见的证据不完整警告，并执行受限的降级工作。
- SQLite 中不保留原始事件流或注册表值内容。
- 未经用户接受，任何候选项都不会成为存档位置。
- 默认孤立存档扫描能识别有代表性的 Ren'Py/Unity/Ludusavi 遗留存档。
- 缺少上下文的通用 `save01.dat` 保持低置信度且不命名。
- 关联、仅存档和忽略操作绝不改动已发现文件。
