from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import pytest

from gameshelf.bridge.tasks import TaskCancelled
from gameshelf.saves.batch_models import BatchScanScope
from gameshelf.saves.batch_rules import (
    BatchPathRule,
    BatchRuleCatalog,
    RuleIdentity,
)
from gameshelf.saves.batch_scanner import (
    BatchFilesystemScanner,
    BatchScanCancelled,
)


@dataclass
class _Context:
    cancel_after: int | None = None
    checks: int = 0
    reports: list[dict[str, object]] = field(default_factory=list)

    def raise_if_cancelled(self) -> None:
        self.checks += 1
        if self.cancel_after is not None and self.checks >= self.cancel_after:
            raise TaskCancelled("cancel")

    def report(
        self,
        completed: int,
        total: int | None,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self.reports.append(
            {
                "completed": completed,
                "total": total,
                "message": message,
                **(details or {}),
            }
        )


def test_scanner_uses_most_specific_scope_and_skips_noise_and_reparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = tmp_path / "Documents"
    custom = documents / "Approved"
    game = documents / "Game"
    game.mkdir(parents=True)
    custom_game = custom / "RJ123456"
    custom_game.mkdir(parents=True)
    cache = documents / "Cache"
    cache.mkdir()
    reparse = documents / "FakeLink"
    reparse.mkdir()
    save = game / "save01.sav"
    custom_save = custom_game / "slot.dat"
    skipped_cache = cache / "save02.sav"
    skipped_reparse = reparse / "save03.sav"
    for path in (save, custom_save, skipped_cache, skipped_reparse):
        path.write_bytes(b"private")
    real_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
        if path.suffix in {".sav", ".dat"}:
            raise AssertionError("不得读取存档正文")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    scopes = (
        BatchScanScope("documents", "文档", documents, "standard", 6, None),
        BatchScanScope("custom:one", "自定义", custom, "custom", 6, "one"),
    )
    catalog = _catalog(
        BatchPathRule(
            source="ludusavi",
            kind="file",
            root_token="<winDocuments>",
            relative_pattern=r"Game\*.sav",
            first_segment_key="game",
            identity=_identity(),
        )
    )
    context = _Context()
    scanner = BatchFilesystemScanner(
        progress_interval=1,
        is_reparse_point=lambda path: path == reparse,
    )

    output = scanner.scan(scopes, catalog, context)

    assert output.total_entries > 0
    assert {item.display_path for item in output.candidates} == {
        str(game),
        str(custom_game),
    }
    custom_candidate = next(
        item for item in output.candidates if item.display_path == str(custom_game)
    )
    assert custom_candidate.scope_key == "custom:one"
    assert output.scope("documents").status == "completed"
    assert output.scope("custom:one").status == "completed"
    assert context.reports
    assert {"phase", "scope", "currentPath", "entries", "candidateCount"} <= set(
        context.reports[-1]
    )
    with pytest.raises(KeyError):
        output.scope("missing")


def test_scanner_enforces_entry_and_candidate_limits(tmp_path: Path) -> None:
    root = tmp_path / "Custom"
    for index in range(8):
        directory = root / f"Game-{index}"
        directory.mkdir(parents=True)
        (directory / f"save-{index}.sav").write_bytes(b"x")
    scope = BatchScanScope("custom:one", "自定义", root, "custom", 4, "one")
    scanner = BatchFilesystemScanner(
        max_entries_per_custom=6,
        max_total_entries=7,
        max_candidates=2,
        progress_interval=1,
    )

    output = scanner.scan((scope,), _catalog(), _Context())

    assert output.total_entries <= 7
    assert output.scope("custom:one").entries <= 6
    assert output.scope("custom:one").status == "truncated"
    assert len(output.candidates) <= 2


def test_scanner_does_not_treat_an_unrelated_json_file_as_a_save(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Custom"
    ordinary = root / "Ordinary"
    ordinary.mkdir(parents=True)
    (ordinary / "settings.json").write_text("{}", encoding="utf-8")
    save_data = root / "SaveData"
    save_data.mkdir()
    (save_data / "metadata.json").write_text("{}", encoding="utf-8")
    scope = BatchScanScope("custom:one", "自定义", root, "custom", 4, "one")

    output = BatchFilesystemScanner(progress_interval=1).scan((scope,), _catalog(), _Context())

    assert {item.display_path for item in output.candidates} == {str(save_data)}


def test_scanner_limits_representatives_and_allows_json_after_a_save_signal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Custom"
    directory = root / "Game"
    directory.mkdir(parents=True)
    for index in range(4):
        (directory / f"save-{index}.sav").write_bytes(b"x")
    (directory / "metadata.json").write_text("{}", encoding="utf-8")
    scope = BatchScanScope("custom:one", "自定义", root, "custom", 4, "one")

    output = BatchFilesystemScanner(
        max_representative_files=2,
        progress_interval=1,
    ).scan((scope,), _catalog(), _Context())

    candidate = output.candidates[0]
    assert candidate.matched_file_count == 5
    assert len(candidate.representative_files) == 2
    assert candidate.representatives_truncated is True


def test_scanner_reports_unavailable_scope_and_cancelled_partial_output(
    tmp_path: Path,
) -> None:
    unavailable = BatchScanScope(
        "documents",
        "文档",
        tmp_path / "Missing",
        "standard",
        3,
        None,
    )
    root = tmp_path / "Available"
    (root / "Game").mkdir(parents=True)
    (root / "Game" / "save.sav").write_bytes(b"x")
    available = BatchScanScope("custom:one", "自定义", root, "custom", 3, "one")
    scanner = BatchFilesystemScanner(progress_interval=1)

    unavailable_output = scanner.scan((unavailable,), _catalog(), _Context())
    assert unavailable_output.scope("documents").status == "unavailable"

    with pytest.raises(BatchScanCancelled) as captured:
        scanner.scan((available,), _catalog(), _Context(cancel_after=2))

    assert captured.value.reason == "user"
    assert captured.value.output.scope("custom:one").status == "cancelled"


def _catalog(*rules: BatchPathRule) -> BatchRuleCatalog:
    return BatchRuleCatalog(
        candidates=(),
        identities_by_path=MappingProxyType({}),
        reverse_path_rules=rules,
        warnings=(),
        rules_version="test",
    )


def _identity() -> RuleIdentity:
    return RuleIdentity(
        source="ludusavi",
        game_id=None,
        external_title="Game",
        external_product_id=None,
        engine_id=None,
        confidence="high",
        strong_group_key="ludusavi:1",
        evidence=("规则命中",),
    )
