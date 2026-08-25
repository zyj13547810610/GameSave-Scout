from __future__ import annotations

from pathlib import Path

import pytest

from gamesave_scout.rules.import_export import (
    RuleImportDecision,
    RuleImportExportError,
    RuleImportExportService,
)
from tests.unit.rules.test_rule_management import _engine_draft, _service


def test_import_preview_enforces_bounds_and_reports_conflict_decisions(
    tmp_path: Path,
) -> None:
    management, catalog, repository, _ = _service(tmp_path)
    management.save_rule(None, _engine_draft("existing_user"), None)
    service = RuleImportExportService(catalog=catalog, repository=repository)
    files = tmp_path / "incoming"
    files.mkdir()
    builtin_conflict = files / "builtin.yaml"
    builtin_conflict.write_text(_document("declared_engine"), encoding="utf-8")
    user_conflict = files / "user.yaml"
    user_conflict.write_text(_document("existing_user"), encoding="utf-8")
    fresh = files / "fresh.yaml"
    fresh.write_text(_document("fresh"), encoding="utf-8")

    preview = service.begin_import((builtin_conflict, user_conflict, fresh))

    by_name = {item.file_name: item for item in preview.items}
    assert by_name["builtin.yaml"].allowed_decisions == ("new_id", "skip")
    assert by_name["user.yaml"].allowed_decisions == (
        "replace",
        "new_id",
        "skip",
    )
    assert by_name["fresh.yaml"].allowed_decisions == ("import", "skip")
    assert all(str(tmp_path) not in item.file_name for item in preview.items)

    with pytest.raises(RuleImportExportError) as too_many:
        service.begin_import(tuple(files / f"{index}.yaml" for index in range(33)))
    assert too_many.value.code == "rule_import_file_count"

    large = files / "large.yaml"
    large.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(RuleImportExportError) as oversized:
        service.begin_import((large,))
    assert oversized.value.code == "rule_import_file_too_large"


def test_import_preview_requires_one_rule_and_enforces_total_size(
    tmp_path: Path,
) -> None:
    _, catalog, repository, _ = _service(tmp_path)
    service = RuleImportExportService(catalog=catalog, repository=repository)
    files = tmp_path / "incoming"
    files.mkdir()
    multiple = files / "multiple.yaml"
    multiple.write_text(
        """\
version: imported-v1
rules:
  - id: first
    label: First
    type: engine
    all: [{op: path_exists, path: first.dat, weight: 1.0}]
  - id: second
    label: Second
    type: engine
    all: [{op: path_exists, path: second.dat, weight: 1.0}]
""",
        encoding="utf-8",
    )

    preview = service.begin_import((multiple,))

    assert preview.items[0].valid is False
    assert preview.items[0].allowed_decisions == ("skip",)
    assert "恰好包含一条规则" in preview.items[0].errors[0]

    oversized_total: list[Path] = []
    for index in range(5):
        path = files / f"chunk-{index}.yaml"
        path.write_bytes(b"x" * 900_000)
        oversized_total.append(path)
    with pytest.raises(RuleImportExportError) as total:
        service.begin_import(tuple(oversized_total))
    assert total.value.code == "rule_import_total_too_large"


def test_import_sessions_are_memory_bounded_and_expire(tmp_path: Path) -> None:
    _, catalog, repository, _ = _service(tmp_path)
    now = [0.0]
    service = RuleImportExportService(
        catalog=catalog,
        repository=repository,
        monotonic=lambda: now[0],
    )
    incoming = tmp_path / "incoming.yaml"
    incoming.write_text(_document("fresh"), encoding="utf-8")

    previews = [service.begin_import((incoming,)) for _ in range(9)]

    with pytest.raises(RuleImportExportError) as evicted:
        service.confirm_import(
            previews[0].session_id,
            (RuleImportDecision(previews[0].items[0].item_id, "skip", None),),
        )
    assert evicted.value.code == "rule_import_session_not_found"

    now[0] = 30 * 60
    with pytest.raises(RuleImportExportError) as expired:
        service.confirm_import(
            previews[-1].session_id,
            (RuleImportDecision(previews[-1].items[0].item_id, "skip", None),),
        )
    assert expired.value.code == "rule_import_session_not_found"


def test_import_confirmation_is_atomic_and_preserves_imported_formal_status(
    tmp_path: Path,
) -> None:
    management, catalog, repository, _ = _service(tmp_path)
    management.save_rule(None, _engine_draft("existing_user"), None)
    service = RuleImportExportService(catalog=catalog, repository=repository)
    files = tmp_path / "incoming"
    files.mkdir()
    replacement = files / "replacement.yaml"
    replacement.write_text(
        _document("existing_user", label="Replaced", status="formal"),
        encoding="utf-8",
    )
    renamed = files / "renamed.yaml"
    renamed.write_text(_document("declared_engine"), encoding="utf-8")
    preview = service.begin_import((replacement, renamed))
    before_generation = catalog.snapshot().generation

    result = service.confirm_import(
        preview.session_id,
        (
            RuleImportDecision(preview.items[0].item_id, "replace", None),
            RuleImportDecision(preview.items[1].item_id, "new_id", "imported_engine"),
        ),
    )

    assert result.imported_qualified_ids == (
        "user:existing_user",
        "user:imported_engine",
    )
    assert catalog.snapshot().generation == before_generation + 1
    assert management.get_rule("user:existing_user").status == "formal"
    assert management.get_rule("user:imported_engine").status == "experimental"

    invalid = files / "invalid.yaml"
    invalid.write_text("version: 1\nrules: [", encoding="utf-8")
    invalid_preview = service.begin_import((invalid,))
    files_before = dict(repository.read_all())
    snapshot_before = catalog.snapshot()
    with pytest.raises(RuleImportExportError):
        service.confirm_import(
            invalid_preview.session_id,
            (RuleImportDecision(invalid_preview.items[0].item_id, "import", None),),
        )
    assert dict(repository.read_all()) == files_before
    assert catalog.snapshot() is snapshot_before

    fresh_formal = files / "fresh-formal.yaml"
    fresh_formal.write_text(
        _document("fresh_formal", status="formal"),
        encoding="utf-8",
    )
    formal_preview = service.begin_import((fresh_formal,))
    service.confirm_import(
        formal_preview.session_id,
        (RuleImportDecision(formal_preview.items[0].item_id, "import", None),),
    )
    assert management.get_rule("user:fresh_formal").status == "formal"


def test_import_rejects_duplicate_batch_target_before_writing(tmp_path: Path) -> None:
    _, catalog, repository, _ = _service(tmp_path)
    service = RuleImportExportService(catalog=catalog, repository=repository)
    files = tmp_path / "incoming"
    files.mkdir()
    fresh = files / "fresh.yaml"
    fresh.write_text(_document("fresh"), encoding="utf-8")
    builtin_conflict = files / "builtin.yaml"
    builtin_conflict.write_text(_document("declared_engine"), encoding="utf-8")
    preview = service.begin_import((fresh, builtin_conflict))
    before = dict(repository.read_all())

    with pytest.raises(RuleImportExportError) as conflict:
        service.confirm_import(
            preview.session_id,
            (
                RuleImportDecision(preview.items[0].item_id, "import", None),
                RuleImportDecision(preview.items[1].item_id, "new_id", "fresh"),
            ),
        )

    assert conflict.value.code == "rule_import_target_conflict"
    assert dict(repository.read_all()) == before


def test_export_is_canonical_and_contains_no_runtime_or_local_fields(
    tmp_path: Path,
) -> None:
    management, catalog, repository, _ = _service(tmp_path)
    management.save_rule(None, _engine_draft("mine"), None)
    service = RuleImportExportService(catalog=catalog, repository=repository)
    output = tmp_path / "exports" / "mine.yaml"

    result = service.export_rule("user:mine", output)
    content = output.read_text(encoding="utf-8")

    assert result.file_name == "mine.yaml"
    assert "sourcePath" not in content
    assert "gameId" not in content
    assert "verification" not in content
    assert str(tmp_path) not in content
    assert "data/" not in content


def _document(
    rule_id: str,
    *,
    label: str = "Imported",
    status: str = "experimental",
) -> str:
    return f"""\
version: imported-v1
rules:
  - id: {rule_id}
    label: {label}
    type: engine
    status: {status}
    priority: 0
    enabled: true
    references: []
    threshold: 0.8
    all:
      - op: path_exists
        path: marker.dat
        weight: 1.0
    any: []
    negative: []
"""
