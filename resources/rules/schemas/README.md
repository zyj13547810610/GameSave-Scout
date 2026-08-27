# GameSave Scout 规则 Schema

本目录发布 GameSave Scout 声明式规则的 JSON Schema（Draft 2020-12），供编辑器提示、导入预检和人工审阅使用。

- `engines.schema.json`：引擎识别规则，包含 `all`、`any`、`negative` 三组受限证据，以及 `general` / `visual_novel_doujin` 两种维护生态。
- `saves.schema.json`：`save_game` 游戏专属存档规则与 `save_engine` 引擎通用存档规则。

YAML 文档统一使用 `{version, rules}` 顶层结构。随包内置文件可包含多条规则；`data/rules/user/engines` 和 `data/rules/user/saves` 中的用户文件由程序额外限制为每个文件恰好一条规则。

引擎规则的 `category` 在公开 Schema 中保持可选，是为了让 V0.3.5 以前创建、尚未分类的用户 YAML 仍可读取、测试和编辑；程序不会自动迁移或猜测此值。随包 `resources/rules/builtin/engines.yaml` 中的每条规则必须显式填写分类，新建用户引擎规则也必须由用户选择分类。该字段仅用于规则维护和编辑器展示，不参与检测分数、优先级、验证指纹、存档规则匹配或数据库筛选。

Schema 只描述公开结构。路径越界、无界 glob、注册表范围、读取预算和其他安全约束仍以 GameSave Scout 的 Python 校验器为最终依据，不能仅凭通用 JSON Schema 校验结果判定规则可执行。
