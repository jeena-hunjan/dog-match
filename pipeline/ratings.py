"""Rate each breed's traits from its Wikipedia article with an LLM, with checked evidence.

For every breed the model reads the cached article and returns, per trait, a 1-5 score or
"unknown" plus a short quote copied from the article. The code then checks that each quote
really appears in the article; a rating whose quote is missing, too short or not found
becomes `unknown`. The model is never asked to use outside knowledge.

- Responses are cached in data/raw/ratings/ (by prompt version, variant and article
  revision), so re-runs are free and reproducible.
- Variant "a" writes the published ratings, pipeline/breed_ratings.csv. Variant "b" lists
  the traits in reverse order and is only used for the E4 consistency check.
- The ratings and quotes are adapted from Wikipedia and released under CC BY-SA 4.0.
- No model may be trained on these ratings (Anthropic usage policy).

Run: python -m pipeline.ratings [--variant a|b] [--limit N]   (real LLM calls)
"""

import argparse
import csv
import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

from app.llm.llm_client import LLMClient, LLMError
from pipeline.wikipedia import Article

PROMPT_VERSION = "v1"
RATINGS_PATH = Path(__file__).with_name("breed_ratings.csv")
DEFAULT_CACHE_DIR = Path("data/raw/ratings")
MIN_QUOTE_CHARS = 20
MAX_QUOTE_CHARS = 400

Variant = Literal["a", "b"]
Status = Literal["rated", "unknown", "quote_not_found", "quote_too_short"]

# Trait key -> what 1 and 5 mean. The recommender maps profile answers onto these.
TRAITS: dict[str, str] = {
    "energy": "Daily exercise and activity needed. 1 = very low (short walks are enough); "
    "5 = very high (hours of vigorous exercise, working stamina).",
    "trainability": "How readily the breed learns and follows commands. 1 = very "
    "independent or stubborn; 5 = very eager to please and easy to train.",
    "good_with_young_children": "Suitability for a home with young children. 1 = not "
    "recommended; 5 = notably gentle, patient and tolerant with children.",
    "good_with_other_dogs": "How the breed tends to get on with other dogs. 1 = often "
    "aggressive or intolerant; 5 = very sociable with other dogs.",
    "shedding": "How much the coat sheds. 1 = minimal (little or no shedding); "
    "5 = very heavy or constant shedding.",
    "copes_alone": "How well the breed copes with being left alone. 1 = prone to "
    "separation anxiety, should rarely be alone; 5 = copes well alone for several hours.",
    "barking": "How vocal the breed is (barking, howling, baying). 1 = quiet; 5 = very vocal.",
    "grooming": "Coat care needed. 1 = minimal, occasional brushing; 5 = daily brushing "
    "and/or regular professional grooming or clipping.",
}

SYSTEM_PROMPT = """You rate dog breeds on a few traits using ONLY the Wikipedia article \
you are given. You are building an evidence-backed dataset, so accuracy matters more \
than coverage.

Rules:
- Use only what the article says. Do not use your own knowledge of the breed, even if \
you are confident.
- For each trait, either give a score from 1 to 5, or "unknown" when the article does \
not clearly support a score. "unknown" is a good answer, not a failure.
- Every score needs a quote: one passage copied character for character from the \
article (at most two sentences) that directly supports the score. Do not paraphrase, \
shorten, merge or fix the wording of the quote.
- If the article covers several varieties (for example sizes of Poodle, or the Belgian \
Shepherd varieties), rate the named breed: use passages about that variety where the \
article separates them, otherwise passages about the breed as a whole.
- For "unknown", set the quote to an empty string."""


@dataclass(frozen=True)
class BreedToRate:
    name: str
    article: Article


@dataclass(frozen=True)
class Rating:
    breed: str
    trait: str
    score: int | None  # None = unknown
    evidence: str  # verbatim article quote; empty when unknown
    status: Status
    wikipedia_title: str
    wikipedia_revision_id: int
    model: str
    prompt_version: str


def trait_order(variant: Variant) -> list[str]:
    order = list(TRAITS)
    return order if variant == "a" else order[::-1]


def response_schema(variant: Variant) -> dict[str, Any]:
    trait_schema = {
        "type": "object",
        "properties": {
            "score": {"type": "string", "enum": ["1", "2", "3", "4", "5", "unknown"]},
            "quote": {"type": "string"},
        },
        "required": ["score", "quote"],
        "additionalProperties": False,
    }
    order = trait_order(variant)
    return {
        "type": "object",
        "properties": {trait: trait_schema for trait in order},
        "required": order,
        "additionalProperties": False,
    }


def user_prompt(breed: BreedToRate, variant: Variant) -> str:
    traits = "\n".join(f"- {t}: {TRAITS[t]}" for t in trait_order(variant))
    return (
        f"Breed to rate: {breed.name}\n\n"
        f"Traits:\n{traits}\n\n"
        f'<article title="{breed.article.title}">\n{breed.article.text}\n</article>'
    )


# Unicode hyphens and dashes (U+2010-U+2015, U+2212) and curly quotes, by code point.
_DASHES = str.maketrans(dict.fromkeys(map(chr, [*range(0x2010, 0x2016), 0x2212]), "-"))
_QUOTES = str.maketrans({chr(0x2018): "'", chr(0x2019): "'", chr(0x201C): '"', chr(0x201D): '"'})


def normalise_for_match(text: str) -> str:
    """Forgive only typography: Unicode forms, curly quotes, dash types, spacing, case."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).translate(_DASHES)
    return " ".join(text.split()).casefold()


def check_quote(quote: str, article_text: str) -> Status:
    normalised = normalise_for_match(quote).strip(" .\"'")
    if len(normalised) < MIN_QUOTE_CHARS or len(normalised) > MAX_QUOTE_CHARS:
        return "quote_too_short" if len(normalised) < MIN_QUOTE_CHARS else "quote_not_found"
    return "rated" if normalised in normalise_for_match(article_text) else "quote_not_found"


def parse_ratings(
    breed: BreedToRate, answer: dict[str, Any], model: str, variant: Variant
) -> list[Rating]:
    """Turn the model's answer into ratings, demoting any unsupported score to unknown."""
    ratings = []
    for trait in TRAITS:  # always output in the canonical order
        item = answer[trait]
        score_text, quote = str(item["score"]), str(item["quote"]).strip()
        score: int | None = None
        status: Status = "unknown"
        if score_text != "unknown":
            status = check_quote(quote, breed.article.text)
            if status == "rated":
                score = int(score_text)
        ratings.append(
            Rating(
                breed=breed.name,
                trait=trait,
                score=score,
                evidence=quote if score is not None else "",
                status=status,
                wikipedia_title=breed.article.title,
                wikipedia_revision_id=breed.article.revision_id,
                model=model,
                prompt_version=f"{PROMPT_VERSION}{variant}",
            )
        )
    return ratings


def _cache_file(cache_dir: Path, breed: BreedToRate, variant: Variant) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", breed.name).strip("_")
    return cache_dir / f"{PROMPT_VERSION}{variant}" / f"{slug}.json"


def rate_breed(
    client: LLMClient, breed: BreedToRate, variant: Variant, cache_dir: Path
) -> list[Rating]:
    """One LLM call per breed, cached by prompt version, variant and article revision."""
    path = _cache_file(cache_dir, breed, variant)
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached["revision_id"] == breed.article.revision_id and cached["model"] == client.model:
            return parse_ratings(breed, cached["answer"], cached["model"], variant)
    answer = client.complete_json(
        system=SYSTEM_PROMPT, user=user_prompt(breed, variant), schema=response_schema(variant)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"revision_id": breed.article.revision_id, "model": client.model, "answer": answer}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return parse_ratings(breed, answer, client.model, variant)


def rate_breeds(
    client: LLMClient,
    breeds: Sequence[BreedToRate],
    variant: Variant,
    cache_dir: Path,
    workers: int = 4,
    on_error: Callable[[str, LLMError], None] | None = None,
) -> list[Rating]:
    """Rate every breed (a few in parallel); results keep the input order."""

    def one(breed: BreedToRate) -> list[Rating]:
        try:
            return rate_breed(client, breed, variant, cache_dir)
        except LLMError as e:
            if on_error is None:
                raise
            on_error(breed.name, e)
            return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, breeds))
    return [rating for ratings in results for rating in ratings]


RATING_FIELDS = [f.name for f in fields(Rating)]


def write_ratings(ratings: Iterable[Rating], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RATING_FIELDS, lineterminator="\n")
        writer.writeheader()
        for r in ratings:
            row = asdict(r)
            row["score"] = "" if r.score is None else r.score
            writer.writerow(row)


def read_ratings(path: Path = RATINGS_PATH) -> list[Rating]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        Rating(
            breed=row["breed"],
            trait=row["trait"],
            score=int(row["score"]) if row["score"] else None,
            evidence=row["evidence"],
            status=row["status"],  # type: ignore[arg-type]
            wikipedia_title=row["wikipedia_title"],
            wikipedia_revision_id=int(row["wikipedia_revision_id"]),
            model=row["model"],
            prompt_version=row["prompt_version"],
        )
        for row in rows
    ]


def summarise(ratings: Sequence[Rating]) -> str:
    by_status = Counter(r.status for r in ratings)
    rated_per_trait = Counter(r.trait for r in ratings if r.score is not None)
    breeds = len({r.breed for r in ratings})
    lines = [
        f"{len(ratings)} ratings for {breeds} breeds: "
        + ", ".join(f"{status} {n}" for status, n in sorted(by_status.items())),
        "rated per trait: " + ", ".join(f"{t} {rated_per_trait[t]}/{breeds}" for t in TRAITS),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    from app.llm.llm_client import client_from_env
    from pipeline.breed_mapping import load_breed_list
    from pipeline.wikipedia import DEFAULT_CACHE_DIR as ARTICLES_DIR
    from pipeline.wikipedia import load_cached

    parser = argparse.ArgumentParser(description="Rate breed traits from Wikipedia (LLM).")
    parser.add_argument("--variant", choices=["a", "b"], default="a")
    parser.add_argument("--limit", type=int, help="only the first N breeds (for a trial)")
    parser.add_argument("--out", type=Path, help="default: pipeline/breed_ratings.csv for a")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("pipeline.ratings")
    try:
        import truststore
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - both are optional
        pass
    else:
        truststore.inject_into_ssl()
        load_dotenv()

    breeds = []
    for entry in load_breed_list().values():
        article = load_cached(ARTICLES_DIR, entry.wikipedia_title)
        if article is None:
            raise SystemExit("articles missing; run python -m pipeline.wikipedia first")
        breeds.append(BreedToRate(entry.name, article))
    breeds = breeds[: args.limit] if args.limit else breeds

    client = client_from_env()
    failures: list[str] = []
    ratings = rate_breeds(
        client,
        breeds,
        args.variant,
        args.cache_dir,
        on_error=lambda name, e: failures.append(f"{name}: {e}"),
    )
    out = args.out or (RATINGS_PATH if args.variant == "a" else Path("data/interim/ratings_b.csv"))
    out.parent.mkdir(parents=True, exist_ok=True)
    write_ratings(ratings, out)
    log.info("%s", summarise(ratings))
    log.info(
        "%d API calls this run, %d input / %d output tokens -> %s",
        client.usage.requests,
        client.usage.input_tokens,
        client.usage.output_tokens,
        out,
    )
    if failures:
        raise SystemExit(f"{len(failures)} breeds failed: {failures}")


if __name__ == "__main__":
    main()
