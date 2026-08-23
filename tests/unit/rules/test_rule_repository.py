from pathlib import Path

import pytest

from gameshelf.rules.repository import (
    MAX_RULE_FILE_BYTES,
    MAX_RULE_FILE_COUNT,
    MAX_RULE_TOTAL_BYTES,
    RuleFileError,
    UserRuleRepository,
    safe_rule_filename,
)


def _repository(tmp_path: Path) -> UserRuleRepository:
    return UserRuleRepository(
        tmp_path / "rules" / "engines",
        tmp_path / "rules" / "saves",
        tmp_path / "temp",
    )


def test_read_all_ignores_other_extensions_and_sorts_by_directory_and_filename(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    (repository.engine_dir / "z.yml").write_bytes(b"z")
    (repository.engine_dir / "A.yaml").write_bytes(b"a")
    (repository.engine_dir / "notes.txt").write_bytes(b"ignored")
    (repository.save_dir / "b.yaml").write_bytes(b"b")

    files = repository.read_all()

    assert list(files) == [
        repository.engine_dir / "A.yaml",
        repository.engine_dir / "z.yml",
        repository.save_dir / "b.yaml",
    ]
    assert tuple(files.values()) == (b"a", b"z", b"b")


def test_read_all_rejects_symbolic_links(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    target = tmp_path / "outside.yaml"
    target.write_bytes(b"outside")
    link = repository.engine_dir / "linked.yaml"
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"当前环境不能创建符号链接：{error}")

    with pytest.raises(RuleFileError, match="链接|重解析"):
        repository.read_all()


def test_read_all_rejects_windows_reparse_points(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    candidate = repository.engine_dir / "junction.yaml"
    candidate.write_bytes(b"content")
    monkeypatch.setattr(
        "gameshelf.rules.repository._is_link_or_reparse",
        lambda path: path == candidate,
    )

    with pytest.raises(RuleFileError, match="链接|重解析"):
        repository.read_all()


def test_read_all_enforces_file_count_limit(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    for index in range(MAX_RULE_FILE_COUNT + 1):
        (repository.engine_dir / f"r{index:03}.yaml").write_bytes(b"x")

    with pytest.raises(RuleFileError, match="512"):
        repository.read_all()


def test_read_all_enforces_per_file_limit(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.save_dir.mkdir(parents=True)
    (repository.save_dir / "large.yaml").write_bytes(
        b"x" * (MAX_RULE_FILE_BYTES + 1)
    )

    with pytest.raises(RuleFileError, match="1 MiB"):
        repository.read_all()


def test_read_all_enforces_total_size_limit(tmp_path: Path, monkeypatch) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    monkeypatch.setattr("gameshelf.rules.repository.MAX_RULE_TOTAL_BYTES", 5)
    (repository.engine_dir / "a.yaml").write_bytes(b"aaa")
    (repository.engine_dir / "b.yaml").write_bytes(b"bbb")

    with pytest.raises(RuleFileError, match="8 MiB"):
        repository.read_all()


@pytest.mark.parametrize(
    ("rule_id", "expected"),
    (("my_rule_1", "my_rule_1.yaml"), ("unity", "unity.yaml")),
)
def test_safe_rule_filename_uses_validated_rule_id(
    rule_id: str,
    expected: str,
) -> None:
    assert safe_rule_filename(rule_id) == expected


@pytest.mark.parametrize("rule_id", ("../escape", "Upper", "a-b", ""))
def test_safe_rule_filename_rejects_unsafe_ids(rule_id: str) -> None:
    with pytest.raises(RuleFileError, match="规则 ID"):
        safe_rule_filename(rule_id)


def test_write_and_delete_reject_paths_outside_direct_user_directories(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    nested = repository.engine_dir / "nested" / "rule.yaml"
    outside = tmp_path / "outside.yaml"

    with pytest.raises(RuleFileError, match="用户规则目录"):
        repository.write_one(nested, b"value")
    with pytest.raises(RuleFileError, match="用户规则目录"):
        repository.delete_one(outside)


def test_apply_batch_rolls_back_existing_and_new_files_when_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    existing = repository.engine_dir / "existing.yaml"
    created = repository.save_dir / "created.yaml"
    existing.write_bytes(b"old")
    real_replace = __import__("os").replace
    calls = 0

    def fail_second_staged_replace(source: Path, destination: Path) -> None:
        nonlocal calls
        if "rule-write-" in str(source) and destination in {existing, created}:
            calls += 1
            if calls == 2:
                raise OSError("injected replace failure")
        real_replace(source, destination)

    monkeypatch.setattr("gameshelf.rules.repository.os.replace", fail_second_staged_replace)

    with pytest.raises(OSError, match="injected"):
        repository.apply_batch({existing: b"new", created: b"created"})

    assert existing.read_bytes() == b"old"
    assert not created.exists()


def test_apply_batch_enforces_resulting_catalog_total_size(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    existing = repository.engine_dir / "existing.yaml"
    existing.write_bytes(b"aaa")
    monkeypatch.setattr("gameshelf.rules.repository.MAX_RULE_TOTAL_BYTES", 5)

    with pytest.raises(RuleFileError, match="8 MiB"):
        repository.write_one(repository.save_dir / "created.yaml", b"bbb")


def test_apply_batch_enforces_resulting_catalog_file_count(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = _repository(tmp_path)
    repository.engine_dir.mkdir(parents=True)
    repository.save_dir.mkdir(parents=True)
    (repository.engine_dir / "existing.yaml").write_bytes(b"a")
    monkeypatch.setattr("gameshelf.rules.repository.MAX_RULE_FILE_COUNT", 1)

    with pytest.raises(RuleFileError, match="最多"):
        repository.write_one(repository.save_dir / "created.yaml", b"b")


def test_declared_limits_match_design() -> None:
    assert MAX_RULE_FILE_COUNT == 512
    assert MAX_RULE_FILE_BYTES == 1024 * 1024
    assert MAX_RULE_TOTAL_BYTES == 8 * 1024 * 1024
