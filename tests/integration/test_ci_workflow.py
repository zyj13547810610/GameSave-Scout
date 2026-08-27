from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_ci_source_smoke_uses_current_product_identity() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m gamesave_scout.app --smoke-test" in workflow
    assert "gameshelf" not in workflow.casefold()
