# GameShelf 分阶段实施路线图

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 先交付稳定好用的 GameShelf V0.1 Windows 10/11 x64 便携游戏书架，再独立实施引导式存档检测与孤立存档反推。

**架构：** Vue 3/TypeScript 前端运行在 pywebview 中，并调用范围受限且带类型定义的 Python 桥接层。Python 负责 SQLite、扫描、Windows 集成、引擎识别、封面处理和存档发现；应用自身的所有持久化文件均存放在可执行文件旁的 `data` 目录中。

**技术栈：** V0.1 使用 Python 3.12、pywebview 6.2.x/WebView2、SQLite、Vue 3、TypeScript、Vite、Vitest、pytest、Pillow、pefile、PyYAML、RapidFuzz、PyInstaller 6.21.x、Node.js 24 LTS。`watchdog` 与 `psutil` 延至 V0.2 引导式检测时引入。

## 全局约束

- V0.1 仅面向 Windows 10 和 Windows 11 x64；只有被测单元与平台无关时，开发测试才可在其他主机上运行。
- 发布 PyInstaller `onedir` 构建，禁止使用 `onefile`。
- 配置、数据库、封面、清单、WebView 状态、备份、日志和临时文件都必须位于可执行文件旁的 `data/` 下。
- 默认离线运行；只有用户明确执行 Ludusavi 更新操作时才可访问网络。
- 绝不上传游戏名称、路径、存档路径、文件列表或存档内容。
- 扫描期间绝不执行 EXE；V0.1 只有用户明确执行普通启动操作时才运行用户选择的主程序，V0.2 的存档检测会话同样必须由用户明确启动。
- 绝不删除、移动、解包或修改用户的游戏文件和存档文件。
- 后续扫描必须保留用户手动设置的标题、可执行文件、引擎和存档路径。
- 将引擎识别视为可选元数据：引擎未知的 Windows 游戏也必须完整可用。
- 静态建议、动态候选和孤立存档都不得未经用户确认写入存档位置。
- V0.1 不实现引导式动态检测、孤立存档发现、翻译、资源提取、DLL 注入、作弊以及存档备份/恢复。
- 行为变更采用 TDD；先运行针对性测试，再运行完整测试套件；每个任务完成后提交一次。
- Python 必须使用参数数组并设置 `shell=False`；绝不根据 UI 输入拼接 shell 命令。
- 用户作出最终项目许可证决定前，不得公开发布仓库。

---

## 为什么要拆分实施

已确认的规格涵盖多个故障模式各不相同的子系统。V0.1 只由增量 1 至 5 和增量 7 构成；增量 6 拆为后续版本，不能阻塞首发便携包。

| 增量 | 计划 | 可运行交付物 |
|---|---|---|
| 1 | [基础设施与桌面外壳](2026-08-12-GameShelf-01-基础架构.md) | 一个空的便携版 GameShelf 窗口，具备已迁移的 SQLite 数据库和类型化桥接层 |
| 2 | [游戏库扫描与启动](2026-08-12-GameShelf-02-游戏库扫描与启动.md) | 将多个根目录扫描到持久化游戏库中，并可启动游戏和打开文件夹 |
| 3 | [封面与游戏库体验](2026-08-12-GameShelf-03-封面与游戏库界面.md) | 封面网格、详情抽屉、搜索/筛选、本地选择及剪贴板粘贴 |
| 4 | [引擎识别](2026-08-12-GameShelf-04-游戏引擎识别.md) | 已确认的正式和实验性引擎识别器，包含证据展示与手动覆盖 |
| 5 | [静态存档位置](2026-08-12-GameShelf-05-静态存档位置.md) | V0.1 的手动多存档路径，以及只在用户主动请求时运行的可选静态建议 |
| 6 | [动态及孤立存档发现](2026-08-12-GameShelf-06-动态与孤立存档发现.md) | 延后：V0.2 引导式监控；V0.3 孤立存档扫描与审核 |
| 7 | [便携打包与发布](2026-08-12-GameShelf-07-便携版打包与发布.md) | 可复现的 onedir 安装包，包含固定版 WebView2 运行时及干净机器检查 |

## 依赖顺序

```text
01 基础设施
  └─ 02 游戏库扫描与启动
       ├─ 03 封面与游戏库体验
       └─ 04 引擎识别
            └─ 05 手动存档位置/按需静态建议
                 └─ 07 V0.1 便携发布

05 ──后续──> 06A V0.2 引导式检测 ──> 06B V0.3 孤立存档
```

计划 02 完成后，计划 03 和 04 可以任选顺序开发，但两者都必须在计划 05 验收前完成。计划 05 完成后可直接执行计划 07 并发布 V0.1；计划 06 不再是首发版依赖，在执行前应按 V0.2/V0.3 重新拆分和复审。

## 固定的文件结构

```text
GameShelf/
├─ pyproject.toml
├─ README.md
├─ THIRD_PARTY_NOTICES.md
├─ frontend/
│  ├─ package.json
│  ├─ package-lock.json
│  ├─ vite.config.ts
│  ├─ vitest.config.ts
│  ├─ src/
│  │  ├─ api/                        # 桥接契约与客户端
│  │  ├─ app/                        # 应用外壳与路由
│  │  ├─ features/library/
│  │  ├─ features/scan-roots/
│  │  ├─ features/covers/
│  │  ├─ features/engines/
│  │  └─ features/saves/
│  └─ tests/
├─ src/gameshelf/
│  ├─ app.py                         # 组合根与桌面入口
│  ├─ bootstrap/                     # 便携路径、日志、启动
│  ├─ bridge/                        # pywebview 白名单与任务进度
│  ├─ db/                            # SQLite 连接、迁移、写入器
│  ├─ library/                       # 游戏/根目录模型、仓储、服务
│  ├─ scanning/                      # 路径键、发现、EXE 排名
│  ├─ covers/                        # 导入、缩略图、资源访问
│  ├─ engines/                       # 识别器接口、规则、检测器
│  ├─ saves/                         # 模板、清单、监控、评分
│  ├─ platform/windows/              # 进程、注册表、文件系统、shell
│  └─ web/                           # 只读回环 UI/封面服务器
├─ resources/
│  ├─ ui/                            # 生成的 Vite 生产构建输出
│  ├─ manifests/
│  └─ rules/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ scripts/
├─ packaging/
└─ docs/superpowers/
```

优先使用职责集中的文件，不要创建庞大的 `utils.py`、`services.py` 或共享“杂项”模块。功能模块可以导入平台接口、数据库基础设施和共享契约，但不得导入前端构建代码。

计划片段中出现的每个具名 pytest/Vitest 测试工具或夹具，都必须在该任务中实现在同一测试文件，或最近的功能专用 `conftest.py`/测试辅助文件中。测试工具应使用临时目录、内存假对象或注入的适配器；不得依赖开发者真实的游戏库、注册表、剪贴板、网络或已安装应用。

## 跨计划接口

以下名称在所有计划中保持稳定：

```python
@dataclass(frozen=True)
class AppPaths:
    app_root: Path
    data_dir: Path
    database_file: Path
    config_file: Path
    covers_original_dir: Path
    covers_thumbs_dir: Path
    manifests_dir: Path
    webview_dir: Path
    backups_dir: Path
    logs_dir: Path
    temp_dir: Path

class TaskRegistry:
    def submit(self, kind: str, operation: Callable[[TaskContext], JSONValue]) -> str: ...
    def get_snapshot(self, task_id: str) -> TaskSnapshot: ...
    def cancel(self, task_id: str) -> bool: ...

class BridgeApi:
    def bootstrap(self) -> dict[str, JSONValue]: ...
    def task_snapshot(self, task_id: str) -> dict[str, JSONValue]: ...
    def cancel_task(self, task_id: str) -> dict[str, JSONValue]: ...
```

桥接响应始终使用以下封装：

```ts
export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string; details?: unknown } }
```

所有跨越桥接层的日期/时间字符串均采用 UTC ISO 8601 格式。所有主 ID 均为 UUID 字符串。文件系统路径只有在明确面向用户的操作中才以显示值形式跨越桥接层；内部资源访问使用 ID。

## 集成门禁

每个增量完成后运行：

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
git status --short
```

预期结果：每条命令的退出码均为 `0`，并且增量提交完成后 `git status --short` 没有输出。

计划 07 还会在此门禁中加入 Windows 打包产物冒烟测试。

## 规格覆盖关系

| 已确认的设计内容 | 实施计划 |
|---|---|
| 目标、V0.1 范围、离线/只读/用户确认原则 | 所有计划的全局约束；计划 01、02、05、07 |
| 首次启动及日常优先显示缓存的启动流程 | 计划 01 和 02 |
| 多根目录、扫描模式、深度、排除项、重叠、失效、重映射/移动 | 计划 02 |
| EXE 推荐、手动覆盖、参数、工作目录、安全启动 | 计划 02 |
| 正式/实验性引擎覆盖、置信度/证据/手动覆盖 | 计划 04 |
| 多个存档位置及便携/绝对路径模板 | 计划 05 |
| Ludusavi 内置规则/手动更新/自定义清单（V0.1 可选、按需运行） | 计划 05 |
| 引导式动态检测、溢出降级、进程生命周期、定向注册表监控（V0.2） | 计划 06，执行前重新拆分复审 |
| 已删除游戏/孤立存档扫描、仅存档卡片、关联/忽略审核（V0.3） | 计划 06，执行前重新拆分复审 |
| 非破坏性的本地/剪贴板封面流程 | 计划 03 |
| 封面网格、搜索/筛选、详情抽屉、错误状态 | 计划 03 |
| Vue/pywebview/Python/SQLite 架构及并发 | 计划 01；由所有功能计划继续扩展 |
| 可执行文件旁的 `data`、迁移/备份、一致性 | 计划 01 和 07 |
| 安全/隐私/日志/资源服务边界 | 计划 01、03、06、07 |
| 单元/集成/虚拟机测试及 V0.1 验收条件 | 计划 01 至 05 和 07；最终证据由计划 07 提供 |
| onedir x64、固定版 WebView2、第三方声明、本地产物 | 计划 07 |
| 排除动态/孤立存档与存档备份/恢复 | 全局约束；V0.1 不以这些功能作为交付条件 |
