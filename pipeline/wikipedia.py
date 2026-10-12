"""Download the breed articles from English Wikipedia (MediaWiki Action API), politely.

Follows Wikimedia's API etiquette and User-Agent policy: one request at a time with a
pause, a descriptive User-Agent with a contact URL, `maxlag` so we back off when the
servers are busy, retries with backoff on 429/5xx, and a local cache so no article is
fetched twice. Each article is stored with its revision ID, which the ratings cite.

Article text is CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).
It is cached in data/raw/wikipedia/ and never committed.

Run: python -m pipeline.wikipedia [--refresh]
"""

import argparse
import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import requests

API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = (
    "DogMatch/0.1 (https://github.com/jeena-hunjan/dog-match) "
    f"python-requests/{requests.__version__}"
)
DEFAULT_CACHE_DIR = Path("data/raw/wikipedia")
MAXLAG_S = 5
PAUSE_S = 1.0
MAX_ATTEMPTS = 6
_TIMEOUT_S = 30

log = logging.getLogger("pipeline.wikipedia")


class WikipediaError(RuntimeError):
    pass


class _Response(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    def json(self) -> Any: ...


class ApiSession(Protocol):
    """The slice of requests.Session used here; tests pass a fake.

    `params` is Any because requests types it as a broad union that a plain Mapping
    cannot match exactly.
    """

    def get(
        self,
        url: str,
        *,
        params: Any,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response: ...


@dataclass(frozen=True)
class Article:
    title: str
    page_id: int
    revision_id: int
    revision_timestamp: str
    text: str

    @property
    def url(self) -> str:
        return "https://en.wikipedia.org/wiki/" + quote(self.title.replace(" ", "_"))

    @property
    def permalink(self) -> str:
        """The exact revision the ratings were made from."""
        return f"https://en.wikipedia.org/w/index.php?oldid={self.revision_id}"


def _params(title: str) -> dict[str, str | int]:
    return {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "titles": title,
        "prop": "extracts|revisions|info|pageprops",
        "explaintext": 1,
        "exsectionformat": "plain",
        "rvprop": "ids|timestamp",
        "ppprop": "disambiguation",
        "maxlag": MAXLAG_S,
    }


def _wait_seconds(response: _Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "")
    return float(retry_after) if retry_after.isdigit() else float(2**attempt)


def _parse(title: str, data: Mapping[str, Any]) -> Article:
    [page] = data["query"]["pages"]
    if page.get("missing"):
        raise WikipediaError(f"no Wikipedia article titled {title!r}")
    if page.get("redirect"):
        raise WikipediaError(f"{title!r} is a redirect; use the target title in breeds.yaml")
    if "disambiguation" in page.get("pageprops", {}):
        raise WikipediaError(f"{title!r} is a disambiguation page")
    text = page.get("extract", "").strip()
    if not text:
        raise WikipediaError(f"{title!r} returned no article text")
    [revision] = page["revisions"]
    return Article(
        title=page["title"],
        page_id=int(page["pageid"]),
        revision_id=int(revision["revid"]),
        revision_timestamp=str(revision["timestamp"]),
        text=text,
    )


def fetch_article(
    session: ApiSession, title: str, sleep: Callable[[float], None] = time.sleep
) -> Article:
    """One article, retrying when the API asks us to slow down."""
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = session.get(API_URL, params=_params(title), headers=headers, timeout=_TIMEOUT_S)
        if response.status_code == 429 or response.status_code >= 500:
            wait = _wait_seconds(response, attempt)
            log.warning("HTTP %d for %r, retrying in %.0f s", response.status_code, title, wait)
            sleep(wait)
            continue
        if response.status_code != 200:
            raise WikipediaError(f"HTTP {response.status_code} for {title!r}")
        data = response.json()
        error = data.get("error")
        if error and error.get("code") == "maxlag":
            wait = _wait_seconds(response, attempt)
            log.warning("servers lagged for %r, retrying in %.0f s", title, wait)
            sleep(wait)
            continue
        if error:
            raise WikipediaError(f"API error for {title!r}: {error.get('info', error)}")
        return _parse(title, data)
    raise WikipediaError(f"gave up on {title!r} after {MAX_ATTEMPTS} attempts")


def cache_path(cache_dir: Path, title: str) -> Path:
    return cache_dir / (re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") + ".json")


def load_cached(cache_dir: Path, title: str) -> Article | None:
    path = cache_path(cache_dir, title)
    if not path.exists():
        return None
    return Article(**json.loads(path.read_text(encoding="utf-8")))


def download_articles(
    titles: Iterable[str],
    cache_dir: Path,
    session: ApiSession,
    *,
    refresh: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Article]:
    """Title -> article. Cached articles are not requested again unless `refresh`."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    articles: dict[str, Article] = {}
    fetched = 0
    for title in dict.fromkeys(titles):  # unique, in order
        cached = None if refresh else load_cached(cache_dir, title)
        if cached is not None:
            articles[title] = cached
            continue
        if fetched:
            sleep(PAUSE_S)  # serial requests with a pause between them
        article = fetch_article(session, title, sleep=sleep)
        if article.title != title:
            raise WikipediaError(f"asked for {title!r}, got {article.title!r}")
        cache_path(cache_dir, title).write_text(
            json.dumps(asdict(article), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        articles[title] = article
        fetched += 1
    log.info(
        "%d articles (%d downloaded, %d cached)", len(articles), fetched, len(articles) - fetched
    )
    return articles


def main(argv: list[str] | None = None) -> None:
    from pipeline.breed_mapping import load_breed_list

    parser = argparse.ArgumentParser(description="Download the breed articles from Wikipedia.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--refresh", action="store_true", help="download cached articles again")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        import truststore
    except ImportError:  # pragma: no cover - truststore is optional
        pass
    else:
        truststore.inject_into_ssl()

    titles = [entry.wikipedia_title for entry in load_breed_list().values()]
    with requests.Session() as session:
        articles = download_articles(titles, args.cache_dir, session, refresh=args.refresh)
    words = sum(len(a.text.split()) for a in articles.values())
    log.info("%d words in total, cached in %s", words, args.cache_dir)


if __name__ == "__main__":
    main()
