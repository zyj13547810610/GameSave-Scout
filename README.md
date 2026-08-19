# GameShelf

GameShelf 是一个面向 Windows 10/11 x64 的本地优先、便携式个人游戏库与存档定位工具，目前主要面向同人游戏，也适用于其他能够独立启动的 Windows 游戏。它用于整理分散在不同目录中的游戏、维护启动配置与封面、识别常见游戏引擎，并帮助用户查找和确认存档位置。

GameShelf 不需要账号或云服务。游戏库、配置、封面、日志和 WebView 用户数据默认保存在程序旁的 `data` 目录，可以随整个程序目录迁移。当前源码范围与实现状态见[开发路线图](docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md)。

## 主要功能

- 管理多个游戏根目录，支持直接子目录或 1～8 层递归扫描、独立排除规则和后台快速核验；
- 编辑游戏标题、主程序、工作目录、启动参数和环境变量，并使用经过验证的配置启动游戏；
- 使用封面网格搜索和筛选游戏，通过主页批量管理一次处理已安装或失效记录，并支持 80%～120% 五档界面缩放；
- 创建、重命名和删除扁平自定义分组；一个游戏可属于多个分组，并支持详情编辑、批量加入/移出以及与搜索、状态、引擎组合筛选；
- 为单个游戏选择、粘贴、替换或移除封面，也可在批量封面工作台中从 VNDB、拖放/粘贴、游戏目录浅层扫描和自定义非递归封面目录收集候选；
- 批量封面不会自动采用图片；VNDB 默认关闭，开启后只发送游戏标题，不发送安装路径或本地文件；
- 主页和批量封面使用固定控制区与内部独立滚动，滚动条采用统一深色主题；
- 通过专用检测器与声明式规则识别 Galgame、RPG Maker、Unity、Ren'Py、Unreal 等引擎，并保留证据和手动覆盖；
- 按需使用自定义清单、Ludusavi 和引擎提示查找静态存档位置；
- 提供单次引导式存档寻找：先监控文件变化，再启动游戏并由用户完成一次保存，最后审核候选位置；
- 使用程序旁 SQLite 数据库和便携配置，不扫描或上传未授权的全盘内容。

当前源码不包含孤立存档发现、存档备份、恢复、同步、云服务和常驻后台监控。

## 版本更新记录

以下记录按源码开发里程碑整理；`V0.1.0` 和 `V0.1.4` 已生成本地双版本便携候选包，其余小版本不表示曾单独生成便携包或发布到 GitHub Release。详细设计、实现边界和验证记录以[固定设计文档](docs/superpowers/plans)为准。

<details open>
<summary><strong>V0.2.0 — 2026-08-19（最新源码）</strong></summary>

- 新增扁平自定义游戏分组，支持新建、重命名、删除和成员数量展示；一个游戏可同时属于多个分组；
- 主页新增“全部分组”“未分组”和具体分组筛选，并与标题、状态和引擎条件共同取交集；
- 详情抽屉支持原子替换单个游戏的全部分组，主页批量管理支持把最多 500 个游戏加入或移出一个分组；
- `installed`、`missing` 和 `save_only` 均可参与分组；选择含仅存档记录时仍可调整分组，但批量删除会禁用并说明原因；
- 数据库升级为 schema 3。开发阶段不提供 schema 2 迁移，旧库必须由用户自行移走或删除后重新建立，程序不会自动改动旧数据库或 `data/covers` 文件；
- 完整自动门禁通过：Python 743 项、前端 38 个测试文件共 169 项，并通过 Ruff、mypy、Vue 类型检查、生产构建和隔离 schema 3 源码 smoke；
- 本条只表示 V0.2.0 源码里程碑，尚未构建或发布 V0.2.0 便携包。

</details>

<details>
<summary><strong>V0.1.4 — 2026-08-18</strong></summary>

- 启动快速核验改为只检查已入库游戏，并可全局关闭；手动完整扫描继续负责发现新游戏；
- 新增持久化游戏分析缓存、文件指纹分层失效和 1～4 全局共享分析并发，减少未变化游戏的重复遍历；
- 新增 quick/full 分阶段进度、缓存统计、扫描中耗时和单游戏“重新检测主程序和引擎”；
- 新根目录默认排除 `Mods` 与 `**/Mods`，规则可由用户删除；相关自动门禁和 10 项真实人工验收全部通过。
- 从干净提交 `fc540ea` 重建完整离线版与轻量联网版；构建内部通过 Python 717 项、前端 142 项和两版冻结 smoke，发布清单记录 `gitDirty: false`。

</details>

<details>
<summary><strong>V0.1.3 — 2026-08-18</strong></summary>

- 游戏标题与版本号改为独立保存、展示和搜索，扫描时保守识别目录名中的明确版本尾缀；
- 重扫和移动确认分别维护自动检测值与用户设置，避免覆盖手动标题、版本号、主程序或引擎；
- VNDB 当前游戏与批量搜索只发送纯游戏标题，不携带版本号、本地路径或其他本地信息；
- 修复批量 VNDB 搜索过程中切换审核游戏后进度停留的问题。

</details>

<details>
<summary><strong>V0.1.2 — 2026-08-17</strong></summary>

- 主页游戏目录、游戏网格、批量封面队列和候选画廊改为独立滚动，关键控制区保持固定；
- 候选设置改为锚定浮层，并为应用内滚动区域统一深色滚动条；
- 优化五档界面缩放及窄窗口布局，限制横向、纵向封面始终位于详情标题上方；
- 修复批量封面队列项目较多或标题换行时条目压缩、重叠的问题。

</details>

<details>
<summary><strong>V0.1.1 — 2026-08-17</strong></summary>

- 新增批量封面工作台，可从 VNDB、拖放/粘贴、游戏目录浅层扫描和自定义非递归封面目录收集候选；
- 所有候选均由用户逐项确认采用，联网默认关闭，在线请求不发送安装路径或本地文件；
- 增加批量任务进度、取消、临时候选清理和单项失败隔离；
- 优化 VNDB 批量进度、浅层扫描空结果提示、主页批量入口间距和详情封面显示边界。

</details>

<details>
<summary><strong>V0.1.0 — 2026-08-16</strong></summary>

- 完成多游戏根目录扫描、安全启动、主程序排序、常见游戏引擎识别和手动覆盖；
- 完成游戏库筛选、详情设置、封面管理、界面缩放和事务式批量管理；
- 完成基于自定义清单、Ludusavi 索引和引擎提示的静态存档查找，以及引导式文件变化监控；
- 建立完整离线版和轻量联网版 Windows x64 便携构建、校验与本机验收流程。

</details>

## 当前状态

V0.1.x 已完成源码、便携包与既定验收收口。V0.2.0 自定义游戏分组的源码实现已经完成；本轮真实 pywebview 人工验收仍以实施计划中的未勾选清单为准，不能由自动测试代替。完整目标 Windows 10/11 设备、SmartScreen、UNC/只读目录和特殊运行时故障矩阵没有全部执行，不记为已通过，作为后续可选兼容性复核。

V0.2 后续仍计划单独设计和实现孤立存档发现与可能游戏反推；V0.3 或更晚再考虑存档备份、恢复、同步和版本管理。这些后续功能目前尚未实现。

## 界面预览

### 游戏库概览

![GameShelf 游戏库概览](docs/assets/readme/library-overview.png)

扫描多个游戏目录，在封面网格中搜索、筛选和管理已识别的游戏。

### 游戏详情与启动设置

![GameShelf 游戏详情与启动设置](docs/assets/readme/game-detail.png)

在右侧详情面板中启动游戏、管理封面，并调整标题、主程序和其他启动设置。

### 存档位置与引擎识别

![GameShelf 存档位置与引擎识别](docs/assets/readme/save-locations.png)

集中维护已确认的存档目录，按需查找或引导式寻找存档，并查看游戏引擎识别结果。

## 便携版选择与使用

当前可用的 V0.1.4 提供两个 Windows x64 便携包；V0.2.0 目前只有源码，尚未构建便携包：

| 版本 | 目录/ZIP 名称 | WebView2 | 适用场景 |
| --- | --- | --- | --- |
| 完整离线版 | `GameShelf-0.1.4-win-x64` | 自带 Fixed Version Runtime | 体积较大，可在系统没有 WebView2 时离线启动 |
| 轻量联网版 | `GameShelf-0.1.4-win-x64-lite` | 使用系统 Evergreen Runtime | 下载体积较小，系统缺失 Runtime 时需要联网手动安装 |

使用步骤：

1. 将 ZIP 完整解压到本地固定磁盘上的可写目录，不要直接在压缩包内运行。
2. 保持 `GameShelf.exe`、`_internal` 以及完整版的 `runtime` 或轻量版的 `prerequisites` 相对位置不变。
3. 双击 `GameShelf.exe` 启动。首次正常启动会在程序旁创建 `data`。
4. 添加一个或多个游戏根目录并执行扫描；游戏详情中可以继续设置启动方式、封面、引擎和存档位置。

轻量版如果检测不到系统 Evergreen WebView2 Runtime，会先校验随包的微软官方 `MicrosoftEdgeWebview2Setup.exe`，再询问是否打开安装位置。选择“是”后，GameShelf 只会在 Explorer 中选中安装器并正常退出；请手动双击安装器联网完成安装，然后重新启动 GameShelf。GameShelf 不会静默运行安装器，也不会自动重新启动自身。

便携使用注意事项：

- 完全退出 GameShelf 后，复制整个程序目录即可迁移；不要只移动 `GameShelf.exe`。
- 删除整个 GameShelf 目录即可删除程序及其便携数据；轻量版使用的系统 Evergreen Runtime 不会随之卸载。
- V0.1 只支持本地文件系统中的可写目录，且完整发布负载的绝对路径必须少于 260 个字符；不支持 UNC 或网络共享路径。
- 启动错误日志位于 `data\logs\startup-error.log`，普通运行日志位于 `data\logs\gameshelf.log`。
- GameShelf V0.1 本体未进行 Authenticode 签名，Windows 可能显示未知发布者或 SmartScreen 提示。请只使用可信来源的发布包并核对 ZIP 的 SHA-256，不要为运行程序而关闭系统安全功能。

## 开发环境

- Git 与 PowerShell
- Conda（Anaconda、Miniconda 或兼容发行版）
- 项目内 Conda 环境：Python 3.12、Node.js 24

以下命令均在项目根目录执行。首次开发时创建项目内 `.venv` 环境并安装依赖：

```powershell
conda create --prefix .\.venv --override-channels -c conda-forge python=3.12 nodejs=24 -y
conda activate .\.venv
python -m pip install -e ".[dev]"
npm --prefix frontend ci
```

`.venv` 同时提供项目所需的 Python 和 Node.js，不需要修改系统中已有的 Node.js。以后重新打开终端时，只需先进入项目根目录并激活环境：

```powershell
conda activate .\.venv
```

当前源码使用 SQLite schema 3，并按开发期约定不迁移 V0.1 的 schema 1/2 数据库。如果程序提示检测到旧库，请先完全退出 GameShelf，再自行移走或删除可舍弃的 `data\library.db` 后重启。该操作会丢失旧数据库记录；程序不会自动删除 `data\covers` 中的图片，但新库也不会自动恢复旧封面关联。

后端检查：

```powershell
python -m pytest
python -m ruff check src tests scripts
python -m mypy src scripts
```

前端检查与生产构建：

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

前端生产构建会直接更新 `resources/ui`。随后可以在不打开窗口的情况下验证便携路径与数据库：

```powershell
python -m gameshelf --smoke-test
```

## 构建 Windows x64 便携包

正式构建需要两个微软官方输入文件：

- WebView2 Fixed Version Runtime 151.0.4129.86 x64 CAB，用于完整离线版；
- Evergreen WebView2 Bootstrapper，用于轻量联网版缺少系统 Runtime 时的手动安装引导。

构建脚本要求两个参数都是绝对路径，并会按照 `release/webview2-runtime.json` 和 `release/webview2-bootstrapper.json` 校验文件名、版本、SHA-256 与 Microsoft Authenticode 签名。脚本不会联网下载输入，也不会自动运行安装器。仓库约定把本地输入放在被 Git 忽略的 `webview安装包` 目录：

```text
webview安装包/
├─ Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab
└─ MicrosoftEdgeWebview2Setup.exe
```

在已经激活 `.venv` 的项目根目录 PowerShell 中执行：

```powershell
$webView2Archive = (Resolve-Path ".\webview安装包\Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab").Path
$webView2Bootstrapper = (Resolve-Path ".\webview安装包\MicrosoftEdgeWebview2Setup.exe").Path

.\scripts\build_release.ps1 `
  -WebView2Archive $webView2Archive `
  -WebView2Bootstrapper $webView2Bootstrapper
```

脚本会执行 Python 与前端完整门禁、生产 UI 构建、源码 smoke、单次 PyInstaller onedir 冻结、两种 WebView2 布局派生、两版冻结 smoke、发布清单与 ZIP 复核。只有六个目标全部成功后，才会原子替换 `dist` 中的当前版本：

```text
dist/
├─ GameShelf-0.1.4-win-x64/
├─ GameShelf-0.1.4-win-x64.zip
├─ GameShelf-0.1.4-win-x64.zip.sha256
├─ GameShelf-0.1.4-win-x64-lite/
├─ GameShelf-0.1.4-win-x64-lite.zip
└─ GameShelf-0.1.4-win-x64-lite.zip.sha256
```

可以独立复核两个 ZIP：

```powershell
Get-FileHash .\dist\GameShelf-0.1.4-win-x64.zip -Algorithm SHA256
Get-Content .\dist\GameShelf-0.1.4-win-x64.zip.sha256

Get-FileHash .\dist\GameShelf-0.1.4-win-x64-lite.zip -Algorithm SHA256
Get-Content .\dist\GameShelf-0.1.4-win-x64-lite.zip.sha256
```

2026-08-18 本地 V0.1.4 候选包的 ZIP SHA-256 为：

- 完整离线版：`4ceef6e5759977beaab2dc89cec73f2356aed1e677b6e2135b443c8682f9693b`
- 轻量联网版：`5a454fa05da362f822b6a39eef374bc898c546cd644aae3321e305354dd6156d`

构建失败时，脚本不会用不完整的新结果覆盖上一组六个正式产物。`build/`、`dist/` 与 `webview安装包/` 都是本地内容，不应提交到 Git。

## 源码启动与调试

在项目根目录打开 PowerShell，激活项目环境并启动桌面程序：

```powershell
conda activate .\.venv
python -m gameshelf
```

该命令会加载已经构建到 `resources/ui` 的前端。如果修改过前端源码，应先执行 `npm --prefix frontend run build`。

需要前端热更新时，打开两个已经激活 `.venv` 的 PowerShell 窗口。第一个窗口启动 Vite：

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1
```

第二个窗口让桌面程序加载 Vite 页面：

```powershell
$env:GAMESHELF_DEV_SERVER_URL = "http://127.0.0.1:5173"
python -m gameshelf
```

如果 Vite 因端口占用显示了其他地址，应把 `GAMESHELF_DEV_SERVER_URL` 改为终端中实际显示的地址。冻结版会忽略该变量并只加载随包 UI。

## 项目文档与许可证

- [总体设计](docs/superpowers/specs/2026-08-12-GameShelf-总体设计.md)
- [开发路线图](docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md)
- [封面与游戏库界面](docs/superpowers/plans/2026-08-12-GameShelf-03-封面与游戏库界面.md)
- [静态存档位置](docs/superpowers/plans/2026-08-12-GameShelf-05-静态存档位置.md)
- [引导式与孤立存档发现](docs/superpowers/plans/2026-08-12-GameShelf-06-动态与孤立存档发现.md)
- [便携版打包与发布设计](docs/superpowers/plans/2026-08-12-GameShelf-07-便携版打包与发布.md)
- [MIT License](LICENSE)
- [第三方声明](THIRD_PARTY_NOTICES.md)
