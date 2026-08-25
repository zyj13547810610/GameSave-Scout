"""Token-gated loopback HTTP server with a deliberately tiny route surface."""

from __future__ import annotations

import mimetypes
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import unquote, urlsplit

type CoverVariant = str
type CoverLookup = Callable[[str, CoverVariant], Path | None]
type CandidateLookup = Callable[[str, str], Path | None]

_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'"
)


@dataclass(frozen=True)
class AssetServerAddress:
    origin: str
    session_token: str
    ui_url: str


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True


class AssetServer:
    def __init__(
        self,
        ui_root: Path,
        cover_lookup: CoverLookup,
        *,
        managed_cover_roots: tuple[Path, ...] = (),
        candidate_lookup: CandidateLookup | None = None,
        candidate_root: Path | None = None,
    ) -> None:
        self._ui_root = ui_root.resolve(strict=False)
        self._cover_lookup = cover_lookup
        self._cover_roots = tuple(
            root.resolve(strict=False) for root in managed_cover_roots
        )
        self._candidate_lookup = candidate_lookup
        self._candidate_root = (
            candidate_root.resolve(strict=False) if candidate_root is not None else None
        )
        self._lock = Lock()
        self._server: _LoopbackServer | None = None
        self._thread: Thread | None = None
        self._address: AssetServerAddress | None = None

    def start(self) -> AssetServerAddress:
        with self._lock:
            if self._address is not None:
                return self._address
            token = secrets.token_urlsafe(32)
            handler = self._handler(token)
            server = _LoopbackServer(("127.0.0.1", 0), handler)
            host, port = server.server_address[:2]
            if host != "127.0.0.1":
                server.server_close()
                raise RuntimeError("Asset server must bind to IPv4 loopback.")
            origin = f"http://127.0.0.1:{port}"
            address = AssetServerAddress(
                origin=origin,
                session_token=token,
                ui_url=f"{origin}/session/{token}/ui/index.html",
            )
            thread = Thread(
                target=server.serve_forever,
                name="gamesave-scout-assets",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._address = address
            thread.start()
            return address

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._address = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise TimeoutError("Asset server did not stop in time.")

    def _handler(self, token: str) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._serve(send_body=True)

            def do_HEAD(self) -> None:
                self._serve(send_body=False)

            def do_POST(self) -> None:
                self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

            def end_headers(self) -> None:
                self.send_header("Content-Security-Policy", _CSP)
                self.send_header("X-Content-Type-Options", "nosniff")
                super().end_headers()

            def log_message(self, _format: str, *args: object) -> None:
                del args

            def _serve(self, *, send_body: bool) -> None:
                raw_path = urlsplit(self.path).path
                decoded = unquote(raw_path)
                if "\\" in decoded:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                parts = decoded.split("/")[1:]
                if any(part in {"", ".", ".."} for part in parts):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if len(parts) < 4 or parts[0] != "session":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if not secrets.compare_digest(parts[1], token):
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                if parts[2] == "ui":
                    self._serve_ui(parts[3:], send_body=send_body)
                    return
                if parts[2] == "cover" and len(parts) == 5:
                    self._serve_cover(parts[3], parts[4], send_body=send_body)
                    return
                if parts[2] == "candidate" and len(parts) == 5:
                    self._serve_candidate(parts[3], parts[4], send_body=send_body)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def _serve_ui(self, relative_parts: list[str], *, send_body: bool) -> None:
                candidate = owner._safe_ui_path(relative_parts)
                if candidate is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_file(candidate, "no-cache", send_body=send_body)

            def _serve_cover(
                self, game_id: str, variant: str, *, send_body: bool
            ) -> None:
                if variant not in {"original", "thumb"} or not _safe_identifier(game_id):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                candidate = owner._safe_cover_path(game_id, variant)
                if candidate is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_file(
                    candidate,
                    "private, max-age=31536000, immutable",
                    send_body=send_body,
                )

            def _serve_candidate(
                self, session_id: str, candidate_id: str, *, send_body: bool
            ) -> None:
                if not _safe_identifier(session_id) or not _safe_identifier(candidate_id):
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                candidate = owner._safe_candidate_path(session_id, candidate_id)
                if candidate is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_file(candidate, "no-store", send_body=send_body)

            def _send_file(self, path: Path, cache: str, *, send_body: bool) -> None:
                try:
                    payload = path.read_bytes()
                except OSError:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                content_type = _content_type(path)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                if send_body:
                    self.wfile.write(payload)

        return Handler

    def _safe_ui_path(self, parts: list[str]) -> Path | None:
        if not parts or any(part in {"", ".", ".."} for part in parts):
            return None
        candidate = self._ui_root.joinpath(*parts).resolve(strict=False)
        try:
            candidate.relative_to(self._ui_root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _safe_cover_path(self, game_id: str, variant: str) -> Path | None:
        candidate = self._cover_lookup(game_id, variant)
        if candidate is None:
            return None
        resolved = candidate.resolve(strict=False)
        if not resolved.is_file():
            return None
        if not self._cover_roots:
            return None
        for root in self._cover_roots:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            return resolved
        return None

    def _safe_candidate_path(
        self, session_id: str, candidate_id: str
    ) -> Path | None:
        if self._candidate_lookup is None or self._candidate_root is None:
            return None
        candidate = self._candidate_lookup(session_id, candidate_id)
        if candidate is None:
            return None
        resolved = candidate.resolve(strict=False)
        if resolved.suffix.casefold() != ".webp" or not resolved.is_file():
            return None
        try:
            resolved.relative_to(self._candidate_root)
        except ValueError:
            return None
        return resolved


def _safe_identifier(value: str) -> bool:
    return bool(value) and all(
        character.isalnum() or character in {"-", "_", "."} for character in value
    ) and value not in {".", ".."}


def _content_type(path: Path) -> str:
    fixed = {
        ".webp": "image/webp",
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }
    return fixed.get(
        path.suffix.casefold(),
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    )
