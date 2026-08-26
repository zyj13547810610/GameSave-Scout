# GameSave Scout 便携版打包与发布

> 文档性质：固定模块设计与发布基准；适用版本：V0.1 及后续版本；最后更新：2026-08-26；状态：V0.3.3 已完成 GameSave Scout 技术身份与双版本发布链迁移，但不保留正式 V0.3.3 便携包；V0.3.4 已完成源码与远端收口，正式双版本便携包尚未构建。历史 V0.1 的本机真实窗口、路径与 Windows Sandbox 人工验收结论继续作为兼容性证据。完整发布负载绝对路径达到或超过 260 字符仍不受支持。完整目标 Windows 10/11、Evergreen 断网、安装器失败、特殊路径故障和 SmartScreen 实机矩阵保留为后续可选兼容性复核。

## 1. 发布目标与已确认边界

当前版本目标产出两个基于同一份 PyInstaller onedir 核心的 Windows 10/11 x64 便携包：

- `GameSave-Scout-0.3.4-win-x64` 是完整离线版，自带 Microsoft Fixed Version WebView2 Runtime x64，可在没有系统 WebView2、没有网络的电脑上运行。
- `GameSave-Scout-0.3.4-win-x64-lite` 是轻量联网版，优先使用系统 Evergreen WebView2 Runtime；系统缺失时，经用户明确同意后打开 `prerequisites` 文件夹并选中微软官方 Bootstrapper，GameSave Scout 随即正常退出。用户手动双击安装，完成后重新启动 GameSave Scout。
- 两个版本都不要求用户安装 Python、Node.js、Visual Studio 或项目开发依赖。
- 配置、数据库、封面、用户规则、活动 Ludusavi 快照、日志和 WebView 用户数据都位于 `GameSaveScout.exe` 旁的 `data`。
- 整个程序目录在退出 GameSave Scout 后可以复制到其他本地磁盘位置继续使用。
- 两组发布物分别包含 MIT 许可证、第三方声明、构建清单和可独立验证的 SHA-256。

首版明确只做以下交付物：

- 完整离线版和轻量联网版各一个 onedir 目录。
- 每个目录各生成一个 zip。
- 每个 zip 旁各生成一个记录其 SHA-256 的文本文件。

当前仍不制作 onefile、GameSave Scout 安装器、自动更新器和精简开发包，构建脚本不上传产物，也不自动创建公开 Release。轻量版中的 WebView2 Bootstrapper 只是缺失系统运行时的受控先决条件安装器，不改变 GameSave Scout 本身的便携形态。V0.3.4 目标发布包携带 `0001`～`0004` 四个新库初始化结构并使用 schema 4；开发阶段不提供 schema 1/2/3 到 schema 4 的迁移，检测到旧库时在写入前拒绝启动并提示用户自行移走或删除数据库。

### 1.1 V0.3.3 发布链改名与 V0.3.4 目标身份

V0.3.3 已把发布链迁移到统一的 GameSave Scout 技术身份，但该版本不保留正式便携包、标签或 Release。V0.3.4 继承这套发布链，不复用 V0.3.2 文件名或校验记录；以下能力已经实现，0.3.4 正式本地候选尚未构建：

- PyInstaller 配置为 `GameSaveScout.spec`，冻结核心目录和可执行文件为 `GameSaveScout` / `GameSaveScout.exe`。
- 完整版与轻量版目录分别为 `GameSave-Scout-0.3.4-win-x64` 和 `GameSave-Scout-0.3.4-win-x64-lite`，ZIP 与 `.sha256` 使用同一前缀。
- 发布清单、冻结 smoke、两份随包 README、LICENSE、第三方声明及构建错误信息统一使用新身份。
- `data` 继续位于 `GameSaveScout.exe` 旁，发布树仍不得预置或携带开发机 `data`。
- 正式构建必须从同一冻结核心派生两版，验证模式隔离、规则树、schema 4、无 `data`、ZIP 和 SHA-256；构建脚本仍不自动上传 Release。

V0.3.2 及更早实际生成的 `GameShelf-*`、`GameShelf.exe`、提交号和 SHA-256 均保持历史事实，不以新名称改写。

2026-08-26 完成的多根目录并发扫描修复、顶部全局导航、固定游戏目录、仅存档卡片回退与删除，以及批量封面已有封面标识统一归入 V0.3.4。V0.3.4 便携包尚未构建；后续需要发布时再从干净源码生成并记录真实清单、大小与 SHA-256。V0.3.3 不作为正式便携版本保留。

## 2. 当前实现状态与后续兼容性复核

当前已经实现并由自动测试或本机真实候选包验证：

- 源码与冻结环境统一的只读资源定位和缺失资源诊断。
- 固定版 WebView2 的受控 CAB 校验、安全解包、`runtime` 放置、运行时选择及 Windows 10 ACL 准备。
- 无控制台 PyInstaller onedir、从当前项目 Conda 前缀确定性收集原生依赖，以及 pywebview WinForms/WebView2 后端资源收集。
- 单一 PowerShell 构建入口、受控暂存/发布边界、发布清单、ZIP 复核和 SHA-256。
- 格式版本 2 的双模式发布清单、两种严格布局、双 ZIP 复核和六产物原子发布；质量门和 PyInstaller 核心在一次正式构建中只执行一次。
- `fixed`、`evergreen` 与源码三种明确运行时模式，以及轻量版的官方 API Evergreen 检测。轻量版缺失 Runtime 时先验证 Bootstrapper，再经用户确认调用系统 Explorer 选中文件并正常退出；生产代码不执行或等待安装器，也不自动重新启动。用户取消和成功打开位置不写崩溃日志，真实校验或 Explorer 故障继续使用冻结错误报告器。
- 源码与冻结版 JSON smoke；smoke 同时导入 `ssl`、`sqlite3`、pywebview 和 Edge 后端，冻结版数据与 WebView 用户数据仍位于程序旁 `data`。
- MIT 许可证、按实际候选包核对的第三方声明和 WebView2 原始许可证材料保留。
- Windows CI 继续覆盖 Python 测试、Ruff、mypy、前端测试、类型检查、生产构建和源码 smoke。

V0.1 按当前自动、本机与 Windows Sandbox 证据完成收尾。以下场景没有完整执行，不记为已通过，但已从 V0.1 发布前门槛移为后续可选兼容性复核：

- 干净目标 Windows 10/11 x64 设备中的两版完整复核。
- 轻量版在已经安装 Evergreen 时断网启动，以及微软安装器断网或失败后的行为。
- UNC/网络路径、只读目录、Fixed Runtime 缺失或损坏等补充故障场景。
- 未签名 GameSave Scout 在不同 Windows 环境中的 SmartScreen 实际提示。
- 模块 06 在其他目标 Windows 10/11 设备上的重复验收。

跨盘复制按当前范围决定不执行，不列为后续必做项。此前包含静默安装逻辑的候选只保留为历史证据。

## 3. 发布物结构

构建完成后的本地输出为：

```text
dist/
├─ GameSave-Scout-0.3.4-win-x64/
│  ├─ GameSaveScout.exe
│  ├─ _internal/
│  │  └─ resources/              # UI、内置规则、schema 与随包 Ludusavi 快照等只读资源
│  ├─ runtime/                   # 固定版 WebView2，根部包含 msedgewebview2.exe
│  ├─ README.txt
│  ├─ LICENSE
│  ├─ THIRD_PARTY_NOTICES.md
│  └─ release-manifest.json
├─ GameSave-Scout-0.3.4-win-x64.zip
├─ GameSave-Scout-0.3.4-win-x64.zip.sha256
├─ GameSave-Scout-0.3.4-win-x64-lite/
│  ├─ GameSaveScout.exe
│  ├─ _internal/
│  │  └─ resources/
│  ├─ prerequisites/
│  │  └─ MicrosoftEdgeWebview2Setup.exe
│  ├─ README.txt
│  ├─ LICENSE
│  ├─ THIRD_PARTY_NOTICES.md
│  └─ release-manifest.json
├─ GameSave-Scout-0.3.4-win-x64-lite.zip
└─ GameSave-Scout-0.3.4-win-x64-lite.zip.sha256
```

两个发布目录都不包含 `data`。首次正常启动时，程序才在 `GameSaveScout.exe` 旁创建 `data`。构建和压缩过程不得把开发机上的数据库、配置、封面、游戏、存档或其他本地用户数据带入发布物。V0.3.4 尚未产生可记录的目录、ZIP 大小或 SHA-256；V0.3.2 历史候选实测轻量版目录/ZIP 为 92.07/35.23 MiB，完整离线版为 751.35/326.15 MiB。

## 4. 资源与运行时定位

### 4.1 `ResourcePaths`

增加统一的只读资源定位组件 `ResourcePaths`：

- 源码模式读取仓库内的 `resources`。
- PyInstaller 冻结模式读取 `_internal/resources` 对应的冻结资源根目录。
- 应用代码不再各自推断 UI、引擎规则或 Ludusavi 种子位置，也不从系统 `PATH` 查找项目资源。
- 启动和冒烟测试一次性校验关键资源，错误信息应指出缺少的逻辑资源名称。

可写数据继续由现有应用路径组件定位到程序旁的 `data`，不得写入 `_internal/resources`。

V0.3.1 源码和后续冻结资源采用统一规则树：

```text
_internal/resources/rules/
├─ builtin/
│  ├─ engines.yaml
│  └─ saves.yaml
├─ schemas/
│  ├─ engines.schema.json
│  ├─ saves.schema.json
│  └─ README.md
└─ ludusavi/
   ├─ manifest.yaml
   ├─ manifest-meta.json
   ├─ manifest-index.sqlite
   └─ LICENSE
```

两个发布目录仍不得携带 `data`。首次正常启动才在 exe 旁创建 `data/rules/user/engines`、`data/rules/user/saves` 和其他可写目录。旧 `resources/manifests` 不再进入 V0.3.x 冻结载荷；开发机的 `data/manifests`、`data/rules/settings.json` 和活动 Ludusavi 快照也不得被打入发布包。

### 4.2 `WebViewRuntime`

`WebViewRuntime` 负责源码、完整离线版和轻量联网版三种明确模式。冻结版从 `release-manifest.json` 的 `runtimeMode` 读取模式，不根据目录是否碰巧存在进行静默猜测或回退：

- `fixed`：只接受 `GameSaveScout.exe` 旁的完整 `runtime`，至少验证 `runtime/msedgewebview2.exe` 存在，并在创建 pywebview 窗口前设置固定运行时路径。运行时缺失或损坏时直接报告错误，不回退系统 Evergreen。
- `evergreen`：发布目录不得包含 Fixed Runtime，不设置 `WEBVIEW2_RUNTIME_PATH`。程序先通过 WebView2 官方 API 检测系统 Evergreen；已安装时直接启动，缺失时进入手动安装引导。
- 源码模式：继续使用系统 Evergreen，不要求仓库存在发布清单、`runtime` 或 Bootstrapper。
- 所有模式的 WebView 用户数据都写入 `data/webview`。

轻量版缺失 Evergreen 时，程序必须先验证 `prerequisites/MicrosoftEdgeWebview2Setup.exe` 是绝对路径普通文件且与发布清单 SHA-256 一致，再显示原生中文确认框，说明安装需要联网、需要用户手动双击安装器，并且安装完成后要重新启动 GameSave Scout。用户同意后，程序只调用 Windows Explorer 打开 `prerequisites` 文件夹并选中该文件，随后正常退出；不得直接执行安装器、传递 `/silent /install`、等待外部安装进程、轮询安装结果或自动启动第二个 GameSave Scout 进程。用户取消以及成功打开安装位置都属于正常中止，退出码为 `0` 且不写错误堆栈。Bootstrapper 缺失或哈希错误、Evergreen 检测失败、Explorer 无法打开属于真实启动故障，应写入启动日志并显示可操作的中文错误。用户完成微软安装程序后手动再次启动 GameSave Scout，程序重新检测到 Evergreen 后正常创建主窗口。

当前两个包都仅支持本地文件系统路径。程序位于 UNC 或网络共享路径时直接拒绝启动，并提示用户将完整目录复制到本地可写位置。

### 4.3 `FrozenStartupReporter`

正式 exe 使用无控制台窗口模式。冻结版在关键资源、运行时、Bootstrapper、程序目录可写性、打开安装位置或早期初始化失败时，应通过原生 Windows 消息框显示可操作错误，不能只产生用户看不到的 traceback。轻量版的手动安装提示、成功打开安装位置与用户取消应和真实启动故障区分处理。

## 5. WebView2 受控输入策略

构建者手动从 Microsoft 官方来源下载指定版本的 Fixed Version WebView2 Runtime x64 归档和 Evergreen Bootstrapper。本地约定放入仓库根目录下被 `.gitignore` 排除的 `webview安装包`，再把两个文件的绝对路径传给构建脚本：

```powershell
$repoPath = (Get-Location).Path
& .\scripts\build_release.ps1 `
  -WebView2Archive (Join-Path $repoPath 'webview安装包\Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab') `
  -WebView2Bootstrapper (Join-Path $repoPath 'webview安装包\MicrosoftEdgeWebview2Setup.exe')
```

仓库内的受版本控制发布配置分别记录唯一允许的 Fixed Runtime 版本、CAB SHA-256，以及 Bootstrapper 文件版本、SHA-256、官方来源。构建脚本必须：

1. 验证两个输入文件存在、是本地普通文件且名称符合受控配置。
2. 分别计算 SHA-256 并与固定值比较，失败立即停止。
3. 验证 CAB 内部主程序和 Bootstrapper 的 Authenticode 签名均有效且签名者为 Microsoft Corporation。
4. 使用 Windows 本机可用方式解压到构建暂存区。
5. 将归档内部目录规范化为发布目录的 `runtime`，并验证其根部存在 `msedgewebview2.exe`。
6. 保留运行时归档中随附的许可证材料。
7. 只把 Bootstrapper 复制到轻量版的 `prerequisites`，不得放入完整离线版。

脚本不自动联网下载、不维护下载缓存、不实现多版本管理，也不把 `webview安装包` 中的两个外部二进制提交进 Git。受控输入升级通过人工下载官方文件、核验来源并更新版本和哈希完成。轻量版只有在目标电脑缺失 Evergreen 且用户手动运行安装器时，Bootstrapper 才会联网。

当前受控输入位于 `webview安装包/Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab` 和 `webview安装包/MicrosoftEdgeWebview2Setup.exe`。Fixed Runtime 版本为 `151.0.4129.86`，CAB SHA-256 为 `b62fc1e38544d038646173917ad158c8fb3d2c1c4b3c3ea5225e07d5d92fac68`；Bootstrapper SHA-256 为 `be695eb3732a94e181f008ab5cf6ee650f8644676e87f9e02b6ab0d02f2ea08e`。两个输入和 CAB 内部主程序均已核对为 Microsoft Corporation 有效签名；升级时不得静默覆盖这些值。

## 6. 单一构建入口与流水线

当前发布只提供一个用户入口 `scripts/build_release.ps1`，配合一个 `GameSaveScout.spec`。为避免在 PowerShell 中重复实现易错的版本、路径、哈希和 JSON 逻辑，使用 `scripts/release_tools.py` 维护受控发布原语，但不拆分出更多用户入口脚本。全部质量门禁和 PyInstaller 核心只执行一次，再从同一核心派生两个版本。

构建脚本按以下顺序执行：

1. 验证当前系统为 Windows x64，Python 为 3.12 x64，Node 为 24，并检查 npm、锁文件、仓库根目录、两个 WebView2 输入和构建机系统 Evergreen 可用性。
2. 验证 `pyproject.toml`、`src/gamesave_scout/__init__.py` 和 `frontend/package.json` 中的应用版本完全一致。
3. 运行现有全部 Python 和前端质量门禁，并生成最新 UI 生产资源。
4. 使用 `GameSaveScout.spec` 在 `build/release` 暂存区生成无控制台 onedir 产物。
5. 从同一核心建立两个暂存目录：完整版校验并解压 Fixed Runtime，轻量版只复制已校验的 Bootstrapper。
6. 为两个包分别写入对应说明的 `README.txt`、共同的 `LICENSE` 和 `THIRD_PARTY_NOTICES.md`，以及各自的 `release-manifest.json`。
7. 分别把两个暂存产物复制到独立临时目录执行冻结版结构化冒烟；构建期间不得弹出安装确认或运行 Bootstrapper。轻量版 smoke 使用构建机已安装的 Evergreen，安装分支由自动测试和干净虚拟机覆盖。
8. 分别验证两个目录、两个 zip 和两个 SHA-256；原始待压缩目录不得被首次运行产生的 `data` 污染。
9. 只有六个产物全部成功后，才以一个发布事务替换 `dist` 中当前版本的两组产物，不能出现一组新、一组旧。

构建失败时保留 `build/release` 中有助于诊断的暂存结果，并保留 `dist` 中上一次成功产物。构建脚本不得上传、暂存或提交 Git 内容，也不得改写 Git 历史。

开发工作区存在未提交修改时允许生成本地候选包，但 `release-manifest.json` 必须记录 `gitDirty: true`。正式对外分发前应在干净工作区重新构建。

## 7. PyInstaller 约束

- 目标架构仅 Windows x64。
- 使用 onedir 和 `--windowed` 等效的无控制台窗口入口，不制作 onefile。
- 显式收集 pywebview 后端、Pillow 插件、PyYAML、pefile、证书和项目只读资源；V0.3.x 必须完整包含 `rules/builtin`、`rules/schemas` 及 `rules/ludusavi` 四件套。
- 只读项目资源进入 `_internal/resources`；固定版 WebView2 只进入完整版 exe 旁的 `runtime`；Bootstrapper 只进入轻量版的 `prerequisites`；运行时生成的 `data` 不进入产物。
- 构建产物不得依赖开发机绝对路径、虚拟环境、Codex 专用运行时位置或当前工作目录。
- 发布入口版本与 Python 包版本保持一致。
- `GameSaveScout.spec` 是唯一的 PyInstaller 正式配置来源。
- 冻结载荷必须同时包含 `_internal/gamesave_scout/db/migrations/0001_initial.sql`、`0002_initial.sql`、`0003_initial.sql` 和 `0004_initial.sql`；发布关键文件校验缺少任一迁移都必须失败。
- 使用 Conda 构建时，必须在 PyInstaller `Analysis` 前把当前 `sys.prefix/Library/bin` 置于 `PATH` 首位，禁止从继承的父级 Anaconda 路径解析同名 DLL；集成测试至少逐字节核对发布包中的 OpenSSL DLL 与当前项目 Conda 前缀一致。
- 当前 Conda Python 3.12 的 `pyexpat.pyd` 依赖单独收集 `libexpat.dll`；实际构建测试必须防止该依赖再次缺失。
- pywebview 保留 WebView2 Core、WinForms，以及其 Edge 后端导入时会无条件解析的 `win-arm64`、`win-x64`、`win-x86` 三个 Loader 目录。发布目标仍仅为 Windows x64；这些目录是 pywebview 6.2.1 的启动依赖，不表示支持另外两种 CPU 架构。Android JAR 和未使用的 MSHTML interop 不进入发布物。

## 8. 冻结版启动诊断与冒烟协议

现有文本冒烟模式继续保留。新增适合无控制台 exe 的文件输出协议：

```powershell
GameSaveScout.exe --smoke-test --json-output <绝对临时文件路径>
```

成功时退出码为零，并向指定文件写入至少包含以下信息的 JSON。完整版示例为：

```json
{
  "schemaVersion": 4,
  "ok": true,
  "appVersion": "0.3.4",
  "frozen": true,
  "runtimeMode": "fixed",
  "executable": "D:\\Temp\\GameSave-Scout-0.3.4-win-x64\\GameSaveScout.exe",
  "resourceRoot": "D:\\Temp\\GameSave-Scout-0.3.4-win-x64\\_internal\\resources",
  "webviewRuntime": "D:\\Temp\\GameSave-Scout-0.3.4-win-x64\\runtime",
  "checks": {
    "resources": true,
    "ui": true,
    "engineRules": true,
    "ludusavi": true,
    "desktopDependencies": true,
    "webviewRuntime": true,
    "windows10Permissions": true,
    "applicationBootstrap": true
  },
  "error": null
}
```

轻量版报告 `runtimeMode: "evergreen"`、`webviewRuntime: null`，并记录系统 Evergreen 检测和 Bootstrapper 结构校验结果。构建脚本在两个发布目录副本中运行该命令，校验退出码、JSON 可解析性、版本、冻结状态、模式、路径和所有关键结果。`desktopDependencies` 必须实际导入 `ssl`、`sqlite3`、`webview` 和 `webview.platforms.edgechromium`，使 OpenSSL 错配及 pywebview Loader 缺失在发布前直接导致 smoke 失败。smoke 不得运行安装器或修改构建机系统状态；测试产生的 `data` 和 JSON 输出只存在于临时副本，验证后删除，不污染原始发布目录。

## 9. 发布清单、版本与哈希

双版本发布后，`release-manifest.json` 使用 `formatVersion: 2`，至少记录：

- GameSave Scout 版本、UTC 构建时间、Git 提交号和 `gitDirty`。
- 目标平台 `windows-x64`。
- Python、Node、npm、PyInstaller 和 pywebview 版本。
- 数据库架构版本、引擎规则版本、存档规则版本和规则 schema 版本。
- Ludusavi SHA-256 与已记录的上游提交号。
- `runtimeMode: fixed | evergreen`，并保留 `signed: false`。
- 完整版记录 Fixed Runtime 版本、CAB SHA-256 和 `fixedRuntime: true`；轻量版记录 Bootstrapper 文件版本、SHA-256、微软签名校验结果和 `fixedRuntime: false`。
- `GameSaveScout.exe`、关键只读资源，以及当前模式下 `runtime/msedgewebview2.exe` 或 `prerequisites/MicrosoftEdgeWebview2Setup.exe` 的实际 SHA-256。

V0.3.2 发布工具与冻结 smoke 已确认内置引擎/存档规则、两个 schema、Ludusavi YAML/元数据/SQLite/许可证均来自 `_internal/resources/rules`，随包快照可以完成只读状态与冷查询检查，首次启动只在临时发布副本旁生成空的用户规则目录，不复制开发机规则或旧 manifest 目录；完整离线版和轻量联网版冻结 smoke 均已实际执行并通过。

两个 zip 的 SHA-256 分别写在各自旁边的 `.sha256` 文件中，不写回 zip 内的发布清单，避免循环依赖。生成 zip 后必须分别重新打开归档验证模式对应的关键文件存在，再独立重算一次 SHA-256 并与 `.sha256` 内容比较。

版本必须由以下三个受版本控制位置共同校验，不允许静默选取其中一个覆盖其他位置：

- `pyproject.toml`
- `src/gamesave_scout/__init__.py`
- `frontend/package.json`

## 10. 许可证、第三方声明与签名

GameSave Scout 使用 MIT License。仓库根目录和发布目录都包含 `LICENSE`，版权行为：

```text
Copyright (c) 2026 GameSave Scout Contributors
```

仓库中的 `THIRD_PARTY_NOTICES.md` 作为固定维护文件，按真正随包分发的 Python、Vue、Pinia、Ludusavi、WebView2 等组件人工核对并补齐。当前不引入自动许可证爬取器；完整离线版保留 Fixed Runtime 原归档自带的许可证材料，轻量联网版明确记录 Evergreen Bootstrapper 的官方来源与再分发说明。

两个包使用各自的 `README.txt`：完整版明确可全程离线运行；轻量版明确依赖系统 Evergreen，系统缺失时 GameSave Scout 只打开并选中随包的微软 Bootstrapper，不会代替用户运行安装。README 必须说明手动双击、联网安装、安装后重新启动 GameSave Scout，以及取消、断网和微软安装器失败时的处理方式。

当前 GameSave Scout 本体不进行 Authenticode 签名，发布清单明确记录 `signed: false`。构建流水线预留“产物完整、压缩前”的未来签名点，但当前不要求证书或签名工具。发布说明应提示用户：未签名的新版本可能触发 Microsoft Defender SmartScreen 的“Windows 已保护你的电脑”或未知发布者提示，并且不同文件哈希的版本需要分别积累信誉。

## 11. 文件系统安全边界

构建脚本只允许清理或替换以下已解析的仓库内目标：

- 仓库内固定的 `build/release`。
- `dist` 内与当前应用版本完全匹配的完整版和 `-lite` 目录。
- `dist` 内与当前应用版本完全匹配的两个 zip 和两个 `.sha256`。

执行删除或替换前必须验证目标为绝对路径、父目录正确、仍位于预期仓库目录内，并拒绝重解析点、未经解析的变量、通配符和过宽目标。不得递归清理仓库根目录、用户目录、程序 `data`、外部 WebView2 归档或其他用户指定目录。

`.gitignore` 应忽略 `build/`、`dist/` 和约定的本地发布输入位置。构建日志不得输出用户游戏路径或 `data` 内容，也不得把商业游戏、用户封面或存档复制进构建区。

## 12. 自动验证与人工验收

### 12.1 自动验证

发布实现至少覆盖以下层次：

1. 单元测试：`ResourcePaths` 的源码/冻结/缺失资源，UNC 拒绝，`fixed`/`evergreen` 模式选择，Fixed Runtime 缺失，Evergreen 已安装，用户同意或取消，Bootstrapper 缺失或哈希不一致，Explorer 成功打开或启动失败，版本不一致，两个输入哈希不一致，危险清理目标拒绝和两种发布清单生成。
2. 全部现有质量门禁：Python 测试、Ruff、mypy、前端单元测试、TypeScript 类型检查、Vite 生产构建和源码冒烟。
3. 运行时安装安全：程序在提示前验证 Bootstrapper，并且只有用户明确同意后才打开其所在文件夹并选中文件；自动测试必须证明 GameSave Scout 不执行安装器、不等待外部进程、不创建主窗口，正常引导与取消不写错误堆栈，Explorer 或完整性真实失败写启动日志。
4. 真实 PyInstaller 构建：从同一核心生成两个独立副本并执行冻结版 JSON 冒烟，覆盖桌面原生依赖和 Edge 后端导入，并确认所有写入仅发生在副本的 `data`。
5. 发布物完整性：两个正式目录都没有 `data`；完整版只含 `runtime`，轻量版只含 `prerequisites`；两个 zip 可重新打开，关键文件齐全，独立重算哈希与各自 `.sha256` 一致。
6. 原子发布：在任一目录、清单、ZIP、SHA-256 或 smoke 失败时保留上一组完整的六个产物，不允许只替换其中一版。

本机开发与构建默认使用项目内 Conda prefix（`.venv`）提供的 Python 3.12 和 Node.js 24；正式构建入口仍必须显式校验 Node 主版本为 24，不能依赖 Codex 或某台开发机的私有 Node 路径。

2026-08-16 的手动引导修复前历史候选在 Windows 10 x64 使用受控 WebView2 151.0.4129.86 x64 CAB 和微软签名的 Evergreen Bootstrapper 1.3.257.13，从同一 PyInstaller 核心原子生成两个真实候选包。自动门禁为 Python 550 项、前端 86 项，并通过 Ruff、mypy、前端类型检查和生产构建；构建入口内部再次通过同一门禁。完整版目录/ZIP 为 746.52/324.64 MiB，轻量版为 87.24/33.72 MiB；两个发布副本的 JSON smoke 均退出 0，真实窗口均持续运行至少 8 秒并通过 `WM_CLOSE` 正常退出 0，未生成 `startup-error.log`。Fixed Runtime 与 Bootstrapper 的 Authenticode 签名均为有效 Microsoft Corporation，GameSave Scout 本体按 V0.1 设计未签名。该记录不替代下一节的干净虚拟机验收。

同日 Windows Sandbox 验收确认旧轻量版在用户同意后会同时保留 `MicrosoftEdgeWebview2Setup` 和多个 `MicrosoftEdgeUpdate` 进程，而 GameSave Scout 因同步、无超时地等待静默安装器而长期没有窗口或状态反馈。Sandbox 中读取到的 `msedge_installer.log` 是镜像旧有 Edge 浏览器初始化记录，未能提供本次 WebView2 安装结果。上述轻量版候选因此不再视为可分发候选；其体积与下列旧哈希只作为历史构建证据保留，不能与修复后的新候选混用。

该历史候选两个 ZIP 的 SHA-256 为：

- 完整离线版：`83f1f2e71c001c91ffe7e9e3df9db633e9c2b8fbbf267010fdc91d9e4ccc05c7`
- 轻量联网版：`b2751cd95258bd6c2b066513299f46f85106c9716db1422427831947ded50216`

受控 Evergreen Bootstrapper 的 SHA-256 为 `be695eb3732a94e181f008ab5cf6ee650f8644676e87f9e02b6ab0d02f2ea08e`；Fixed Runtime CAB 的 SHA-256 为 `b62fc1e38544d038646173917ad158c8fb3d2c1c4b3c3ea5225e07d5d92fac68`。

同日完成手动安装引导修复后，使用同一对受控输入重新执行正式构建。构建入口内部再次通过 Python 553 项、前端 86 项、Ruff、mypy、类型检查和生产构建，并从单一 PyInstaller 核心原子发布六个新产物。独立复核确认两个发布目录与 ZIP 清单、`.sha256`、模式隔离和冻结 JSON smoke 均通过：完整版目录/ZIP 为 746.52/324.64 MiB，轻量版为 87.24/33.72 MiB；正式目录都没有 `data`，完整版只有 `runtime`，轻量版只有 `prerequisites`。Fixed Runtime 与 Bootstrapper 的 Authenticode 状态均为 `Valid`，签名者为 Microsoft Corporation。

手动引导修复后新候选两个 ZIP 的 SHA-256 为：

- 完整离线版：`3f7677424866c52bb4ebdc38006c4757577afaf089712124dcfa1ec9beba7be9`
- 轻量联网版：`d3a058b66c2d4ef40676bc995f4b70f7d6e2160551743ffa962196127eddd4b8`

用户随后在全新 Windows Sandbox 按发布交接步骤验证轻量版主闭环：缺失 Evergreen 时显示新的手动安装提示；选择“是”后 Explorer 打开 `prerequisites` 并选中 Bootstrapper，GameSave Scout 正常退出，没有自动启动安装器且没有生成 `startup-error.log`；用户手动双击安装器并完成安装后，再次手动启动 GameSave Scout，主窗口正常出现。用户又在隔离副本中确认四项补充场景均通过：完整版在无系统 WebView2 且断网时直接启动；轻量版选择“否”后正常退出、不打开 Explorer 且不写错误日志；Bootstrapper 改名后显示缺失文件错误并生成启动日志；Bootstrapper 内容被修改后显示 SHA-256 错误并生成启动日志。上述结果覆盖本次 WebView2 修复的主路径和关键故障路径，但不替代完整 Windows 10/11、路径兼容性、微软安装器断网失败与 SmartScreen 场景矩阵。

同日完成本机路径兼容性验收。完整版放入中文与空格父目录、轻量版放入日文与空格父目录后，发布清单、冻结 JSON smoke、真实窗口启动、正常关闭、程序旁数据库落点和无启动错误日志均通过。随后在 D 盘内移动到常规长路径：完整版/轻量版的 `GameShelf.exe` 绝对路径为 181/186 字符，发布清单中最长负载绝对路径为 249/254 字符；两版再次通过清单、smoke 和真实窗口验收。把 EXE 路径提高到 272/277 字符时 Windows 进程创建即失败；缩短至 243/248 字符但使包内负载超过 260 字符时，两版均弹出“文件名或扩展名太长”，未进入 GameSave Scout 业务启动。V0.1 因此明确只支持完整发布负载绝对路径低于 260 字符的安装位置，达到或超过 260 字符不支持；发布说明和验收步骤必须写明该边界。全程只在 D 盘隔离副本间复制或移动，按用户决定未执行跨盘复制。

完成损坏声明式规则降级修复后，同日从干净提交 `6b29a8f1785dd123904e8e39dc9dadfa3bf89b9f` 再次运行正式构建入口。构建内部通过 Python 558 项、前端 88 项、Ruff、mypy、前端类型检查、生产构建、源码 smoke 和两版冻结 smoke，并原子发布六个当前候选产物。独立复核确认两个正式目录都没有 `data`，模式文件隔离正确，目录、ZIP、`.sha256` 和发布清单一致；完整版目录/ZIP 为 746.52/324.64 MiB，轻量版为 87.24/33.72 MiB。当前 ZIP SHA-256 为：

- 完整离线版：`a6421b7b2d692eebc845412eb5c801545828de5e69f36439c4730d0ae5ed948d`
- 轻量联网版：`d4470ab865f840ed73d3957c68e11dcbdc517ef61b1e833ce3ae764281a8656b`

Fixed Runtime 主程序与轻量版 Bootstrapper 的 Authenticode 状态均为 `Valid`，签名者为 Microsoft Corporation。在隔离轻量版冻结副本中损坏 `engines.yaml` 后，JSON smoke 仍退出 0，应用构建和引擎规则检查均通过，普通日志记录仅启用内置检测器的 WARNING，且不生成 `startup-error.log`；恢复规则后 smoke 再次通过。该结果确认当前冻结候选包含模块 04 的损坏规则降级修复，并满足 V0.1 当前收尾范围。

2026-08-18 从干净提交 `fc540ea5a6d94050b00911458f94ef7c5d50f5e7` 执行 V0.1.4 正式双版本构建。构建入口内部通过 Python 717 项、前端 142 项、Ruff、mypy、前端类型检查、生产构建、源码 smoke 和两版冻结 smoke；PyInstaller 6.22.1 只构建一次核心，再原子生成六个 V0.1.4 产物。两份发布清单均记录 `appVersion: 0.1.4`、`databaseSchemaVersion: 2`、上述完整 Git 提交号及 `gitDirty: false`。

构建后独立逐文件复核两个正式目录的清单大小与 SHA-256，并重新打开两个 ZIP 检查根目录、关键文件和模式隔离。完整版含 `runtime` 而不含 `prerequisites`，轻量版反之；两版目录和 ZIP 均不含 `data`，并同时含 `0001_initial.sql` 与 `0002_initial.sql`。Fixed Runtime 主程序和 Bootstrapper 的 Authenticode 状态均为 `Valid`，签名者为 Microsoft Corporation。完整版目录/ZIP 为 746.63/324.72 MiB，轻量版为 87.35/33.80 MiB。V0.1.4 ZIP SHA-256 为：

- 完整离线版：`4ceef6e5759977beaab2dc89cec73f2356aed1e677b6e2135b443c8682f9693b`
- 轻量联网版：`5a454fa05da362f822b6a39eef374bc898c546cd644aae3321e305354dd6156d`

2026-08-20 首次执行 V0.2.1 正式构建时，独立复核发现两个包内的 `README.txt` 仍硬编码为 `0.1.4`，因此该组六产物立即作废且未作为候选交付。根因是发布模板原样复制且发布布局未校验说明版本；新增回归测试先复现“旧版本 README 仍被接受”，再让发布布局要求 README 包含当前应用版本，并把两份模板更新为 `0.2.1`。发布工具测试 33 项、Ruff 和 mypy 聚焦检查均通过后，从干净提交 `184ac7acb999e06e36fba5b2f5f94b08a776dbe7` 重新执行正式构建。

最终 V0.2.1 构建入口通过 Python 858 项、前端 48 个测试文件共 193 项、Ruff、mypy、Vue 类型检查、115 模块生产构建、schema 4 源码 smoke 和两版冻结 smoke；PyInstaller 6.22.1 只构建一次核心，再原子生成六个产物。两份清单均记录 `appVersion: 0.2.1`、`databaseSchemaVersion: 4`、上述完整 Git 提交号及 `gitDirty: false`。独立复核逐文件验证两个目录和 ZIP，确认 README 版本正确，四个迁移齐全，完整版只含 `runtime`、轻量版只含 `prerequisites`，两版均不含 `data`；Fixed Runtime 主程序与 Bootstrapper 的 Authenticode 状态均为 `Valid`，签名者为 Microsoft Corporation。完整版目录/ZIP 为 751.14/326.03 MiB，轻量版为 91.87/35.11 MiB。V0.2.1 ZIP SHA-256 为：

- 完整离线版：`bf821d6b0d00a00f9c184cdbf1b7df3ba1da0001cf7aa3e7ced9851b79064af5`
- 轻量联网版：`8e8749a44343ce021aaaca840c81fef73b1777d58fd59f3289753659f7f5f44f`

2026-08-25 首次执行 V0.3.2 正式构建时，发布布局在 PyInstaller 核心完成后发现两份随包 README 仍写 `0.2.1`。构建在写清单阶段退出，未用错误内容覆盖 `dist`。新增直接把仓库真实发布模板放入当前版本发布树并构建清单的回归测试后，两份模板更新为 `0.3.2`，再从干净提交 `55d8024768ff50c5722a9ff85816c7d382d93855` 重跑完整入口。

最终 V0.3.2 构建入口通过 Python 1276 项、1 项平台条件跳过，前端 57 个测试文件共 241 项、Ruff、mypy、Vue 类型检查、141 模块生产构建、schema 4 源码 smoke 和两版冻结 smoke；PyInstaller 6.22.1 只构建一次核心，再原子生成六个产物。两份清单均记录 `appVersion: 0.3.2`、`databaseSchemaVersion: 4`、引擎/存档规则版本 `2026.08.25-1`、上述完整 Git 提交号及 `gitDirty: false`。独立复核逐文件验证两个目录与 ZIP，确认规则树、四个初始化结构、README 版本和模式隔离正确，两版均不含 `data`；Fixed Runtime 主程序与 Bootstrapper 的 Authenticode 状态均为 `Valid`，签名者为 Microsoft Corporation。完整版目录/ZIP 为 751.35/326.15 MiB，轻量版为 92.07/35.23 MiB。V0.3.2 ZIP SHA-256 为：

- 完整离线版：`af4c7b50236a25ed0f3529e6466078904b8b20a910d93af26ee39ee40491e252`
- 轻量联网版：`181dbb7156b97778a7739dac59baa3107d99decaa94cced7bb8d387d628880bb`

V0.3.4 当前只完成源码与发布链收口，尚未运行正式双版本构建。本节不得提前记录 V0.3.4 提交号、目录/ZIP 大小或 SHA-256；这些数据必须在后续从干净提交完成构建和独立复核后补充。

### 12.2 人工验收结论

V0.3.4 本轮源码质量门禁已通过：Python 1281 项通过、1 项跳过，前端 57 个测试文件共 248 项通过，并通过 Ruff、mypy、Vue 类型检查、141 模块生产构建和 schema 4 源码 smoke。本轮不执行冻结 smoke 或本机构建产物独立复核；下列历史兼容性证据继续保留，未执行场景不记为本轮新通过。

2026-08-16 已在本机和 Windows Sandbox 完成 V0.1 当前范围验收：轻量版手动安装与重新启动主闭环、用户取消、Bootstrapper 缺失与 SHA-256 不匹配、完整版在无系统 WebView2 且断网时启动、中文/日文/空格与常规长路径、首次与重复启动、便携数据落点、游戏库主流程，以及模块 06 的真实游戏、资源占用、多缩放和启动器脱离降级。完整发布负载绝对路径达到或超过 260 字符明确不受支持，跨盘复制按范围决定不执行。

以下没有完整执行，不记为已通过；从 2026-08-16 起统一作为后续版本可选兼容性复核，不再阻塞 V0.1：

- 在额外的干净 Windows 10/11 x64 目标设备上重复两版完整流程。
- 轻量版在已经安装 Evergreen 时断网启动。
- 微软 Evergreen 安装器在断网或安装失败时的实际界面与后续重启行为。
- Explorer 无法打开、UNC/网络路径、只读目录，以及 Fixed Runtime 缺失或损坏等补充故障场景。
- 未签名 GameSave Scout 在不同系统环境中的 SmartScreen 实际提示。

## 13. 实施顺序

1. 以测试驱动方式把轻量版的 Bootstrapper 执行、等待和同进程继续逻辑替换为手动安装引导：先验证文件，再由用户确认，只打开 Explorer 并正常退出。
2. 将发布清单升级为格式版本 2，增加双包命名、受控 Bootstrapper 配置、两种布局验证和六产物原子发布模型。
3. 扩展 `scripts/build_release.ps1`：两个输入只校验一次，质量门和 PyInstaller 只运行一次，从同一核心派生完整离线版与轻量联网版。
4. 扩展冻结 smoke、README、许可证/第三方声明和完整性验证，确保 smoke 不运行安装器或修改构建机系统状态。
5. 运行全部自动门禁，生成两个真实候选包并核对体积、原生依赖、清单、ZIP 和 SHA-256。
6. 记录本机与 Windows Sandbox 的 V0.1 验收结论；额外目标设备和特殊故障矩阵保留为后续可选兼容性复核。

一次性详细实施计划放入 `docs/历史归档`；后续缺陷修复和需求变化继续直接维护本文，不为每个小改动新建固定设计文档。

## 14. 变更记录

| 日期 | 变更 |
| --- | --- |
| 2026-08-12 | 确定 PyInstaller onedir、程序旁 `data` 和固定版 WebView2 方向。 |
| 2026-08-13 | 明确当前只完成源码运行与便携路径，正式冻结发布仍未实施。 |
| 2026-08-15 | 确认 V0.1 只生成本地完整离线 onedir、zip 和 SHA-256，不上传或自动创建公开 Release。 |
| 2026-08-15 | 确认构建者手动提供官方 Fixed Version WebView2 x64 归档，脚本仅做固定版本与哈希校验、解压和随包放置，不自动联网或回退 Evergreen。 |
| 2026-08-15 | 确认 MIT License、`GameSave Scout Contributors` 版权行、首版不签名、单一 PowerShell 构建入口、冻结副本 JSON 冒烟及候选包/可分发包验收边界。 |
| 2026-08-16 | 完成自动化发布实现并锁定 WebView2 151.0.4129.86 x64；真实构建审计补齐 Conda `libexpat.dll`、核对 pywebview 运行资源并更新第三方声明。本机候选包通过自动门禁，干净 Windows 10/11 离线验收仍待执行。 |
| 2026-08-16 | 修复本机与 Windows Sandbox 冻结启动失败：PyInstaller 现优先从项目 Conda 前缀收集 OpenSSL 等原生 DLL，避免把 Python 3.12.13 的 `_ssl.pyd` 与父级 Anaconda OpenSSL 3.0.13 错配；同时保留 pywebview Edge 后端导入所需的三套 Loader 目录。冻结 smoke 新增桌面依赖与 Edge 后端导入检查，本机真实窗口启动后无 `startup-error.log`，Windows Sandbox 仍需用新候选包复验。 |
| 2026-08-16 | 批准双版本发布：保留现有完整离线包名，并新增 `GameShelf-0.1.0-win-x64-lite`。轻量版使用系统 Evergreen，缺失时经用户同意运行随包官方 Bootstrapper，安装成功后同一进程继续启动；构建只执行一次核心和质量门，再原子发布两组目录、ZIP 与 SHA-256。 |
| 2026-08-16 | 完成双版本发布实现和本机真实候选验证：受控 Bootstrapper 版本为 1.3.257.13；Python 550 项与前端 86 项门禁通过；一次核心构建原子生成六个产物，完整版/轻量版解压体积为 746.52/87.24 MiB，两个发布副本的 smoke 和 8 秒真实窗口启动/正常退出均通过。下一项转入四类干净 Windows 10/11 场景验收。 |
| 2026-08-16 | Windows Sandbox 发现轻量版静默 Bootstrapper 在确认后长期无反馈；进程证据显示安装器与 Edge Update 仍在运行，而 GameSave Scout 的超时只覆盖安装器退出后的重检。批准改为手动安装引导：GameSave Scout 验证文件后只打开目录并选中安装器，正常退出；用户手动安装并重新启动。原轻量版候选作废，待修复后重建。 |
| 2026-08-16 | 完成轻量版手动安装引导实现：删除 Bootstrapper 执行、等待、轮询和自动续启路径，改为校验后用系统 Explorer 选中文件并正常退出；提示与轻量版 README 明确由用户手动安装和重新启动。Python 553 项、前端 86 项、Ruff、mypy、类型检查、生产构建和源码 smoke 均通过，新的双版本候选与 Sandbox 闭环仍待完成。 |
| 2026-08-16 | 使用手动安装引导源码重新完成正式双版本构建，六个新产物原子发布并通过独立目录/ZIP/校验文件、模式隔离、微软签名和两版冻结 smoke 复核；新 ZIP 哈希为 `3f767742…be9` 与 `d3a058b6…4b8`。真实窗口、干净 Sandbox 和 Windows 10/11 人工验收仍待完成。 |
| 2026-08-16 | 用户在全新 Windows Sandbox 完成修复后轻量版主闭环：提示后只打开目录并选中安装器，GameSave Scout 正常退出且不自动运行安装器、不写崩溃日志；用户手动安装并重新启动后主窗口正常出现。取消、完整性故障、完整版断网及完整 Windows 10/11 验收仍保留为首发待办。 |
| 2026-08-16 | Windows Sandbox 四项补充验收均通过：完整版无系统 WebView2 断网启动；轻量版取消后不打开 Explorer、不写错误日志；Bootstrapper 缺失和 SHA-256 篡改均显示原生错误并生成启动日志。模块 07 剩余范围收敛为目标 Windows 10/11、路径/跨盘、安装器断网失败和 SmartScreen 验收。 |
| 2026-08-16 | 用户确认当前没有可用于完整 Windows 10/11 验收的设备；目标系统矩阵暂缓但不视为通过或取消，仍保留为正式分发前门槛。现有设备可执行的路径、跨盘和故障降级检查可独立继续。 |
| 2026-08-16 | 本机双版本已通过中文、日文、空格及最长负载绝对路径 249/254 字符的常规长路径清单、冻结 smoke 和真实窗口验收；负载路径达到或超过 260 字符时两版均在业务启动前失败。跨盘复制按用户决定未执行；确认 V0.1 明确不支持完整发布负载绝对路径达到或超过 260 字符。 |
| 2026-08-16 | 损坏声明式规则降级修复后，从干净提交 `6b29a8f1785dd123904e8e39dc9dadfa3bf89b9f` 重建并原子发布双版本六产物；Python 558 项、前端 88 项及完整构建门禁通过，当前 ZIP 哈希为 `a6421b7b…948d` / `d4470ab8…a8656b`。隔离轻量版冻结副本在损坏规则下继续启动、记录降级 WARNING 且不生成启动错误日志，恢复规则后再次通过。 |
| 2026-08-16 | 确认 V0.1 按现有自动、本机和 Windows Sandbox 证据完成收尾；完整目标 Windows 10/11、Evergreen 断网、微软安装器失败、UNC/只读目录/Fixed Runtime 损坏和 SmartScreen 实机矩阵改为后续可选兼容性复核，不记为已通过，也不再阻塞 V0.1。跨盘复制维持不执行。 |
| 2026-08-18 | 源码与后续冻结载荷升级为数据库 schema 2；PyInstaller 和发布关键文件校验同时要求 `0001_initial.sql`、`0002_initial.sql`，源码冒烟通过 schema 2。用户随后批准将本轮统一收口为 V0.1.4 并重建最新便携候选包。 |
| 2026-08-18 | 从干净提交 `fc540ea5` 完成 V0.1.4 双版本正式构建与独立复核；构建门禁为 Python 717 项、前端 142 项，两版冻结 smoke、清单、模式隔离、schema 2 迁移、无 `data`、ZIP 和微软签名均通过。完整版/轻量版 ZIP 为 324.72/33.80 MiB，SHA-256 为 `4ceef6e5…f9693b` / `5a454fa0…6156d`。 |
| 2026-08-20 | 发布载荷升级为 V0.2.1 与 schema 4，关键文件校验要求 `0001`～`0004` 四个迁移；首次构建复核发现并作废仍含 0.1.4 README 的产物，新增 README 版本一致性回归后从干净提交 `184ac7a` 重建。 |
| 2026-08-20 | 完成 V0.2.1 双版本正式构建与独立复核；Python 858 项、前端 193 项及完整门禁、两版冻结 smoke、清单、模式隔离、schema 4、无 `data`、ZIP 和微软签名均通过。完整版/轻量版 ZIP 为 326.03/35.11 MiB，SHA-256 为 `bf821d6b…4af5` / `8e8749a4…f44f`。 |
| 2026-08-23 | 确认 V0.3.x 冻结资源设计：内置引擎/存档规则、schema 和 Ludusavi 四件套统一进入 `_internal/resources/rules`；发布物继续不携带 `data`，首次启动创建空用户规则目录，冻结 smoke 与发布清单增加规则树、许可证和活动数据隔离检查。 |
| 2026-08-23 | 完成 V0.3.1 发布前源码校验：PyInstaller spec 与严格发布布局要求统一规则树，smoke 检查规则目录/许可证/已编译快照，发布元数据读取双规则版本并对 Ludusavi 索引执行冷查询；V0.3.1 未单独构建便携包，相应功能随后随 V0.3.2 进入候选。 |
| 2026-08-25 | V0.3.2 首次正式构建在 PyInstaller 核心完成后由发布清单校验发现两份随包 README 仍写 0.2.1；未原子发布错误产物，新增直接构建真实发布模板的版本一致性回归并更新说明为 0.3.2。 |
| 2026-08-25 | 从干净提交 `55d8024768ff50c5722a9ff85816c7d382d93855` 完成 V0.3.2 双版本正式构建与独立复核；Python 1276 项通过、1 项跳过，前端 241 项及完整门禁、两版冻结 smoke、格式 2 清单、schema 4、规则版本 `2026.08.25-1`、模式隔离、无 `data`、ZIP 与微软签名均通过。完整版/轻量版目录为 751.35/92.07 MiB，ZIP 为 326.15/35.23 MiB，SHA-256 为 `af4c7b50236a25ed0f3529e6466078904b8b20a910d93af26ee39ee40491e252` / `181dbb7156b97778a7739dac59baa3107d99decaa94cced7bb8d387d628880bb`。 |
| 2026-08-25 | 完成 GameSave Scout 单一产品技术身份与发布链源码迁移；旧 V0.3.2 产物与校验记录保持原样，后续构建不自动上传 Release。 |
| 2026-08-26 | 确认当天新增功能统一归入 V0.3.4；V0.3.4 便携包、清单与 SHA-256 待源码和文档收口后重新生成，V0.3.3 不作为正式便携版本保留。 |
