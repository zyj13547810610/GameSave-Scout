# GameShelf

GameShelf 是一个面向 Windows 10/11 x64 的本地优先、便携式个人游戏库与存档定位工具。

当前正在按 [`docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md`](docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md) 完成 V0.1 首发版。

## 开发环境

- Conda（Anaconda 或 Miniconda）
- 项目内 Conda 环境：Python 3.12、Node.js 24

以下命令均在项目根目录执行。首次开发时创建项目内 `.venv` 环境并安装依赖：

```powershell
conda create --prefix .\.venv --override-channels -c conda-forge python=3.12 nodejs=24 -y
conda activate .\.venv
python -m pip install -e ".[dev]"
npm --prefix frontend install
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

## 构建 Windows x64 便携候选包

正式构建只接受微软官方 WebView2 Fixed Version Runtime x64 CAB 的绝对路径。CAB 的文件名、版本和 SHA-256 必须与受版本控制的 `release/webview2-runtime.json` 完全一致；构建脚本不会联网下载或自动选择其他版本。

在已激活仓库 `.venv` 的 PowerShell 中执行：

```powershell
.\scripts\build_release.ps1 `
  -WebView2Archive "D:\absolute\Microsoft.WebView2.FixedVersionRuntime.151.0.4129.86.x64.cab"
```

脚本会运行全部 Python/前端门禁、生成无控制台 PyInstaller onedir、解包内置 WebView2、执行源码及冻结版 JSON smoke、验证发布清单，再原子发布以下三个目标：

```text
dist/GameShelf-0.1.0-win-x64/
dist/GameShelf-0.1.0-win-x64.zip
dist/GameShelf-0.1.0-win-x64.zip.sha256
```

可以独立复核 ZIP 哈希：

```powershell
Get-FileHash .\dist\GameShelf-0.1.0-win-x64.zip -Algorithm SHA256
Get-Content .\dist\GameShelf-0.1.0-win-x64.zip.sha256
```

成功生成只代表本机候选包通过自动验证。正式分发前仍需按模块 07 固定设计，在无 Python、Node.js、Visual Studio 和系统 WebView2 的干净 Windows 10/11 x64 虚拟机中断网验收。

## 启动项目

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

## 当前游戏库能力

- 可配置多个根目录，每个目录可选择“直接子目录”或 1–8 层递归扫描，并拥有独立排除规则；
- 启动时先显示 SQLite 中的缓存游戏，再在后台执行快速扫描；递归根目录的快速扫描只核验已知游戏；
- 完整扫描成功后才会把消失的游戏标记为失效，取消、错误或盘符暂时不可用不会改变原状态；
- 支持编辑标题、选择主 EXE、工作目录、参数数组和环境变量，并以 `shell=False` 启动；
- 每个游戏可设置一张封面，支持选择本地 PNG/JPEG/WebP/BMP 或直接粘贴截图；外部原文件不会被移动或删除；
- 游戏库支持标题搜索、状态/引擎筛选、2:3 封面网格和保留网格上下文的右侧详情抽屉；
- 主页支持跨筛选批量选择已安装/失效游戏，并通过单个事务安全更新排除项和删除记录；
- 界面支持 80%～120% 五档缩放，比例保存在程序旁的便携配置中；
- UI 与封面只通过带随机会话令牌的 `127.0.0.1` 只读服务访问，不向前端开放任意本地路径；
- 配置与游戏库数据库位于程序旁的 `data` 目录，可随整个程序目录迁移。
