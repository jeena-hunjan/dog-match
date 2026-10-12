# CLAUDE.md — Dog Match

This file tells Claude (and any human contributor) what this project is, how it is built, and the rules to follow when working in this repo. Read it fully before making changes.

---

## 1. What this project is

**Dog Match** recommends dog breeds based on a person's lifestyle and, optionally, on a photo of a dog they like the look of.

There are two user flows:

1. **Lifestyle only.** The user fills in a form or writes free text, for example: *"London flat, work 9–5, mild allergy, 30 min a day to train"*. The app returns the top 5 breeds, each with a match score, a per-trait breakdown and a plain-English explanation that includes one honest downside.
2. **Lifestyle + photo.** The user also uploads a photo. A fine-tuned vision model predicts the likely breed (top 3, with calibrated confidence) and its traits. The app says whether that breed suits the user and suggests lookalike breeds that fit their lifestyle better.

### Why it exists
This is a **portfolio project** for a graduate ML engineer CV. It must show:
- a **trained, evaluated ML model** at its core (not just an LLM wrapper or a rules engine), and
- **production engineering**: API, containers, CI/CD, cloud, tests, SQL and LLM integration.

The ML is deliberately small. The rigour (baselines, calibration, an external test set, honest limitations) and the engineering are what matter.

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
| 6 | LLM / GenAI integration | `app/llm/` profile parser + grounded explainer |
| 7 | SQL | `sql/`, Alembic migrations, analytics queries |

### Tier 2 — target at least 8, 9, 10
| # | Skill | Where it lives |
|---|---|---|
| 8 | Experiment tracking & reproducibility | MLflow runs E1–E6, fixed seeds, pinned deps |
| 9 | Domain-specific data handling | Breed-name mapping across sources, `data_card.md` |
| 10 | Responsible AI | `MODEL_CARD.md`, calibration, abstention, allergy and legal caveats |
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
                      [trained]        traits, embedding,  (SQL filters,     (grounded,         + explanations
                                       abstain)            scoring,          template fallback)
                                                           lookalike re-rank)
                                   ▲
                                   │  SQL filters + request/feedback logging
                                   ▼
                     Postgres (breeds, traits, restrictions, requests, recommendations, feedback)
```

- Everything runs in one **FastAPI** service on **Cloud Run** (CPU only).
- The **form path skips the LLM parser**, so the app still works if the LLM is unavailable.
- The **vision model is the only route from a photo to a recommendation**. This is the ML centrepiece.

---

## 4. Tech stack

- **Language:** Python 3.11
- **ML:** PyTorch, `timm` (ConvNeXt-Tiny), `open_clip` (CLIP baselines), scikit-learn (linear probe), MLflow
- **API:** FastAPI, Pydantic v2, Uvicorn
- **DB:** PostgreSQL (Neon in the cloud, Docker locally), SQLAlchemy 2.x, Alembic
- **LLM:** a provider-agnostic client in `app/llm/llm_client.py` (structured output / tool calling)
- **Data:** pandas, `rapidfuzz` (name matching), `requests`
- **Quality:** pytest, pytest-cov, ruff, mypy, pre-commit
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
├── pipeline/build_dataset.py
├── training/                # train.py, evaluate.py, calibrate.py, configs/
├── sql/                     # analytics/*.sql
├── migrations/              # Alembic
├── tests/                   # unit/, api/, personas/, model/
├── eval/                    # llm_parsing_set.jsonl, grounding_check.py
├── .github/workflows/       # ci.yml, deploy.yml
├── Dockerfile
├── docker-compose.yml
├── Makefile
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
| Stanford Dogs | About 20.6k images, 120 breeds, official train/test split | ImageNet-derived; **non-commercial licence**; never commit images |
| AKC breed traits (TidyTuesday, Feb 2022) | About 195 breeds rated 1–5 (energy, shedding, trainability, good with young children, good with other dogs, barking, grooming, etc.) | **No size or weight columns** |
| TheDogAPI | Weight and height ranges, life span | Needs a free API key; fills the size gap |
| Country restrictions | Banned or restricted breeds for 3–5 countries | Hand-curated; every row has `source_url` and `last_checked` |
| Oxford-IIIT Pet | 25 dog + 12 cat breeds | **External test set** and not-a-dog (OOD) checks only |

### Pipeline (`pipeline/build_dataset.py`), which must be re-runnable end to end
1. Download all sources with code, never by hand.
2. Normalise breed names (lowercase, replace underscores) and apply `pipeline/aliases.yaml`.
3. Fuzzy-match the remaining names with `rapidfuzz`, and write unmatched names to a report.
4. Exclude the wild canids (dingo, dhole, African hunting dog), leaving **117 photo breeds**.
5. Split off a stratified **15% validation set** from the official train split (seed 42).
6. Load breeds, traits, sizes and restrictions into Postgres.
7. Regenerate `data_card.md` (counts, matches, exclusions).

---

## 7. ML core

### Model
- **Backbone:** ConvNeXt-Tiny (`timm`, ImageNet-pretrained).
- **Head 1:** breed classification, a softmax over 117 classes.
- **Head 2:** trait regression on selected AKC traits (energy, shedding, trainability, good with children, barking), scaled to 0–1.
- **Loss:** cross-entropy + λ × MSE.
- **Training:** fine-tune the last 2 stages for 3–5 epochs on a free Kaggle or Colab GPU, with AdamW, mixed precision, standard augmentation and fixed seeds.

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
| E3 | Fine-tune, classification head only | What does fine-tuning add? |
| E4 | Fine-tune, multi-task | Does the trait head help or hurt? |
| E5 | Direct trait head vs probability-weighted traits | Which trait estimate is better (MAE)? |
| E6 | Before vs after temperature scaling | Are the probabilities trustworthy? |

**Metrics to report:** top-1, top-5, macro-F1, ECE, trait MAE, not-a-dog AUROC, the 5 most-confused pairs, CPU latency. Report accuracy on **both** the Stanford test split and the external Oxford-IIIT dog images.

---

## 8. Lifestyle recommender

**Profile fields:** country, home type, daily exercise time, weekly training time, first-time owner, children under 5, other pets, allergy level, hours alone per day, noise tolerance, grooming willingness, size preference.

### Hard filters (SQL)
- Breed banned in the user's country → removed
- Severe allergy → shedding ≤ 2, plus a warning
- Children under 5 → good with young children ≥ 3
- Flat with no garden → giant breeds removed

### Soft score
```
score = 100 × Σ wᵢ (1 − |tᵢ − bᵢ| / 4) / Σ wᵢ
```
`t` is the user's target level (1–5), `b` is the breed's rating and `w` is the weight. Dealbreaker answers get 3× weight. Always return the per-trait breakdown so results explain themselves without the LLM.

---

## 9. LLM integration

1. **Parser** (`app/llm/parser.py`): turns free text into a Pydantic `Profile` via structured output. Missing fields are set to `unknown`, and the API returns at most 2 follow-up questions. Never guess.
2. **Explainer** (`app/llm/explainer.py`): the prompt contains **only** the top-5 trait rows, the score breakdown and (if there is a photo) the prediction and confidence. It must cite only the supplied data, give one downside per breed, and hedge when confidence is low. Run at temperature 0 with a timeout; on any failure, fall back to a template explanation.

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
| GET | `/breeds`, `/breeds/{id}` | Breed data and restrictions |
| POST | `/feedback` | Thumbs up or down, plus a comment |
| GET | `/health` | Liveness and model-loaded check |
| GET | `/metrics` | Prometheus-format counters |

### Tables
- `breeds`: id, name, stanford_label, weight_min_kg, weight_max_kg, height_cm, lifespan_years
- `breed_traits`: breed_id, trait, score
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

### Setup (about 1 hour)
- [ ] Accounts and keys: GCP project (with a billing alert), Neon, Kaggle, LLM provider, TheDogAPI
- [ ] Repo skeleton, `pyproject.toml`, ruff, mypy, pre-commit, Makefile, and CI running on an empty test

### Day 1: data, training and a deployed thin app
- [ ] `build_dataset.py`: downloads, mapping, splits, Postgres load, data card
- [ ] E1 + E2 on the GPU (MLflow); then start E3/E4 fine-tuning in the background
- [ ] Filters and scoring with unit tests and the persona suite
- [ ] FastAPI `/recommend` (form), `/breeds`, `/health`, plus API tests
- [ ] Docker, docker-compose, deploy workflow → **first Cloud Run deploy (lifestyle only)**
- [ ] Collect the fine-tuning results; run E5

### Day 2: model in the app, LLM, rigour, docs
- [ ] E6 temperature scaling, abstention threshold, not-a-dog gate, external Oxford-IIIT test
- [ ] Export embeddings and centroids; publish the weights as a GitHub Release asset with a checksum
- [ ] `/identify`, the photo path in `/recommend`, lookalike re-rank, model smoke test
- [ ] LLM parser + explainer with fallback; parsing eval; grounding check
- [ ] `/feedback`, request logging, analytics SQL, `/metrics`; redeploy
- [ ] README, `MODEL_CARD.md`, results table, calibration plot, architecture diagram, demo GIF

**Rule:** keep `main` deployable at all times. Deploy a thin version early and add to it, rather than deploying everything at the end.

---

## 12. Cut list (if behind schedule, cut from the top)
1. Tier 3 stretch goals (front end, ONNX)
2. `/metrics` and the drift query
3. The direct trait head (keep only probability-weighted traits; drop E4/E5)
4. Lookalike re-ranking
5. The LLM free-text parser (keep the form; **keep the explainer** so Tier 1 skill 6 survives)

**Never cut:** calibration, the external test set, tests, or any Tier 1 item.

---

## 13. Commands

Create these Makefile targets during setup, and keep them working:

```bash
make setup        # install deps, pre-commit hooks
make data         # python pipeline/build_dataset.py
make train        # python training/train.py --config training/configs/<cfg>.yaml
make evaluate     # python training/evaluate.py (Stanford + external test, ECE, confusion)
make calibrate    # python training/calibrate.py
make lint         # ruff check . && ruff format --check . && mypy app
make test         # pytest -m "not slow" --cov=app
make test-all     # pytest (includes model regression test)
make eval-llm     # python eval/grounding_check.py and parsing eval (real LLM calls)
make up           # docker compose up --build
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

### Never
- Commit dataset images, model weights, `.env` files or API keys.
- Store uploaded user photos. Process them in memory only; store predictions only.
- Call a real LLM in CI. Mock it with fixtures.
- Let the explainer state a trait value that is not in the supplied data.
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

---

## 15. Known caveats (and how they are handled)

| Issue | Handling |
|---|---|
| Stanford Dogs comes from ImageNet, so pretrained backbones have seen its test images and accuracy is inflated | Disclose it; treat the **Oxford-IIIT external test** as the honest number |
| Only 117 photo breeds vs about 195 AKC breeds | Recommend from all AKC breeds; flag "photo not supported for this breed"; document coverage |
| Breed names differ between sources | Alias file + fuzzy matching + an unmatched report + a test for known breeds |
| No size data in the AKC traits | Join TheDogAPI weight and height; record manual fills |
| Mixed breeds and odd photos | Top 3, calibrated probabilities, abstention, not-a-dog gate, "looks like" wording |
| Look-alike breeds (e.g. husky vs malamute) | Report top-5 accuracy and the most-confused pairs |
| No ground truth for the "best breed" | Persona test suite, feedback logging, stated limitation |
| AKC ratings are breed averages and partly subjective | Model card note; present ratings as tendencies |
| "Hypoallergenic" is largely a myth | Shedding is a proxy only; show a warning; advise meeting the breed first |
| LLM hallucination | Grounded prompts, temperature 0, schema validation, grounding check, template fallback |
| Breed laws change | Limited countries, source URL + last-checked date, "check local law" disclaimer |
| Large PyTorch images and cold starts | CPU-only wheel, small backbone, optional ONNX, `min-instances=1` when demoing |
| Licences | Download scripts only; cite every dataset; no images in the repo |

---

## 16. README must include
1. One-line pitch, **live URL**, demo GIF, CI and coverage badges
2. Architecture diagram
3. Results table (E1–E6) with Stanford and external accuracy side by side, plus the calibration plot
4. How recommendations work (filters, scoring, lookalikes, the LLM's role)
5. Limitations and responsible AI (link to `MODEL_CARD.md`; state the ImageNet overlap)
6. Running locally (`make up`) and reproducing training
7. "What I'd do with more time"
