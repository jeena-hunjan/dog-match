# CLAUDE.md — Dog Match

This file tells Claude (and any human contributor) what this project is, how it is built, and the rules to follow when working in this repo. Read it fully before making changes.

> **Compliance comes first.** Before adding or changing any data source, dataset, API, model, library or service, **read its licence, terms of use and usage policies in full** and confirm that the way we intend to use it is allowed. This applies even though this is a personal, non-commercial project. Record the outcome in the licence register (section 6). If the terms do not clearly allow our use, do not use it. Ask the owner instead.

---

## 1. What this project is

**Dog Match** recommends dog breeds based on a person's lifestyle and, optionally, on a photo of a dog they like the look of.

There are two user flows:

1. **Lifestyle only.** The user fills in a form or writes free text, for example: *"London flat, work 9–5, mild allergy, 30 min a day to train"*. The app returns the top 5 breeds, each with a match score, a per-trait breakdown and a plain-English explanation that includes one honest downside.
2. **Lifestyle + photo.** The user also uploads a photo. A fine-tuned vision model predicts the likely breed (top 3, with calibrated confidence), and the app looks up that breed's trait ratings. The app says whether that breed suits the user and suggests lookalike breeds that fit their lifestyle better.

The app covers the **117 Stanford Dogs photo breeds**, so every breed it recommends can also be recognised from a photo.

### Why it exists
This is a **personal portfolio project** (not commercial, not coursework) for a graduate ML engineer CV. It must show:
- a **trained, evaluated ML model** at its core (not just an LLM wrapper or a rules engine), and
- **production engineering**: API, containers, CI/CD, cloud, tests, SQL and LLM integration.

The ML is deliberately small. The rigour (baselines, calibration, an external test set, honest limitations, licence compliance) and the engineering are what matter.

### Time budget
About **2 days** of work. Scope decisions must respect this. See the cut list in section 12.

---

## 2. Definition of done

### Tier 1 — all required
| # | Skill | Where it lives |
|---|---|---|
| 1 | Model serving via an API | `app/` FastAPI (`/identify`, `/recommend`) |
| 2 | Containerisation | `Dockerfile`, `docker-compose.yml` |
| 3 | Cloud deployment | Google Cloud Run + Neon Postgres; live URL in README |
| 4 | CI/CD | `.github/workflows/ci.yml`, `deploy.yml` |
| 5 | Testing & code quality | `tests/`, ruff, mypy, pre-commit, coverage |
| 6 | LLM / GenAI integration | `app/llm/`: evidence-backed breed ratings (offline), profile parser, grounded explainer |
| 7 | SQL | `sql/`, Alembic migrations, analytics queries |

### Tier 2 — target at least 8, 9, 10
| # | Skill | Where it lives |
|---|---|---|
| 8 | Experiment tracking & reproducibility | MLflow runs E1–E5, fixed seeds, pinned deps |
| 9 | Domain-specific data handling | Breed-name mapping across Stanford, Wikipedia, TheDogAPI and Oxford; LLM-assisted ratings with verified quotes; `data_card.md` |
| 10 | Responsible AI | `MODEL_CARD.md`, calibration, abstention, allergy and legal caveats, licence register |
| 11 | Monitoring (if time) | `/metrics`, structured logs, SQL drift query |
| 12 | Data pipeline (light) | `pipeline/build_dataset.py` |

### Tier 3 — stretch only, after Tiers 1–2 are deployed
- Simple front end (Gradio or Streamlit calling the API)
- Model optimisation (ONNX export + latency comparison)

---

## 3. Architecture

```
 Lifestyle (form / free text) ──► LLM parser ──────────────┐
                                                           ▼
 Photo (optional) ──► Vision model ──► (breed probs,  ──► Recommender ──► LLM explainer ──► Top 5 breeds
                      [trained]        embedding,          (SQL filters,     (grounded,         + explanations
                                       abstain)            scoring,          template fallback)
                                                           lookalike re-rank)
                                   ▲
                                   │  SQL filters + request/feedback logging
                                   ▼
                     Postgres (breeds, traits, restrictions, requests, recommendations, feedback)
                                   ▲
                                   │  loaded by `make data` (offline, never at request time)
                                   │
 Wikipedia articles ──► LLM rater ──► pipeline/breed_ratings.csv (quotes verified, owner spot-checked)
```

- Everything runs in one **FastAPI** service on **Cloud Run** (CPU only).
- The **form path skips the LLM parser**, so the app still works if the LLM is unavailable.
- The **vision model is the only route from a photo to a recommendation**. This is the ML centrepiece.
- **Breed ratings are produced offline** by the pipeline and committed as a reviewed CSV. The app never calls the LLM to rate breeds.
- A photo's traits are the **probability-weighted ratings** of its top predictions. No model is trained to predict traits (see section 7).

---

## 4. Tech stack

- **Language:** Python 3.11
- **ML:** PyTorch, `timm` (ConvNeXt-Tiny), `open_clip` (CLIP baselines), scikit-learn (linear probe), MLflow
- **API:** FastAPI, Pydantic v2, Uvicorn
- **DB:** PostgreSQL (Neon in the cloud, Docker locally), SQLAlchemy 2.x, Alembic
- **LLM:** a provider-agnostic client in `app/llm/llm_client.py` (structured output / tool calling); currently Anthropic Claude Haiku
- **Data:** pandas, `rapidfuzz` (name matching), `requests`, `scipy` (Stanford `.mat` lists), MediaWiki API (Wikipedia)
- **Quality:** pytest, pytest-cov, ruff, mypy, pre-commit, detect-secrets
- **Infra:** Docker (multi-stage, CPU-only torch wheel), GitHub Actions, Google Cloud Run, Artifact Registry, Secret Manager, Workload Identity Federation

---

## 5. Repository layout

```
dog-match/
├── app/
│   ├── main.py              # FastAPI app and routes
│   ├── recommender/         # filters.py, scoring.py, lookalike.py
│   ├── vision/              # model loading, predict, calibration, OOD gate
│   ├── llm/                 # llm_client.py, parser.py, explainer.py, prompts/
│   ├── db/                  # SQLAlchemy models, session
│   └── schemas.py           # Pydantic Profile and response models
├── pipeline/                # build_dataset.py, aliases.yaml, country_restrictions.csv,
│                            # manual_sizes.csv, breed_ratings.csv (CC BY-SA 4.0)
├── data/splits/             # committed split manifests (file names and labels only)
├── training/                # train.py, evaluate.py, calibrate.py, configs/
├── sql/                     # analytics/*.sql
├── migrations/              # Alembic
├── tests/                   # unit/, api/, personas/, model/
├── eval/                    # llm_parsing_set.jsonl, grounding_check.py
├── .github/workflows/       # ci.yml, deploy.yml
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── LICENSE                  # code only; data, ratings and weights have their own terms
├── MODEL_CARD.md
├── data_card.md
├── CLAUDE.md
└── README.md
```

Keep this layout. Each folder maps to a checklist skill, so recruiters can find them quickly.

---

## 6. Data

| Source | Provides | Notes |
|---|---|---|
| Stanford Dogs | About 20.6k images, 120 breeds, official train/test split | ImageNet-derived; **non-commercial research and education only**; never commit or show images |
| Wikipedia (one article per breed) | Text the trait ratings are based on; canonical breed names (article titles) | CC BY-SA 4.0; downloaded once via the MediaWiki API and cached, with the revision ID |
| LLM breed ratings (ours) | 8 traits rated 1–5 or `unknown`, each with a verbatim supporting quote | Generated offline from Wikipedia text; released as **CC BY-SA 4.0** in `pipeline/breed_ratings.csv` |
| TheDogAPI | Weight and height ranges, life span | Free API key; tell users the app uses it |
| Country restrictions | Banned or restricted breeds for 5 countries | Hand-curated; every row has `source_url` and `last_checked`; only breeds in our list can have rows |
| Oxford-IIIT Pet | 25 dog + 12 cat breeds | **External test set** and not-a-dog (OOD) checks only; CC BY-SA 4.0 |

**Not used:** the AKC breed ratings (TidyTuesday, Feb 2022). AKC's terms only allow viewing the content. They forbid storing it in a database, creating derivative works and displaying it online, and AKC's reproduction policy refuses online use. Never reintroduce AKC data.

### Licence register

Every external source, provider and dataset must have a row here **before** it is used. Re-check the terms when a source is added or its use changes.

| Source | Terms read | What we use it for | Conditions we follow |
|---|---|---|---|
| Stanford Dogs / ImageNet | ImageNet terms of access; Stanford Dogs page | Training, validation, test | Non-commercial research and education only. Cite Khosla et al. 2011 and Deng et al. 2009. No images in the repo, README or demo. Trained weights are released for non-commercial use only. |
| Oxford-IIIT Pet | CC BY-SA 4.0; image copyright stays with the owners | External test and not-a-dog checks only | Credit the dataset and cite Parkhi et al. 2012. `data/splits/oxford.csv` is CC BY-SA 4.0. Never show the images. |
| Wikipedia | CC BY-SA 4.0; Wikimedia Terms of Use; API etiquette; User-Agent and Robot policies | Breed names; source text for ratings | Credit each article (URL + revision ID). Ratings and quotes are released as CC BY-SA 4.0, marked as modified. Requests are serial and cached, with `maxlag`, backoff and a descriptive User-Agent that contains the repo URL (never a personal email). |
| Anthropic API | Commercial Terms; Usage Policy | Breed ratings (offline), profile parser, explainer | We own the outputs. **Never train any model on LLM outputs** (the usage policy forbids it without authorisation). Never score people. |
| TheDogAPI | TheDogAPI terms (free tier) | Sizes, cached in Postgres | Tell users the app uses TheDogAPI (README and API). Never put "Dog API" in the app's name, use their logo or resell the service. |
| Government and law sites (gov.uk, gov.ie, gesetze-im-internet.de, service-public.gouv.fr, danskelove.dk) | Site terms (gov.uk: Open Government Licence v3.0) | Country restrictions | Link every row to its source, add the credit lines each site requires, show a "check local law" disclaimer. |
| FCI breed standard no. 94 | Copyrighted document | One size fill (Portuguese Podengo Pequeno) | Cite the source. Only facts (measurements) are used. |
| AKC (via TidyTuesday) | AKC Terms of Use; Material Reproduction Policy | **Nothing.** | Do not download, store, display or derive from it. |

### Pipeline (`pipeline/build_dataset.py`), which must be re-runnable end to end
1. Download all sources with code, never by hand (cached and checksummed in `data/raw/`).
2. Build the breed list: the 120 Stanford classes minus the wild canids (dingo, dhole, African hunting dog) = **117 breeds**, named by their Wikipedia article title via `pipeline/aliases.yaml`.
3. Match TheDogAPI and Oxford-IIIT names to those breeds (aliases, then normalised exact match, then `rapidfuzz`); write unmatched names to a report.
4. Split off a stratified **15% validation set** from the official Stanford train split (seed 42); write the manifests to `data/splits/`.
5. Load the committed breed ratings (`pipeline/breed_ratings.csv`). Rating new breeds or re-rating needs real LLM calls (`make ratings`) and an owner review.
6. Load breeds, ratings, sizes and restrictions into Postgres.
7. Regenerate `data_card.md` (counts, matches, exclusions, licences).

### Breed ratings (`make ratings`)
- **8 traits:** energy, trainability, good with young children, good with other dogs, shedding, copes with being alone, barking, grooming.
- Each rating is 1–5 or `unknown`, plus a short quote from the article that supports it. **The code checks that each quote appears verbatim in the cached article**; a rating without a valid quote becomes `unknown`.
- Temperature 0, fixed prompt version, results committed. The owner spot-checks 20 breeds before the ratings are used.

---

## 7. ML core

### Model
- **Backbone:** ConvNeXt-Tiny (`timm`, ImageNet-pretrained).
- **Head:** breed classification, a softmax over 117 classes. There is **no trait head**: it would mean training on LLM-generated ratings, which Anthropic's usage policy does not allow without authorisation.
- **Loss:** cross-entropy.
- **Training:** fine-tune the last 2 stages for 3–5 epochs on a free Kaggle GPU, with AdamW, mixed precision, standard augmentation and fixed seeds.
- **Photo traits:** the probability-weighted average of the top-3 breeds' ratings (skipping `unknown`). This is arithmetic, not a trained model.

### Calibration and safety
- **Temperature scaling** fitted on the validation set. Report ECE (15 bins) before and after, plus a reliability diagram.
- **Abstention** when the top probability is below a threshold chosen on the validation set.
- **Not-a-dog gate:** CLIP zero-shot "dog vs not a dog", measured by AUROC on the Oxford-IIIT cat images.
- Always return the **top 3 with probabilities**. Use "looks like" wording; never claim genetics.

### Lookalike search
1. Average the penultimate-layer embeddings into one **centroid per breed**.
2. Compare the user's photo to the centroids by cosine similarity.
3. Re-rank lifestyle-compatible breeds by `0.5 × visual similarity + 0.5 × lifestyle score`, tuning the weight on the persona tests.

### Experiments (all logged to MLflow)
| ID | Experiment | Question |
|---|---|---|
| E1 | CLIP zero-shot | How good is a model with no training? |
| E2 | Linear probe on frozen embeddings | How far does a cheap method get? |
| E3 | Fine-tune, classification head | What does fine-tuning add? |
| E4 | Rating consistency (no training) | Are the LLM ratings stable? Rate twice with different prompt orderings; report agreement (exact and ±1) and quote validity |
| E5 | Before vs after temperature scaling | Are the probabilities trustworthy? |

**Metrics to report:** top-1, top-5, macro-F1, ECE, not-a-dog AUROC, the 5 most-confused pairs, CPU latency, rating agreement. Report accuracy on **both** the Stanford test split and the external Oxford-IIIT dog images.

---

## 8. Lifestyle recommender

**Profile fields → traits:**

| Profile field | Trait / data used |
|---|---|
| Daily exercise time | energy |
| Weekly training time, first-time owner | trainability |
| Children under 5 | good with young children (hard filter) |
| Other pets | good with other dogs |
| Allergy level | shedding (hard filter when severe) |
| Hours alone per day | copes with being alone |
| Noise tolerance | barking |
| Grooming willingness | grooming |
| Size preference, home type | TheDogAPI weight/height |
| Country | country restrictions |

### Hard filters (SQL)
- Breed banned in the user's country → removed
- Severe allergy → shedding ≤ 2, plus a warning
- Children under 5 → good with young children ≥ 3
- Flat with no garden → giant breeds removed
- **`unknown` fails a hard filter**: a breed is only kept when its rating shows that it passes.

### Soft score
```
score = 100 × Σ wᵢ (1 − |tᵢ − bᵢ| / 4) / Σ wᵢ
```
`t` is the user's target level (1–5), `b` is the breed's rating and `w` is the weight. Dealbreaker answers get 3× weight. **`unknown` ratings are left out of the sum** and listed in the breakdown as "not enough information". Always return the per-trait breakdown so results explain themselves without the LLM.

---

## 9. LLM integration

1. **Breed rater** (offline, `pipeline/`): see section 6. It is the first use of `app/llm/llm_client.py`.
2. **Parser** (`app/llm/parser.py`): turns free text into a Pydantic `Profile` via structured output. Missing fields are set to `unknown`, and the API returns at most 2 follow-up questions. Never guess.
3. **Explainer** (`app/llm/explainer.py`): the prompt contains **only** the top-5 rating rows (with their quotes), the score breakdown and (if there is a photo) the prediction and confidence. It must cite only the supplied data, give one downside per breed, and hedge when confidence is low. Run at temperature 0 with a timeout; on any failure, fall back to a template explanation.

**Cost and security:**
- Use a cheap model.
- Cache responses by profile hash.
- Rate-limit by IP.
- Keep keys in Secret Manager, never in code.
- Set a budget alert.

**Evaluation (`eval/`):**
- 30 hand-labelled descriptions, scored on field-level parsing accuracy.
- A grounding check that every trait claim matches the database.

---

## 10. API and database

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| POST | `/recommend` | Profile or free text, plus an optional photo → top 5 breeds with scores, breakdown and explanation |
| POST | `/identify` | Photo → top 3 breeds, confidence and traits, or an abstention |
| GET | `/breeds`, `/breeds/{id}` | Breed data, ratings with quotes, restrictions and source credits (Wikipedia article, TheDogAPI) |
| POST | `/feedback` | Thumbs up or down, plus a comment |
| GET | `/health` | Liveness and model-loaded check |
| GET | `/metrics` | Prometheus-format counters |

### Tables
- `breeds`: id, name, stanford_label, wikipedia_title, wikipedia_revision_id, weight_min_kg, weight_max_kg, height_min_cm, height_max_cm, lifespan_min_years, lifespan_max_years (TheDogAPI gives ranges, so size and lifespan are stored as min/max pairs)
- `breed_traits`: breed_id, trait, score, evidence (the verbatim Wikipedia quote). `unknown` ratings have no row.
- `country_restrictions`: country, breed_id, status, source_url, last_checked
- `requests`: id, created_at, profile (jsonb), has_photo, predicted_breed_id, confidence, abstained, latency_ms, model_version
- `recommendations`: request_id, rank, breed_id, score
- `feedback`: request_id, rating, comment, created_at

### Analytics SQL (`sql/analytics/`)
- Most-recommended breeds per country
- Feedback by breed
- Weekly abstention rate and mean confidence (drift)
- p95 latency per day
- Breeds that are never recommended (a bias check)

---

## 11. Build order (follow this sequence)

Work is grouped into milestones. Each milestone is one feature branch and one pull request. Each step inside it is one commit.

### Setup (about 1 hour)
- [x] Accounts and keys: GCP project (with a billing alert), Neon, Kaggle, LLM provider, TheDogAPI
- [x] Repo skeleton, `pyproject.toml`, ruff, mypy, pre-commit, Makefile, and CI running on an empty test
- [x] Database layer: SQLAlchemy models, Alembic, local Postgres (PR #1)

### Day 1: data, training and a deployed thin app
- [x] **A. Dataset pipeline:** downloads, name mapping, country restrictions, image splits, Postgres load, data card (PR #2)
- [ ] **A2. Open ratings (replaces AKC):**
  - [ ] A2.1 Update CLAUDE.md with the revised plan and the licence register
  - [ ] A2.2 Breed list = 117 Stanford breeds named by Wikipedia title; re-match TheDogAPI and Oxford; trim restrictions to listed breeds; regenerate splits (class indices unchanged)
  - [ ] A2.3 Polite Wikipedia downloader (serial, cached, User-Agent, `maxlag`, revision IDs)
  - [ ] A2.4 `llm_client.py` + rating step: 8 traits, 1–5 or `unknown`, quotes verified verbatim, results committed
  - [ ] A2.5 E4 rating consistency; **owner spot-checks 20 breeds**
  - [ ] A2.6 Migration (Wikipedia columns, `evidence`), load ratings, remove AKC from the pipeline, delete local AKC data
  - [ ] A2.7 Licences and credits: `LICENSE`, `data/splits/` licence note, README "Data and licences", data card
- [ ] **B. Baselines:** shared training code; E1 + E2 on the GPU (MLflow); start the E3 fine-tune in the background
- [ ] **C. Recommender:** filters and scoring (8 traits, `unknown` handling) with unit tests and the persona suite
- [ ] **D. API:** `/recommend` (form), `/breeds` (with credits), `/health`, plus API tests
- [ ] **E. First deploy:** Docker, docker-compose, deploy workflow → **first Cloud Run deploy (lifestyle only)**. May slip to early Day 2.
- [ ] **F. Results:** collect E3; evaluate on Stanford and Oxford-IIIT

### Day 2: model in the app, LLM, rigour, docs
- [ ] E5 temperature scaling, abstention threshold, not-a-dog gate, external Oxford-IIIT test
- [ ] Export embeddings and centroids; publish the weights as a GitHub Release asset with a checksum and a non-commercial notice
- [ ] `/identify`, the photo path in `/recommend` (probability-weighted traits), lookalike re-rank, model smoke test
- [ ] LLM parser + explainer with fallback (reusing `llm_client.py`); parsing eval; grounding check
- [ ] `/feedback`, request logging, analytics SQL, `/metrics`; redeploy
- [ ] README, `MODEL_CARD.md`, results table, calibration plot, architecture diagram, demo GIF (own or openly licensed photos only)

**Rule:** keep `main` deployable at all times. Deploy a thin version early and add to it, rather than deploying everything at the end.

---

## 12. Cut list (if behind schedule, cut from the top)
1. Tier 3 stretch goals (front end, ONNX)
2. `/metrics` and the drift query
3. Lookalike re-ranking
4. The LLM free-text parser (keep the form; **keep the explainer** so Tier 1 skill 6 survives)

Already cut: the trait head and the old E4/E5 trait experiments (they would train on LLM outputs).

**Never cut:** calibration, the external test set, tests, licence compliance, or any Tier 1 item.

---

## 13. Commands

Create these Makefile targets during setup, and keep them working:

```bash
make setup        # install deps, pre-commit hooks
make data         # python -m pipeline.build_dataset (uses the committed ratings; no LLM calls)
make ratings      # rate breeds from cached Wikipedia text (real LLM calls; review before committing)
make train        # python training/train.py --config training/configs/<cfg>.yaml
make evaluate     # python training/evaluate.py (Stanford + external test, ECE, confusion)
make calibrate    # python training/calibrate.py
make lint         # ruff check . && ruff format --check . && mypy app pipeline
make test         # pytest -m "not slow" --cov=app
make test-all     # pytest (includes model regression test)
make eval-llm     # python eval/grounding_check.py and parsing eval (real LLM calls)
make up           # docker compose up --build
make db-up        # docker compose up -d db
make migrate      # alembic upgrade head
make mlflow       # mlflow ui
```

### Environment variables (`.env.example` must list all of them; never commit `.env`)
```
DATABASE_URL=
LLM_API_KEY=
LLM_MODEL=
DOG_API_KEY=
MODEL_WEIGHTS_URL=
MODEL_WEIGHTS_SHA256=
ABSTAIN_THRESHOLD=
RATE_LIMIT_PER_MIN=
```

---

## 14. Rules for working in this repo

### Compliance
- **Read the licence, terms of use and usage policies of every source, dataset, API, model, library and service before using it**, and add it to the licence register (section 6). Personal or non-commercial use does not exempt us.
- If a use is not clearly allowed, do not use it. Stop and ask the owner.
- Never use AKC content in any form.
- Never train any model on LLM outputs.
- Never show dataset images (Stanford, Oxford) in the README, demo GIF or app.
- Always credit sources as their terms require (Wikipedia articles, TheDogAPI, Oxford-IIIT, Stanford Dogs, government sites).
- Respect API etiquette: cache downloads, make requests serially, identify the client.

### Never
- Commit dataset images, model weights, `.env` files or API keys.
- Store uploaded user photos. Process them in memory only; store predictions only.
- Call a real LLM in CI. Mock it with fixtures.
- Let the explainer state a trait value that is not in the supplied data.
- Accept a breed rating whose quote is not found verbatim in its article.
- Report Stanford Dogs accuracy without also reporting the external test-set accuracy.
- Weaken a hard filter to make a persona test pass.

### Always
- Use type hints and Pydantic models at API boundaries; keep mypy clean.
- Add or update tests with every behaviour change. Persona tests must show **zero hard-constraint violations**.
- Set seeds and log every training run to MLflow (config, metrics, git SHA).
- Keep functions small and pure in `recommender/` so they are easy to unit-test.
- Use SQLAlchemy and parameterised queries; never build SQL with string formatting.
- Update `MODEL_CARD.md`, `data_card.md` and the README results table when results change.
- Use Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).

### Workflow
- One commit per step, one branch and pull request per milestone.
- Claude prepares the changes, runs lint and tests, and hands over the exact `git` commands and commit message. **The owner makes all commits, pushes and merges.**

---

## 15. Known caveats (and how they are handled)

| Issue | Handling |
|---|---|
| Stanford Dogs comes from ImageNet, so pretrained backbones have seen its test images and accuracy is inflated | Disclose it; treat the **Oxford-IIIT external test** as the honest number |
| Only 117 breeds | Recommend and recognise the same 117 breeds; document coverage and name popular breeds that are missing |
| Breed names differ between sources | Alias file + fuzzy matching + an unmatched report + a test for known breeds |
| Breed ratings are LLM-generated from Wikipedia | Verbatim quotes checked in code, `unknown` allowed, E4 consistency check, owner spot-check, ratings shown as tendencies with their source |
| Wikipedia articles say little about some traits | `unknown` instead of a guess; `unknown` fails hard filters and is left out of the score |
| Size data comes from a different source | Join TheDogAPI weight and height; record manual fills with sources |
| Mixed breeds and odd photos | Top 3, calibrated probabilities, abstention, not-a-dog gate, "looks like" wording |
| Look-alike breeds (e.g. husky vs malamute) | Report top-5 accuracy and the most-confused pairs |
| No ground truth for the "best breed" | Persona test suite, feedback logging, stated limitation |
| "Hypoallergenic" is largely a myth | Shedding is a proxy only; show a warning; advise meeting the breed first |
| LLM hallucination | Grounded prompts, temperature 0, schema validation, quote verification, grounding check, template fallback |
| Breed laws change, and some laws name types rather than breeds (e.g. UK pit bull type, XL Bully) | Limited countries, source URL + last-checked date, "check local law" disclaimer |
| Large PyTorch images and cold starts | CPU-only wheel, small backbone, optional ONNX, `min-instances=1` when demoing |
| Licences and terms | Licence register (section 6); download scripts only; credit every source; no dataset images anywhere public; weights non-commercial |

---

## 16. README must include
1. One-line pitch, **live URL**, demo GIF, CI and coverage badges
2. Architecture diagram
3. Results table (E1–E5) with Stanford and external accuracy side by side, plus the calibration plot
4. How recommendations work (filters, scoring, ratings and their evidence, lookalikes, the LLM's role)
5. Limitations and responsible AI (link to `MODEL_CARD.md`; state the ImageNet overlap)
6. **Data and licences:** every source with its licence, citations and credits; the ratings' CC BY-SA 4.0 licence; the non-commercial terms of the weights
7. Running locally (`make up`) and reproducing training
8. "What I'd do with more time"
