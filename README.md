# GameShelf

GameShelf 是一个面向 Windows 10/11 x64 的本地优先、便携式个人游戏库与存档定位工具。

当前正在按 [`docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md`](docs/superpowers/plans/2026-08-12-GameShelf-开发路线图.md) 实施 V1。

## 开发环境

- Python 3.12
- Node.js 24 LTS

后端安装与检查：

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check src tests
python -m mypy src
```

前端安装与检查：

```powershell
npm --prefix frontend install
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

前端生产构建会直接更新 `resources/ui`。随后可以在不打开窗口的情况下验证便携路径与数据库：

```powershell
python -m gameshelf --smoke-test
```

正常开发启动使用 `python -m gameshelf`。可通过 `GAMESHELF_DEV_SERVER_URL` 指向本地 Vite 开发服务器；冻结版会忽略该变量并只加载随包 UI。

## 当前游戏库能力

- 可配置多个根目录，每个目录可选择“直接子目录”或 1–8 层递归扫描，并拥有独立排除规则；
- 启动时先显示 SQLite 中的缓存游戏，再在后台执行快速扫描；递归根目录的快速扫描只核验已知游戏；
- 完整扫描成功后才会把消失的游戏标记为失效，取消、错误或盘符暂时不可用不会改变原状态；
- 支持编辑标题、选择主 EXE、工作目录、参数数组和环境变量，并以 `shell=False` 启动；
- 每个游戏可设置一张封面，支持选择本地 PNG/JPEG/WebP/BMP 或直接粘贴截图；外部原文件不会被移动或删除；
- 游戏库支持标题搜索、状态/引擎筛选、2:3 封面网格和保留网格上下文的右侧详情抽屉；
- UI 与封面只通过带随机会话令牌的 `127.0.0.1` 只读服务访问，不向前端开放任意本地路径；
- 配置与游戏库数据库位于程序旁的 `data` 目录，可随整个程序目录迁移。
