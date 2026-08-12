# GameShelf

GameShelf 是一个面向 Windows 10/11 x64 的本地优先、便携式个人游戏库与存档定位工具。

当前正在按 [`docs/superpowers/plans/2026-08-12-gameshelf-roadmap.md`](docs/superpowers/plans/2026-08-12-gameshelf-roadmap.md) 实施 V1。

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
