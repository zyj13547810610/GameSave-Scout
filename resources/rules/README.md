# GameShelf 内置规则证据台账

本目录保存 GameShelf 随程序发布的声明式规则。规则只用于受限、只读的静态识别与存档位置建议，不解包游戏资源，不读取存档正文，也不执行来自游戏目录的脚本。

## 状态与来源要求

- `formal`（正式）：必须有公开、可复核的格式或产品资料，并同时具备明确的正向与相似结构负向测试。
- `experimental`（实验）：证据或排他性尚不足，可以显示为实验候选，但不能伪装成正式结论。
- `enabled: false`：规则保留在资源中但不参与检测。
- `references` 只记录公开的 HTTPS 页面；资料访问日期统一为 **2026-08-21**。
- GARbro 的格式实现和支持列表可证明“某种归档签名确实存在，并被相关格式处理器使用”，但单个归档扩展名或短魔数通常不能独立证明唯一引擎。GameShelf 不复制 GARbro 解析器代码，也不借此解包或收集游戏内容。
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
| `livemaker` / LiveMaker | LiveMaker VF/GAL 等格式组合；[GARbro LiveMaker 目录](https://github.com/morkt/GARbro/tree/master/ArcFormats/LiveMaker) | 单个 `.gal` 图像格式不足以证明游戏引擎 | 计划正向：归档/脚本组合；负向：孤立 GAL、随机同扩展名 | **暂不加入**；Task 4 先确定至少两项独立稳定证据 |
| `cmvs` / CMVS/CVNS | CPZ 归档族及配套文件；[GARbro Cmvs 目录](https://github.com/morkt/GARbro/tree/master/ArcFormats/Cmvs) | CPZ 版本较多，单一通用文件可能误报 | 计划正向：受支持 CPZ 头加配套证据；负向：随机/孤立 CPZ | **暂不加入**；Task 4 校准版本与组合门槛 |
| `godot` / Godot | `project.godot` 配置或导出 PCK 结构；[Godot 数据路径](https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html)、[Godot PCKPacker](https://docs.godotengine.org/en/stable/classes/class_pckpacker.html) | `.pck` 并非 Godot 独占，文件名也可能被修改 | 计划正向：官方配置或 PCK 头加独立结构；负向：普通 `.pck`、随机同名 | **暂不加入**；Task 4 完成格式与负向验证后决定正式/实验 |

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

## 维护规则

1. 新增或升级正式规则前，先写正向和相似结构负向测试，再修改 YAML。
2. 每个正式内置规则至少保留一个可访问的公开依据；无法确认时降为实验，不填充虚假链接。
3. 规则 ID 一经进入业务数据便保持稳定；显示名称可以修订，ID 不随品牌写法变化。
4. 真实游戏仅用于人工复核。可分享诊断必须经过脱敏，不得提交绝对路径、用户名、文件正文、游戏归档或存档内容。
5. GARbro 等项目可继续作为同人游戏、Galgame 格式候选来源；是否加入 GameShelf 仍取决于排他性、受限读取能力和负向测试结果。
