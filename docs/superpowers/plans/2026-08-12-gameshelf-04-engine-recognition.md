# GameShelf Engine Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identify the approved MTool-listed, Galgame, Unity, and experimental engine families from bounded read-only evidence while preserving unknown games and manual corrections.

**Architecture:** A detector registry runs cheap probes before bounded inspection. Most formats use declarative file/magic rules; metadata-heavy families use focused Python detectors. Results retain every weighted evidence item, distinguish detected from adopted values, and refuse a definitive label when evidence is ambiguous.

**Tech Stack:** Existing scanning/library stack, Python protocols/dataclasses, pefile, YAML rules, pytest fixtures, Vue 3/Vitest.

## Global Constraints

- Engine recognition never controls whether a directory is allowed in the library.
- Read names, directory structure, PE metadata, small text configs, and bounded file regions only.
- Never execute, inject into, decrypt, extract, or rewrite a game.
- Never commit commercial game assets; tests use synthetic directory trees and minimal legal byte headers.
- Every result includes confidence and human-readable evidence.
- Preserve manual engine values while continuing to refresh detected suggestions.
- A weak recognizer returns unknown or “疑似”; it does not force the closest label.
- Formal support means a maintained recognizer and fixtures, not guaranteed recognition of every customized build.
- Follow TDD and commit after every task.

---

### Task 1: Build the Detector Protocol, Bounded Reader, and Registry

**Files:**
- Create: `src/gameshelf/engines/__init__.py`
- Create: `src/gameshelf/engines/models.py`
- Create: `src/gameshelf/engines/base.py`
- Create: `src/gameshelf/engines/bounded_reader.py`
- Create: `src/gameshelf/engines/registry.py`
- Create: `tests/unit/engines/test_registry.py`
- Create: `tests/unit/engines/test_bounded_reader.py`

**Interfaces:**
- Produces: `EngineEvidence(code, detail, weight, path)`.
- Produces: `EngineMatch(engine_id, variant, confidence, evidence, rule_version, experimental)`.
- Produces protocol `EngineDetector.cheap_probe(context) -> bool` and `inspect(context) -> EngineMatch | None`.
- Produces: `DetectorRegistry.detect(game_dir, executable) -> DetectionOutcome`.
- Produces bounded reads `read_prefix`, `read_suffix`, `contains_in_edges`, and `read_text_limit`.

- [ ] **Step 1: Write failing confidence, ambiguity, and read-limit tests**

```python
def test_registry_runs_inspection_only_after_cheap_probe(tmp_path) -> None:
    no = RecordingDetector("no", probe=False, confidence=1.0)
    yes = RecordingDetector("yes", probe=True, confidence=0.9)
    outcome = DetectorRegistry([no, yes]).detect(tmp_path, None)
    assert no.inspections == 0
    assert yes.inspections == 1
    assert outcome.best.engine_id == "yes"


def test_close_scores_are_reported_as_ambiguous(tmp_path) -> None:
    outcome = DetectorRegistry([
        RecordingDetector("a", True, 0.82),
        RecordingDetector("b", True, 0.78),
    ]).detect(tmp_path, None)
    assert outcome.best is None
    assert [item.engine_id for item in outcome.alternatives] == ["a", "b"]


def test_bounded_reader_never_reads_unbounded_file(tmp_path, spy_open) -> None:
    archive = tmp_path / "archive.bin"
    archive.write_bytes(b"A" * 10_000_000)
    assert contains_in_edges(archive, b"missing", edge_bytes=4096) is False
    assert spy_open.total_bytes_read <= 8192
```

- [ ] **Step 2: Run engine-core tests and verify failure**

Run: `python -m pytest tests/unit/engines/test_registry.py tests/unit/engines/test_bounded_reader.py -v`

Expected: FAIL because the engine package is absent.

- [ ] **Step 3: Implement immutable results and conservative selection**

```python
@dataclass(frozen=True)
class EngineEvidence:
    code: str
    detail: str
    weight: float
    path: str | None = None

@dataclass(frozen=True)
class EngineMatch:
    engine_id: str
    variant: str | None
    confidence: float
    evidence: tuple[EngineEvidence, ...]
    rule_version: str
    experimental: bool = False
```

Clamp confidence to `0..1`, sort by confidence then stable engine ID, require `>=0.70` for a best formal result and `>=0.80` for a best experimental result, and mark ambiguous when the top two differ by less than `0.08`. Keep at most three alternatives. A detector exception becomes diagnostic evidence/logging and must not abort other detectors.

Bounded text reads are at most 256 KiB with BOM/UTF-8/CP932 fallback; binary inspection reads at most 64 KiB per file unless a detector explicitly uses prefix+suffix limits whose sum remains 128 KiB.

- [ ] **Step 4: Run focused tests and static checks**

Run:

```powershell
python -m pytest tests/unit/engines/test_registry.py tests/unit/engines/test_bounded_reader.py -v
python -m ruff check src/gameshelf/engines tests/unit/engines
python -m mypy src/gameshelf/engines
```

Expected: all pass.

- [ ] **Step 5: Commit detector infrastructure**

```powershell
git add src/gameshelf/engines tests/unit/engines
git commit -m "feat: add bounded engine detector registry"
```

### Task 2: Implement the Declarative Rule Detector

**Files:**
- Modify: `pyproject.toml`
- Create: `src/gameshelf/engines/rule_schema.py`
- Create: `src/gameshelf/engines/rule_detector.py`
- Create: `resources/rules/engines.schema.json`
- Create: `resources/rules/engines.yaml`
- Create: `tests/unit/engines/test_rule_detector.py`

**Interfaces:**
- Produces: `load_engine_rules(path: Path) -> tuple[EngineRule, ...]` with strict unknown-key rejection.
- Produces: `RuleDetector(rule: EngineRule)`.
- Supported evidence operators: `path_exists`, `glob_exists`, `magic_at`, `edge_contains`, `text_contains`, `pe_field_contains`.
- Rule combination supports required `all`, weighted `any`, and negative evidence.

- [ ] **Step 1: Write failing schema and matching tests**

```python
def test_rule_requires_all_and_scores_any_evidence(tmp_path) -> None:
    (tmp_path / "game" / "data" / "system").mkdir(parents=True)
    (tmp_path / "game" / "data" / "system" / "Config.tjs").write_text(
        ";projectID = sample\n;System.title = Sample", encoding="utf-8"
    )
    (tmp_path / "game" / "tyrano").mkdir()
    (tmp_path / "game" / "tyrano" / "tyrano.js").write_text("TYRANO", encoding="utf-8")
    match = RuleDetector(tyrano_rule()).inspect(context_for(tmp_path / "game"))
    assert match is not None
    assert match.engine_id == "tyrano"
    assert match.confidence >= 0.9


def test_unknown_rule_key_is_rejected(tmp_path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("version: 1\nrules:\n- id: x\n  surprise: true\n", encoding="utf-8")
    with pytest.raises(RuleSchemaError, match="surprise"):
        load_engine_rules(path)
```

- [ ] **Step 2: Run rule tests and verify failure**

Add `PyYAML>=6.0.2,<7` to project dependencies, reinstall the editable package, then run: `python -m pytest tests/unit/engines/test_rule_detector.py -v`.

Expected: FAIL because the rule engine is absent.

- [ ] **Step 3: Implement strict YAML parsing and weighted evidence**

Use this stable YAML shape:

```yaml
version: "2026.08.12-1"
rules:
  - id: tyrano
    label: TyranoScript
    variant: TyranoBuilder/TyranoScript
    experimental: false
    threshold: 0.70
    all:
      - op: path_exists
        path: data/system/Config.tjs
        weight: 0.45
    any:
      - op: path_exists
        path: tyrano/tyrano.js
        weight: 0.45
      - op: text_contains
        path: data/system/Config.tjs
        value: projectID
        weight: 0.25
    negative:
      - op: path_exists
        path: Editor.exe
        weight: -0.10
```

Normalize rule-relative paths and reject absolute paths/`..`. Glob only below the game root and cap matches at 128 per evidence item. Confidence is the sum of present weights divided by the sum of positive weights, adjusted by negative evidence and clamped. Every matched operator becomes a localized evidence code; missing optional evidence is not shown as an error.

- [ ] **Step 4: Run rule tests and validate the shipped YAML**

Run:

```powershell
python -m pytest tests/unit/engines/test_rule_detector.py -v
python -c "from pathlib import Path; from gameshelf.engines.rule_schema import load_engine_rules; print(len(load_engine_rules(Path('resources/rules/engines.yaml'))))"
```

Expected: tests pass and the validation command prints at least `1`.

- [ ] **Step 5: Commit declarative engine rules**

```powershell
git add pyproject.toml src/gameshelf/engines resources/rules tests/unit/engines
git commit -m "feat: add declarative engine recognition rules"
```

### Task 3: Add RPG Maker, WOLF, Ren'Py, and Unity Detectors

**Files:**
- Create: `src/gameshelf/engines/detectors/__init__.py`
- Create: `src/gameshelf/engines/detectors/rpg_maker.py`
- Create: `src/gameshelf/engines/detectors/renpy.py`
- Create: `src/gameshelf/engines/detectors/unity.py`
- Create: `src/gameshelf/engines/detectors/wolf.py`
- Create: `tests/unit/engines/detectors/test_rpg_maker.py`
- Create: `tests/unit/engines/detectors/test_renpy.py`
- Create: `tests/unit/engines/detectors/test_unity.py`
- Create: `tests/unit/engines/detectors/test_wolf.py`

**Interfaces:**
- Produces formal IDs/variants: `rpg_maker_2k`, `rpg_maker_xp`, `rpg_maker_vx`, `rpg_maker_vx_ace`, `mkxp_z`, `rgu`, `rpg_maker_mv`, `rpg_maker_mz`, `renpy`, `unity`, and `wolf_rpg`.
- Unity match metadata may include `company_name` and `product_name` when extracted reliably.
- Tyrano/Visual Novel Maker are not misclassified as generic RPG Maker MV merely because they use NW.js.

- [ ] **Step 1: Write parameterized positive and near-negative fixtures**

```python
@pytest.mark.parametrize(("files", "engine_id", "variant"), [
    ({"RPG_RT.exe": b"MZ", "RPG_RT.ldb": b"LcfDataBase"}, "rpg_maker_2k", None),
    ({"Game.ini": b"[Game]\nLibrary=RGSS104E.dll", "Game.rgssad": b"RGSSAD"}, "rpg_maker_xp", "XP"),
    ({"Game.ini": b"[Game]\nLibrary=RGSS202E.dll", "Game.rgss2a": b"RGSS2A"}, "rpg_maker_vx", "VX"),
    ({"Game.ini": b"[Game]\nLibrary=RGSS301.dll", "Game.rgss3a": b"RGSS3A"}, "rpg_maker_vx_ace", "VX Ace"),
    ({"www/js/rpg_core.js": b"Utils.RPGMAKER_NAME = 'MV'", "www/data/System.json": b"{}"}, "rpg_maker_mv", "MV"),
    ({"js/rmmz_core.js": b"Utils.RPGMAKER_NAME = 'MZ'", "data/System.json": b"{}"}, "rpg_maker_mz", "MZ"),
])
def test_rpg_maker_variants(file_tree, files, engine_id, variant):
    root = file_tree(files)
    match = detect_with(RpgMakerDetector(), root)
    assert (match.engine_id, match.variant) == (engine_id, variant)
```

Add tests for `mkxp.json`/`mkxp-z` PE metadata, `RGU.exe`/RGSS library evidence, Ren'Py `game/*.rpyc` plus `renpy/`, Unity `UnityPlayer.dll + <exe>_Data/globalgamemanagers`, and WOLF `Game.exe + Data/BasicData/Game.dat` or encrypted `Data.wolf`. Add near-negative tests with only `Game.exe`, only `UnityPlayer.dll`, or only a `www` folder.

- [ ] **Step 2: Run detector tests and verify failure**

Run: `python -m pytest tests/unit/engines/detectors -v`

Expected: FAIL because the focused detectors are absent.

- [ ] **Step 3: Implement variant-specific combination rules**

Use these minimum high-confidence combinations:

```text
RPG Maker 2k/2k3 : RPG_RT.exe + (RPG_RT.ldb or RPG_RT.lmt)
XP/VX/VX Ace     : Game.ini Library=RGSS1/2/3 + matching archive/DLL family
MKXP-Z           : mkxp.json/mkxp.conf + executable/PE metadata containing mkxp-z
RGU              : RGU executable/PE product evidence + RGSS project/archive evidence
MV               : rpg_core.js + data/System.json, optionally package.json
MZ               : rmmz_core.js + data/System.json, optionally package.json
Ren'Py           : game directory containing .rpyc/.rpy + renpy runtime/lib evidence
Unity            : UnityPlayer.dll + executable-named *_Data + globalgamemanagers
WOLF             : Game.exe + Data/BasicData/Game.dat, or Game.exe + encrypted .wolf data
```

For Unity, read product/company metadata only from bounded supported metadata/PE fields; absent metadata does not reduce a valid Unity engine match below threshold. For MV/MZ, check both root and `www/` layouts. Do not treat a generic RGSS archive without its matching launcher/config evidence as definitive.

- [ ] **Step 4: Run detector and registry tests**

Run:

```powershell
python -m pytest tests/unit/engines -v
python -m ruff check src/gameshelf/engines tests/unit/engines
python -m mypy src/gameshelf/engines
```

Expected: all pass.

- [ ] **Step 5: Commit core RPG/runtime detectors**

```powershell
git add src/gameshelf/engines/detectors tests/unit/engines/detectors
git commit -m "feat: recognize RPG Maker RenPy Unity and WOLF"
```

### Task 4: Add the Remaining MTool-Listed Recognizers

**Files:**
- Modify: `resources/rules/engines.yaml`
- Create: `src/gameshelf/engines/detectors/creator_engines.py`
- Create: `tests/unit/engines/detectors/test_creator_engines.py`
- Create: `tests/fixtures/engines/README.md`

**Interfaces:**
- Produces formal IDs: `smile_game_builder`, `rpg_developer_bakin`, `tyrano`, `kirikiri`, `visual_novel_maker`, `choicescript`, `srpg_studio`, and `pixel_game_maker_mv`.
- KiriKiri variant is `2`, `Z`, or unknown when evidence cannot distinguish.
- A Unity-exported SMILE GAME BUILDER game may return Unity unless SGB-specific evidence exists; this is correct conservative behavior.

- [ ] **Step 1: Write failing fixtures for every MTool-listed family**

```python
@pytest.mark.parametrize(("engine_id", "files"), [
    ("tyrano", {"data/system/Config.tjs": b";projectID = sample", "tyrano/tyrano.js": b"TYRANO"}),
    ("kirikiri", {"data.xp3": b"XP3\x0d\x0a\x20\x0a\x1a\x8b\x67\x01", "startup.tjs": b"System"}),
    ("choicescript", {"scenes/startup.txt": b"*title Sample", "scenes/choicescript_stats.txt": b"*stat_chart"}),
    ("srpg_studio", {"data.dts": b"\x00DTS", "runtime.rts": b"\x00RTS"}),
    ("pixel_game_maker_mv", {"package.json": b'{"name":"ActionGameKit"}', "js/libs/AGtk.js": b"Agtk"}),
])
def test_mtool_listed_rules(engine_registry, file_tree, engine_id, files):
    outcome = engine_registry.detect(file_tree(files), None)
    assert outcome.best.engine_id == engine_id
```

Add explicit PE metadata fixtures/fakes for SMILE GAME BUILDER (`SMILE GAME BUILDER` or `SmileBoom`), RPG Developer Bakin (`RPG Developer Bakin`/`BakinPlayer`), and Visual Novel Maker (`Visual Novel Maker`) combined with their runtime data layout. Add a generic Unity/NW.js negative for each so product metadata alone or a generic runtime alone cannot misclassify.

- [ ] **Step 2: Run creator-engine tests and verify failure**

Run: `python -m pytest tests/unit/engines/detectors/test_creator_engines.py -v`

Expected: FAIL for all newly listed IDs.

- [ ] **Step 3: Add conservative formal recognizers**

Implement the following evidence policy:

```text
TyranoBuilder/Script : data/system/Config.tjs + tyrano runtime or projectID
KiriKiri 2/Z         : XP3 magic + TJS/KS/runtime evidence; variant only from reliable PE/runtime name
ChoiceScript         : scenes/startup.txt with *title + choicescript_stats.txt or ChoiceScript runtime
SRPG Studio          : paired data.dts/runtime.rts or PE product name + one data file
Pixel Game Maker MV  : AGtk runtime symbol/file + package/data structure
SMILE GAME BUILDER   : Unity base match + SGB/SmileBoom PE or managed-runtime evidence
RPG Developer Bakin  : Bakin player/product evidence + Bakin data layout
Visual Novel Maker   : VNM product/runtime evidence + VNM script/data structure
```

When only the shared Unity or NW.js base is present, return the base engine (Unity) or no specialized result. Never use a folder name alone as sufficient formal evidence.

- [ ] **Step 4: Run all formal-engine tests**

Run: `python -m pytest tests/unit/engines -v`

Expected: every approved MTool-listed engine has a positive fixture and a near-negative fixture; all tests pass.

- [ ] **Step 5: Commit remaining MTool recognizers**

```powershell
git add resources/rules src/gameshelf/engines tests/unit/engines tests/fixtures/engines
git commit -m "feat: recognize MTool-listed creator engines"
```

### Task 5: Add Formal Galgame Format Recognizers

**Files:**
- Modify: `resources/rules/engines.yaml`
- Create: `tests/unit/engines/test_galgame_rules.py`

**Interfaces:**
- Produces formal IDs: `artemis`, `reallive`, `siglus`, `bgi_ethornell`, `catsystem2`, `yuris`, and `nscripter`.
- Variant field distinguishes `RealLive`/`SiglusEngine` and `NScripter`/`ONScripter` only when evidence supports it.

- [ ] **Step 1: Write failing synthetic magic-header tests**

```python
@pytest.mark.parametrize(("engine_id", "files"), [
    ("artemis", {"data.pfs": b"pf\x00\x00", "movie.mja": b"MJA0"}),
    ("reallive", {"Gameexe.ini": b"[Window]", "seen.txt": b"PACL" + b"\x00" * 32}),
    ("bgi_ethornell", {"data.arc": b"PackFile    " + b"\x00" * 32}),
    ("catsystem2", {"data.dat": b"CsPack2" + b"\x00" * 32, "scene.cst": b"CatScene"}),
    ("yuris", {"data.ypf": b"YPF\x00" + b"\x00" * 32, "script.ybn": b"YBN"}),
    ("nscripter", {"nscript.dat": b"\x84\x00", "arc.nsa": b"\x00" * 16}),
])
def test_galgame_signature_combinations(engine_registry, file_tree, engine_id, files):
    assert engine_registry.detect(file_tree(files), None).best.engine_id == engine_id
```

Add Siglus (`SiglusEngine.exe` PE/product evidence plus `Scene.pck`/scenario data), KiriKiri already covered, BGI `BURI` + `KO ARC20`, CatSystem `KIF` INT, and ONScripter executable-name/runtime evidence. Test that a generic `.arc`, `.dat`, `.int`, `.pac`, or `Game.exe` alone does not match.

- [ ] **Step 2: Run Galgame rule tests and verify failure**

Run: `python -m pytest tests/unit/engines/test_galgame_rules.py -v`

Expected: FAIL because rules are not yet shipped.

- [ ] **Step 3: Encode combination rules with magic plus companion evidence**

Use bounded signatures derived from public format documentation/reference implementations:

```text
Artemis       : PFS "pf" + MJA0 or Artemis PE/runtime evidence
RealLive      : Gameexe.ini + SEEN "PACL" evidence
SiglusEngine  : Siglus PE/product evidence + Scene/scenario package
BGI/Ethornell : "Pack" with "File    " at offset 4, or "BURI" with "KO ARC20"
CatSystem2    : "CsPack2" DAT or "KIF" INT + CST/engine companion
YU-RIS        : YPF\0 within bounded header + YBN/engine companion
NScripter     : nscript.dat/0.txt + NSA/SAR/NS2 archive or NScripter runtime
ONScripter    : ONScripter runtime name/PE evidence + NScripter script/archive layout
```

Require at least two independent signals when an extension or four-byte magic is common. Evidence messages must name the matched file and signal without exposing file contents.

- [ ] **Step 4: Run all formal and negative tests**

Run: `python -m pytest tests/unit/engines -v`

Expected: all pass; generic extension near-negatives remain unknown.

- [ ] **Step 5: Commit formal Galgame rules**

```powershell
git add resources/rules/engines.yaml tests/unit/engines/test_galgame_rules.py
git commit -m "feat: recognize formal Galgame engine families"
```

### Task 6: Add Experimental Legacy Recognizers

**Files:**
- Modify: `resources/rules/engines.yaml`
- Create: `tests/unit/engines/test_experimental_rules.py`

**Interfaces:**
- Produces experimental IDs: `qlie`, `majiro`, `malie`, `shiina_rio`, `softpal_amusecraft`, `entis`, and `nitroplus`.
- All returned matches have `experimental=True` and require confidence `>=0.80`.

- [ ] **Step 1: Write failing strong-signature and generic-extension tests**

```python
@pytest.mark.parametrize(("engine_id", "filename", "content"), [
    ("qlie", "data.pack", b"\x00" * 32 + b"FilePackVer3.0" + b"\x00" * 32),
    ("majiro", "data.arc", b"MajiroArcV3.000\x00"),
    ("malie", "data.lib", b"LIBP" + b"\x00" * 32),
    ("shiina_rio", "data.war", b"WARC" + b"\x00" * 32),
    ("softpal_amusecraft", "data.pac", b"PAC " + b"\x00" * 32),
    ("entis", "data.noa", b"Entis\x1a" + b"\x00" * 32),
    ("nitroplus", "data.npa", b"NPA\x01" + b"\x00" * 32),
])
def test_experimental_magic(engine_registry, tmp_path, engine_id, filename, content):
    (tmp_path / filename).write_bytes(content)
    outcome = engine_registry.detect(tmp_path, None)
    assert outcome.best.engine_id == engine_id
    assert outcome.best.experimental is True
```

For each extension, add a same-extension random-content negative that stays unknown.

- [ ] **Step 2: Run experimental tests and verify failure**

Run: `python -m pytest tests/unit/engines/test_experimental_rules.py -v`

Expected: FAIL because experimental rules are absent.

- [ ] **Step 3: Add bounded strong signatures and experimental labels**

Use `FilePackVer` in bounded file edges for QLIE, `MajiroArcV`, `LIB`/`LIBP`/`LIBU` plus Malie companions, `WARC`, `VAFS`/`PAC ` plus SoftPal companions, `Entis\x1a`/`VIST\x1a`, and `NPA\x01`/`nitP`. A single generic extension never contributes confidence.

Expose “实验性识别” in the result evidence. Vendor-custom engines are not represented by a fake catch-all rule; users can manually set `custom:<label>` later through the UI.

- [ ] **Step 4: Run all engine rules and schema validation**

Run:

```powershell
python -m pytest tests/unit/engines -v
python -c "from pathlib import Path; from gameshelf.engines.rule_schema import load_engine_rules; rules=load_engine_rules(Path('resources/rules/engines.yaml')); print(len(rules))"
```

Expected: all pass and the rule count covers formal plus experimental families.

- [ ] **Step 5: Commit experimental recognizers**

```powershell
git add resources/rules/engines.yaml tests/unit/engines/test_experimental_rules.py
git commit -m "feat: add experimental legacy engine signatures"
```

### Task 7: Integrate Engine Detection into Scanning Without Overwriting Manual Values

**Files:**
- Create: `src/gameshelf/engines/service.py`
- Modify: `src/gameshelf/scanning/service.py`
- Modify: `src/gameshelf/library/models.py`
- Modify: `src/gameshelf/library/repository.py`
- Create: `tests/integration/engines/test_scan_engine_integration.py`

**Interfaces:**
- Produces: `EngineDetectionService.detect(game_dir, executable) -> DetectionOutcome`.
- Scan writes `detected_engine_id`, `detected_engine_variant`, `engine_confidence`, and evidence every successful observation.
- Scan copies detected values into adopted `engine_id`/`variant` only when `engine_is_manual` is false.

- [ ] **Step 1: Write failing scan/manual-override tests**

```python
def test_scan_adopts_detected_engine_when_not_manual(engine_scan_harness) -> None:
    game = engine_scan_harness.scan_fixture("renpy")
    assert game.detected_engine_id == "renpy"
    assert game.engine_id == "renpy"
    assert game.engine_is_manual is False


def test_scan_refreshes_suggestion_but_preserves_manual_engine(engine_scan_harness) -> None:
    game = engine_scan_harness.scan_fixture("renpy")
    engine_scan_harness.set_manual_engine(game.id, "custom:my-engine", None)
    engine_scan_harness.replace_fixture(game.id, "unity")
    refreshed = engine_scan_harness.rescan(game.id)
    assert refreshed.detected_engine_id == "unity"
    assert refreshed.engine_id == "custom:my-engine"
    assert refreshed.engine_is_manual is True
```

- [ ] **Step 2: Run integration tests and verify failure**

Run: `python -m pytest tests/integration/engines/test_scan_engine_integration.py -v`

Expected: FAIL because scanning does not call the registry.

- [ ] **Step 3: Add detection after candidate/EXE ranking and before reconciliation**

Call engine detection only for observed game candidates, not every traversed folder. Store evidence as a JSON array of `{code, detail, path, weight}` and rule version in the same scan reconciliation transaction. Ambiguous results store no `detected_engine_id` but retain alternatives in evidence. A detector failure becomes a scan warning and leaves the game usable.

- [ ] **Step 4: Run scanning and engine suites**

Run: `python -m pytest tests/unit/engines tests/integration/engines tests/integration/scanning -v`

Expected: all pass.

- [ ] **Step 5: Commit scan integration**

```powershell
git add src/gameshelf/engines/service.py src/gameshelf/scanning src/gameshelf/library tests/integration/engines
git commit -m "feat: detect engines during library scans"
```

### Task 8: Show Evidence and Support Manual Engine Overrides

**Files:**
- Modify: `src/gameshelf/bridge/api.py`
- Create: `tests/unit/bridge/test_engine_api.py`
- Modify: `frontend/src/api/contracts.ts`
- Create: `frontend/src/features/engines/EngineBadge.vue`
- Create: `frontend/src/features/engines/EngineDetails.vue`
- Create: `frontend/src/features/engines/EnginePicker.vue`
- Create: `frontend/tests/EngineDetails.spec.ts`
- Create: `frontend/tests/EnginePicker.spec.ts`
- Modify: `frontend/src/features/library/GameCard.vue`
- Modify: `frontend/src/features/library/GameDetailDrawer.vue`
- Modify: `frontend/src/features/library/LibraryToolbar.vue`
- Create: `src/gameshelf/tools/__init__.py`
- Create: `src/gameshelf/tools/detect_directory.py`

**Interfaces:**
- Adds bridge methods `list_engine_options`, `set_game_engine`, and `clear_manual_engine`.
- Game DTO includes adopted engine, detected suggestion, confidence, evidence, ambiguity, and experimental flag.
- Manual custom value is `{ engineId: 'custom', customLabel: string }`, normalized in storage to `custom:<label>`.

- [ ] **Step 1: Write failing API and UI tests**

```python
def test_manual_engine_api_rejects_empty_custom_label(engine_api) -> None:
    result = engine_api.set_game_engine({
        "gameId": "game-1", "engineId": "custom", "customLabel": "  "
    })
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_engine"
```

```ts
it('shows adopted value and a different detected suggestion', () => {
  const wrapper = mount(EngineDetails, { props: {
    adopted: { id: 'custom:mine', label: 'Mine', manual: true },
    detected: { id: 'unity', label: 'Unity', confidence: 0.94,
      evidence: [{ code: 'unity_player', detail: '发现 UnityPlayer.dll' }] },
  } })
  expect(wrapper.text()).toContain('当前：Mine')
  expect(wrapper.text()).toContain('自动建议：Unity')
  expect(wrapper.text()).toContain('发现 UnityPlayer.dll')
})
```

- [ ] **Step 2: Run engine API/UI tests and verify failure**

Run:

```powershell
python -m pytest tests/unit/bridge/test_engine_api.py -v
npm --prefix frontend run test:unit -- --run tests/EngineDetails.spec.ts tests/EnginePicker.spec.ts
```

Expected: FAIL for missing endpoints/components.

- [ ] **Step 3: Implement transparent evidence and override behavior**

Cards show only a compact adopted-engine badge. The drawer displays adopted/detected values, “疑似” for ambiguity, “实验性识别” when applicable, confidence as high/medium/low rather than fake precision, and an expandable evidence list. The picker lists all formal IDs, experimental IDs, Unknown, and Custom.

Setting Unknown is a manual override that prevents auto-adoption; clearing the override returns to the latest detected value. Changing an engine never changes save locations automatically; later save-hint generation remains an explicit reviewed action.

- [ ] **Step 4: Add a read-only detector CLI and run the acceptance gate**

Add `python -m gameshelf.tools.detect_directory "D:\Games\Sample"` as a developer command that prints JSON evidence and performs no DB writes. Then run:

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

Expected: all checks pass; the CLI exits nonzero only for invalid/unreadable input.

- [ ] **Step 5: Commit completed engine recognition**

```powershell
git add src frontend tests
git commit -m "feat: expose explainable engine recognition"
```

## Engine Increment Acceptance Gate

- Every approved formal family has at least one positive and one near-negative synthetic fixture.
- Every experimental family requires strong magic/companion evidence and is visibly marked experimental.
- Generic `.arc`, `.pac`, `.dat`, `.int`, `.lib`, `.war`, `Game.exe`, Unity, or NW.js evidence alone does not force a specialized label.
- Unknown games remain launchable and filterable.
- Manual Unknown/custom/formal choices survive scans while latest automatic evidence remains visible.
- Detection reads bounded data, never executes or extracts files, and never blocks successful library reconciliation.
