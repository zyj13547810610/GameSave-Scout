"""Bounded, atomic storage for user-authored declarative rule files."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from gameshelf.rules.validation import RuleMetadataError, validate_rule_id

MAX_RULE_FILE_COUNT = 512
MAX_RULE_FILE_BYTES = 1024 * 1024
MAX_RULE_TOTAL_BYTES = 8 * 1024 * 1024
_RULE_EXTENSIONS = frozenset({".yaml", ".yml"})
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class RuleFileError(OSError):
    """Raised when user rule storage violates its ownership or size boundary."""


def safe_rule_filename(rule_id: str) -> str:
    """Return the canonical YAML filename for an already-declarative rule ID."""

    try:
        normalized = validate_rule_id(rule_id)
    except RuleMetadataError as error:
        raise RuleFileError(str(error)) from error
    return f"{normalized}.yaml"


class UserRuleRepository:
    """Read and atomically mutate direct children of the two user rule roots."""

    def __init__(self, engine_dir: Path, save_dir: Path, temp_dir: Path) -> None:
        self.engine_dir = engine_dir
        self.save_dir = save_dir
        self.temp_dir = temp_dir

    @property
    def roots(self) -> tuple[Path, Path]:
        return (self.engine_dir, self.save_dir)

    def read_all(self) -> Mapping[Path, bytes]:
        candidates: list[Path] = []
        for root in self.roots:
            if not root.exists():
                continue
            if _is_link_or_reparse(root) or not root.is_dir():
                raise RuleFileError(f"用户规则目录不是普通目录：{root}")
            for path in root.iterdir():
                if path.suffix.casefold() not in _RULE_EXTENSIONS:
                    continue
                candidates.append(path)

        candidates.sort(
            key=lambda path: (
                0 if path.parent == self.engine_dir else 1,
                path.name.casefold(),
                path.name,
            )
        )
        if len(candidates) > MAX_RULE_FILE_COUNT:
            raise RuleFileError(f"用户规则文件最多 {MAX_RULE_FILE_COUNT} 个。")

        result: dict[Path, bytes] = {}
        total = 0
        for path in candidates:
            _require_owned_rule_file(path, self.roots)
            if _is_link_or_reparse(path) or not path.is_file():
                raise RuleFileError(f"规则文件不能是链接或重解析点：{path.name}")
            try:
                size = path.stat(follow_symlinks=False).st_size
            except OSError as error:
                raise RuleFileError(f"无法读取规则文件：{path.name}") from error
            if size > MAX_RULE_FILE_BYTES:
                raise RuleFileError(f"单个规则文件不能超过 1 MiB：{path.name}")
            total += size
            if total > MAX_RULE_TOTAL_BYTES:
                raise RuleFileError("用户规则文件总大小不能超过 8 MiB。")
            try:
                content = path.read_bytes()
            except OSError as error:
                raise RuleFileError(f"无法读取规则文件：{path.name}") from error
            if len(content) != size:
                raise RuleFileError(f"规则文件在读取期间发生变化：{path.name}")
            result[path] = content
        return result

    def write_one(self, path: Path, content: bytes) -> None:
        self.apply_batch({path: content})

    def delete_one(self, path: Path) -> None:
        self.apply_batch({path: None})

    def apply_batch(self, changes: Mapping[Path, bytes | None]) -> None:
        if not changes:
            return
        normalized: list[tuple[Path, bytes | None]] = []
        for path, content in changes.items():
            target = _require_owned_rule_file(path, self.roots)
            if target.exists() and (_is_link_or_reparse(target) or not target.is_file()):
                raise RuleFileError(f"规则文件不能是链接或重解析点：{target.name}")
            if content is not None:
                if not isinstance(content, bytes):
                    raise RuleFileError("规则文件内容必须是 bytes。")
                if len(content) > MAX_RULE_FILE_BYTES:
                    raise RuleFileError(f"单个规则文件不能超过 1 MiB：{target.name}")
            normalized.append((target, content))
        normalized.sort(key=lambda item: str(item[0]).casefold())

        resulting = dict(self.read_all())
        for target, content in normalized:
            if content is None:
                resulting.pop(target, None)
            else:
                resulting[target] = content
        if len(resulting) > MAX_RULE_FILE_COUNT:
            raise RuleFileError(f"用户规则文件最多 {MAX_RULE_FILE_COUNT} 个。")
        if sum(len(content) for content in resulting.values()) > MAX_RULE_TOTAL_BYTES:
            raise RuleFileError("用户规则文件总大小不能超过 8 MiB。")

        staging = self.temp_dir / f"rule-write-{uuid4()}"
        new_dir = staging / "new"
        backup_dir = staging / "backup"
        new_dir.mkdir(parents=True)
        backup_dir.mkdir()
        prepared: dict[Path, Path] = {}
        backups: dict[Path, Path] = {}
        touched: list[Path] = []
        try:
            for index, (target, content) in enumerate(normalized):
                if target.exists():
                    backup = backup_dir / f"{index}.yaml"
                    _copy_file_fsynced(target, backup)
                    backups[target] = backup
                if content is not None:
                    staged = new_dir / f"{index}.yaml"
                    _write_bytes_fsynced(staged, content)
                    prepared[target] = staged

            for target, content in normalized:
                target.parent.mkdir(parents=True, exist_ok=True)
                if content is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(prepared[target], target)
                touched.append(target)
        except OSError:
            for target in reversed(touched):
                restored_backup = backups.get(target)
                if restored_backup is None:
                    target.unlink(missing_ok=True)
                elif restored_backup.exists():
                    os.replace(restored_backup, target)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _require_owned_rule_file(path: Path, roots: tuple[Path, Path]) -> Path:
    try:
        resolved_parent = path.parent.resolve(strict=True)
        resolved_roots = {
            root.resolve(strict=root.exists())
            for root in roots
        }
    except OSError as error:
        raise RuleFileError("规则文件不在用户规则目录内。") from error
    if resolved_parent not in resolved_roots:
        raise RuleFileError("规则文件不在用户规则目录内。")
    if path.suffix.casefold() not in _RULE_EXTENSIONS:
        raise RuleFileError("规则文件扩展名无效。")
    return path


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_FLAG
    )


def _write_bytes_fsynced(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _copy_file_fsynced(source: Path, destination: Path) -> None:
    with source.open("rb") as source_stream, destination.open("xb") as output:
        shutil.copyfileobj(source_stream, output)
        output.flush()
        os.fsync(output.fileno())
