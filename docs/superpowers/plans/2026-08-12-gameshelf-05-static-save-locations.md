# GameShelf Static Save Locations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every game own multiple portable, user-reviewable save locations discovered manually, from Ludusavi, or from conservative engine hints.

**Architecture:** Save paths are stored as templates backed by Windows known-folder adapters, then expanded only for display/open/verification. Ludusavi is parsed into a narrow internal model and matched locally; engine hints propose only existing, evidence-backed locations, with manual confirmation retaining priority.

**Tech Stack:** Existing engine/library stack plus PyYAML, RapidFuzz, Windows known-folder/registry adapters, SQLite, Vue 3/Vitest, pytest.

## Global Constraints

- Support multiple directory, file, glob, and registry locations per game.
- Manual locations are confirmed and never overwritten by later suggestions.
- Store portable templates where a known root can replace an absolute prefix.
- Opening a glob opens its nearest existing parent; opening a registry location starts Registry Editor only after confirmation.
- Ludusavi updates occur only after an explicit user action.
- Validate a downloaded manifest before replacing the active snapshot; preserve the old snapshot on failure.
- Do not claim that an engine hint is a confirmed save path.
- Do not implement save copy, backup, restore, or modification.
- Follow TDD and commit after every task.

---

### Task 1: Expand and Collapse Portable Save-Path Templates

**Files:**
- Create: `src/gameshelf/platform/windows/known_folders.py`
- Create: `src/gameshelf/saves/__init__.py`
- Create: `src/gameshelf/saves/templates.py`
- Create: `tests/unit/saves/test_templates.py`
- Create: `tests/unit/platform/windows/test_known_folders.py`

**Interfaces:**
- Produces: `KnownFolders(home, app_data, local_app_data, local_app_data_low, documents, saved_games, program_data, public, windows)`.
- Produces: `WindowsKnownFolderProvider.load() -> KnownFolders` using `SHGetKnownFolderPath` where appropriate.
- Produces: `PathTemplateResolver.collapse(path: Path, game_dir: Path | None) -> str`.
- Produces: `PathTemplateResolver.expand(template: str, game_dir: Path | None) -> Path`.
- Supported tokens: `<game>`, `<home>`, `<winAppData>`, `<winLocalAppData>`, `<winLocalAppDataLow>`, `<winDocuments>`, `<winSavedGames>`, `<winProgramData>`, `<winPublic>`, and `<winDir>`.

- [ ] **Step 1: Write failing longest-prefix, Unicode, and traversal tests**

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

- [ ] **Step 2: Run template tests and verify failure**

Run: `python -m pytest tests/unit/saves/test_templates.py tests/unit/platform/windows/test_known_folders.py -v`

Expected: FAIL because known-folder/template modules are absent.

- [ ] **Step 3: Implement known-folder lookup and deterministic template conversion**

Use `SHGetKnownFolderPath` for Roaming AppData, Local AppData, Documents, Saved Games, Public, and Windows; derive LocalLow as the sibling of Local when no direct known-folder ID is available. Use `%PROGRAMDATA%` only after validating it is absolute. Wrap access errors as `KnownFolderError` with a stable code.

When collapsing, compare normalized Windows keys for all available token roots plus `<game>`, choose the longest matching root, and retain the original display spelling of remaining components. When expanding, require exactly one leading token and reject any `..`, drive, UNC, or embedded token in the suffix. Raw absolute manual selections must be collapsed before persistence rather than stored directly.

- [ ] **Step 4: Run template/platform tests and static checks**

Run:

```powershell
python -m pytest tests/unit/saves/test_templates.py tests/unit/platform/windows/test_known_folders.py -v
python -m ruff check src/gameshelf/saves src/gameshelf/platform/windows tests/unit/saves tests/unit/platform/windows
python -m mypy src/gameshelf/saves src/gameshelf/platform/windows
```

Expected: all pass.

- [ ] **Step 5: Commit portable save templates**

```powershell
git add src/gameshelf/saves src/gameshelf/platform/windows tests/unit/saves tests/unit/platform/windows
git commit -m "feat: add portable save path templates"
```

### Task 2: Persist and Verify Multiple Save Locations

**Files:**
- Create: `src/gameshelf/saves/models.py`
- Create: `src/gameshelf/saves/repository.py`
- Create: `src/gameshelf/saves/service.py`
- Create: `tests/unit/saves/test_repository.py`
- Create: `tests/integration/saves/test_save_location_service.py`

**Interfaces:**
- Produces immutable `SaveLocation` matching the V1 schema.
- Produces: `SaveLocationService.add_manual(game_id, kind, selected_path) -> SaveLocation`.
- Produces: `accept_suggestion`, `disable`, `remove`, `verify_game`, `list_for_game`, and `open_location`.
- Produces: `SaveLocationSuggestion(kind, path_template, display_path, source, confidence, evidence)`.

- [ ] **Step 1: Write failing multi-location, dedupe, and manual-priority tests**

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

- [ ] **Step 2: Run save-service tests and verify failure**

Run: `python -m pytest tests/unit/saves/test_repository.py tests/integration/saves/test_save_location_service.py -v`

Expected: FAIL because save repositories/services do not exist.

- [ ] **Step 3: Implement save-location lifecycle**

Manual file/directory inputs must exist at selection time and collapse through `PathTemplateResolver`; suggestions may reference currently missing globs but cannot become `confirmed` until the user accepts. Deduplicate by `(game_id, kind, path_key)` after template expansion.

`verify_game` checks file/directory existence, evaluates glob matches with a 1,000-match cap, and checks registry-key existence through an adapter. It updates only `last_verified_at`; existence is returned in the DTO and not stored as a destructive status.

`open_location` behavior:

```text
directory -> open that directory if it exists
file      -> open its parent and select the file when supported
glob      -> open common/nearest existing non-glob parent
registry  -> require confirmed=true, then open regedit at the key through adapter
```

Removing a location deletes only the database record.

- [ ] **Step 4: Run save persistence and library regression tests**

Run: `python -m pytest tests/unit/saves tests/integration/saves tests/unit/library -v`

Expected: all pass.

- [ ] **Step 5: Commit save-location persistence**

```powershell
git add src/gameshelf/saves tests/unit/saves tests/integration/saves
git commit -m "feat: persist multiple save locations"
```

### Task 3: Add Manual Save-Location UI and Open Actions

**Files:**
- Modify: `src/gameshelf/bridge/api.py`
- Create: `tests/unit/bridge/test_save_location_api.py`
- Modify: `frontend/src/api/contracts.ts`
- Create: `frontend/src/features/saves/SaveLocationList.vue`
- Create: `frontend/src/features/saves/AddSaveLocationDialog.vue`
- Create: `frontend/src/features/saves/saveLocationLabels.ts`
- Create: `frontend/tests/SaveLocationList.spec.ts`
- Create: `frontend/tests/AddSaveLocationDialog.spec.ts`
- Modify: `frontend/src/features/library/GameDetailDrawer.vue`

**Interfaces:**
- Adds bridge methods `list_save_locations`, `choose_save_path`, `add_manual_save_location`, `remove_save_location`, `verify_save_locations`, and `open_save_location`.
- DTO exposes template only in an advanced disclosure; default display uses expanded display path.

- [ ] **Step 1: Write failing bridge and UI tests**

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

- [ ] **Step 2: Run API/UI tests and verify failure**

Run:

```powershell
python -m pytest tests/unit/bridge/test_save_location_api.py -v
npm --prefix frontend run test:unit -- --run tests/SaveLocationList.spec.ts tests/AddSaveLocationDialog.spec.ts
```

Expected: FAIL for missing APIs/components.

- [ ] **Step 3: Implement explicit path selection and list actions**

The picker selects a directory for `directory`, one file for `file`, and a directory plus user-entered pattern for `glob`; registry paths are entered as text and validated against `HKEY_CURRENT_USER`/`HKEY_LOCAL_MACHINE` syntax. Display source, confirmed/suggested state, confidence band, last verification, and missing status. Removing requires confirmation; opening an unconfirmed suggestion is allowed only after a “此路径尚未确认” prompt.

- [ ] **Step 4: Run save UI and backend tests**

Run:

```powershell
python -m pytest tests/unit/bridge/test_save_location_api.py tests/integration/saves -v
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
```

Expected: all pass.

- [ ] **Step 5: Commit manual save-location UX**

```powershell
git add src/gameshelf/bridge frontend/src frontend/tests tests/unit/bridge
git commit -m "feat: manage save locations from game details"
```

### Task 4: Parse and Match the Ludusavi Manifest Locally

**Files:**
- Modify: `pyproject.toml`
- Create: `src/gameshelf/saves/ludusavi_models.py`
- Create: `src/gameshelf/saves/ludusavi_parser.py`
- Create: `src/gameshelf/saves/ludusavi_matcher.py`
- Create: `tests/unit/saves/test_ludusavi_parser.py`
- Create: `tests/unit/saves/test_ludusavi_matcher.py`
- Create: `tests/fixtures/ludusavi/manifest.yaml`

**Interfaces:**
- Produces: `parse_manifest(stream) -> LudusaviManifest`.
- Produces: `LudusaviMatcher.find(game: Game, install_dir: Path) -> tuple[ManifestMatch, ...]`.
- Produces only Windows-applicable `files` and `registry` entries; store-specific conditions are retained as evidence but never assumed without platform integration.
- Alias recursion limit is `8`; glob expansion occurs later in verification, not parser loading.

- [ ] **Step 1: Write failing parser/matcher tests against a representative fixture**

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

- [ ] **Step 2: Add dependencies and run tests to verify failure**

PyYAML was added by the engine-rule plan. Add `RapidFuzz>=3.13,<4`, retain `PyYAML>=6.0.2,<7`, reinstall, then run:

```powershell
python -m pytest tests/unit/saves/test_ludusavi_parser.py tests/unit/saves/test_ludusavi_matcher.py -v
```

Expected: FAIL because parser/matcher are absent.

- [ ] **Step 3: Implement the supported manifest subset and scored matching**

Support canonical game keys, `files`, `registry`, `installDir`, `alias`, `when`, and `tags`. Ignore unknown future fields rather than rejecting the whole manifest, but reject wrong types, recursive aliases beyond eight hops, paths without a recognized leading placeholder, and YAML objects above 200,000 game entries.

Match inputs in descending weight: exact normalized canonical title, exact `installDir` basename, detected title, display title, executable stem, then RapidFuzz ratio. Return exact matches at `1.0`; return fuzzy candidates only at `>=0.86`, mark them unconfirmed, and retain the compared names as evidence. Tags containing `save`, or no tags, become save suggestions; `config`-only entries are visible as “配置” but are not preselected as saves.

Expand `<base>` to the known game install directory, `<game>` to a matched `installDir` or canonical name, and standard Windows tokens through `PathTemplateResolver`. Do not invent store user IDs or store roots.

- [ ] **Step 4: Run manifest unit tests and type checks**

Run:

```powershell
python -m pytest tests/unit/saves/test_ludusavi_parser.py tests/unit/saves/test_ludusavi_matcher.py -v
python -m ruff check src/gameshelf/saves tests/unit/saves
python -m mypy src/gameshelf/saves
```

Expected: all pass.

- [ ] **Step 5: Commit Ludusavi parsing/matching**

```powershell
git add pyproject.toml src/gameshelf/saves tests/unit/saves tests/fixtures/ludusavi
git commit -m "feat: match local games to Ludusavi rules"
```

### Task 5: Bundle, Update, Validate, and Roll Back Ludusavi Snapshots

**Files:**
- Create: `src/gameshelf/saves/ludusavi_provider.py`
- Create: `resources/manifests/ludusavi/manifest.yaml`
- Create: `resources/manifests/ludusavi/manifest-meta.json`
- Create: `resources/manifests/ludusavi/LICENSE`
- Create: `scripts/update_ludusavi_snapshot.py`
- Create: `tests/unit/saves/test_ludusavi_provider.py`
- Modify: `THIRD_PARTY_NOTICES.md`
- Create: `src/gameshelf/saves/custom_manifest_provider.py`
- Create: `tests/unit/saves/test_custom_manifest_provider.py`

**Interfaces:**
- Produces: `LudusaviProvider.ensure_initial_snapshot()`, `load()`, `metadata()`, and `update_explicitly() -> UpdateResult`.
- Produces: `CustomManifestProvider.load_all() -> tuple[LudusaviManifest, ...]` from `data/manifests/custom/*.yaml`.
- Update URL is `https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml`.
- Metadata stores `etag`, `sha256`, `downloadedAt`, `sourceUrl`, and upstream commit when prepared for release.

- [ ] **Step 1: Write failing initial-copy, 304, success, and invalid-download tests**

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

- [ ] **Step 2: Run provider tests and verify failure**

Run: `python -m pytest tests/unit/saves/test_ludusavi_provider.py -v`

Expected: FAIL because provider/resources are absent.

- [ ] **Step 3: Implement explicit HTTPS update with validation and atomic replacement**

Use `urllib.request` with a 30-second timeout, `If-None-Match`, a GameShelf user agent, HTTPS-only URL, and 64 MiB response cap. Stream to `data/temp`, calculate SHA-256, parse through `parse_manifest`, then copy the current file to `data/manifests/ludusavi/previous/` and `os.replace` the validated download. Retain at most two previous manifests.

The maintainer script downloads the same URL, validates it, obtains the upstream HEAD commit through the GitHub commits API, writes exact metadata, and copies the upstream MIT license. It is a release-maintenance command, never an automatic application startup action.

`CustomManifestProvider` loads UTF-8 `.yaml`/`.yml` files sorted by filename from `data/manifests/custom`, applies the same parser, caps each file at 8 MiB and the directory at 100 files, disables aliases that cross files, and returns per-file errors without blocking the bundled/active manifest. Custom matches show their source filename as evidence and override an identical canonical/path rule only when the user placed that file locally.

- [ ] **Step 4: Generate the pinned resource snapshot and run provider tests**

Run:

```powershell
python scripts/update_ludusavi_snapshot.py
python -m pytest tests/unit/saves/test_ludusavi_provider.py tests/unit/saves/test_custom_manifest_provider.py -v
```

Expected: the resource manifest parses, metadata contains a 64-character SHA-256, and tests pass. If the network is unavailable, do not commit an empty resource; rerun when reachable.

- [ ] **Step 5: Commit the licensed local snapshot provider**

```powershell
git add src/gameshelf/saves resources/manifests/ludusavi scripts/update_ludusavi_snapshot.py tests/unit/saves THIRD_PARTY_NOTICES.md
git commit -m "feat: manage validated Ludusavi snapshots"
```

### Task 6: Generate Conservative Engine Save Hints

**Files:**
- Create: `src/gameshelf/saves/engine_hints.py`
- Create: `tests/unit/saves/test_engine_hints.py`

**Interfaces:**
- Produces: `EngineSaveHintProvider.suggest(game, install_dir, engine_metadata) -> tuple[SaveLocationSuggestion, ...]`.
- Hints include source `engine`, confidence, and evidence; they do not persist until accepted.

- [ ] **Step 1: Write failing known-layout and no-evidence tests**

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

- [ ] **Step 2: Run hint tests and verify failure**

Run: `python -m pytest tests/unit/saves/test_engine_hints.py -v`

Expected: FAIL because hint provider is absent.

- [ ] **Step 3: Implement evidence-backed hints only**

Support these V1 hints:

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

Parse only literal Ren'Py assignments; do not execute Python. Sanitize company/product as path components and reject separators/control characters. For other formal engines without stable standard paths, return no hint and rely on dynamic detection.

- [ ] **Step 4: Run hint and engine regression tests**

Run: `python -m pytest tests/unit/saves/test_engine_hints.py tests/unit/engines -v`

Expected: all pass.

- [ ] **Step 5: Commit engine save hints**

```powershell
git add src/gameshelf/saves/engine_hints.py tests/unit/saves/test_engine_hints.py
git commit -m "feat: suggest conservative engine save paths"
```

### Task 7: Present and Accept Static Save Suggestions

**Files:**
- Create: `src/gameshelf/saves/static_discovery.py`
- Modify: `src/gameshelf/bridge/api.py`
- Create: `tests/integration/saves/test_static_discovery.py`
- Modify: `frontend/src/api/contracts.ts`
- Create: `frontend/src/features/saves/SaveSuggestionList.vue`
- Create: `frontend/src/features/saves/LudusaviSettings.vue`
- Create: `frontend/tests/SaveSuggestionList.spec.ts`
- Create: `frontend/tests/LudusaviSettings.spec.ts`
- Modify: `frontend/src/features/library/GameDetailDrawer.vue`

**Interfaces:**
- Produces: `StaticSaveDiscovery.suggest_for_game(game_id) -> tuple[SaveLocationSuggestion, ...]`.
- Adds bridge methods `suggest_save_locations`, `accept_save_suggestions`, `ludusavi_status`, and `update_ludusavi`.
- `update_ludusavi` runs in `TaskRegistry` and never on startup.

- [ ] **Step 1: Write failing merge/dedupe and UI-confirmation tests**

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

- [ ] **Step 2: Run static-discovery/UI tests and verify failure**

Run:

```powershell
python -m pytest tests/integration/saves/test_static_discovery.py -v
npm --prefix frontend run test:unit -- --run tests/SaveSuggestionList.spec.ts tests/LudusaviSettings.spec.ts
```

Expected: FAIL because orchestration/UI are absent.

- [ ] **Step 3: Merge sources, expose evidence, and require explicit acceptance**

Run custom manifests first, then exact Ludusavi matching, then engine hints. Deduplicate by expanded kind/path key, retain all evidence, prefer manual-existing locations over suggestions, and never suggest a location already confirmed. UI groups exact, likely, and experimental hints; none are prechecked below high confidence, and registry hints always require an additional confirmation sentence. Settings show `data/manifests/custom` with an “打开自定义规则目录” action and per-file parse errors; V1 edits these YAML files outside the app.

The settings view shows bundled/active manifest source, timestamp, SHA-256 prefix, ETag, update action, progress, “already current,” invalid-download rollback, and last error. It contains no automatic-update toggle in V1.

- [ ] **Step 4: Run the static-save acceptance gate**

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

- [ ] **Step 5: Commit completed static save discovery**

```powershell
git add src frontend tests
git commit -m "feat: review static save location suggestions"
```

## Static Save Increment Acceptance Gate

- One game can retain multiple confirmed directory/file/glob/registry locations.
- Known-folder and game-relative paths round-trip through portable templates.
- Manual selections are never silently disabled or overwritten.
- Ludusavi works from a bundled local snapshot with no startup network request.
- An explicit update validates/atomically replaces the manifest and rolls back on failure.
- Exact and fuzzy Ludusavi matches are distinguishable and require user review where appropriate.
- Engine hints are limited to stable metadata or existing matching files.
- No save data is copied, edited, backed up, or restored.
