# GameShelf 规则 Schema

本目录发布 GameShelf 声明式规则的 JSON Schema（Draft 2020-12），供编辑器提示、导入预检和人工审阅使用。

- `engines.schema.json`：引擎识别规则，包含 `all`、`any`、`negative` 三组受限证据。
- `saves.schema.json`：`save_game` 游戏专属存档规则与 `save_engine` 引擎通用存档规则。

YAML 文档统一使用 `{version, rules}` 顶层结构。随包内置文件可包含多条规则；`data/rules/user/engines` 和 `data/rules/user/saves` 中的用户文件由程序额外限制为每个文件恰好一条规则。

Schema 只描述公开结构。路径越界、无界 glob、注册表范围、读取预算和其他安全约束仍以 GameShelf 的 Python 校验器为最终依据，不能仅凭通用 JSON Schema 校验结果判定规则可执行。
