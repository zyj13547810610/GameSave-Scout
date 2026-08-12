from pathlib import Path

from gameshelf.saves.custom_manifest_provider import CustomManifestProvider


def test_invalid_custom_manifest_is_reported_without_blocking_valid_files(
    tmp_path: Path,
) -> None:
    custom = tmp_path / "data" / "manifests" / "custom"
    custom.mkdir(parents=True)
    (custom / "valid.yaml").write_text(
        "Alice:\n  files:\n    <winAppData>/Alice: {}\n",
        encoding="utf-8",
    )
    (custom / "broken.yaml").write_text("Alice: [", encoding="utf-8")

    result = CustomManifestProvider(custom).load_all()

    assert [manifest.source_name for manifest in result.manifests] == ["valid.yaml"]
    assert result.errors[0].source_name == "broken.yaml"


def test_custom_provider_uses_sorted_names_and_ignores_other_extensions(
    tmp_path: Path,
) -> None:
    custom = tmp_path / "custom"
    custom.mkdir()
    valid = "Game:\n  files:\n    <base>/save: {}\n"
    (custom / "z.yml").write_text(valid, encoding="utf-8")
    (custom / "a.yaml").write_text(valid, encoding="utf-8")
    (custom / "ignored.txt").write_text(valid, encoding="utf-8")

    result = CustomManifestProvider(custom).load_all()

    assert [manifest.source_name for manifest in result.manifests] == ["a.yaml", "z.yml"]
    assert result.errors == ()


def test_custom_provider_rejects_files_over_eight_mib(tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "large.yaml").write_bytes(b"x" * (8 * 1024 * 1024 + 1))

    result = CustomManifestProvider(custom).load_all()

    assert result.manifests == ()
    assert "8 MiB" in result.errors[0].message
