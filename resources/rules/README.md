# GameSave Scout 内置规则证据台账

本目录保存 GameSave Scout 随程序发布的声明式规则。规则只用于受限、只读的静态识别与存档位置建议，不解包游戏资源，不读取存档正文，也不执行来自游戏目录的脚本。

## 状态与来源要求

- `formal`（正式）：必须有公开、可复核的格式或产品资料，并同时具备明确的正向与相似结构负向测试。
- `experimental`（实验）：证据或排他性尚不足，可以显示为实验候选，但不能伪装成正式结论。
- `enabled: false`：规则保留在资源中但不参与检测。
- `references` 只记录公开的 HTTPS 页面；V0.3.0～V0.3.2 资料访问日期为 **2026-08-21**，V0.3.5 新增资料复核日期为 **2026-08-27**。
- GARbro 的格式实现和支持列表可证明“某种归档签名确实存在，并被相关格式处理器使用”，但单个归档扩展名或短魔数通常不能独立证明唯一引擎。GameSave Scout 不复制 GARbro 解析器代码，也不借此解包或收集游戏内容。
- 正向夹具只保存人工生成的最小字节和目录结构；负向夹具覆盖同名随机文件、常见扩展名、签名偏移/截断及容易混淆的组合。仓库不纳入真实游戏文件。

本轮通用上游资料包括 [GARbro 仓库](https://github.com/morkt/GARbro)、[GARbro 许可](https://github.com/morkt/GARbro/blob/master/LICENSE)、[支持格式表](https://morkt.github.io/GARbro/supported.html) 和 [ArcFormats 项目清单](https://github.com/morkt/GARbro/blob/master/ArcFormats/ArcFormats.csproj)。规则行仍尽量链接到对应格式实现，便于逐项复核。

## V0.3.0 首批校准目标

下表记录首批 10 项当前结论。Task 3 已完成旧规则校准；Task 4 完成新增规则后会继续原地更新，不另建临时台账。

| 稳定 ID / 标签 | 候选签名与公开依据 | 主要误报风险 | 合成测试边界 | 当前结论与理由 |
| --- | --- | --- | --- | --- |
| `qlie` / QLIE | `data.pack` 距文件尾 28 字节处为 `FilePackVer3.0`；[GARbro ArcQLIE](https://github.com/morkt/GARbro/blob/master/ArcFormats/Qlie/ArcQLIE.cs) | 文件名常见，宽泛边缘搜索会误收包装器残留 | 正向：精确尾部位置；负向：随机同名、偏移/截断签名 | **转正式**；使用受限尾部读取精确复现上游位置检查 |
| `majiro` / Majiro | `data.arc` 起始完整 `MajiroArcV3.000\0`；[GARbro ArcMajiro](https://github.com/morkt/GARbro/blob/master/ArcFormats/Majiro/ArcMajiro.cs) | `data.arc` 极常见，省略终止字节会放宽匹配 | 正向：含终止字节的完整头；负向：随机同名、偏移/截断头 | **转正式**；完整长版本头具备排他性 |
| `malie` / Malie | `data.lib` 起始原始 `LIB\0`；[GARbro ArcLIB](https://github.com/morkt/GARbro/blob/master/ArcFormats/Malie/ArcLIB.cs) | `LIBP` 是已解密后的头，不能直接当作磁盘原始字节 | 正向：公开原始格式头；负向：`LIBP`、随机 `.lib`、偏移/截断头 | **转正式**；修正旧规则后与上游原始签名一致 |
| `shiina_rio` / ShiinaRio | `data.war` 起始 `WARC`，偏移 4 同时为 ` 1.`；[GARbro ArcWARC](https://github.com/morkt/GARbro/blob/master/ArcFormats/ShiinaRio/ArcWARC.cs) | 单独 `WARC` 可能与其他归档混淆 | 正向：魔数与版本前缀组合；负向：随机 `.war`、孤立 WARC、偏移/截断头 | **转正式**；加入上游版本结构检查后不再依赖短魔数 |
| `softpal_amusecraft` / SoftPal/AmuseCraft | `data.pac` 起始 `PAC `；[GARbro ArcPAC](https://github.com/morkt/GARbro/blob/master/ArcFormats/Softpal/ArcPAC.cs) | `.pac` 与短头均不唯一；现有只读数据库仅提供单个文件名证据 | 正向：最小格式头；负向：随机 `.pac`、偏移/截断头、相似 PAC | **保持实验**；现有真实样本证据不足以转正式 |
| `entis` / Entis/ERI/NOA | `data.noa` 起始 `Entis\x1a`，偏移 8 同时为固定 ID `0x02000400`；[GARbro ArcNOA](https://github.com/morkt/GARbro/blob/master/ArcFormats/Entis/ArcNOA.cs) | 产品族格式不必然等于单一作品，但可归于 Entis 格式族 | 正向：魔数与固定 ID 组合；负向：纯文本 `Entis`、错误 ID、偏移/截断头 | **转正式**；两段独立固定字段与上游校验一致 |
| `nitroplus` / Nitroplus | `data.npa` 起始完整 `NPA\x01`；[GARbro ArcNPA](https://github.com/morkt/GARbro/blob/master/ArcFormats/NitroPlus/ArcNPA.cs) | 仅识别受支持的 NPA 版本，不泛化到其他 NPA 写法 | 正向：完整版本头；负向：随机 `.npa`、偏移/截断头 | **转正式**；公开固定版本签名通过正负夹具 |
| `livemaker` / LiveMaker/LiveNovel | `game.dat` 起始完整 `vff\0`；[GARbro ArcVF](https://github.com/morkt/GARbro/blob/master/ArcFormats/LiveMaker/ArcVF.cs) | 单个 GAL/GALX 只是图像格式；独立 EXE 内嵌归档不在本轮声明式读取范围 | 正向：标准外置 VF 归档；负向：随机 DAT、偏移头、孤立 GALX | **转正式**；公开 VF 头直接标注为 LiveMaker 资源归档，且不使用通用图像格式 |
| `cmvs` / CMVS/CVNS | `start.ps3` 加任一 CPZ5/6/7 归档；[GARbro ArcCPZ](https://github.com/morkt/GARbro/blob/master/ArcFormats/Cmvs/ArcCPZ.cs) | 单一 CPZ 可能是孤立资源，版本 4 或未知版本不能类推 | 正向：启动脚本与受支持归档组合；负向：随机/孤立 CPZ、孤立脚本、CPZ4 | **转正式**；两类独立证据组合达到正式门槛 |
| `godot` / Godot | 游戏 EXE 加 `project.godot` 配置，或 EXE 加 PCK 的 `GDPC` 头；[Godot 文件系统](https://docs.godotengine.org/en/stable/tutorials/scripting/filesystem.html)、[PCK 导出](https://docs.godotengine.org/en/stable/tutorials/export/exporting_pcks.html)、[官方魔数定义](https://github.com/godotengine/godot/blob/master/core/io/file_access_pack.h) | 任意 `.pck` 扩展名或普通 INI 文本都不足；内嵌 PCK 暂不扫描 EXE 尾部 | 正向：官方项目配置或独立 PCK 头；负向：普通 PCK、偏移魔数、伪配置 | **转正式**；官方文件名/格式与游戏 EXE 组合通过负向测试 |

## V0.3.5 第三批声明式规则

本批六条规则只检查文件名、受限魔数或目录组合，不解析资源正文。公开资料用于证明这些文件或结构与对应引擎有关；是否达到正式门槛仍由组合证据、相似结构负向夹具和误报边界共同决定。

| 稳定 ID / 标签 | 检测组合与公开依据 | 主要误报边界 | 当前状态 |
| --- | --- | --- | --- |
| `game_maker` / GameMaker | 根目录 `data.win` 同时以 `FORM` 开头且偏移 8 为 `GEN8`；[GameMaker Windows 目标设置](https://manual.gamemaker.io/monthly/en/Settings/Windows.htm)、[UndertaleModTool 的 FORM/GEN8 数据模型](https://github.com/UnderminersTeam/UndertaleModTool/blob/master/UndertaleModLib/UndertaleData.cs) | `data.win` 文件名、孤立 `FORM` 或偏移错误的 `GEN8` 均不命中；不覆盖 YYC 等不携带该数据文件的构建 | **正式**；固定位置双签名比单文件名具有足够排他性 |
| `cryengine` / CRYENGINE | 同一受限目录树同时存在 `CrySystem.dll` 与 `CryAction.dll`；[CRYENGINE Game Code 文档](https://www.cryengine.com/docs/static/engines/cryengine-3/categories/1638401/pages/1605726)、[CryAction 文档](https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756813/pages/23309036) | 单个 DLL、只有 `Cry*` 名称的第三方文件或新版不再分发 `CryAction.dll` 的布局不命中；本规则只覆盖经典 Windows 动态库布局 | **正式**；两项官方运行时模块组合，覆盖范围主动收窄 |
| `re_engine` / RE Engine | 根目录 EXE 与根目录 `re_chunk_000.pak` 组合；[REE.PAK.Tool](https://github.com/Ekey/REE.PAK.Tool)、[REFramework](https://github.com/praydog/REFramework) | 任意 PAK、仅补丁 PAK、无 EXE 的解包目录或模组工具缓存不命中；该社区证据能证明 PC 发行布局，但不是 Capcom 的公开格式规范 | **正式**；固定根文件名再绑定可执行文件，且负向夹具排除孤立归档 |
| `mt_framework` / MT Framework | `nativePC` 目录中实际存在至少一个 ARC；[ARCtool](https://github.com/FluffyQuack/ARCtool)、[KnuxLib 的 MT Framework 格式表](https://github.com/Knuxfan24/KnuxLib) | `nativePC` 可能由模组工具创建，`.arc` 也不是唯一格式；未读取 ARC 版本或头部，无法排除所有同名目录 | **实验**；保留候选价值，但不把目录名与扩展名组合提升为正式结论 |
| `defold` / Defold | 根目录同时存在 `game.arci`、`game.arcd`、`game.dmanifest`；[Defold 官方归档格式](https://github.com/defold/defold/blob/dev/engine/docs/ARCHIVE_FORMAT.md) | 只复制其中一两个文件、改名备份或普通同扩展名文件不命中；不覆盖 Web 分片与定制输出名 | **正式**；官方文档明确给出三件套及各自职责 |
| `suika2` / Suika2 | 根目录 `suika.exe`、`conf/config.txt` 与 `txt/init.txt` 三件套；[Suika2 上游仓库](https://github.com/denisoa/suika2) | 单独同名 EXE、普通 `config.txt` 或只有脚本目录不命中；定制启动器或改变标准目录的发行可能漏检 | **正式**；上游示例目录中的执行文件、配置与初始脚本组合通过正负夹具 |

## 当前正式引擎规则

| 稳定 ID / 标签 | 当前检测依据 | 公开依据 | 风险与夹具边界 |
| --- | --- | --- | --- |
| `tyrano` / TyranoScript | `data/system/Config.tjs` 加 Tyrano 脚本结构 | [TyranoScript V5 教程](https://tyranoscript.com/usage/tutorial/ready_v5) | 排除普通 TJS 项目和仅有编辑器文件的目录 |
| `kirikiri` / KiriKiri 2/Z | XP3 完整头加 `startup.tjs` 或 `.ks` | [KiriKiri](https://krkren.github.io/)、[GARbro ArcXP3](https://github.com/morkt/GARbro/blob/master/ArcFormats/KiriKiri/ArcXP3.cs) | 排除随机 XP3 文件和无脚本配套的孤立归档 |
| `choicescript` / ChoiceScript | `startup.txt` 的 `*title` 加统计场景 | [ChoiceScript 入门](https://www.choiceofgames.com/make-your-own-games/choicescript-intro/) | 排除一般文本项目及只有单个同名文件的目录 |
| `srpg_studio` / SRPG Studio | `data.dts` 与 `runtime.rts` 同时存在 | [SRPG Studio 格式说明](https://docs.rhi.zone/reincarnate/targets/srpg-studio.html) | 两文件必须组合命中，孤立同名文件为负向 |
| `pixel_game_maker_mv` / Pixel Game Maker MV | `AGtk.js` 内容加 `package.json` | [官方插件规范](https://tkool.jp/act/en/manual/Plug-in_Spec_en_20200204.pdf) | 排除普通 NW.js 项目和无 Agtk 标识的 JavaScript |
| `artemis` / Artemis | PFS 完整头加 `movie.mja` 的 MJA0 头 | [GARbro ArcPFS](https://github.com/morkt/GARbro/blob/master/ArcFormats/Artemis/ArcPFS.cs)、[GARbro ArcMJA](https://github.com/morkt/GARbro/blob/master/ArcFormats/Artemis/ArcMJA.cs) | 两类格式组合命中，孤立 PFS/MJA 不足 |
| `reallive` / RealLive | `Gameexe.ini` 加 `seen.txt` 的 PACL 头 | [GARbro ArcSEEN](https://github.com/morkt/GARbro/blob/master/ArcFormats/RealLive/ArcSEEN.cs) | 配置与场景归档必须同时命中 |
| `siglus` / SiglusEngine | EXE 产品名包含 Siglus，加 Scene 文件之一 | [SiglusSceneScriptUtility](https://github.com/Jirehlov/SiglusSceneScriptUtility) | 只存在 Scene 文件或同名 EXE 均不够 |
| `bgi_ethornell` / BGI/Ethornell | `data.arc` 的 `PackFile` 头，加 BSS/ARC 配套 | [GARbro ArcBGI](https://github.com/morkt/GARbro/blob/master/ArcFormats/Ethornell/ArcBGI.cs) | 排除普通 ARC 和只有短文本头的文件 |
| `catsystem2` / CatSystem2 | `data.dat` 的 `CsPack2` 头加 `.cst` | [GARbro ArcDAT](https://github.com/morkt/GARbro/blob/master/ArcFormats/CatSystem/ArcDAT.cs) | 归档与脚本组合命中 |
| `yuris` / YU-RIS | `data.ypf` 的 YPF 头加 `.ybn` | [GARbro ArcYPF](https://github.com/morkt/GARbro/blob/master/ArcFormats/YuRis/ArcYPF.cs) | 排除随机 YPF 和缺少配套脚本的目录 |
| `nscripter` / NScripter/ONScripter | `nscript.dat` 加 `.nsa` | [NScripter 官方站](https://www.nscripter.com/)、[GARbro ArcNSA](https://github.com/morkt/GARbro/blob/master/ArcFormats/NScripter/ArcNSA.cs) | 两类文件组合命中，孤立 NSA 不足 |
| `qlie` / QLIE | `data.pack` 的固定尾部版本签名 | [GARbro ArcQLIE](https://github.com/morkt/GARbro/blob/master/ArcFormats/Qlie/ArcQLIE.cs) | 只匹配距文件尾 28 字节的完整 `FilePackVer3.0` |
| `majiro` / Majiro | `data.arc` 的完整 V3 版本头 | [GARbro ArcMajiro](https://github.com/morkt/GARbro/blob/master/ArcFormats/Majiro/ArcMajiro.cs) | 包含终止字节，偏移和截断均不命中 |
| `malie` / Malie | `data.lib` 的原始 `LIB\0` 头 | [GARbro ArcLIB](https://github.com/morkt/GARbro/blob/master/ArcFormats/Malie/ArcLIB.cs) | 不把仅在解密后出现的 `LIBP` 当成原始签名 |
| `shiina_rio` / ShiinaRio | WARC 魔数加版本前缀 | [GARbro ArcWARC](https://github.com/morkt/GARbro/blob/master/ArcFormats/ShiinaRio/ArcWARC.cs) | 两段固定位置同时命中，孤立 WARC 不足 |
| `entis` / Entis/ERI/NOA | Entis 控制头加固定归档 ID | [GARbro ArcNOA](https://github.com/morkt/GARbro/blob/master/ArcFormats/Entis/ArcNOA.cs) | 错误 ID 和单独产品字符串不命中 |
| `nitroplus` / Nitroplus | NPA 版本 1 完整头 | [GARbro ArcNPA](https://github.com/morkt/GARbro/blob/master/ArcFormats/NitroPlus/ArcNPA.cs) | 只覆盖 `NPA\x01`，不推测未知版本 |
| `livemaker` / LiveMaker/LiveNovel | `game.dat` 的 VF 完整头 | [GARbro ArcVF](https://github.com/morkt/GARbro/blob/master/ArcFormats/LiveMaker/ArcVF.cs) | 不使用孤立 GAL/GALX；本轮不读取 EXE 内嵌归档 |
| `cmvs` / CMVS/CVNS | `start.ps3` 加 CPZ5/6/7 | [GARbro ArcCPZ](https://github.com/morkt/GARbro/blob/master/ArcFormats/Cmvs/ArcCPZ.cs) | 孤立脚本、孤立 CPZ 和未知版本均不命中 |
| `godot` / Godot | EXE 加官方项目配置或 PCK 魔数 | [Godot 文件系统](https://docs.godotengine.org/en/stable/tutorials/scripting/filesystem.html)、[PCK 导出](https://docs.godotengine.org/en/stable/tutorials/export/exporting_pcks.html)、[魔数定义](https://github.com/godotengine/godot/blob/master/core/io/file_access_pack.h) | 普通 PCK、偏移魔数、无配置头文本不命中 |

## 当前正式存档规则

| 稳定 ID / 类型 | 当前建议依据 | 公开依据 | 风险与负向边界 |
| --- | --- | --- | --- |
| `godot_user_data` / 引擎通用 | Windows 默认 `user://` 位于 `%APPDATA%\Godot\app_userdata\<项目名>` | [Godot 数据路径](https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html) | 必须先从受限项目配置取得安全的 `project_name`；缺失、非法路径段或启用自定义用户目录时不拼接默认路径 |
| `unity_user_data` / 引擎通用 | Windows Player 的 `persistentDataPath` 与 PlayerPrefs 由公司名、产品名组成 | [Unity persistentDataPath](https://docs.unity3d.com/2023.1/Documentation/ScriptReference/Application-persistentDataPath.html)、[Unity PlayerPrefs](https://docs.unity3d.com/2020.2/Documentation/ScriptReference/PlayerPrefs.html) | 只接受受限 `app.info` 中两个安全路径段；缺失或包含表达式/路径分隔符时不建议 |
| `unreal_save_games` / 引擎通用 | 项目名对应 `Saved\SaveGames`，Windows 安装版使用项目用户目录 | [Unreal SaveGame](https://dev.epicgames.com/documentation/unreal-engine/saving-and-loading-your-game-in-unreal-engine)、[FPaths](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Core/FPaths) | 只从受限、有效的 `.uproject` 取得项目名；不能用安装目录名猜测，命令行重定向和自定义存储不在本规则覆盖范围 |

## 可分享的脱敏诊断

需要在另一台电脑采集引擎识别线索时，必须显式使用脱敏模式：

```powershell
.venv\python.exe -m gamesave_scout.tools.detect_directory "D:\Games\目标游戏" --sanitized > engine-diagnostic.json
```

脱敏报告不包含游戏根绝对路径、用户名、文件正文、图片、音频、存档内容或归档载荷；
只保留相对证据路径、候选引擎、置信度、实验状态、规则版本，以及最多 256 项、
深度 3 的受限文件概况。已知二进制类型最多读取并输出前 16 字节十六进制魔数，
根级 EXE 只输出受限 PE 产品字段；重解析点会记录但不会继续遍历。读取失败只记录
相对路径、操作名和异常类型。报告仍需人工打开复核后再分享，且不得直接提交仓库。

不带 `--sanitized` 的旧命令继续保留本机诊断兼容行为，会输出所选绝对目录，不能用于分享。

## 维护规则

1. 新增或升级正式规则前，先写正向和相似结构负向测试，再修改 YAML。
2. 每个正式内置规则至少保留一个可访问的公开依据；无法确认时降为实验，不填充虚假链接。
3. 规则 ID 一经进入业务数据便保持稳定；显示名称可以修订，ID 不随品牌写法变化。
4. 真实游戏仅用于人工复核。可分享诊断必须经过脱敏，不得提交绝对路径、用户名、文件正文、游戏归档或存档内容。
5. GARbro 等项目可继续作为同人游戏、Galgame 格式候选来源；是否加入 GameSave Scout 仍取决于排他性、受限读取能力和负向测试结果。
