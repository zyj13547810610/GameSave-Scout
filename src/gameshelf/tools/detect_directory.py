"""Inspect one game directory and emit bounded engine evidence as JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from gameshelf.bootstrap.resources import ResourcePaths
from gameshelf.engines.models import EngineMatch
from gameshelf.engines.service import EngineDetectionService
from gameshelf.scanning.pe_metadata import PeMetadata, read_pe_metadata

_SANITIZED_MAX_ENTRIES = 256
_SANITIZED_MAX_DEPTH = 3
_SANITIZED_HEADER_BYTES = 16
_SANITIZED_MAX_ERRORS = 32
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)")
_BINARY_SUFFIXES = frozenset(
    {
        ".arc",
        ".bin",
        ".cpz",
        ".dat",
        ".dll",
        ".exe",
        ".lib",
        ".noa",
        ".npa",
        ".nsa",
        ".pac",
        ".pack",
        ".pak",
        ".pck",
        ".pfs",
        ".rpa",
        ".rpyc",
        ".war",
        ".xp3",
        ".ypf",
    }
)


def main(
    argv: Sequence[str] | None = None,
    *,
    resources: ResourcePaths | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m gameshelf.tools.detect_directory")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--sanitized", action="store_true")
    args = parser.parse_args(argv)
    game_dir = args.directory.resolve(strict=False)
    if not game_dir.is_dir():
        _write_json(
            sys.stderr,
            _error_payload("directory_not_found", game_dir, args.sanitized),
        )
        return 2
    try:
        next(game_dir.iterdir(), None)
    except OSError:
        _write_json(
            sys.stderr,
            _error_payload("directory_unreadable", game_dir, args.sanitized),
        )
        return 2
    executable = args.executable.resolve(strict=False) if args.executable else None
    if executable is not None and (
        not executable.is_file() or executable.parent != game_dir
    ):
        _write_json(
            sys.stderr,
            _error_payload("invalid_executable", executable, args.sanitized),
        )
        return 2
    service = EngineDetectionService.from_rules_file(
        (resources or ResourcePaths.for_runtime()).engine_rules_file
    )
    outcome = service.detect(game_dir, executable)
    payload: dict[str, object]
    if args.sanitized:
        payload = {
            "sanitized": True,
            "best": _sanitized_match_data(outcome.best, game_dir),
            "ambiguous": outcome.ambiguous,
            "alternatives": [
                _sanitized_match_data(match, game_dir)
                for match in outcome.alternatives
            ],
            "diagnostics": [
                {
                    "code": item.code,
                    "relativePath": _relative_evidence_path(item.path, game_dir),
                }
                for item in outcome.diagnostics
            ],
            "fileOverview": _sanitized_file_overview(game_dir),
        }
    else:
        payload = {
            "directory": str(game_dir),
            "best": _match_data(outcome.best),
            "ambiguous": outcome.ambiguous,
            "alternatives": [
                _match_data(match) for match in outcome.alternatives
            ],
            "diagnostics": [
                {
                    "code": item.code,
                    "detail": item.detail,
                    "path": item.path,
                }
                for item in outcome.diagnostics
            ],
        }
    _write_json(
        sys.stdout,
        payload,
    )
    return 0


def _match_data(match: EngineMatch | None) -> dict[str, object] | None:
    if match is None:
        return None
    return {
        "engineId": match.engine_id,
        "variant": match.variant,
        "confidence": match.confidence,
        "experimental": match.experimental,
        "ruleVersion": match.rule_version,
        "evidence": [
            {
                "code": item.code,
                "detail": item.detail,
                "path": item.path,
                "weight": item.weight,
            }
            for item in match.evidence
        ],
    }


def _sanitized_match_data(
    match: EngineMatch | None,
    game_dir: Path,
) -> dict[str, object] | None:
    if match is None:
        return None
    return {
        "engineId": match.engine_id,
        "variant": match.variant,
        "confidence": match.confidence,
        "experimental": match.experimental,
        "ruleVersion": match.rule_version,
        "evidence": [
            {
                "code": item.code,
                "relativePath": _relative_evidence_path(item.path, game_dir),
                "weight": item.weight,
            }
            for item in match.evidence
        ],
    }


def _error_payload(code: str, path: Path, sanitized: bool) -> dict[str, object]:
    if sanitized:
        return {"error": code, "sanitized": True}
    return {"error": code, "path": str(path)}


def _relative_evidence_path(value: str | None, game_dir: Path) -> str | None:
    if value is None or not value.strip() or "\x00" in value:
        return None
    clean = value.strip().replace("\\", "/")
    candidate = Path(value)
    if candidate.is_absolute() or _WINDOWS_ABSOLUTE_PATH.search(value):
        try:
            relative = candidate.resolve(strict=False).relative_to(game_dir)
        except (OSError, ValueError):
            return None
        clean = relative.as_posix()
    parts = tuple(part for part in clean.split("/") if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)[:512]


def _sanitized_file_overview(game_dir: Path) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    pending: deque[tuple[Path, int]] = deque([(game_dir, 0)])
    truncated = False

    while pending and len(entries) < _SANITIZED_MAX_ENTRIES:
        directory, parent_depth = pending.popleft()
        remaining = _SANITIZED_MAX_ENTRIES - len(entries)
        try:
            with os.scandir(directory) as iterator:
                children = []
                for child in iterator:
                    children.append(child)
                    if len(children) > remaining:
                        truncated = True
                        break
        except OSError as error:
            _append_inventory_error(
                errors,
                directory,
                game_dir,
                "list_directory",
                error,
            )
            continue

        for child in sorted(children[:remaining], key=lambda item: item.name.casefold()):
            path = Path(child.path)
            relative_path = _relative_inventory_path(path, game_dir)
            if relative_path is None:
                continue
            depth = parent_depth + 1
            if _is_link_or_reparse(path):
                entries.append({"relativePath": relative_path, "kind": "reparse"})
                continue
            try:
                if child.is_dir(follow_symlinks=False):
                    entries.append({"relativePath": relative_path, "kind": "directory"})
                    if depth < _SANITIZED_MAX_DEPTH:
                        pending.append((path, depth))
                    continue
                if not child.is_file(follow_symlinks=False):
                    entries.append({"relativePath": relative_path, "kind": "other"})
                    continue
                size = max(0, child.stat(follow_symlinks=False).st_size)
            except OSError as error:
                _append_inventory_error(
                    errors,
                    path,
                    game_dir,
                    "inspect_entry",
                    error,
                )
                continue

            item: dict[str, object] = {
                "relativePath": relative_path,
                "kind": "file",
                "size": size,
            }
            if path.suffix.casefold() in _BINARY_SUFFIXES:
                try:
                    header = _read_magic_header(path)
                except OSError as error:
                    _append_inventory_error(
                        errors,
                        path,
                        game_dir,
                        "read_header",
                        error,
                    )
                else:
                    if header is not None:
                        item["headerHex"] = header
            if depth == 1 and path.suffix.casefold() == ".exe":
                item["pe"] = _pe_metadata_data(read_pe_metadata(path))
            entries.append(item)

    if pending:
        truncated = True
    return {
        "limits": {
            "maxEntries": _SANITIZED_MAX_ENTRIES,
            "maxDepth": _SANITIZED_MAX_DEPTH,
            "headerBytes": _SANITIZED_HEADER_BYTES,
        },
        "entries": entries,
        "errors": errors,
        "truncated": truncated,
    }


def _relative_inventory_path(path: Path, game_dir: Path) -> str | None:
    try:
        relative = path.relative_to(game_dir)
    except ValueError:
        return None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    return relative.as_posix()[:512]


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return True
    return path.is_symlink() or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG
    )


def _read_magic_header(path: Path) -> str | None:
    with path.open("rb") as stream:
        payload = stream.read(_SANITIZED_HEADER_BYTES)
    return payload.hex() if payload else None


def _pe_metadata_data(metadata: PeMetadata) -> dict[str, str]:
    return {
        "productName": _sanitized_metadata_value(metadata.product_name),
        "fileDescription": _sanitized_metadata_value(metadata.file_description),
        "companyName": _sanitized_metadata_value(metadata.company_name),
        "architecture": metadata.architecture,
    }


def _sanitized_metadata_value(value: str) -> str:
    clean = " ".join(value.replace("\x00", " ").split())[:160]
    if _WINDOWS_ABSOLUTE_PATH.search(clean):
        return ""
    return clean


def _append_inventory_error(
    errors: list[dict[str, str]],
    path: Path,
    game_dir: Path,
    operation: str,
    error: OSError,
) -> None:
    if len(errors) >= _SANITIZED_MAX_ERRORS:
        return
    relative_path = _relative_inventory_path(path, game_dir)
    if relative_path is None:
        return
    errors.append(
        {
            "relativePath": relative_path,
            "operation": operation,
            "errorType": type(error).__name__,
        }
    )


def _write_json(stream: TextIO, payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
