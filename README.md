# Dog Match

Recommends dog breeds that fit your lifestyle and, optionally, look like a dog in a photo you upload.

> **Status:** the data pipeline and the breed trait ratings are built. The recommender, API and vision model are in progress. See [CLAUDE.md](CLAUDE.md) for the full plan.

## Quick start

Requires Python 3.11, [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make setup   # install core + dev dependencies, pre-commit hooks
make lint    # ruff + mypy
make test    # pytest with coverage
```

Copy `.env.example` to `.env` and fill in the values. Never commit `.env`.

## Breed trait ratings

The recommender scores the 117 Stanford Dogs breeds on 8 traits: energy, trainability, good with young children, good with other dogs, shedding, copes with being alone, barking and grooming.

### Where the ratings come from

The obvious source, the American Kennel Club's breed ratings, cannot be used: AKC's terms of use only allow viewing their content, and forbid storing it in a database, building on it or showing it online. Dog Match therefore makes its own ratings:

1. Each breed's English Wikipedia article is downloaded once, politely, following Wikimedia's API rules.
2. Claude Haiku 5.5 reads the article and rates each trait from 1 to 5, or says `unknown` when the article does not support a rating. It may not use outside knowledge.
3. Every score must come with a quote from the article. The code checks that the quote really appears in the article; if it does not, the score is discarded and the trait becomes `unknown`.

The ratings and quotes are in [`pipeline/breed_ratings.csv`](pipeline/breed_ratings.csv) and are released under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), like the Wikipedia text they are adapted from. Each row links to the exact article revision it was rated from. No model is trained on these ratings.

### How reliable they are

| Check | Result |
|---|---|
| Scores whose quote was found in the article | 285 of 287 (the other 2 became `unknown`) |
| Two runs with the traits in a different order: same rated-or-unknown decision | 93% |
| ...scores within one point of each other | 99% |
| ...quadratic-weighted kappa | 0.93 |

Details: [`eval/e4_rating_consistency.md`](eval/e4_rating_consistency.md). A spot-check sheet of 20 breeds for human review is in [`eval/ratings_spotcheck.csv`](eval/ratings_spotcheck.csv).

### Decision: accept low coverage

Many Wikipedia breed articles are mostly history and say little about temperament or care, so most traits are `unknown`:

| Trait | Breeds rated (of 117) |
|---|---|
| Grooming | 57 |
| Trainability | 52 |
| Good with young children | 43 |
| Barking | 35 |
| Energy | 28 |
| Shedding | 28 |
| Good with other dogs | 27 |
| Copes with being alone | 15 |
| **All traits** | **285 of 936 (30%)** |

22 breeds have no ratings at all. We chose to keep this honest gap rather than fill it with ratings that have no source: a missing rating is stated as "not enough information", never guessed.

### Limitations this causes

- **Hard filters are strict.** A breed only passes a safety filter when its rating shows that it passes; `unknown` fails. Only 16 breeds pass the severe-allergy filter (documented low shedding) and 34 pass the young-children filter; 8 pass both. Some breeds that are well known to suit these situations are left out because their articles do not say so. The Poodles are the clearest example: they are not in the allergy list.
- **Scores rest on fewer traits for some breeds.** `unknown` traits are left out of the match score, so a breed with two rated traits is compared on less evidence than one with seven. The per-trait breakdown always shows which traits were used.
- **Breeds with no ratings** can be identified from a photo but cannot be matched to a lifestyle.
- **The ratings come from one source.** They reflect what each article happens to cover and how the model reads it.

### How to improve it with more time

1. **Add other-language Wikipedia articles.** German and French breed articles often have temperament and coat-care sections. They have the same CC BY-SA licence and API rules, so they fit the same pipeline: rate from each article, keep the verified quote, and prefer the English one when both rate a trait.
2. **Add other openly licensed sources**, such as breed-standard facts and Wikidata, after checking each one's terms.
3. **Ask the breed clubs or AKC for permission** to use their ratings, which would fill most gaps in one step.
4. **Human review at scale:** verify every rating rather than a sample, and record each reviewer's agreement.
5. **Show uncertainty in the score:** report how many traits each match is based on, and down-rank breeds whose score rests on very few traits.

## Data and licences

Every source's terms were read before it was used; see the licence register in [CLAUDE.md](CLAUDE.md) (section 6) and the [data card](data_card.md). A full credits section will be added before the first release.
