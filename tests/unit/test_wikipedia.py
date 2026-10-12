"""Wikipedia downloader: parsing, refusals, backoff, caching, etiquette. No network."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pipeline.wikipedia import (
    MAXLAG_S,
    PAUSE_S,
    USER_AGENT,
    Article,
    WikipediaError,
    cache_path,
    download_articles,
    fetch_article,
)


def _page(title: str, **extra: Any) -> dict[str, Any]:
    page = {
        "pageid": 42,
        "title": title,
        "extract": f"The {title} is a dog breed.",
        "revisions": [{"revid": 1234, "timestamp": "2026-09-01T10:00:00Z"}],
    }
    return {"query": {"pages": [page | extra]}}


class FakeResponse:
    def __init__(self, body: Any, status_code: int = 200, headers: dict[str, str] | None = None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> Any:
        return self.body


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[Mapping[str, str | int], Mapping[str, str]]] = []

    def get(
        self,
        url: str,
        *,
        params: Any,
        headers: Mapping[str, str],
        timeout: float,
    ) -> FakeResponse:
        self.calls.append((params, headers))
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(_page(str(params["titles"])))


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_fetch_parses_article_and_sends_etiquette_headers() -> None:
    session = FakeSession()
    article = fetch_article(session, "Pug")

    assert article == Article("Pug", 42, 1234, "2026-09-01T10:00:00Z", "The Pug is a dog breed.")
    assert article.url == "https://en.wikipedia.org/wiki/Pug"
    assert article.permalink == "https://en.wikipedia.org/w/index.php?oldid=1234"
    [(params, headers)] = session.calls
    assert headers["User-Agent"] == USER_AGENT
    assert "https://github.com/" in USER_AGENT  # contact URL, not a personal email
    assert params["maxlag"] == MAXLAG_S
    assert params["titles"] == "Pug"


def test_url_encodes_titles() -> None:
    article = Article("St. Bernard (dog breed)", 1, 2, "t", "x")
    assert article.url == "https://en.wikipedia.org/wiki/St._Bernard_%28dog_breed%29"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"missing": True}, "no Wikipedia article"),
        ({"redirect": True}, "is a redirect"),
        ({"pageprops": {"disambiguation": ""}}, "disambiguation"),
        ({"extract": "  "}, "no article text"),
    ],
)
def test_unusable_pages_are_refused(extra: dict[str, Any], message: str) -> None:
    session = FakeSession(FakeResponse(_page("Boxer", **extra)))
    with pytest.raises(WikipediaError, match=message):
        fetch_article(session, "Boxer")


def test_maxlag_and_server_errors_back_off_then_succeed() -> None:
    session = FakeSession(
        FakeResponse({"error": {"code": "maxlag", "info": "lagged"}}, headers={"Retry-After": "5"}),
        FakeResponse({}, status_code=503),
        FakeResponse(_page("Pug")),
    )
    sleeps = Sleeps()
    assert fetch_article(session, "Pug", sleep=sleeps).title == "Pug"
    assert sleeps.calls == [5.0, 4.0]  # Retry-After first, then exponential backoff


def test_gives_up_after_repeated_429() -> None:
    session = FakeSession(*[FakeResponse({}, status_code=429) for _ in range(10)])
    with pytest.raises(WikipediaError, match="gave up"):
        fetch_article(session, "Pug", sleep=Sleeps())


def test_other_api_errors_raise() -> None:
    session = FakeSession(FakeResponse({"error": {"code": "badvalue", "info": "bad title"}}))
    with pytest.raises(WikipediaError, match="bad title"):
        fetch_article(session, "Pug")


def test_download_is_serial_cached_and_deduplicated(tmp_path: Path) -> None:
    session = FakeSession()
    sleeps = Sleeps()
    titles = ["Pug", "Poodle", "Poodle", "Beagle"]

    articles = download_articles(titles, tmp_path, session, sleep=sleeps)

    assert list(articles) == ["Pug", "Poodle", "Beagle"]
    assert [p["titles"] for p, _ in session.calls] == ["Pug", "Poodle", "Beagle"]
    assert sleeps.calls == [PAUSE_S, PAUSE_S]  # a pause between requests, not before the first
    assert cache_path(tmp_path, "Poodle").exists()

    again = download_articles(titles, tmp_path, FakeSession(*[]), sleep=sleeps)
    assert again == articles  # read from the cache

    refresh_session = FakeSession()
    download_articles(["Pug"], tmp_path, refresh_session, refresh=True, sleep=sleeps)
    assert len(refresh_session.calls) == 1


def test_title_mismatch_is_an_error(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(_page("Pug (dog)")))
    with pytest.raises(WikipediaError, match="got 'Pug \\(dog\\)'"):
        download_articles(["Pug"], tmp_path, session, sleep=Sleeps())


def test_cache_file_names_are_safe() -> None:
    path = cache_path(Path("c"), "English Toy Terrier (Black & Tan)")
    assert path == Path("c") / "English_Toy_Terrier_Black_Tan.json"
