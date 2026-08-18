from pathlib import Path

from gameshelf.engines.service import EngineDetectionService


def _rules(path: Path, version: str) -> None:
    path.write_text(
        f"""version: {version}
rules:
  - id: custom_engine
    label: Custom Engine
    all:
      - op: path_exists
        path: data.bin
        weight: 1
""",
        encoding="utf-8",
    )


def test_builtin_engine_cache_version_is_stable() -> None:
    first = EngineDetectionService.builtins_only()
    second = EngineDetectionService.builtins_only()

    assert first.cache_version == second.cache_version
    assert first.cache_version


def test_declarative_rule_version_changes_engine_cache_version(tmp_path: Path) -> None:
    first_path = tmp_path / "first.yaml"
    second_path = tmp_path / "second.yaml"
    _rules(first_path, "rules-1")
    _rules(second_path, "rules-2")

    first = EngineDetectionService.from_rules_file(first_path)
    second = EngineDetectionService.from_rules_file(second_path)

    assert first.cache_version != second.cache_version
