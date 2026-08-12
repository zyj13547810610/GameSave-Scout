"""Inspect one game directory and emit bounded engine evidence as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from gameshelf.engines.models import EngineMatch
from gameshelf.engines.service import EngineDetectionService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gameshelf.tools.detect_directory")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args(argv)
    game_dir = args.directory.resolve(strict=False)
    if not game_dir.is_dir():
        _write_json(sys.stderr, {"error": "directory_not_found", "path": str(game_dir)})
        return 2
    executable = args.executable.resolve(strict=False) if args.executable else None
    if executable is not None and (
        not executable.is_file() or executable.parent != game_dir
    ):
        _write_json(
            sys.stderr,
            {"error": "invalid_executable", "path": str(executable)},
        )
        return 2
    app_root = Path(__file__).resolve().parents[3]
    service = EngineDetectionService.from_rules_file(
        app_root / "resources" / "rules" / "engines.yaml"
    )
    outcome = service.detect(game_dir, executable)
    _write_json(
        sys.stdout,
        {
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
        },
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


def _write_json(stream: TextIO, payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
