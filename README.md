# Dog Match

Recommends dog breeds that fit your lifestyle and, optionally, look like a dog in a photo you upload.

> **Status:** project setup only. No features yet. See [CLAUDE.md](CLAUDE.md) for the full plan.

## Quick start

Requires Python 3.11, [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make setup   # install core + dev dependencies, pre-commit hooks
make lint    # ruff + mypy
make test    # pytest with coverage
```

Copy `.env.example` to `.env` and fill in the values. Never commit `.env`.
