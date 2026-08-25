from types import SimpleNamespace

import pytest

from gamesave_scout.saves.batch_external import (
    BatchExternalLookup,
    BatchExternalLookupError,
)


class FakeRepository:
    def __init__(self, candidate: object | None) -> None:
        self.candidate = candidate
        self.requested_ids: list[str] = []

    def get_candidate(self, candidate_id: str) -> object | None:
        self.requested_ids.append(candidate_id)
        return self.candidate


class FakeShell:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def open_url(self, url: str) -> None:
        self.urls.append(url)


@pytest.mark.parametrize(
    ("provider", "product_id", "title", "expected"),
    (
        ("vndb", None, "千恋＊万花", "https://vndb.org/v?q=%E5%8D%83%E6%81%8B%EF%BC%8A%E4%B8%87%E8%8A%B1"),
        ("dlsite", "RJ123456", "ignored", "https://www.dlsite.com/maniax/work/=/product_id/RJ123456.html"),
        ("dlsite", "VJ123456", "ignored", "https://www.dlsite.com/pro/work/=/product_id/VJ123456.html"),
        ("dlsite", None, "Alice & Bob", "https://www.dlsite.com/maniax/fsr/=/keyword/Alice%20%26%20Bob"),
        ("2dfan", None, "Alice & Bob", "https://2dfan.com/subjects/search?keyword=Alice+%26+Bob"),
    ),
)
def test_external_lookup_builds_url_only_from_persisted_candidate(
    provider: str,
    product_id: str | None,
    title: str,
    expected: str,
) -> None:
    repository = FakeRepository(
        SimpleNamespace(external_product_id=product_id, suggested_title=title)
    )
    shell = FakeShell()
    lookup = BatchExternalLookup(repository, shell)

    url = lookup.open("candidate-1", provider)

    assert url == expected
    assert repository.requested_ids == ["candidate-1"]
    assert shell.urls == [expected]


def test_external_lookup_ignores_invalid_product_id_and_uses_title() -> None:
    repository = FakeRepository(
        SimpleNamespace(external_product_id="https://evil.example", suggested_title="Alice")
    )
    shell = FakeShell()

    url = BatchExternalLookup(repository, shell).open("candidate-1", "dlsite")

    assert url == "https://www.dlsite.com/maniax/fsr/=/keyword/Alice"


@pytest.mark.parametrize("provider", ("", "google", "https://vndb.org"))
def test_external_lookup_rejects_unknown_provider(provider: str) -> None:
    lookup = BatchExternalLookup(
        FakeRepository(SimpleNamespace(external_product_id=None, suggested_title="Alice")),
        FakeShell(),
    )

    with pytest.raises(BatchExternalLookupError) as caught:
        lookup.open("candidate-1", provider)

    assert caught.value.code == "batch_lookup_provider_invalid"


def test_external_lookup_rejects_missing_candidate_or_title() -> None:
    missing = BatchExternalLookup(FakeRepository(None), FakeShell())
    no_identity = BatchExternalLookup(
        FakeRepository(SimpleNamespace(external_product_id=None, suggested_title=None)),
        FakeShell(),
    )

    with pytest.raises(BatchExternalLookupError) as missing_error:
        missing.open("candidate-1", "vndb")
    with pytest.raises(BatchExternalLookupError) as identity_error:
        no_identity.open("candidate-1", "vndb")

    assert missing_error.value.code == "batch_candidate_not_found"
    assert identity_error.value.code == "batch_lookup_unavailable"


def test_external_lookup_limits_title_length_before_encoding() -> None:
    repository = FakeRepository(
        SimpleNamespace(external_product_id=None, suggested_title="游" * 161)
    )
    lookup = BatchExternalLookup(repository, FakeShell())

    with pytest.raises(BatchExternalLookupError) as caught:
        lookup.open("candidate-1", "2dfan")

    assert caught.value.code == "batch_lookup_unavailable"
