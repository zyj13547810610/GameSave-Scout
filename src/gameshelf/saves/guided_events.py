"""Bounded, thread-safe aggregation of guided filesystem events."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Literal

from gameshelf.scanning.path_keys import is_same_or_child, windows_path_key

type FileChangeOperation = Literal["created", "modified", "deleted", "moved"]


@dataclass(frozen=True, slots=True)
class RawFileChange:
    operation: FileChangeOperation
    path: Path
    destination_path: Path | None
    occurred_ns: int
    root: Path | None = None
    size: int | None = None
    modified_ns: int | None = None


@dataclass(frozen=True, slots=True)
class AggregatedFileChange:
    display_path: str
    path_key: str
    root_path: str
    operations: tuple[FileChangeOperation, ...]
    first_occurred_ns: int
    last_occurred_ns: int
    size: int | None
    modified_ns: int | None
    exists: bool | None


@dataclass(frozen=True, slots=True)
class AggregatorSnapshot:
    changes: tuple[AggregatedFileChange, ...]
    event_count: int
    overflowed_roots: tuple[str, ...]
    failed_roots: tuple[str, ...]
    dropped_event_count: int


@dataclass(slots=True)
class _MutableChange:
    display_path: str
    path_key: str
    root_path: str
    sequence: int
    operations: list[FileChangeOperation] = field(default_factory=list)
    first_occurred_ns: int = 0
    last_occurred_ns: int = 0
    size: int | None = None
    modified_ns: int | None = None
    exists: bool | None = None

    def apply(self, event: RawFileChange, display_path: str) -> None:
        self.display_path = display_path
        if event.operation not in self.operations:
            self.operations.append(event.operation)
        if not self.first_occurred_ns or event.occurred_ns < self.first_occurred_ns:
            self.first_occurred_ns = event.occurred_ns
        self.last_occurred_ns = max(self.last_occurred_ns, event.occurred_ns)
        if event.size is not None:
            self.size = event.size
        if event.modified_ns is not None:
            self.modified_ns = event.modified_ns
        if event.operation == "deleted":
            self.exists = False
        elif event.operation in {"created", "modified", "moved"}:
            self.exists = True

    def merge(self, other: _MutableChange) -> None:
        self.sequence = min(self.sequence, other.sequence)
        for operation in other.operations:
            if operation not in self.operations:
                self.operations.append(operation)
        if not self.first_occurred_ns or (
            other.first_occurred_ns
            and other.first_occurred_ns < self.first_occurred_ns
        ):
            self.first_occurred_ns = other.first_occurred_ns
        self.last_occurred_ns = max(self.last_occurred_ns, other.last_occurred_ns)
        if self.size is None:
            self.size = other.size
        if self.modified_ns is None:
            self.modified_ns = other.modified_ns

    def freeze(self) -> AggregatedFileChange:
        return AggregatedFileChange(
            display_path=self.display_path,
            path_key=self.path_key,
            root_path=self.root_path,
            operations=tuple(self.operations),
            first_occurred_ns=self.first_occurred_ns,
            last_occurred_ns=self.last_occurred_ns,
            size=self.size,
            modified_ns=self.modified_ns,
            exists=self.exists,
        )


class GuidedChangeAggregator:
    def __init__(self, *, max_paths: int = 20_000, max_events: int = 50_000) -> None:
        if max_paths < 1 or max_events < 1:
            raise ValueError("Guided event limits must be positive.")
        self._max_paths = max_paths
        self._max_events = max_events
        self._lock = RLock()
        self._changes: dict[str, _MutableChange] = {}
        self._overflowed_roots: dict[str, str] = {}
        self._failed_roots: dict[str, str] = {}
        self._event_count = 0
        self._dropped_event_count = 0
        self._next_sequence = 0

    def record(self, event: RawFileChange) -> None:
        root = event.root or event.path.parent
        root_key = windows_path_key(root)
        destination = event.destination_path if event.operation == "moved" else event.path
        source_outside = not self._inside_root(event.path, root_key)
        destination_outside = destination is None or not self._inside_root(
            destination, root_key
        )
        if source_outside or destination_outside:
            with self._lock:
                self._dropped_event_count += 1
                self._remember_root(self._failed_roots, root)
            return

        with self._lock:
            if self._event_count >= self._max_events:
                self._dropped_event_count += 1
                self._remember_root(self._overflowed_roots, root)
                return
            self._event_count += 1
            if event.operation == "moved" and event.destination_path is not None:
                self._record_move(event, root)
            else:
                self._record_at(event, event.path, root)

    def mark_overflow(self, root: Path) -> None:
        with self._lock:
            self._remember_root(self._overflowed_roots, root)

    def mark_failure(self, root: Path) -> None:
        with self._lock:
            self._remember_root(self._failed_roots, root)

    def snapshot(self) -> AggregatorSnapshot:
        with self._lock:
            ordered = sorted(self._changes.values(), key=lambda item: item.sequence)
            return AggregatorSnapshot(
                changes=tuple(item.freeze() for item in ordered),
                event_count=self._event_count,
                overflowed_roots=tuple(self._ordered_roots(self._overflowed_roots)),
                failed_roots=tuple(self._ordered_roots(self._failed_roots)),
                dropped_event_count=self._dropped_event_count,
            )

    def _record_move(self, event: RawFileChange, root: Path) -> None:
        assert event.destination_path is not None
        source_key = windows_path_key(event.path)
        destination_key = windows_path_key(event.destination_path)
        source = self._changes.pop(source_key, None)
        destination = self._changes.get(destination_key)
        if source is None and destination is None:
            if not self._reserve_path(root):
                return
            source = self._new_change(event.destination_path, root)
        elif source is not None:
            source.display_path = str(event.destination_path)
            source.path_key = destination_key
        if destination is not None and source is not None and destination is not source:
            destination.merge(source)
            target = destination
        else:
            assert source is not None
            target = source
            self._changes[destination_key] = target
        target.apply(event, str(event.destination_path))

    def _record_at(self, event: RawFileChange, path: Path, root: Path) -> None:
        key = windows_path_key(path)
        current = self._changes.get(key)
        if current is None:
            if not self._reserve_path(root):
                return
            current = self._new_change(path, root)
            self._changes[key] = current
        current.apply(event, str(path))

    def _new_change(self, path: Path, root: Path) -> _MutableChange:
        change = _MutableChange(
            display_path=str(path),
            path_key=windows_path_key(path),
            root_path=str(root),
            sequence=self._next_sequence,
        )
        self._next_sequence += 1
        return change

    def _reserve_path(self, root: Path) -> bool:
        if len(self._changes) < self._max_paths:
            return True
        self._dropped_event_count += 1
        self._remember_root(self._overflowed_roots, root)
        return False

    @staticmethod
    def _inside_root(path: Path, root_key: str) -> bool:
        return is_same_or_child(windows_path_key(path), root_key)

    @staticmethod
    def _remember_root(target: dict[str, str], root: Path) -> None:
        target.setdefault(windows_path_key(root), str(root))

    @staticmethod
    def _ordered_roots(roots: dict[str, str]) -> list[str]:
        return [roots[key] for key in sorted(roots)]
