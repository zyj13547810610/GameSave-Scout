# GameShelf

GameShelf 是一个面向 Windows 10/11 x64 的本地优先、便携式个人游戏库与存档定位工具。它用于整理分散在不同目录中的游戏、维护启动配置与封面、识别常见游戏引擎，并帮助用户查找和确认存档位置。

GameShelf 不需要账号或云服务。游戏库、配置、封面、日志和 WebView 用户数据默认保存在程序旁的 `data` 目录，可以随整个程序目录迁移。V0.1 当前范围与实现状态见[开发路线图](docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md)。

## 主要功能

- 管理多个游戏根目录，支持直接子目录或 1～8 层递归扫描、独立排除规则和后台快速核验；
- 编辑游戏标题、主程序、工作目录、启动参数和环境变量，并使用经过验证的配置启动游戏；
- 管理单张游戏封面，支持搜索、状态/引擎筛选、批量处理和 80%～120% 界面缩放；
- 通过专用检测器与声明式规则识别 Galgame、RPG Maker、Unity、Ren'Py、Unreal 等引擎，并保留证据和手动覆盖；
- 按需使用自定义清单、Ludusavi 和引擎提示查找静态存档位置；
- 提供单次引导式存档寻找：先监控文件变化，再启动游戏并由用户完成一次保存，最后审核候选位置；
- 使用程序旁 SQLite 数据库和便携配置，不扫描或上传未授权的全盘内容。

V0.1 不包含存档备份、恢复、同步、云服务和常驻后台监控。

## 便携版选择与使用

V0.1 提供两个 Windows x64 便携包：

| 版本 | 目录/ZIP 名称 | WebView2 | 适用场景 |
| --- | --- | --- | --- |
| 完整离线版 | `GameShelf-0.1.0-win-x64` | 自带 Fixed Version Runtime | 体积较大，可在系统没有 WebView2 时离线启动 |
| 轻量联网版 | `GameShelf-0.1.0-win-x64-lite` | 使用系统 Evergreen Runtime | 下载体积较小，系统缺失 Runtime 时需要联网手动安装 |

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
├─ GameShelf-0.1.0-win-x64/
├─ GameShelf-0.1.0-win-x64.zip
├─ GameShelf-0.1.0-win-x64.zip.sha256
├─ GameShelf-0.1.0-win-x64-lite/
├─ GameShelf-0.1.0-win-x64-lite.zip
└─ GameShelf-0.1.0-win-x64-lite.zip.sha256
```

可以独立复核两个 ZIP：

```powershell
Get-FileHash .\dist\GameShelf-0.1.0-win-x64.zip -Algorithm SHA256
Get-Content .\dist\GameShelf-0.1.0-win-x64.zip.sha256

Get-FileHash .\dist\GameShelf-0.1.0-win-x64-lite.zip -Algorithm SHA256
Get-Content .\dist\GameShelf-0.1.0-win-x64-lite.zip.sha256
```

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
- [便携版打包与发布设计](docs/superpowers/plans/2026-08-12-GameShelf-07-便携版打包与发布.md)
- [MIT License](LICENSE)
- [第三方声明](THIRD_PARTY_NOTICES.md)
