# GameShelf 静态存档位置实施计划

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 让每个游戏都能拥有多个便于迁移且可由用户审核的存档位置；这些位置可由用户手动添加，也可来自 Ludusavi 或保守的引擎提示。

**架构：** 存档路径以模板形式存储，并由 Windows 已知文件夹适配器支持；仅在显示、打开或验证时展开。Ludusavi 被解析为范围受限的内部模型并在本地匹配；引擎提示只提出已存在且有证据支持的位置，手动确认始终具有最高优先级。

**技术栈：** 现有引擎/游戏库技术栈，加上 PyYAML、RapidFuzz、Windows 已知文件夹/注册表适配器、SQLite、Vue 3/Vitest、pytest。

## 全局约束

- 每个游戏支持多个目录、文件、glob 和注册表位置。
- 手动位置视为已确认，绝不被后续建议覆盖。
- 如果已知根目录可以替换绝对路径前缀，则存储便携路径模板。
- 打开 glob 时打开其最近的已存在父目录；打开注册表位置时，必须确认后才启动注册表编辑器。
- 只有用户明确操作后才更新 Ludusavi。
- 替换活动快照前先校验下载的清单；失败时保留旧快照。
- 不得将引擎提示声称为已确认的存档路径。
- 不实现存档复制、备份、恢复或修改。
- 遵循 TDD，并在每个任务完成后提交。

---

### 任务 1：展开与折叠便携存档路径模板

**文件：**
- 新建：`src/gameshelf/platform/windows/known_folders.py`
- 新建：`src/gameshelf/saves/__init__.py`
- 新建：`src/gameshelf/saves/templates.py`
- 新建：`tests/unit/saves/test_templates.py`
- 新建：`tests/unit/platform/windows/test_known_folders.py`

**接口：**
- 产出：`KnownFolders(home, app_data, local_app_data, local_app_data_low, documents, saved_games, program_data, public, windows)`。
- 产出：适当时使用 `SHGetKnownFolderPath` 的 `WindowsKnownFolderProvider.load() -> KnownFolders`。
- 产出：`PathTemplateResolver.collapse(path: Path, game_dir: Path | None) -> str`。
- 产出：`PathTemplateResolver.expand(template: str, game_dir: Path | None) -> Path`。
- 支持的令牌：`<game>`、`<home>`、`<winAppData>`、`<winLocalAppData>`、`<winLocalAppDataLow>`、`<winDocuments>`、`<winSavedGames>`、`<winProgramData>`、`<winPublic>` 和 `<winDir>`。

- [ ] **步骤 1：编写会失败的最长前缀、Unicode 与路径穿越测试**

```python
def test_collapse_uses_longest_known_prefix(fake_known_folders, resolver) -> None:
    path = Path(r"C:\Users\Alice\AppData\LocalLow\Studio\作品")
    assert resolver.collapse(path, None) == r"<winLocalAppDataLow>\Studio\作品"


def test_game_relative_path_round_trips(fake_known_folders, resolver) -> None:
    game = Path(r"D:\Games\Alice")
    template = resolver.collapse(game / "save" / "slot1.dat", game)
    assert template == r"<game>\save\slot1.dat"
    assert resolver.expand(template, game) == game / "save" / "slot1.dat"


@pytest.mark.parametrize("template", [
    r"<game>\..\OtherGame", r"<unknown>\x", r"C:\absolute\path"
])
def test_expand_rejects_escape_unknown_token_and_raw_absolute(template, resolver) -> None:
    with pytest.raises(InvalidPathTemplate):
        resolver.expand(template, Path(r"D:\Games\Alice"))
```

- [ ] **步骤 2：运行模板测试并确认失败**

运行：`python -m pytest tests/unit/saves/test_templates.py tests/unit/platform/windows/test_known_folders.py -v`

预期：失败，因为已知文件夹/模板模块尚不存在。

- [ ] **步骤 3：实现已知文件夹查找与确定性的模板转换**

对 Roaming AppData、Local AppData、Documents、Saved Games、Public 和 Windows 使用 `SHGetKnownFolderPath`；没有直接的已知文件夹 ID 时，将 LocalLow 推导为 Local 的同级目录。仅在验证 `%PROGRAMDATA%` 为绝对路径后使用它。将访问错误封装为带稳定错误码的 `KnownFolderError`。

折叠时，比较所有可用令牌根目录和 `<game>` 的规范化 Windows 键，选择最长的匹配根目录，并保留剩余路径分段原本的显示拼写。展开时，要求开头恰好有一个令牌，并拒绝后缀中的任何 `..`、驱动器、UNC 或嵌入令牌。手动选择的原始绝对路径必须先折叠再持久化，不得直接存储。

- [ ] **步骤 4：运行模板/平台测试与静态检查**

运行：

```powershell
python -m pytest tests/unit/saves/test_templates.py tests/unit/platform/windows/test_known_folders.py -v
python -m ruff check src/gameshelf/saves src/gameshelf/platform/windows tests/unit/saves tests/unit/platform/windows
python -m mypy src/gameshelf/saves src/gameshelf/platform/windows
```

预期：全部通过。

- [ ] **步骤 5：提交便携存档模板**

```powershell
git add src/gameshelf/saves src/gameshelf/platform/windows tests/unit/saves tests/unit/platform/windows
git commit -m "feat: add portable save path templates"
```

### 任务 2：持久化并验证多个存档位置

**文件：**
- 新建：`src/gameshelf/saves/models.py`
- 新建：`src/gameshelf/saves/repository.py`
- 新建：`src/gameshelf/saves/service.py`
- 新建：`tests/unit/saves/test_repository.py`
- 新建：`tests/integration/saves/test_save_location_service.py`

**接口：**
- 产出：与 V1 架构匹配的不可变 `SaveLocation`。
- 产出：`SaveLocationService.add_manual(game_id, kind, selected_path) -> SaveLocation`。
- 产出：`accept_suggestion`、`disable`、`remove`、`verify_game`、`list_for_game` 和 `open_location`。
- 产出：`SaveLocationSuggestion(kind, path_template, display_path, source, confidence, evidence)`。

- [ ] **步骤 1：编写会失败的多位置、去重与手动优先级测试**

```python
def test_game_can_have_multiple_confirmed_manual_locations(save_service, game) -> None:
    first = save_service.add_manual(game.id, "directory", r"C:\Saves\Alice")
    second = save_service.add_manual(game.id, "file", r"D:\Games\Alice\save.dat")
    assert [item.id for item in save_service.list_for_game(game.id)] == [first.id, second.id]
    assert all(item.confirmed for item in (first, second))


def test_accepting_same_suggestion_twice_deduplicates(save_service, game) -> None:
    suggestion = make_suggestion(r"<game>\save", source="engine", confidence=0.8)
    first = save_service.accept_suggestion(game.id, suggestion)
    second = save_service.accept_suggestion(game.id, suggestion)
    assert first.id == second.id
    assert len(save_service.list_for_game(game.id)) == 1


def test_verification_updates_existence_but_never_disables_manual_path(save_service, game) -> None:
    location = save_service.add_manual(game.id, "directory", r"C:\MissingSave")
    verified = save_service.verify_game(game.id)[0]
    assert verified.confirmed is True
    assert verified.enabled is True
    assert verified.exists is False
```

- [ ] **步骤 2：运行存档服务测试并确认失败**

运行：`python -m pytest tests/unit/saves/test_repository.py tests/integration/saves/test_save_location_service.py -v`

预期：失败，因为存档仓储/服务尚不存在。

- [ ] **步骤 3：实现存档位置生命周期**

手动选择的文件/目录在选择时必须存在，并通过 `PathTemplateResolver` 折叠；建议可以引用当前不存在的 glob，但用户接受前不能成为 `confirmed`。模板展开后按 `(game_id, kind, path_key)` 去重。

`verify_game` 检查文件/目录是否存在，以最多 1,000 个匹配项为上限计算 glob 匹配，并通过适配器检查注册表键是否存在。它只更新 `last_verified_at`；存在状态在 DTO 中返回，不存储为破坏性状态。

`open_location` 行为：

```text
directory -> open that directory if it exists
file      -> open its parent and select the file when supported
glob      -> open common/nearest existing non-glob parent
registry  -> require confirmed=true, then open regedit at the key through adapter
```

移除位置时只删除数据库记录。

- [ ] **步骤 4：运行存档持久化与游戏库回归测试**

运行：`python -m pytest tests/unit/saves tests/integration/saves tests/unit/library -v`

预期：全部通过。

- [ ] **步骤 5：提交存档位置持久化**

```powershell
git add src/gameshelf/saves tests/unit/saves tests/integration/saves
git commit -m "feat: persist multiple save locations"
```

### 任务 3：添加手动存档位置 UI 与打开操作

**文件：**
- 修改：`src/gameshelf/bridge/api.py`
- 新建：`tests/unit/bridge/test_save_location_api.py`
- 修改：`frontend/src/api/contracts.ts`
- 新建：`frontend/src/features/saves/SaveLocationList.vue`
- 新建：`frontend/src/features/saves/AddSaveLocationDialog.vue`
- 新建：`frontend/src/features/saves/saveLocationLabels.ts`
- 新建：`frontend/tests/SaveLocationList.spec.ts`
- 新建：`frontend/tests/AddSaveLocationDialog.spec.ts`
- 修改：`frontend/src/features/library/GameDetailDrawer.vue`

**接口：**
- 添加桥接方法 `list_save_locations`、`choose_save_path`、`add_manual_save_location`、`remove_save_location`、`verify_save_locations` 和 `open_save_location`。
- DTO 只在高级展开区域显示模板；默认使用展开后的显示路径。

- [ ] **步骤 1：编写会失败的桥接与 UI 测试**

```python
def test_manual_api_requires_game_and_supported_kind(save_api) -> None:
    result = save_api.add_manual_save_location({
        "gameId": "game-1", "kind": "socket", "selectedPath": r"C:\Save"
    })
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_save_location"
```

```ts
it('renders multiple locations with source and missing state', () => {
  const wrapper = mount(SaveLocationList, { props: { locations: [
    fixtureSave({ id: '1', source: 'manual', exists: true }),
    fixtureSave({ id: '2', source: 'engine', exists: false, confirmed: true }),
  ] } })
  expect(wrapper.findAll('[data-test="save-location"]')).toHaveLength(2)
  expect(wrapper.text()).toContain('手动添加')
  expect(wrapper.text()).toContain('当前位置不存在')
})
```

- [ ] **步骤 2：运行 API/UI 测试并确认失败**

运行：

```powershell
python -m pytest tests/unit/bridge/test_save_location_api.py -v
npm --prefix frontend run test:unit -- --run tests/SaveLocationList.spec.ts tests/AddSaveLocationDialog.spec.ts
```

预期：因 API/组件缺失而失败。

- [ ] **步骤 3：实现明确的路径选择与列表操作**

选择器为 `directory` 选择一个目录，为 `file` 选择一个文件，为 `glob` 选择一个目录并由用户输入模式；注册表路径通过文本输入，并按 `HKEY_CURRENT_USER`/`HKEY_LOCAL_MACHINE` 语法校验。显示来源、已确认/建议状态、置信度等级、最近验证时间和缺失状态。移除前需要确认；打开未确认建议前必须先显示“此路径尚未确认”提示。

- [ ] **步骤 4：运行存档 UI 与后端测试**

运行：

```powershell
python -m pytest tests/unit/bridge/test_save_location_api.py tests/integration/saves -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
```

预期：全部通过。

- [ ] **步骤 5：提交手动存档位置体验**

```powershell
git add src/gameshelf/bridge frontend/src frontend/tests tests/unit/bridge
git commit -m "feat: manage save locations from game details"
```

### 任务 4：在本地解析并匹配 Ludusavi 清单

**文件：**
- 修改：`pyproject.toml`
- 新建：`src/gameshelf/saves/ludusavi_models.py`
- 新建：`src/gameshelf/saves/ludusavi_parser.py`
- 新建：`src/gameshelf/saves/ludusavi_matcher.py`
- 新建：`tests/unit/saves/test_ludusavi_parser.py`
- 新建：`tests/unit/saves/test_ludusavi_matcher.py`
- 新建：`tests/fixtures/ludusavi/manifest.yaml`

**接口：**
- 产出：`parse_manifest(stream) -> LudusaviManifest`。
- 产出：`LudusaviMatcher.find(game: Game, install_dir: Path) -> tuple[ManifestMatch, ...]`。
- 只产出适用于 Windows 的 `files` 和 `registry` 条目；平台商店专用条件保留为证据，但在没有平台集成时绝不自行假定满足。
- 别名递归上限为 `8`；glob 展开在后续验证阶段执行，而不是在解析器加载时执行。

- [ ] **步骤 1：基于代表性夹具编写会失败的解析器/匹配器测试**

```yaml
# tests/fixtures/ludusavi/manifest.yaml
Alice Story:
  files:
    "<winAppData>/RenPy/Alice":
      tags: [save]
      when:
        - os: windows
    "<base>/config.ini":
      tags: [config]
  installDir:
    AliceGame: {}
  registry:
    HKEY_CURRENT_USER/Software/Studio/Alice:
      tags: [save]
  steam:
    id: 123
Bob:
  alias: Alice Story
```

```python
def test_parser_keeps_save_and_unspecified_entries_but_marks_config_only() -> None:
    manifest = parse_fixture_manifest()
    alice = manifest.games["Alice Story"]
    assert alice.files[0].tags == frozenset({"save"})
    assert alice.files[1].tags == frozenset({"config"})


def test_matcher_uses_title_install_dir_and_bounded_aliases(game_fixture) -> None:
    game = game_fixture(title="Alice Story", relative_dir="AliceGame")
    matches = matcher().find(game, Path(r"D:\Games\AliceGame"))
    assert matches[0].canonical_name == "Alice Story"
    assert matches[0].confidence == 1.0
    assert any(item.kind == "registry" for item in matches[0].locations)
```

- [ ] **步骤 2：添加依赖并运行测试以确认失败**

引擎规则计划已添加 PyYAML。添加 `RapidFuzz>=3.13,<4`，保留 `PyYAML>=6.0.2,<7`，重新安装，然后运行：

```powershell
python -m pytest tests/unit/saves/test_ludusavi_parser.py tests/unit/saves/test_ludusavi_matcher.py -v
```

预期：失败，因为解析器/匹配器尚不存在。

- [ ] **步骤 3：实现受支持的清单子集与评分匹配**

支持规范游戏键、`files`、`registry`、`installDir`、`alias`、`when` 和 `tags`。忽略未来出现的未知字段，而不是拒绝整个清单；但要拒绝错误类型、超过八跳的递归别名、开头没有可识别占位符的路径，以及游戏条目超过 200,000 的 YAML 对象。

匹配输入按权重从高到低排列：完全相同的规范化正式标题、完全相同的 `installDir` 基本名、检测标题、显示标题、可执行文件主干名，最后是 RapidFuzz 比率。精确匹配以 `1.0` 返回；模糊候选仅在 `>=0.86` 时返回，并标记为未确认，同时保留参与比较的名称作为证据。标签包含 `save` 或没有标签的条目成为存档建议；仅含 `config` 的条目显示为“配置”，但不会预选为存档。

将 `<base>` 展开为已知游戏安装目录，将 `<game>` 展开为匹配的 `installDir` 或正式名称，并通过 `PathTemplateResolver` 展开标准 Windows 令牌。不得虚构平台商店用户 ID 或商店根目录。

- [ ] **步骤 4：运行清单单元测试与类型检查**

运行：

```powershell
python -m pytest tests/unit/saves/test_ludusavi_parser.py tests/unit/saves/test_ludusavi_matcher.py -v
python -m ruff check src/gameshelf/saves tests/unit/saves
python -m mypy src/gameshelf/saves
```

预期：全部通过。

- [ ] **步骤 5：提交 Ludusavi 解析/匹配功能**

```powershell
git add pyproject.toml src/gameshelf/saves tests/unit/saves tests/fixtures/ludusavi
git commit -m "feat: match local games to Ludusavi rules"
```

### 任务 5：内置、更新、校验与回滚 Ludusavi 快照

**文件：**
- 新建：`src/gameshelf/saves/ludusavi_provider.py`
- 新建：`resources/manifests/ludusavi/manifest.yaml`
- 新建：`resources/manifests/ludusavi/manifest-meta.json`
- 新建：`resources/manifests/ludusavi/LICENSE`
- 新建：`scripts/update_ludusavi_snapshot.py`
- 新建：`tests/unit/saves/test_ludusavi_provider.py`
- 修改：`THIRD_PARTY_NOTICES.md`
- 新建：`src/gameshelf/saves/custom_manifest_provider.py`
- 新建：`tests/unit/saves/test_custom_manifest_provider.py`

**接口：**
- 产出：`LudusaviProvider.ensure_initial_snapshot()`、`load()`、`metadata()` 和 `update_explicitly() -> UpdateResult`。
- 产出：从 `data/manifests/custom/*.yaml` 加载的 `CustomManifestProvider.load_all() -> tuple[LudusaviManifest, ...]`。
- 更新 URL 为 `https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml`。
- 元数据存储 `etag`、`sha256`、`downloadedAt`、`sourceUrl`，以及准备发布时的上游提交。

- [ ] **步骤 1：编写会失败的初始复制、304、成功与无效下载测试**

```python
def test_initial_snapshot_copies_resource_without_network(provider, fake_http) -> None:
    provider.ensure_initial_snapshot()
    assert provider.active_manifest.exists()
    assert fake_http.calls == []


def test_explicit_update_uses_etag_and_keeps_old_file_on_invalid_yaml(provider, fake_http) -> None:
    old_hash = sha256(provider.active_manifest)
    fake_http.respond(200, b"not: [valid", headers={"ETag": '"new"'})
    result = provider.update_explicitly()
    assert result.status == "invalid"
    assert sha256(provider.active_manifest) == old_hash


def test_not_modified_does_not_rewrite_snapshot(provider, fake_http) -> None:
    before = provider.active_manifest.stat().st_mtime_ns
    fake_http.respond(304, b"")
    assert provider.update_explicitly().status == "not_modified"
    assert provider.active_manifest.stat().st_mtime_ns == before


def test_invalid_custom_manifest_is_reported_without_blocking_valid_files(custom_provider) -> None:
    custom_provider.write("valid.yaml", "Alice:\n  files:\n    <winAppData>/Alice: {}\n")
    custom_provider.write("broken.yaml", "Alice: [")
    result = custom_provider.load_all()
    assert [manifest.source_name for manifest in result.manifests] == ["valid.yaml"]
    assert result.errors[0].source_name == "broken.yaml"
```

- [ ] **步骤 2：运行提供器测试并确认失败**

运行：`python -m pytest tests/unit/saves/test_ludusavi_provider.py -v`

预期：失败，因为提供器/资源尚不存在。

- [ ] **步骤 3：实现带校验与原子替换的明确 HTTPS 更新**

使用 `urllib.request`，设置 30 秒超时、`If-None-Match`、GameShelf 用户代理、仅限 HTTPS 的 URL 和 64 MiB 响应上限。将响应流式写入 `data/temp`，计算 SHA-256，通过 `parse_manifest` 解析，然后将当前文件复制到 `data/manifests/ludusavi/previous/`，再用 `os.replace` 替换为校验通过的下载文件。最多保留两个旧清单。

维护者脚本从同一 URL 下载并校验清单，通过 GitHub commits API 获取上游 HEAD 提交，写入精确元数据，并复制上游 MIT 许可证。它是发布维护命令，绝不是应用启动时的自动操作。

`CustomManifestProvider` 从 `data/manifests/custom` 按文件名排序加载 UTF-8 `.yaml`/`.yml` 文件，应用同一解析器；每个文件上限 8 MiB，目录上限 100 个文件；禁止跨文件别名；返回每个文件的错误，但不阻塞内置/活动清单。自定义匹配将源文件名显示为证据；只有用户在本地放置该文件时，才覆盖相同的正式名称/路径规则。

- [ ] **步骤 4：生成固定版本的资源快照并运行提供器测试**

运行：

```powershell
python scripts/update_ludusavi_snapshot.py
python -m pytest tests/unit/saves/test_ludusavi_provider.py tests/unit/saves/test_custom_manifest_provider.py -v
```

预期：资源清单可正常解析，元数据包含 64 字符 SHA-256，测试通过。网络不可用时不得提交空资源；待网络恢复后重新运行。

- [ ] **步骤 5：提交带许可证的本地快照提供器**

```powershell
git add src/gameshelf/saves resources/manifests/ludusavi scripts/update_ludusavi_snapshot.py tests/unit/saves THIRD_PARTY_NOTICES.md
git commit -m "feat: manage validated Ludusavi snapshots"
```

### 任务 6：生成保守的引擎存档提示

**文件：**
- 新建：`src/gameshelf/saves/engine_hints.py`
- 新建：`tests/unit/saves/test_engine_hints.py`

**接口：**
- 产出：`EngineSaveHintProvider.suggest(game, install_dir, engine_metadata) -> tuple[SaveLocationSuggestion, ...]`。
- 提示包含来源 `engine`、置信度和证据；接受前不持久化。

- [ ] **步骤 1：编写会失败的已知布局与无证据测试**

```python
def test_renpy_reads_literal_save_directory_and_suggests_appdata(file_tree, hint_provider) -> None:
    root = file_tree({"game/options.rpy": b'define config.save_directory = "Alice-123"'})
    suggestions = hint_provider.suggest(game(engine="renpy"), root, {})
    assert suggestions[0].path_template == r"<winAppData>\RenPy\Alice-123"
    assert suggestions[0].confidence >= 0.9


def test_unity_requires_company_and_product_before_local_low_hint(hint_provider) -> None:
    assert hint_provider.suggest(game(engine="unity"), Path(r"D:\Game"), {}) == ()


def test_install_relative_hint_is_returned_only_when_path_or_matching_files_exist(
    file_tree, hint_provider
) -> None:
    empty = file_tree({})
    assert hint_provider.suggest(game(engine="rpg_maker_vx_ace"), empty, {}) == ()
```

- [ ] **步骤 2：运行提示测试并确认失败**

运行：`python -m pytest tests/unit/saves/test_engine_hints.py -v`

预期：失败，因为提示提供器尚不存在。

- [ ] **步骤 3：只实现有证据支持的提示**

支持以下 V1 提示：

```text
Ren'Py             literal config.save_directory -> <winAppData>\RenPy\...
Unity              reliable company+product -> <winLocalAppDataLow>\Company\Product
Unity PlayerPrefs  reliable company+product -> HKCU\Software\Company\Product
RPG Maker 2k/2k3   existing Save*.lsd under <game>
RPG Maker XP       existing Save*.rxdata under <game>
RPG Maker VX       existing Save*.rvdata under <game>
RPG Maker VX Ace   existing Save*.rvdata2 under <game>
RPG Maker MV       existing save/*.rpgsave under <game> or <game>\www
RPG Maker MZ       existing save/*.rmmzsave under <game> or <game>\www
WOLF RPG           existing Save/Data save directory or matching save files below <game>
KiriKiri           existing .sav/.data files in a directory named save/savedata
NScripter family   existing save*.dat/envdata/kidoku.dat under <game>
```

只解析 Ren'Py 字面量赋值；不得执行 Python。将公司/产品名清理为安全的路径分段，并拒绝分隔符/控制字符。对于没有稳定标准路径的其他正式引擎，不返回提示，改为依赖动态检测。

- [ ] **步骤 4：运行提示与引擎回归测试**

运行：`python -m pytest tests/unit/saves/test_engine_hints.py tests/unit/engines -v`

预期：全部通过。

- [ ] **步骤 5：提交引擎存档提示**

```powershell
git add src/gameshelf/saves/engine_hints.py tests/unit/saves/test_engine_hints.py
git commit -m "feat: suggest conservative engine save paths"
```

### 任务 7：展示并接受静态存档建议

**文件：**
- 新建：`src/gameshelf/saves/static_discovery.py`
- 修改：`src/gameshelf/bridge/api.py`
- 新建：`tests/integration/saves/test_static_discovery.py`
- 修改：`frontend/src/api/contracts.ts`
- 新建：`frontend/src/features/saves/SaveSuggestionList.vue`
- 新建：`frontend/src/features/saves/LudusaviSettings.vue`
- 新建：`frontend/tests/SaveSuggestionList.spec.ts`
- 新建：`frontend/tests/LudusaviSettings.spec.ts`
- 修改：`frontend/src/features/library/GameDetailDrawer.vue`

**接口：**
- 产出：`StaticSaveDiscovery.suggest_for_game(game_id) -> tuple[SaveLocationSuggestion, ...]`。
- 添加桥接方法 `suggest_save_locations`、`accept_save_suggestions`、`ludusavi_status` 和 `update_ludusavi`。
- `update_ludusavi` 在 `TaskRegistry` 中运行，绝不在启动时运行。

- [ ] **步骤 1：编写会失败的合并/去重与 UI 确认测试**

```python
def test_static_discovery_merges_same_path_and_keeps_strongest_evidence(static_harness) -> None:
    static_harness.ludusavi_suggest(r"<winAppData>\RenPy\Alice", 1.0)
    static_harness.engine_suggest(r"<winAppData>\RenPy\Alice", 0.9)
    suggestions = static_harness.discover()
    assert len(suggestions) == 1
    assert suggestions[0].confidence == 1.0
    assert {item["source"] for item in suggestions[0].evidence} == {"ludusavi", "engine"}
```

```ts
it('does not persist suggestions until checked and accepted', async () => {
  const bridge = createMockBridge()
  const wrapper = mount(SaveSuggestionList, {
    props: { suggestions: [fixtureSuggestion({ id: 's1' })], bridge },
  })
  await wrapper.get('[data-test="accept-selected"]').trigger('click')
  expect(bridge.accept_save_suggestions).not.toHaveBeenCalled()
  await wrapper.get('[data-test="suggestion-s1"]').setValue(true)
  await wrapper.get('[data-test="accept-selected"]').trigger('click')
  expect(bridge.accept_save_suggestions).toHaveBeenCalledTimes(1)
})
```

- [ ] **步骤 2：运行静态发现/UI 测试并确认失败**

运行：

```powershell
python -m pytest tests/integration/saves/test_static_discovery.py -v
npm --prefix frontend run test:unit -- --run tests/SaveSuggestionList.spec.ts tests/LudusaviSettings.spec.ts
```

预期：失败，因为编排/UI 尚不存在。

- [ ] **步骤 3：合并来源、公开证据并要求明确接受**

先运行自定义清单，再进行 Ludusavi 精确匹配，最后运行引擎提示。按展开后的类型/路径键去重，保留全部证据，手动已有位置优先于建议，绝不建议已经确认的位置。UI 将精确、可能和实验性提示分组；低于高置信度的项都不预先勾选；注册表提示始终要求额外确认。设置页显示 `data/manifests/custom`，提供“打开自定义规则目录”操作，并显示每个文件的解析错误；V1 在应用外编辑这些 YAML 文件。

设置视图显示内置/活动清单来源、时间戳、SHA-256 前缀、ETag、更新操作、进度、“已是最新”、无效下载回滚和最近错误。V1 中不提供自动更新开关。

- [ ] **步骤 4：运行静态存档验收门禁**

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

- [ ] **步骤 5：提交完整的静态存档发现功能**

```powershell
git add src frontend tests
git commit -m "feat: review static save location suggestions"
```

## 静态存档增量验收门禁

- 一个游戏可以保留多个已确认的目录/文件/glob/注册表位置。
- 已知文件夹路径和游戏相对路径可通过便携模板正确往返转换。
- 手动选择绝不会被静默禁用或覆盖。
- Ludusavi 使用内置本地快照运行，启动时不发起网络请求。
- 明确更新操作会校验并原子替换清单，失败时回滚。
- Ludusavi 精确匹配和模糊匹配可以区分，并在适当情况下要求用户审核。
- 引擎提示仅限稳定元数据或已存在的匹配文件。
- 不复制、编辑、备份或恢复任何存档数据。
