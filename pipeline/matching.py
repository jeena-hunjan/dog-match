"""One-to-one name matching: alias, then exact normalised key, then fuzzy (rapidfuzz)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from pipeline.breed_names import match_key

MatchMethod = Literal["alias", "exact", "fuzzy", "none"]

# token_sort_ratio on match keys. Different breeds with similar names score up to ~84
# ("flat coated retriever" / "curly coated retriever"); spelling variants score higher
# ("bull mastiff" / "bullmastiff" = 95.7).
DEFAULT_THRESHOLD = 92.0


@dataclass(frozen=True)
class Match:
    source: str
    target: str | None
    method: MatchMethod
    score: float
    # Best fuzzy candidate, kept for the unmatched report even when below the threshold.
    candidate: str | None = None


def match_names(
    sources: Sequence[str],
    targets: Sequence[str],
    aliases: Mapping[str, str],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Match]:
    """Match each source to at most one target, and each target to at most one source.

    Raises ValueError for aliases that point at an unknown target and for two sources
    claiming the same target through aliases or exact keys, because both mean the alias
    file or the input data is wrong and must be fixed rather than silently resolved.
    """
    target_set = set(targets)
    unknown = sorted(t for s, t in aliases.items() if s in sources and t not in target_set)
    if unknown:
        raise ValueError(f"aliases point at unknown targets: {unknown}")

    target_by_key: dict[str, str] = {}
    for target in targets:
        key = match_key(target)
        if key in target_by_key:
            raise ValueError(f"targets share a match key: {target_by_key[key]!r}, {target!r}")
        target_by_key[key] = target

    matched: dict[str, Match] = {}
    claimed: dict[str, str] = {}

    def claim(source: str, target: str, method: MatchMethod, score: float) -> None:
        if target in claimed:
            raise ValueError(f"{claimed[target]!r} and {source!r} both match {target!r}")
        claimed[target] = source
        matched[source] = Match(source, target, method, score)

    for source in sources:
        if source in aliases:
            claim(source, aliases[source], "alias", 100.0)
        elif (exact := target_by_key.get(match_key(source))) is not None:
            claim(source, exact, "exact", 100.0)

    # Fuzzy: score every remaining pair, then accept the best pairs first (greedy).
    remaining_sources = [s for s in sources if s not in matched]
    remaining_targets = [t for t in targets if t not in claimed]
    pairs = sorted(
        (
            (fuzz.token_sort_ratio(match_key(s), match_key(t)), i, s, t)
            for i, s in enumerate(remaining_sources)
            for t in remaining_targets
        ),
        key=lambda p: (-p[0], p[1], p[3]),
    )
    best_candidate: dict[str, tuple[float, str]] = {}
    for score, _, source, target in pairs:
        best_candidate.setdefault(source, (score, target))
        if score >= threshold and source not in matched and target not in claimed:
            claim(source, target, "fuzzy", score)

    results = []
    for source in sources:
        if source in matched:
            results.append(matched[source])
        else:
            score, candidate = best_candidate.get(source, (0.0, None))
            results.append(Match(source, None, "none", score, candidate))
    return results
