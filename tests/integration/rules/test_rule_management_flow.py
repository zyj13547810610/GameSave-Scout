from __future__ import annotations

import hashlib
from pathlib import Path

from tests.unit.rules.test_rule_management import _engine_draft, _service


def test_readonly_engine_test_changes_neither_database_nor_game_tree(
    tmp_path: Path,
) -> None:
    service, _, _, game_dir = _service(tmp_path)
    marker = game_dir / "marker.dat"
    marker.write_bytes(b"private body")
    database = tmp_path / "data" / "library.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    database.write_bytes(b"database sentinel")
    before_database = _digest(database)
    before_tree = _tree_digest(game_dir)

    result = service.test_draft(_engine_draft("readonly"), "game-1")

    assert result.matched is True
    assert result.verification_token
    assert _digest(database) == before_database
    assert _tree_digest(game_dir) == before_tree
    assert all("private body" not in item for item in result.evidence)


def test_save_rule_test_requires_exact_identity_and_existing_bounded_location(
    tmp_path: Path,
) -> None:
    service, _, _, _ = _service(tmp_path)
    documents = tmp_path / "Profile" / "Documents"
    existing = documents / "Alice"
    existing.mkdir(parents=True)
    draft = {
        "version": "user-test",
        "id": "alice_save",
        "label": "Alice saves",
        "type": "save_game",
        "status": "experimental",
        "priority": 0,
        "enabled": True,
        "notes": None,
        "references": [],
        "titles": ["Alice RJ012345"],
        "product_ids": ["dlsite:RJ012345"],
        "locations": [
            {
                "kind": "directory",
                "path": r"<winDocuments>\Alice",
                "category": "save",
                "confidence": 0.9,
            }
        ],
    }

    found = service.test_draft(draft, "game-1")
    wrong = service.test_draft(
        {**draft, "titles": ["Different"], "product_ids": []},
        "game-1",
    )
    existing.rmdir()
    predicted = service.test_draft(draft, "game-1")

    assert found.matched is True
    assert found.verification_token
    assert found.expanded_locations[0].display_path == str(existing)
    assert wrong.matched is False
    assert wrong.verification_token is None
    assert predicted.matched is True
    assert predicted.verification_token is None


def test_engine_save_rule_requires_exact_engine_and_can_test_while_disabled(
    tmp_path: Path,
) -> None:
    service, _, _, _ = _service(tmp_path)
    existing = tmp_path / "Profile" / "Documents" / "Unity Save"
    existing.mkdir(parents=True)
    draft = {
        "version": "user-test",
        "id": "unity_save",
        "label": "Unity saves",
        "type": "save_engine",
        "status": "experimental",
        "priority": 0,
        "enabled": False,
        "notes": None,
        "references": [],
        "engine_ids": ["unity"],
        "locations": [
            {
                "kind": "directory",
                "path": r"<winDocuments>\Unity Save",
                "category": "save",
                "confidence": 0.8,
            }
        ],
    }

    result = service.test_draft(draft, "game-1")
    mismatch = service.test_draft(
        {**draft, "engine_ids": ["godot"]},
        "game-1",
    )

    assert result.matched is True
    assert result.verification_token
    assert mismatch.matched is False
    assert mismatch.verification_token is None


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        sorted(
            (
                str(path.relative_to(root)),
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in root.rglob("*")
        )
    )
