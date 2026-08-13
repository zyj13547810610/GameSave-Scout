# GameShelf 封面与游戏库体验实施计划

> **供智能体执行者使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 用已确认的大封面游戏库替换占位卡片，加入搜索筛选、右侧详情抽屉，以及从本地文件或剪贴板非破坏性导入单张封面的功能。

**架构：** Python 校验并规范化图像输入，存储由应用管理的原图和一张 2:3 WebP 缩略图，并通过带补偿机制的文件/数据库事务更新 SQLite。一个带令牌的只读回环资源服务器按游戏 ID 提供已打包的 Vue 资源和封面，不暴露任意本地路径。

**技术栈：** 现有游戏库增量，加上 Pillow、Python `ThreadingHTTPServer`、Vue 3、Pinia、CSS Grid、Vitest、pytest。

## 全局约束

- V1 中每个游戏只设置一张封面。
- 支持选择本地文件和粘贴剪贴板位图。
- 绝不保留对用户所选源路径的依赖，也绝不删除该源文件。
- 规范化原图存放在 `data/covers/original` 下，2:3 WebP 缩略图存放在 `data/covers/thumbs` 下。
- 网格缩略图使用居中的 `cover`；详情视图使用显示完整图像的 `contain`。
- V1 不制作裁剪编辑器。
- 不公开任意 `file://` URL 或通用本地 HTTP API。
- 封面操作正在运行或失败时，继续显示缓存的游戏库。
- 遵循 TDD，并在每个任务完成后提交。

---

### 任务 1：以事务方式规范化并存储封面

**文件：**
- 修改：`pyproject.toml`
- 新建：`src/gameshelf/covers/__init__.py`
- 新建：`src/gameshelf/covers/models.py`
- 新建：`src/gameshelf/covers/image_pipeline.py`
- 新建：`src/gameshelf/covers/service.py`
- 新建：`tests/unit/covers/test_image_pipeline.py`
- 新建：`tests/integration/covers/test_cover_service.py`

**接口：**
- 产出：`CoverFiles(original_relpath, thumb_relpath, revision)`。
- 产出：`normalize_cover(source: BinaryIO, content_type: str, destination_stem: Path) -> CoverFiles`。
- 产出：`CoverService.import_file(game_id: str, source_path: Path) -> CoverFiles`。
- 产出：`CoverService.import_clipboard_png(game_id: str, png_bytes: bytes) -> CoverFiles`。
- 产出：`CoverService.remove(game_id: str) -> None`。

- [ ] **步骤 1：编写会失败的图像与补偿测试**

```python
from io import BytesIO

from PIL import Image

from gameshelf.covers.image_pipeline import normalize_cover


def test_pipeline_keeps_full_image_and_creates_centered_two_by_three_thumb(tmp_path) -> None:
    source = BytesIO()
    Image.new("RGB", (1200, 600), "#ac5577").save(source, format="PNG")
    source.seek(0)
    result = normalize_cover(source, "image/png", tmp_path / "game-id")

    with Image.open(tmp_path / result.original_relpath) as original:
        assert original.size == (1200, 600)
    with Image.open(tmp_path / result.thumb_relpath) as thumb:
        assert thumb.size == (400, 600)
        assert thumb.format == "WEBP"


def test_failed_database_update_keeps_old_cover_and_removes_new_files(cover_harness) -> None:
    old = cover_harness.import_png("game-1", color="red")
    cover_harness.fail_next_database_write()
    with pytest.raises(RuntimeError):
        cover_harness.import_png("game-1", color="blue")
    assert cover_harness.game_cover("game-1") == old
    assert cover_harness.managed_files() == {old.original_relpath, old.thumb_relpath}
```

还要测试 EXIF 旋转、剪贴板 PNG、透明 PNG、损坏字节、不支持的格式、解压炸弹图像，以及绝不触碰外部源文件的删除操作。

- [ ] **步骤 2：添加 Pillow 并运行测试以确认失败**

将 `Pillow>=11.3,<13` 添加到依赖，重新安装，然后运行：

```powershell
python -m pytest tests/unit/covers tests/integration/covers -v
```

预期：失败，因为封面模块尚不存在。

- [ ] **步骤 3：实现受限解码、EXIF 处理、原子文件与数据库补偿**

拒绝大于 50 MiB、任一边尺寸超过 16,384 或总像素超过 6400 万的输入。先使用 `Image.verify()`，重新打开后再执行 `ImageOps.exif_transpose`。按以下方式规范化 RGB/RGBA 输出：

- PNG 输入 → 规范化的 PNG 原图；
- JPEG 输入 → 质量 92 的规范化 JPEG 原图；
- WebP 输入 → 质量 92 的规范化 WebP 原图；
- BMP/其他 Pillow 接受的位图 → 规范化的 PNG 原图。

使用 `ImageOps.fit(..., method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))` 创建质量 88 的 400×600 WebP 缩略图。先将两份文件写入 `data/temp` 下带 UUID 后缀的文件，执行 `fsync`，再通过 `os.replace` 移入受管理的封面目录。

采用以下补偿顺序：创建/校验新文件 → 写入器事务更新游戏封面路径 → 删除旧的应用管理文件。数据库事务失败时，只删除新文件。SQLite 中存储的文件路径相对于 `data`，并使用 `/` 分隔符。

- [ ] **步骤 4：运行封面测试与静态检查**

运行：

```powershell
python -m pytest tests/unit/covers tests/integration/covers -v
python -m ruff check src/gameshelf/covers tests/unit/covers tests/integration/covers
python -m mypy src/gameshelf/covers
```

预期：全部通过。

- [ ] **步骤 5：提交封面流水线**

```powershell
git add pyproject.toml src/gameshelf/covers tests/unit/covers tests/integration/covers
git commit -m "feat: store non-destructive game covers"
```

### 任务 2：通过带令牌的只读服务器提供 UI 与封面

**文件：**
- 新建：`src/gameshelf/web/__init__.py`
- 新建：`src/gameshelf/web/asset_server.py`
- 新建：`tests/unit/web/test_asset_server.py`
- 修改：`src/gameshelf/bootstrap/application.py`
- 修改：`src/gameshelf/app.py`
- 修改：`frontend/vite.config.ts`

**接口：**
- 产出：`AssetServer(ui_root, cover_lookup).start() -> AssetServerAddress`。
- 产出：`AssetServerAddress.origin`、`session_token` 和 `ui_url`。
- 路由仅限 `/session/{token}/ui/...` 和 `/session/{token}/cover/{game_id}/{variant}`。
- `variant` 只能是 `original` 或 `thumb`。

- [ ] **步骤 1：编写会失败的路由、路径穿越和令牌测试**

```python
def test_server_serves_known_thumb_with_private_cache(asset_server, http_client) -> None:
    address = asset_server.start()
    response = http_client.get(
        f"{address.origin}/session/{address.session_token}/cover/game-1/thumb"
    )
    assert response.status == 200
    assert response.headers["Content-Type"] == "image/webp"
    assert response.headers["Cache-Control"].startswith("private")


@pytest.mark.parametrize("path", [
    "/session/wrong/ui/index.html",
    "/session/{token}/ui/../../data/library.db",
    "/session/{token}/cover/../library.db/thumb",
])
def test_server_rejects_wrong_token_and_traversal(asset_server, http_client, path) -> None:
    address = asset_server.start()
    response = http_client.get(
        address.origin + path.format(token=address.session_token)
    )
    assert response.status in {403, 404}
```

- [ ] **步骤 2：运行服务器测试并确认失败**

运行：`python -m pytest tests/unit/web/test_asset_server.py -v`

预期：失败，因为资源服务器尚不存在。

- [ ] **步骤 3：实现仅限回环、基于 ID 的资源访问**

将 `ThreadingHTTPServer` 绑定到 `127.0.0.1` 和端口 `0`；生成 256 位 `secrets.token_urlsafe` 令牌。URL 分段只解码一次；拒绝 `..`、ID 内的分隔符、未知路由、`GET`/`HEAD` 之外的方法，以及任何非回环绑定配置。

设置 `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'`、`X-Content-Type-Options: nosniff`，并禁止目录列表。封面路径只能通过 `cover_lookup(game_id, variant)` 解析，并验证解析后的文件仍位于其受管理的封面目录下。

将 Vite 设置为 `base: './'`。用 `address.ui_url` 替换 `app.py` 中的直接文件 URL，将资源服务器加入 `Application.close()`，并且只把 `address.session_token` 传入前端引导状态，以便构造封面 URL。

- [ ] **步骤 4：运行资源测试与桌面冒烟模式**

运行：

```powershell
python -m pytest tests/unit/web tests/integration/test_application_bootstrap.py -v
npm --prefix frontend run build
python -m gameshelf --smoke-test
```

预期：全部通过；冒烟模式能够启停服务器，且不泄漏线程。

- [ ] **步骤 5：提交受控资源服务**

```powershell
git add src/gameshelf/web src/gameshelf/bootstrap src/gameshelf/app.py tests/unit/web frontend/vite.config.ts
git commit -m "feat: serve local assets through a safe loopback endpoint"
```

### 任务 3：添加封面选择、剪贴板粘贴、替换与移除 API

**文件：**
- 修改：`src/gameshelf/bridge/api.py`
- 修改：`src/gameshelf/bootstrap/application.py`
- 新建：`tests/unit/bridge/test_cover_api.py`
- 修改：`frontend/src/api/contracts.ts`
- 修改：`frontend/src/api/bridge.ts`
- 修改：`frontend/src/api/mockBridge.ts`

**接口：**
- 添加桥接方法 `choose_cover_file`、`set_cover_from_file`、`set_cover_from_clipboard` 和 `remove_cover`。
- `set_cover_from_clipboard` 接收 `{ gameId, pngBase64 }`，并拒绝解码后超过 50 MiB 的数据。
- 游戏 DTO 增加 `coverRevision`、`coverThumbUrl` 和 `coverOriginalUrl`，但不包含本地封面路径。

- [ ] **步骤 1：编写会失败的 API 校验测试**

```python
def test_clipboard_api_rejects_non_png_and_oversize_payload(cover_api) -> None:
    invalid = cover_api.set_cover_from_clipboard({
        "gameId": "game-1", "pngBase64": base64.b64encode(b"GIF89a").decode()
    })
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "invalid_cover"


def test_file_picker_limits_extensions(cover_api, fake_window) -> None:
    cover_api.choose_cover_file({})
    assert fake_window.dialog_file_types == (
        "Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",
    )
```

- [ ] **步骤 2：运行桥接测试并确认失败**

运行：`python -m pytest tests/unit/bridge/test_cover_api.py -v`

预期：因缺少封面方法而失败。

- [ ] **步骤 3：实现范围受限的桥接方法与缓存失效 DTO**

选择器返回一个选中路径或 `null`；导入时必须再明确调用一次并传入游戏 ID。使用 `validate=True` 解码 base64，在调用封面服务前验证 PNG 签名，并且绝不记录载荷字节。

按 `/session/{token}/cover/{gameId}/thumb?v={coverRevision}` 构造资源 URL。每次成功替换/移除后递增版本号，避免浏览器显示旧的缓存封面。

- [ ] **步骤 4：运行桥接与封面测试套件**

运行：`python -m pytest tests/unit/bridge/test_cover_api.py tests/unit/covers tests/integration/covers -v`

预期：全部通过。

- [ ] **步骤 5：提交封面桥接 API**

```powershell
git add src/gameshelf/bridge src/gameshelf/bootstrap frontend/src/api tests/unit/bridge
git commit -m "feat: expose cover management commands"
```

### 任务 4：构建封面网格、搜索、筛选与详情抽屉

**文件：**
- 新建：`frontend/src/features/library/GameCard.vue`
- 新建：`frontend/src/features/library/GameGrid.vue`
- 新建：`frontend/src/features/library/GameDetailDrawer.vue`
- 新建：`frontend/src/features/library/LibraryToolbar.vue`
- 新建：`frontend/src/features/library/libraryFilters.ts`
- 新建：`frontend/src/features/library/library.css`
- 新建：`frontend/tests/GameGrid.spec.ts`
- 新建：`frontend/tests/GameDetailDrawer.spec.ts`
- 新建：`frontend/tests/libraryFilters.spec.ts`
- 修改：`frontend/src/features/library/libraryStore.ts`
- 修改：`frontend/src/App.vue`

**接口：**
- 使用：计划 02 的游戏 DTO 和启动/打开命令，以及任务 3 的封面 URL。
- 产出：`filterGames(games, { query, status, engine }) -> GameSummary[]`。
- 产出：游戏库 store 中的 `selectedGameId`；关闭抽屉时保留筛选条件和滚动位置。

- [ ] **步骤 1：编写会失败的筛选与交互测试**

```ts
it('matches title case-insensitively and combines status and engine filters', () => {
  const games = [
    fixtureGame({ id: '1', title: 'Alice', status: 'installed', engineId: 'renpy' }),
    fixtureGame({ id: '2', title: 'Bob', status: 'missing', engineId: 'unity' }),
  ]
  expect(filterGames(games, {
    query: 'ALI', status: 'installed', engine: 'renpy',
  }).map((game) => game.id)).toEqual(['1'])
})


it('opens a right-side drawer without replacing the grid', async () => {
  const wrapper = mount(GameGrid, { props: { games: [fixtureGame({ id: '1' })] } })
  await wrapper.get('[data-test="game-card-1"]').trigger('click')
  expect(wrapper.find('[data-test="game-grid"]').exists()).toBe(true)
  expect(wrapper.find('[data-test="game-detail-drawer"]').exists()).toBe(true)
})
```

- [ ] **步骤 2：运行前端测试并确认失败**

运行：`npm --prefix frontend run test:unit -- --run tests/libraryFilters.spec.ts tests/GameGrid.spec.ts tests/GameDetailDrawer.spec.ts`

预期：失败，因为组件/函数尚不存在。

- [ ] **步骤 3：实现已确认的布局与状态**

使用设置为 `repeat(auto-fill, minmax(168px, 1fr))` 的 CSS Grid；卡片使用 `2 / 3` 宽高比、图像懒加载、图片下方标题，以及小型的已安装/失效/仅存档/无 EXE 徽标。抽屉使用 `role="dialog"`、`aria-modal="false"`，支持按 Escape 关闭，并将焦点返回到打开抽屉的卡片。

详情图像使用 `object-fit: contain`；网格图像使用 `object-fit: cover; object-position: 50% 50%`。抽屉提供启动、打开安装目录、存档占位、引擎/状态、可执行文件配置和封面操作。除非用户展开对应区域，否则不要显示原始证据或高级启动字段。

- [ ] **步骤 4：运行 UI 测试、类型检查与构建**

运行：

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

预期：全部通过。

- [ ] **步骤 5：提交游戏库 UI**

```powershell
git add frontend/src frontend/tests
git commit -m "feat: add cover library and detail drawer"
```

### 任务 5：在抽屉中接入本地选择与剪贴板粘贴

**文件：**
- 新建：`frontend/src/features/covers/coverClipboard.ts`
- 新建：`frontend/src/features/covers/CoverActions.vue`
- 新建：`frontend/tests/CoverActions.spec.ts`
- 修改：`frontend/src/features/library/GameDetailDrawer.vue`
- 修改：`frontend/src/features/library/libraryStore.ts`

**接口：**
- 产出：`readClipboardPng(clipboard: Clipboard) -> Promise<string>`，返回不带 data-URL 前缀的 base64。
- 产出抽屉操作：`choose`、`paste`、`replace` 和 `remove`。
- 成功后只重新加载已变更的游戏 DTO，并保持抽屉打开。

- [ ] **步骤 1：编写会失败的剪贴板与操作状态测试**

```ts
it('selects the first PNG clipboard item and returns raw base64', async () => {
  const clipboard = fakeClipboardWithPng(new Uint8Array([137, 80, 78, 71]))
  const base64 = await readClipboardPng(clipboard)
  expect(base64).toBe('iVBORw==')
})


it('shows a useful message when the clipboard has no image', async () => {
  const wrapper = mount(CoverActions, {
    props: { gameId: 'game-1', bridge: createMockBridge() },
    global: { provide: { clipboard: fakeTextClipboard('hello') } },
  })
  await wrapper.get('[data-test="paste-cover"]').trigger('click')
  expect(wrapper.text()).toContain('剪贴板中没有可用图片')
})
```

- [ ] **步骤 2：运行封面组件测试并确认失败**

运行：`npm --prefix frontend run test:unit -- --run tests/CoverActions.spec.ts`

预期：失败，因为封面操作模块尚不存在。

- [ ] **步骤 3：实现仅限图像的粘贴与稳健的操作反馈**

检查 `ClipboardItem.types`，要求提供 `image/png`，或通过离屏 canvas 将浏览器解码的其他图像类型转换为 PNG；预先检查编码大小不超过 50 MiB，然后调用桥接层。请求进行期间禁用重复点击。失败时保留旧图并显示后端消息；成功时刷新游戏，并通过 `aria-live` 区域播报“封面已更新”。

移除操作需要确认提示；只有后端成功后，才立即切换为共享占位图。

- [ ] **步骤 4：运行封面 UI 与集成检查**

运行：

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
python -m pytest tests/unit/covers tests/integration/covers tests/unit/bridge/test_cover_api.py -v
```

预期：全部通过。

- [ ] **步骤 5：提交封面交互**

```powershell
git add frontend/src/features/covers frontend/src/features/library frontend/tests
git commit -m "feat: choose and paste game covers"
```

### 任务 6：完善视觉、空白、加载与失败状态

**文件：**
- 修改：`frontend/src/styles/base.css`
- 修改：`frontend/src/features/library/library.css`
- 修改：`frontend/src/App.vue`
- 新建：`frontend/tests/LibraryStates.spec.ts`
- 修改：`README.md`

**接口：**
- 产出一致的状态：游戏库为空、筛选无结果、加载中、根目录不可用、游戏失效、仅存档、无可执行文件和封面损坏。

- [ ] **步骤 1：编写会失败的状态渲染测试**

```ts
it.each([
  ['empty', '还没有添加游戏目录'],
  ['no-results', '没有符合筛选条件的游戏'],
  ['root-unavailable', '已有游戏状态未改变'],
  ['broken-cover', '封面加载失败'],
])('renders the %s state', async (state, message) => {
  const wrapper = mountLibraryState(state)
  expect(wrapper.text()).toContain(message)
})
```

- [ ] **步骤 2：运行状态测试并确认失败**

运行：`npm --prefix frontend run test:unit -- --run tests/LibraryStates.spec.ts`

预期：至少不可用/封面损坏用例会失败。

- [ ] **步骤 3：实现最终状态与键盘/无障碍行为**

添加固定的本地占位图、图像 `error` 回退、清晰可见的焦点环、减少动态效果支持、至少 44px 的主要控件，并为每个纯图标按钮添加中文标签。扫描/封面错误只影响相应操作，不得替换整个应用界面。

- [ ] **步骤 4：运行封面增量验收门禁**

运行：

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

预期：全部通过。

- [ ] **步骤 5：提交完整的封面/游戏库体验**

```powershell
git add frontend README.md
git commit -m "feat: complete library visual states"
```

## 封面增量验收门禁

- 本地图像和粘贴的截图即使外部源被删除，仍能正常保留。
- 网格缩略图采用 2:3 居中裁切；详情抽屉显示完整的规范化原图。
- 替换/移除封面绝不删除外部文件，数据库失败时可干净回滚。
- 封面 HTTP 访问必须提供会话令牌，且不能逃逸出受管理的封面目录。
- 搜索及组合状态/引擎筛选具有确定性。
- 抽屉保留网格上下文、筛选条件、滚动位置和键盘焦点。
- 所有规定的空白/加载/错误状态均保持可用。
