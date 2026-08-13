# GameShelf 游戏引擎识别实施计划

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 根据有限的只读证据识别已确认的 MTool 所列引擎、Galgame 引擎、Unity 及实验性引擎系列，同时保留未知游戏和手动修正。

**架构：** 检测器注册表先执行低成本探测，再进行受限检查。大多数格式使用声明式文件/魔数规则；依赖较多元数据的系列使用专用 Python 检测器。结果保留每条加权证据，区分检测值与采用值，并在证据存在歧义时拒绝给出确定标签。

**技术栈：** 现有扫描/游戏库技术栈、Python protocol/dataclass、pefile、YAML 规则、pytest 夹具、Vue 3/Vitest。

## 全局约束

- 引擎识别绝不决定某个目录能否加入游戏库。
- 只读取名称、目录结构、PE 元数据、小型文本配置和受限的文件区域。
- 绝不执行游戏，也不对其进行注入、解密、提取或改写。
- 绝不提交商业游戏资源；测试使用合成目录树和最小合法字节标头。
- 每项结果都包含置信度和便于人理解的证据。
- 保留手动设置的引擎值，同时继续刷新自动检测建议。
- 较弱的识别器返回未知或“疑似”，不会强行套用最接近的标签。
- 正式支持表示我们维护相应识别器和夹具，并不保证识别每个定制构建。
- 遵循 TDD，并在每个任务完成后提交。

---

### 任务 1：构建检测器协议、受限读取器与注册表

**文件：**
- 新建：`src/gameshelf/engines/__init__.py`
- 新建：`src/gameshelf/engines/models.py`
- 新建：`src/gameshelf/engines/base.py`
- 新建：`src/gameshelf/engines/bounded_reader.py`
- 新建：`src/gameshelf/engines/registry.py`
- 新建：`tests/unit/engines/test_registry.py`
- 新建：`tests/unit/engines/test_bounded_reader.py`

**接口：**
- 产出：`EngineEvidence(code, detail, weight, path)`。
- 产出：`EngineMatch(engine_id, variant, confidence, evidence, rule_version, experimental)`。
- 产出协议：`EngineDetector.cheap_probe(context) -> bool` 和 `inspect(context) -> EngineMatch | None`。
- 产出：`DetectorRegistry.detect(game_dir, executable) -> DetectionOutcome`。
- 产出受限读取方法：`read_prefix`、`read_suffix`、`contains_in_edges` 和 `read_text_limit`。

- [ ] **步骤 1：编写会失败的置信度、歧义和读取上限测试**

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

- [ ] **步骤 2：运行引擎核心测试并确认失败**

运行：`python -m pytest tests/unit/engines/test_registry.py tests/unit/engines/test_bounded_reader.py -v`

预期：失败，因为引擎软件包尚不存在。

- [ ] **步骤 3：实现不可变结果与保守选择策略**

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

将置信度限制在 `0..1`，先按置信度、再按稳定引擎 ID 排序；最佳正式结果要求 `>=0.70`，最佳实验性结果要求 `>=0.80`；前两名差值小于 `0.08` 时标记为有歧义。最多保留三个备选项。检测器异常转为诊断证据/日志，不得中止其他检测器。

受限文本读取最多 256 KiB，并按 BOM/UTF-8/CP932 回退；二进制检查每个文件最多读取 64 KiB，除非检测器明确同时使用前缀与后缀上限，但两者合计仍不得超过 128 KiB。

- [ ] **步骤 4：运行针对性测试与静态检查**

运行：

```powershell
python -m pytest tests/unit/engines/test_registry.py tests/unit/engines/test_bounded_reader.py -v
python -m ruff check src/gameshelf/engines tests/unit/engines
python -m mypy src/gameshelf/engines
```

预期：全部通过。

- [ ] **步骤 5：提交检测器基础设施**

```powershell
git add src/gameshelf/engines tests/unit/engines
git commit -m "feat: add bounded engine detector registry"
```

### 任务 2：实现声明式规则检测器

**文件：**
- 修改：`pyproject.toml`
- 新建：`src/gameshelf/engines/rule_schema.py`
- 新建：`src/gameshelf/engines/rule_detector.py`
- 新建：`resources/rules/engines.schema.json`
- 新建：`resources/rules/engines.yaml`
- 新建：`tests/unit/engines/test_rule_detector.py`

**接口：**
- 产出：严格拒绝未知键的 `load_engine_rules(path: Path) -> tuple[EngineRule, ...]`。
- 产出：`RuleDetector(rule: EngineRule)`。
- 支持的证据运算符：`path_exists`、`glob_exists`、`magic_at`、`edge_contains`、`text_contains`、`pe_field_contains`。
- 规则组合支持必需的 `all`、加权的 `any` 和负面证据。

- [ ] **步骤 1：编写会失败的架构与匹配测试**

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

- [ ] **步骤 2：运行规则测试并确认失败**

将 `PyYAML>=6.0.2,<7` 添加到项目依赖，重新安装可编辑软件包，然后运行：`python -m pytest tests/unit/engines/test_rule_detector.py -v`。

预期：失败，因为规则引擎尚不存在。

- [ ] **步骤 3：实现严格 YAML 解析与加权证据**

使用以下稳定的 YAML 结构：

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

规范化规则中的相对路径，并拒绝绝对路径/`..`。glob 仅在游戏根目录下执行，每条证据最多匹配 128 项。置信度等于已出现证据的权重和除以正面权重总和，再根据负面证据调整并限制范围。每个匹配的运算符都转为本地化证据代码；缺少可选证据时不显示为错误。

- [ ] **步骤 4：运行规则测试并校验随附 YAML**

运行：

```powershell
python -m pytest tests/unit/engines/test_rule_detector.py -v
python -c "from pathlib import Path; from gameshelf.engines.rule_schema import load_engine_rules; print(len(load_engine_rules(Path('resources/rules/engines.yaml'))))"
```

预期：测试通过，校验命令输出至少 `1`。

- [ ] **步骤 5：提交声明式引擎规则**

```powershell
git add pyproject.toml src/gameshelf/engines resources/rules tests/unit/engines
git commit -m "feat: add declarative engine recognition rules"
```

### 任务 3：添加 RPG Maker、WOLF、Ren'Py 与 Unity 检测器

**文件：**
- 新建：`src/gameshelf/engines/detectors/__init__.py`
- 新建：`src/gameshelf/engines/detectors/rpg_maker.py`
- 新建：`src/gameshelf/engines/detectors/renpy.py`
- 新建：`src/gameshelf/engines/detectors/unity.py`
- 新建：`src/gameshelf/engines/detectors/wolf.py`
- 新建：`tests/unit/engines/detectors/test_rpg_maker.py`
- 新建：`tests/unit/engines/detectors/test_renpy.py`
- 新建：`tests/unit/engines/detectors/test_unity.py`
- 新建：`tests/unit/engines/detectors/test_wolf.py`

**接口：**
- 产出正式 ID/变体：`rpg_maker_2k`、`rpg_maker_xp`、`rpg_maker_vx`、`rpg_maker_vx_ace`、`mkxp_z`、`rgu`、`rpg_maker_mv`、`rpg_maker_mz`、`renpy`、`unity` 和 `wolf_rpg`。
- 能够可靠提取时，Unity 匹配元数据可包含 `company_name` 和 `product_name`。
- 不会仅因使用 NW.js 就将 Tyrano/Visual Novel Maker 错分为通用 RPG Maker MV。

- [ ] **步骤 1：编写参数化的正例与近似反例夹具**

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

为以下情况添加测试：`mkxp.json`/`mkxp-z` PE 元数据、`RGU.exe`/RGSS 库证据、Ren'Py 的 `game/*.rpyc` 加 `renpy/`、Unity 的 `UnityPlayer.dll + <exe>_Data/globalgamemanagers`，以及 WOLF 的 `Game.exe + Data/BasicData/Game.dat` 或加密 `Data.wolf`。添加仅有 `Game.exe`、仅有 `UnityPlayer.dll` 或仅有 `www` 文件夹的近似反例测试。

- [ ] **步骤 2：运行检测器测试并确认失败**

运行：`python -m pytest tests/unit/engines/detectors -v`

预期：失败，因为专用检测器尚不存在。

- [ ] **步骤 3：实现变体专用组合规则**

至少使用以下高置信度组合：

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

对于 Unity，只从受限且受支持的元数据/PE 字段读取产品和公司信息；缺少元数据不会使有效的 Unity 引擎匹配降到阈值以下。对于 MV/MZ，同时检查根目录和 `www/` 布局。通用 RGSS 归档如果缺少对应启动器/配置证据，不得视为确定结果。

- [ ] **步骤 4：运行检测器与注册表测试**

运行：

```powershell
python -m pytest tests/unit/engines -v
python -m ruff check src/gameshelf/engines tests/unit/engines
python -m mypy src/gameshelf/engines
```

预期：全部通过。

- [ ] **步骤 5：提交核心 RPG/运行时检测器**

```powershell
git add src/gameshelf/engines/detectors tests/unit/engines/detectors
git commit -m "feat: recognize RPG Maker RenPy Unity and WOLF"
```

### 任务 4：添加 MTool 所列的其余识别器

**文件：**
- 修改：`resources/rules/engines.yaml`
- 新建：`src/gameshelf/engines/detectors/creator_engines.py`
- 新建：`tests/unit/engines/detectors/test_creator_engines.py`
- 新建：`tests/fixtures/engines/README.md`

**接口：**
- 产出正式 ID：`smile_game_builder`、`rpg_developer_bakin`、`tyrano`、`kirikiri`、`visual_novel_maker`、`choicescript`、`srpg_studio` 和 `pixel_game_maker_mv`。
- KiriKiri 变体为 `2`、`Z`，证据无法区分时为未知。
- 由 Unity 导出的 SMILE GAME BUILDER 游戏在没有 SGB 专属证据时可能返回 Unity；这是正确的保守行为。

- [ ] **步骤 1：为 MTool 所列的每个系列编写会失败的夹具**

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

为 SMILE GAME BUILDER（`SMILE GAME BUILDER` 或 `SmileBoom`）、RPG Developer Bakin（`RPG Developer Bakin`/`BakinPlayer`）及 Visual Novel Maker（`Visual Novel Maker`）添加明确的 PE 元数据夹具/假对象，并与各自的运行时数据布局组合。为每种情况添加一个通用 Unity/NW.js 反例，确保只有产品元数据或只有通用运行时不会造成误分类。

- [ ] **步骤 2：运行创作工具引擎测试并确认失败**

运行：`python -m pytest tests/unit/engines/detectors/test_creator_engines.py -v`

预期：所有新列出的 ID 都失败。

- [ ] **步骤 3：添加保守的正式识别器**

实现以下证据策略：

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

只有共享的 Unity 或 NW.js 基础运行时时，返回基础引擎（Unity）或不返回专用结果。绝不将单独一个文件夹名称当作充分的正式证据。

- [ ] **步骤 4：运行全部正式引擎测试**

运行：`python -m pytest tests/unit/engines -v`

预期：每个已确认的 MTool 所列引擎都有正例夹具和近似反例夹具；全部测试通过。

- [ ] **步骤 5：提交其余 MTool 识别器**

```powershell
git add resources/rules src/gameshelf/engines tests/unit/engines tests/fixtures/engines
git commit -m "feat: recognize MTool-listed creator engines"
```

### 任务 5：添加正式 Galgame 格式识别器

**文件：**
- 修改：`resources/rules/engines.yaml`
- 新建：`tests/unit/engines/test_galgame_rules.py`

**接口：**
- 产出正式 ID：`artemis`、`reallive`、`siglus`、`bgi_ethornell`、`catsystem2`、`yuris` 和 `nscripter`。
- 只有证据支持时，变体字段才区分 `RealLive`/`SiglusEngine` 和 `NScripter`/`ONScripter`。

- [ ] **步骤 1：编写会失败的合成魔数标头测试**

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

添加 Siglus（`SiglusEngine.exe` 的 PE/产品证据加 `Scene.pck`/场景数据）、已经覆盖的 KiriKiri、BGI 的 `BURI` + `KO ARC20`、CatSystem 的 `KIF` INT，以及 ONScripter 可执行文件名/运行时证据。测试单独一个通用 `.arc`、`.dat`、`.int`、`.pac` 或 `Game.exe` 不会匹配。

- [ ] **步骤 2：运行 Galgame 规则测试并确认失败**

运行：`python -m pytest tests/unit/engines/test_galgame_rules.py -v`

预期：失败，因为规则尚未随应用提供。

- [ ] **步骤 3：编码“魔数加配套证据”的组合规则**

使用来自公开格式文档/参考实现的受限签名：

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

扩展名或四字节魔数较常见时，要求至少两个独立信号。证据消息必须指出匹配的文件和信号，但不得暴露文件内容。

- [ ] **步骤 4：运行全部正式与反例测试**

运行：`python -m pytest tests/unit/engines -v`

预期：全部通过；通用扩展名近似反例仍保持未知。

- [ ] **步骤 5：提交正式 Galgame 规则**

```powershell
git add resources/rules/engines.yaml tests/unit/engines/test_galgame_rules.py
git commit -m "feat: recognize formal Galgame engine families"
```

### 任务 6：添加实验性旧式引擎识别器

**文件：**
- 修改：`resources/rules/engines.yaml`
- 新建：`tests/unit/engines/test_experimental_rules.py`

**接口：**
- 产出实验性 ID：`qlie`、`majiro`、`malie`、`shiina_rio`、`softpal_amusecraft`、`entis` 和 `nitroplus`。
- 所有返回的匹配项都具有 `experimental=True`，并要求置信度 `>=0.80`。

- [ ] **步骤 1：编写会失败的强签名与通用扩展名测试**

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

为每种扩展名添加同扩展名但内容随机的反例，并确保它保持未知。

- [ ] **步骤 2：运行实验性测试并确认失败**

运行：`python -m pytest tests/unit/engines/test_experimental_rules.py -v`

预期：失败，因为实验性规则尚不存在。

- [ ] **步骤 3：添加受限的强签名与实验性标签**

使用以下证据：QLIE 文件受限边缘中的 `FilePackVer`、`MajiroArcV`、`LIB`/`LIBP`/`LIBU` 加 Malie 配套文件、`WARC`、`VAFS`/`PAC ` 加 SoftPal 配套文件、`Entis\x1a`/`VIST\x1a` 及 `NPA\x01`/`nitP`。单独一个通用扩展名绝不贡献置信度。

在结果证据中显示“实验性识别”。厂商定制引擎不使用虚假的兜底规则表示；用户之后可在 UI 中手动设置 `custom:<label>`。

- [ ] **步骤 4：运行全部引擎规则与架构校验**

运行：

```powershell
python -m pytest tests/unit/engines -v
python -c "from pathlib import Path; from gameshelf.engines.rule_schema import load_engine_rules; rules=load_engine_rules(Path('resources/rules/engines.yaml')); print(len(rules))"
```

预期：全部通过，规则数量覆盖正式及实验性系列。

- [ ] **步骤 5：提交实验性识别器**

```powershell
git add resources/rules/engines.yaml tests/unit/engines/test_experimental_rules.py
git commit -m "feat: add experimental legacy engine signatures"
```

### 任务 7：将引擎检测集成到扫描中且不覆盖手动值

**文件：**
- 新建：`src/gameshelf/engines/service.py`
- 修改：`src/gameshelf/scanning/service.py`
- 修改：`src/gameshelf/library/models.py`
- 修改：`src/gameshelf/library/repository.py`
- 新建：`tests/integration/engines/test_scan_engine_integration.py`

**接口：**
- 产出：`EngineDetectionService.detect(game_dir, executable) -> DetectionOutcome`。
- 每次成功观察时，扫描写入 `detected_engine_id`、`detected_engine_variant`、`engine_confidence` 和证据。
- 仅当 `engine_is_manual` 为 false 时，扫描才把检测值复制到采用的 `engine_id`/`variant`。

- [ ] **步骤 1：编写会失败的扫描/手动覆盖测试**

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

- [ ] **步骤 2：运行集成测试并确认失败**

运行：`python -m pytest tests/integration/engines/test_scan_engine_integration.py -v`

预期：失败，因为扫描尚未调用注册表。

- [ ] **步骤 3：在候选项/EXE 排名后、核对前添加检测**

只对观察到的游戏候选项调用引擎检测，而不是对每个遍历到的文件夹调用。在同一扫描核对事务中，将证据存为 `{code, detail, path, weight}` JSON 数组并保存规则版本。有歧义的结果不存储 `detected_engine_id`，但在证据中保留备选项。检测器失败转为扫描警告，游戏仍保持可用。

- [ ] **步骤 4：运行扫描与引擎测试套件**

运行：`python -m pytest tests/unit/engines tests/integration/engines tests/integration/scanning -v`

预期：全部通过。

- [ ] **步骤 5：提交扫描集成**

```powershell
git add src/gameshelf/engines/service.py src/gameshelf/scanning src/gameshelf/library tests/integration/engines
git commit -m "feat: detect engines during library scans"
```

### 任务 8：显示证据并支持手动覆盖引擎

**文件：**
- 修改：`src/gameshelf/bridge/api.py`
- 新建：`tests/unit/bridge/test_engine_api.py`
- 修改：`frontend/src/api/contracts.ts`
- 新建：`frontend/src/features/engines/EngineBadge.vue`
- 新建：`frontend/src/features/engines/EngineDetails.vue`
- 新建：`frontend/src/features/engines/EnginePicker.vue`
- 新建：`frontend/tests/EngineDetails.spec.ts`
- 新建：`frontend/tests/EnginePicker.spec.ts`
- 修改：`frontend/src/features/library/GameCard.vue`
- 修改：`frontend/src/features/library/GameDetailDrawer.vue`
- 修改：`frontend/src/features/library/LibraryToolbar.vue`
- 新建：`src/gameshelf/tools/__init__.py`
- 新建：`src/gameshelf/tools/detect_directory.py`

**接口：**
- 添加桥接方法 `list_engine_options`、`set_game_engine` 和 `clear_manual_engine`。
- 游戏 DTO 包含采用的引擎、检测建议、置信度、证据、歧义状态和实验性标志。
- 手动自定义值为 `{ engineId: 'custom', customLabel: string }`，存储时规范化为 `custom:<label>`。

- [ ] **步骤 1：编写会失败的 API 与 UI 测试**

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

- [ ] **步骤 2：运行引擎 API/UI 测试并确认失败**

运行：

```powershell
python -m pytest tests/unit/bridge/test_engine_api.py -v
npm --prefix frontend run test:unit -- --run tests/EngineDetails.spec.ts tests/EnginePicker.spec.ts
```

预期：因端点/组件缺失而失败。

- [ ] **步骤 3：实现透明的证据展示与覆盖行为**

卡片只显示简洁的已采用引擎徽标。抽屉显示采用值/检测值；有歧义时显示“疑似”；适用时显示“实验性识别”；置信度显示为高/中/低，而不是虚假的精确数值；证据列表可以展开。选择器列出所有正式 ID、实验性 ID、未知和自定义。

将引擎设为未知是一项手动覆盖，会阻止自动采用；清除覆盖后恢复为最新检测值。更改引擎绝不自动更改存档位置；后续生成存档提示仍是一项需要明确审核的操作。

- [ ] **步骤 4：添加只读检测器 CLI 并运行验收门禁**

添加开发者命令 `python -m gameshelf.tools.detect_directory "D:\Games\Sample"`，用于输出 JSON 证据且不执行数据库写入。然后运行：

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

预期：所有检查通过；CLI 仅在输入无效/不可读时以非零状态退出。

- [ ] **步骤 5：提交完整的引擎识别功能**

```powershell
git add src frontend tests
git commit -m "feat: expose explainable engine recognition"
```

## 引擎增量验收门禁

- 每个已确认的正式系列至少拥有一个正例和一个近似反例合成夹具。
- 每个实验性系列都要求强魔数/配套证据，并且显著标记为实验性。
- 单独存在通用 `.arc`、`.pac`、`.dat`、`.int`、`.lib`、`.war`、`Game.exe`、Unity 或 NW.js 证据时，不会强制套用专用标签。
- 未知游戏仍然可以启动和筛选。
- 手动设置的未知/自定义/正式选择在扫描后仍保留，同时继续显示最新自动证据。
- 检测只读取有限数据，绝不执行或提取文件，也绝不阻止游戏库成功核对。
