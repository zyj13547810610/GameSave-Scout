# GameShelf Covers and Library UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace placeholder cards with the approved large-cover library, searchable filters, a right-side detail drawer, and non-destructive single-cover import from local files or the clipboard.

**Architecture:** Python validates and normalizes image input, stores an application-owned original plus a 2:3 WebP thumbnail, and updates SQLite through a compensating file/database transaction. A tokenized loopback read-only asset server serves packaged Vue assets and covers by game ID without exposing arbitrary local paths.

**Tech Stack:** Existing library increment plus Pillow, Python `ThreadingHTTPServer`, Vue 3, Pinia, CSS Grid, Vitest, pytest.

## Global Constraints

- One cover per game in V1.
- Accept local file selection and pasted clipboard bitmap.
- Never retain a dependency on the user-selected source path and never delete that source file.
- Store normalized original under `data/covers/original` and 2:3 WebP thumbnail under `data/covers/thumbs`.
- Grid thumbnails use centered `cover`; detail view uses complete `contain`.
- Do not build a crop editor in V1.
- Do not expose arbitrary `file://` URLs or a general-purpose local HTTP API.
- Keep cached library visible while cover operations run or fail.
- Follow TDD and commit after every task.

---

### Task 1: Normalize and Store Covers Transactionally

**Files:**
- Modify: `pyproject.toml`
- Create: `src/gameshelf/covers/__init__.py`
- Create: `src/gameshelf/covers/models.py`
- Create: `src/gameshelf/covers/image_pipeline.py`
- Create: `src/gameshelf/covers/service.py`
- Create: `tests/unit/covers/test_image_pipeline.py`
- Create: `tests/integration/covers/test_cover_service.py`

**Interfaces:**
- Produces: `CoverFiles(original_relpath, thumb_relpath, revision)`.
- Produces: `normalize_cover(source: BinaryIO, content_type: str, destination_stem: Path) -> CoverFiles`.
- Produces: `CoverService.import_file(game_id: str, source_path: Path) -> CoverFiles`.
- Produces: `CoverService.import_clipboard_png(game_id: str, png_bytes: bytes) -> CoverFiles`.
- Produces: `CoverService.remove(game_id: str) -> None`.

- [ ] **Step 1: Write failing image and compensation tests**

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

Also test EXIF transpose, clipboard PNG, transparent PNG, corrupt bytes, unsupported format, a decompression-bomb image, and removal that never touches the external source.

- [ ] **Step 2: Add Pillow and run tests to verify failure**

Add `Pillow>=11.3,<13` to dependencies, reinstall, then run:

```powershell
python -m pytest tests/unit/covers tests/integration/covers -v
```

Expected: FAIL because cover modules do not exist.

- [ ] **Step 3: Implement bounded decoding, EXIF handling, atomic files, and DB compensation**

Reject input above 50 MiB, dimensions above 16,384 on either axis, or more than 64 million pixels. Use `Image.verify()`, reopen, then `ImageOps.exif_transpose`. Normalize RGB/RGBA output as:

- PNG input → normalized PNG original;
- JPEG input → normalized JPEG original at quality 92;
- WebP input → normalized WebP original at quality 92;
- BMP/other accepted Pillow bitmap → normalized PNG original.

Create the 400×600 WebP thumb with `ImageOps.fit(..., method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))` at quality 88. Write both to UUID-suffixed files under `data/temp`, `fsync`, then `os.replace` into managed cover directories.

Use this compensation order: create/validate new files → writer transaction updates game cover paths → delete old application-managed files. If the DB transaction fails, delete only the new files. File paths stored in SQLite are relative to `data` and use `/` separators.

- [ ] **Step 4: Run cover tests and static checks**

Run:

```powershell
python -m pytest tests/unit/covers tests/integration/covers -v
python -m ruff check src/gameshelf/covers tests/unit/covers tests/integration/covers
python -m mypy src/gameshelf/covers
```

Expected: all pass.

- [ ] **Step 5: Commit the cover pipeline**

```powershell
git add pyproject.toml src/gameshelf/covers tests/unit/covers tests/integration/covers
git commit -m "feat: store non-destructive game covers"
```

### Task 2: Serve UI and Covers Through a Tokenized Read-Only Server

**Files:**
- Create: `src/gameshelf/web/__init__.py`
- Create: `src/gameshelf/web/asset_server.py`
- Create: `tests/unit/web/test_asset_server.py`
- Modify: `src/gameshelf/bootstrap/application.py`
- Modify: `src/gameshelf/app.py`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Produces: `AssetServer(ui_root, cover_lookup).start() -> AssetServerAddress`.
- Produces: `AssetServerAddress.origin`, `session_token`, and `ui_url`.
- Routes are limited to `/session/{token}/ui/...` and `/session/{token}/cover/{game_id}/{variant}`.
- `variant` is exactly `original` or `thumb`.

- [ ] **Step 1: Write failing route, traversal, and token tests**

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

- [ ] **Step 2: Run server tests and verify failure**

Run: `python -m pytest tests/unit/web/test_asset_server.py -v`

Expected: FAIL because the asset server is absent.

- [ ] **Step 3: Implement loopback-only, ID-based asset access**

Bind `ThreadingHTTPServer` to `127.0.0.1` and port `0`; generate a 256-bit `secrets.token_urlsafe` token. Decode URL components once, reject `..`, separators inside IDs, unknown routes, methods other than `GET`/`HEAD`, and any non-loopback bind configuration.

Set `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'`, `X-Content-Type-Options: nosniff`, and no directory listings. Resolve cover paths only through `cover_lookup(game_id, variant)` and verify the resolved file remains beneath its managed cover directory.

Set Vite `base: './'`. Replace the direct file URL in `app.py` with `address.ui_url`, add the asset server to `Application.close()`, and pass only `address.session_token` to frontend bootstrap state so it can construct cover URLs.

- [ ] **Step 4: Run asset tests and desktop smoke mode**

Run:

```powershell
python -m pytest tests/unit/web tests/integration/test_application_bootstrap.py -v
npm --prefix frontend run build
python -m gameshelf --smoke-test
```

Expected: all pass; smoke mode starts and stops the server without a leaked thread.

- [ ] **Step 5: Commit controlled asset serving**

```powershell
git add src/gameshelf/web src/gameshelf/bootstrap src/gameshelf/app.py tests/unit/web frontend/vite.config.ts
git commit -m "feat: serve local assets through a safe loopback endpoint"
```

### Task 3: Add Cover Selection, Clipboard Paste, Replace, and Remove APIs

**Files:**
- Modify: `src/gameshelf/bridge/api.py`
- Modify: `src/gameshelf/bootstrap/application.py`
- Create: `tests/unit/bridge/test_cover_api.py`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/api/bridge.ts`
- Modify: `frontend/src/api/mockBridge.ts`

**Interfaces:**
- Adds bridge methods `choose_cover_file`, `set_cover_from_file`, `set_cover_from_clipboard`, and `remove_cover`.
- `set_cover_from_clipboard` accepts `{ gameId, pngBase64 }` and rejects decoded data above 50 MiB.
- Game DTO gains `coverRevision`, `coverThumbUrl`, and `coverOriginalUrl` but no local cover path.

- [ ] **Step 1: Write failing API validation tests**

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

- [ ] **Step 2: Run bridge tests and verify failure**

Run: `python -m pytest tests/unit/bridge/test_cover_api.py -v`

Expected: FAIL for missing cover methods.

- [ ] **Step 3: Implement narrow bridge methods and cache-busting DTOs**

The picker returns one selected path or `null`; import requires an explicit follow-up call with game ID. Decode base64 with `validate=True`, verify the PNG signature before calling the cover service, and never log payload bytes.

Construct asset URLs as `/session/{token}/cover/{gameId}/thumb?v={coverRevision}`. Increment revision after every successful replace/remove so the browser cannot show an old cached cover.

- [ ] **Step 4: Run bridge and cover suites**

Run: `python -m pytest tests/unit/bridge/test_cover_api.py tests/unit/covers tests/integration/covers -v`

Expected: all pass.

- [ ] **Step 5: Commit cover bridge APIs**

```powershell
git add src/gameshelf/bridge src/gameshelf/bootstrap frontend/src/api tests/unit/bridge
git commit -m "feat: expose cover management commands"
```

### Task 4: Build the Cover Grid, Search, Filters, and Detail Drawer

**Files:**
- Create: `frontend/src/features/library/GameCard.vue`
- Create: `frontend/src/features/library/GameGrid.vue`
- Create: `frontend/src/features/library/GameDetailDrawer.vue`
- Create: `frontend/src/features/library/LibraryToolbar.vue`
- Create: `frontend/src/features/library/libraryFilters.ts`
- Create: `frontend/src/features/library/library.css`
- Create: `frontend/tests/GameGrid.spec.ts`
- Create: `frontend/tests/GameDetailDrawer.spec.ts`
- Create: `frontend/tests/libraryFilters.spec.ts`
- Modify: `frontend/src/features/library/libraryStore.ts`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: Game DTOs and launch/open commands from Plan 02 plus cover URLs from Task 3.
- Produces: `filterGames(games, { query, status, engine }) -> GameSummary[]`.
- Produces: `selectedGameId` in the library store; closing the drawer preserves filters and scroll position.

- [ ] **Step 1: Write failing filter and interaction tests**

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

- [ ] **Step 2: Run frontend tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run tests/libraryFilters.spec.ts tests/GameGrid.spec.ts tests/GameDetailDrawer.spec.ts`

Expected: FAIL because components/functions are absent.

- [ ] **Step 3: Implement the approved layout and states**

Use CSS Grid with `repeat(auto-fill, minmax(168px, 1fr))`; cards use an aspect-ratio `2 / 3`, lazy image loading, a title below the image, and small installed/missing/save-only/no-EXE badges. The drawer uses `role="dialog"`, `aria-modal="false"`, Escape-to-close, and focus return to the originating card.

Detail image uses `object-fit: contain`; grid image uses `object-fit: cover; object-position: 50% 50%`. The drawer exposes launch, open installation directory, save placeholders, engine/status, executable configuration, and cover actions. Do not display raw evidence or advanced launch fields unless the user expands their sections.

- [ ] **Step 4: Run UI tests, type checking, and build**

Run:

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

Expected: all pass.

- [ ] **Step 5: Commit the library UI**

```powershell
git add frontend/src frontend/tests
git commit -m "feat: add cover library and detail drawer"
```

### Task 5: Wire Local Selection and Clipboard Paste into the Drawer

**Files:**
- Create: `frontend/src/features/covers/coverClipboard.ts`
- Create: `frontend/src/features/covers/CoverActions.vue`
- Create: `frontend/tests/CoverActions.spec.ts`
- Modify: `frontend/src/features/library/GameDetailDrawer.vue`
- Modify: `frontend/src/features/library/libraryStore.ts`

**Interfaces:**
- Produces: `readClipboardPng(clipboard: Clipboard) -> Promise<string>` returning base64 without a data-URL prefix.
- Produces drawer actions `choose`, `paste`, `replace`, and `remove`.
- After success, reload only the changed game DTO and preserve the open drawer.

- [ ] **Step 1: Write failing clipboard and action-state tests**

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

- [ ] **Step 2: Run cover component tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run tests/CoverActions.spec.ts`

Expected: FAIL because cover action modules are absent.

- [ ] **Step 3: Implement image-only paste and resilient action feedback**

Inspect `ClipboardItem.types`, require `image/png` or convert another browser-decoded image type to PNG through an offscreen canvas, enforce a 50 MiB encoded-size precheck, and call the bridge. Disable duplicate clicks while a request is active. On failure, keep the old image and display the backend message; on success, refresh the game and announce “封面已更新” through an `aria-live` region.

Removal requires a confirmation prompt and switches immediately to the shared placeholder only after backend success.

- [ ] **Step 4: Run cover UI and integration checks**

Run:

```powershell
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
python -m pytest tests/unit/covers tests/integration/covers tests/unit/bridge/test_cover_api.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit cover interactions**

```powershell
git add frontend/src/features/covers frontend/src/features/library frontend/tests
git commit -m "feat: choose and paste game covers"
```

### Task 6: Complete Visual, Empty, Loading, and Failure States

**Files:**
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/src/features/library/library.css`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/LibraryStates.spec.ts`
- Modify: `README.md`

**Interfaces:**
- Produces consistent states for empty library, no filter results, loading, root unavailable, game missing, save-only, no executable, and broken cover.

- [ ] **Step 1: Write failing state rendering tests**

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

- [ ] **Step 2: Run state tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run tests/LibraryStates.spec.ts`

Expected: at least unavailable/broken-cover cases fail.

- [ ] **Step 3: Implement final states and keyboard/accessibility behavior**

Add a deterministic local placeholder graphic, image `error` fallback, visible focus rings, reduced-motion support, 44px minimum primary controls, and Chinese labels for every icon-only button. Keep scan/cover errors scoped to their operation rather than replacing the entire app.

- [ ] **Step 4: Run the cover increment acceptance gate**

Run:

```powershell
python -m pytest
python -m ruff check src tests
python -m mypy src
npm --prefix frontend run test:unit -- --run
npm --prefix frontend run type-check
npm --prefix frontend run build
```

Expected: all pass.

- [ ] **Step 5: Commit the complete cover/library experience**

```powershell
git add frontend README.md
git commit -m "feat: complete library visual states"
```

## Cover Increment Acceptance Gate

- A local image and a pasted screenshot both survive deletion of their external source.
- Grid thumbnails are 2:3 centered crops; the detail drawer shows the full normalized original.
- Replacing/removing a cover never deletes an external file and rolls back cleanly on DB failure.
- Cover HTTP access requires the session token and cannot escape managed cover directories.
- Search and combined status/engine filters are deterministic.
- The drawer preserves grid context, filters, scroll, and keyboard focus.
- All specified empty/loading/error states remain usable.
