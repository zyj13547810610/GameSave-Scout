from __future__ import annotations

from types import MappingProxyType

from gamesave_scout.library.models import Game
from gamesave_scout.saves.batch_candidates import candidate_path_key
from gamesave_scout.saves.batch_matching import (
    BatchCandidateMatcher,
    group_matched_candidates,
)
from gamesave_scout.saves.batch_models import RawBatchCandidate, RepresentativeFile
from gamesave_scout.saves.batch_rules import (
    BatchPathRule,
    BatchRuleCatalog,
    RuleIdentity,
)
from gamesave_scout.saves.models import SaveLocation
from gamesave_scout.scanning.path_keys import windows_path_key


def test_exact_recorded_path_wins_and_may_target_a_save_only_card() -> None:
    archive = _game("archive", "旧游戏存档", "save_only")
    candidate = _candidate(r"D:\Saves\Alice")
    location = _location("archive", candidate)

    matched = _matcher((archive,), (location,)).match_all((candidate,))[0]

    assert matched.suggested_game_id == "archive"
    assert matched.suggested_title == "旧游戏存档"
    assert matched.classification == "unknown"
    assert matched.confidence == "high"
    assert matched.strong_group_key == "game:archive"
    assert "recorded" in matched.sources


def test_unique_existing_game_rule_precedes_external_rules() -> None:
    alice = _game("alice", "Alice", "installed", engine_id="renpy")
    candidate = _candidate(r"D:\Saves\Alice")
    local = _identity(
        source="user",
        game_id="alice",
        title="Alice",
        strong_group_key="game:alice",
    )
    other = _identity(
        source="ludusavi",
        title="External Alice",
        strong_group_key="ludusavi:42",
    )

    matched = _matcher(
        (alice,),
        catalog=_catalog(candidate, local, other),
    ).match_all((candidate,))[0]

    assert matched.suggested_game_id == "alice"
    assert matched.classification == "installed"
    assert matched.confidence == "high"
    assert matched.engine_id == "renpy"
    assert matched.strong_group_key == "game:alice"
    assert {item.title for item in matched.alternatives} == {"External Alice"}


def test_unique_external_rule_is_high_confidence_but_remains_unknown() -> None:
    candidate = _candidate(
        r"C:\Users\User\Documents\Sandfall\Saved\SaveGames",
        path_template=r"<winDocuments>\Sandfall\Saved\SaveGames",
        representative_names=("slot-1.sav",),
    )
    identity = _identity(
        source="ludusavi",
        title="Clair Obscur: Expedition 33",
        strong_group_key="ludusavi:33000",
    )
    rule = BatchPathRule(
        source="ludusavi",
        kind="file",
        root_token="<winDocuments>",
        relative_pattern=r"Sandfall\Saved\SaveGames\*.sav",
        first_segment_key="sandfall",
        identity=identity,
    )

    matched = _matcher(catalog=_catalog(reverse_rules=(rule,))).match_all((candidate,))[0]

    assert matched.suggested_game_id is None
    assert matched.suggested_title == "Clair Obscur: Expedition 33"
    assert matched.classification == "unknown"
    assert matched.confidence == "high"
    assert matched.strong_group_key == "ludusavi:33000"


def test_conflicting_rules_only_create_weak_alternatives() -> None:
    candidate = _candidate(r"D:\Saves\Shared")
    one = _identity(
        source="ludusavi",
        title="Game One",
        strong_group_key="ludusavi:1",
    )
    two = _identity(
        source="user",
        title="Game Two",
        strong_group_key="custom:user:gametwo",
    )

    matched = _matcher(catalog=_catalog(candidate, one, two)).match_all((candidate,))[0]

    assert matched.suggested_game_id is None
    assert matched.suggested_title is None
    assert matched.strong_group_key is None
    assert {item.title for item in matched.alternatives} == {"Game One", "Game Two"}
    assert {item.reason for item in matched.alternatives} == {"possibleSameGame"}


def test_conflicting_existing_game_rules_are_not_decided_by_title_similarity() -> None:
    alice = _game("alice", "Alice", "installed")
    other = _game("other", "Other", "missing")
    candidate = _candidate(r"D:\Saves\Alice\SaveData")
    alice_rule = _identity(
        source="user",
        game_id="alice",
        title="Alice",
        strong_group_key="game:alice",
    )
    other_rule = _identity(
        source="ludusavi",
        game_id="other",
        title="Other",
        strong_group_key="game:other",
    )

    matched = _matcher(
        (alice, other),
        catalog=_catalog(candidate, alice_rule, other_rule),
    ).match_all((candidate,))[0]

    assert matched.suggested_game_id is None
    assert matched.classification == "unknown"
    assert matched.strong_group_key is None
    assert {item.game_id for item in matched.alternatives} == {"alice", "other"}


def test_new_rules_do_not_automatically_target_save_only_cards() -> None:
    archive = _game("archive", "Archived Alice", "save_only")
    candidate = _candidate(r"D:\Saves\Archived Alice\SaveData")
    archive_rule = _identity(
        source="user",
        game_id="archive",
        title="Archived Alice",
        strong_group_key="game:archive",
    )

    matched = _matcher(
        (archive,),
        catalog=_catalog(candidate, archive_rule),
    ).match_all((candidate,))[0]

    assert matched.suggested_game_id is None
    assert matched.classification == "unknown"
    assert matched.strong_group_key is None
    assert matched.alternatives[0].game_id == "archive"


def test_stable_rj_steam_unity_and_registry_products_create_strong_groups() -> None:
    candidates = (
        _candidate(r"D:\Archive\RJ123456\SaveData"),
        _candidate(r"D:\Steam\userdata\7656119\123456\remote"),
        _candidate(
            r"C:\Users\User\AppData\LocalLow\Studio\Project",
            path_template=r"<winLocalAppDataLow>\Studio\Project",
        ),
        _candidate(
            r"HKEY_CURRENT_USER\Software\Studio\Project",
            kind="registry",
        ),
    )

    matched = _matcher().match_all(candidates)

    assert [(item.external_product_id, item.strong_group_key) for item in matched] == [
        ("RJ123456", "product:rj123456"),
        ("steam:123456", "product:steam:123456"),
        ("unity:studio/project", "product:unity:studio/project"),
        ("registry:studio/project", "product:registry:studio/project"),
    ]
    assert all(item.confidence == "high" for item in matched)


def test_title_fuzzy_match_is_not_a_strong_group_and_skips_save_only() -> None:
    installed = _game("alice", "Wonderful Alice", "installed")
    archive = _game("archive", "Alice", "save_only")
    candidate = _candidate(r"D:\Saves\Wonderful Alice\SaveData")

    matched = _matcher((installed, archive)).match_all((candidate,))[0]

    assert matched.suggested_game_id == "alice"
    assert matched.classification == "installed"
    assert matched.confidence == "medium"
    assert matched.strong_group_key is None


def test_engine_structure_only_sets_engine_and_generic_candidate_stays_unknown() -> None:
    unreal = _candidate(
        r"D:\Unknown\Saved\SaveGames",
        representative_names=("slot.sav",),
    )
    generic = _candidate(
        r"D:\Unknown\Data",
        representative_names=("save01.sav",),
    )

    unreal_match, generic_match = _matcher().match_all((unreal, generic))

    assert unreal_match.engine_id == "unreal"
    assert unreal_match.suggested_game_id is None
    assert unreal_match.suggested_title is None
    assert unreal_match.strong_group_key is None
    assert generic_match.engine_id is None
    assert generic_match.suggested_title is None
    assert generic_match.classification == "unknown"


def test_grouping_only_merges_candidates_with_the_same_strong_key() -> None:
    first, second, weak = _matcher().match_all(
        (
            _candidate(r"D:\RJ123456\SaveData"),
            _candidate(r"E:\RJ123456\SaveData"),
            _candidate(r"D:\Unknown\SaveData"),
        )
    )

    groups = group_matched_candidates((first, weak, second))

    assert groups == ((first, second), (weak,))


def _matcher(
    games: tuple[Game, ...] = (),
    save_locations: tuple[SaveLocation, ...] = (),
    *,
    catalog: BatchRuleCatalog | None = None,
) -> BatchCandidateMatcher:
    return BatchCandidateMatcher(
        games=games,
        save_locations=save_locations,
        catalog=catalog or _catalog(),
    )


def _catalog(
    candidate: RawBatchCandidate | None = None,
    *identities: RuleIdentity,
    reverse_rules: tuple[BatchPathRule, ...] = (),
) -> BatchRuleCatalog:
    by_path = {} if candidate is None else {(candidate.kind, candidate.path_key): tuple(identities)}
    return BatchRuleCatalog(
        candidates=(),
        identities_by_path=MappingProxyType(by_path),
        reverse_path_rules=reverse_rules,
        warnings=(),
        rules_version="test",
    )


def _candidate(
    display_path: str,
    *,
    kind: str = "directory",
    path_template: str | None = None,
    representative_names: tuple[str, ...] = (),
) -> RawBatchCandidate:
    representatives = tuple(RepresentativeFile(name, 10, 100) for name in representative_names)
    return RawBatchCandidate(
        scope_key="test",
        kind=kind,  # type: ignore[arg-type]
        path_template=path_template or display_path,
        display_path=display_path,
        path_key=candidate_path_key(kind, display_path),  # type: ignore[arg-type]
        sources=("bounded_scan",),
        evidence=("测试候选",),
        representative_files=representatives,
        matched_file_count=len(representatives),
        representatives_truncated=False,
    )


def _identity(
    *,
    source: str,
    title: str,
    strong_group_key: str,
    game_id: str | None = None,
) -> RuleIdentity:
    return RuleIdentity(
        source=source,  # type: ignore[arg-type]
        game_id=game_id,
        external_title=title,
        external_product_id=None,
        engine_id=None,
        confidence="high",
        strong_group_key=strong_group_key,
        evidence=(f"规则：{title}",),
    )


def _location(game_id: str, candidate: RawBatchCandidate) -> SaveLocation:
    return SaveLocation(
        id="location-1",
        game_id=game_id,
        kind=candidate.kind,
        path_template=candidate.path_template,
        display_path=candidate.display_path,
        path_key=candidate.path_key,
        source="manual",
        confidence=1.0,
        evidence=("用户确认",),
        confirmed=True,
        enabled=True,
        last_verified_at=None,
    )


def _game(
    game_id: str,
    title: str,
    status: str,
    *,
    engine_id: str | None = None,
) -> Game:
    return Game(
        id=game_id,
        scan_root_id=None,
        relative_dir=title,
        install_path_key=(
            None if status == "save_only" else windows_path_key(rf"D:\Games\{title}")
        ),
        title=title,
        detected_title=title,
        status=status,  # type: ignore[arg-type]
        detected_engine_id=engine_id,
        detected_engine_variant=None,
        engine_id=engine_id,
        engine_variant=None,
        engine_is_manual=False,
        engine_confidence=None,
        engine_evidence=(),
        engine_rules_version="test",
        main_exe_relpath=None,
        main_exe_is_manual=False,
        working_dir_relpath=None,
        launch_args=(),
        environment={},
        exe_arch="unknown",
        cover_original_relpath=None,
        cover_thumb_relpath=None,
        cover_revision=0,
        last_launched_at=None,
        missing_since=None,
    )
