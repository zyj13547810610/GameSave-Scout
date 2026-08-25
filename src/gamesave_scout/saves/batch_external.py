"""User-triggered external identity lookup for persisted batch candidates."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, quote_plus

from gamesave_scout.saves.batch_repository import PersistedBatchCandidate

_PRODUCT_ID = re.compile(r"^(RJ|VJ)[0-9]+$")
_PROVIDERS = frozenset({"vndb", "dlsite", "2dfan"})


class BatchCandidateReader(Protocol):
    def get_candidate(self, candidate_id: str) -> PersistedBatchCandidate | None: ...


class ExternalUrlOpener(Protocol):
    def open_url(self, url: str) -> None: ...


class BatchExternalLookupError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BatchCandidateOpenError(OSError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CandidatePathOpener(Protocol):
    def open_directory(self, path: Path) -> None: ...

    def reveal_file(self, path: Path) -> None: ...


class BatchCandidateOpener:
    """Open only the persisted filesystem location represented by a candidate."""

    def __init__(
        self,
        repository: BatchCandidateReader,
        shell: CandidatePathOpener,
    ) -> None:
        self._repository = repository
        self._shell = shell

    def open(self, candidate_id: str) -> None:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise BatchCandidateOpenError(
                "batch_candidate_not_found",
                "没有找到对应的批量存档候选。",
            )
        if candidate.kind == "registry":
            raise BatchCandidateOpenError(
                "registry_confirmation_required",
                "注册表候选需在接受时二次确认，不能直接打开。",
            )
        path = Path(candidate.display_path)
        if candidate.kind == "directory":
            self._shell.open_directory(path)
            return
        if candidate.kind == "file":
            self._shell.reveal_file(path)
            return
        parent = _glob_parent(path)
        if parent is None:
            raise BatchCandidateOpenError(
                "batch_candidate_open_failed",
                "找不到通配符候选的现有父目录。",
            )
        self._shell.open_directory(parent)


class BatchExternalLookup:
    """Derive an allowlisted URL exclusively from a stored candidate identity."""

    def __init__(
        self,
        repository: BatchCandidateReader,
        shell: ExternalUrlOpener,
    ) -> None:
        self._repository = repository
        self._shell = shell

    def open(self, candidate_id: str, provider: str) -> str:
        if not isinstance(candidate_id, str) or not candidate_id.strip() or "\x00" in candidate_id:
            raise BatchExternalLookupError(
                "batch_candidate_not_found",
                "没有找到对应的批量存档候选。",
            )
        if provider not in _PROVIDERS:
            raise BatchExternalLookupError(
                "batch_lookup_provider_invalid",
                "外部核对来源无效。",
            )
        candidate = self._repository.get_candidate(candidate_id.strip())
        if candidate is None:
            raise BatchExternalLookupError(
                "batch_candidate_not_found",
                "没有找到对应的批量存档候选。",
            )

        product_id = candidate.external_product_id
        valid_product_id = (
            product_id if product_id is not None and _PRODUCT_ID.fullmatch(product_id) else None
        )
        title = _lookup_title(candidate.suggested_title)
        url = _build_url(provider, valid_product_id, title)
        self._shell.open_url(url)
        return url


def _lookup_title(value: str | None) -> str | None:
    if value is None:
        return None
    title = value.strip()
    if not title or "\x00" in title or len(title) > 160:
        return None
    return title


def _build_url(provider: str, product_id: str | None, title: str | None) -> str:
    if provider == "dlsite" and product_id is not None:
        section = "maniax" if product_id.startswith("RJ") else "pro"
        return f"https://www.dlsite.com/{section}/work/=/product_id/{product_id}.html"
    if title is None:
        raise BatchExternalLookupError(
            "batch_lookup_unavailable",
            "该候选没有可用于外部核对的标题或产品编号。",
        )
    if provider == "vndb":
        return f"https://vndb.org/v?q={quote_plus(title)}"
    if provider == "dlsite":
        return f"https://www.dlsite.com/maniax/fsr/=/keyword/{quote(title)}"
    return f"https://2dfan.com/subjects/search?keyword={quote_plus(title)}"


def _glob_parent(path: Path) -> Path | None:
    current = path
    while any(any(marker in part for marker in "*?[") for part in current.parts):
        current = current.parent
    while current != current.parent:
        if current.is_dir():
            return current
        current = current.parent
    return current if current.is_dir() else None
