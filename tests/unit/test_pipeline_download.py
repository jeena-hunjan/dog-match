"""Download caching, API keys, manifest and tar extraction. No network: the session is fake."""

import hashlib
import io
import json
import tarfile
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from pipeline.download import MissingApiKeyError, download, extract_dir, write_manifest
from pipeline.sources import BREED_SOURCES, Source

CSV = Source(name="csv", url="https://example.test/a.csv", filename="akc/a.csv")
KEYED = Source(name="keyed", url="https://example.test/b.json", filename="b.json", api_key_env="K")
TAR = Source(name="tar", url="https://example.test/c.tar", filename="s/c.tar", extract=True)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i : i + chunk_size]


class FakeSession:
    def __init__(self, body: bytes = b"breed,score\nbeagle,3\n", status: int = 200) -> None:
        self.body = body
        self.status = status
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float, stream: bool
    ) -> FakeResponse:
        self.calls.append((url, dict(headers)))
        return FakeResponse(self.body, self.status)


def _tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_downloads_file_with_checksum(tmp_path: Path) -> None:
    session = FakeSession()
    result = download(CSV, tmp_path, session, env={})

    assert result.path.read_bytes() == session.body
    assert result.sha256 == hashlib.sha256(session.body).hexdigest()
    assert result.size_bytes == len(session.body)
    assert not result.cached
    assert not list(tmp_path.rglob("*.part"))


def test_cached_file_is_not_fetched_again(tmp_path: Path) -> None:
    download(CSV, tmp_path, FakeSession(), env={})
    session = FakeSession(body=b"new")

    result = download(CSV, tmp_path, session, env={})

    assert result.cached
    assert session.calls == []
    assert result.path.read_bytes() != b"new"


def test_force_refetches(tmp_path: Path) -> None:
    download(CSV, tmp_path, FakeSession(), env={})

    result = download(CSV, tmp_path, FakeSession(body=b"new"), env={}, force=True)

    assert not result.cached
    assert result.path.read_bytes() == b"new"


def test_api_key_is_sent_as_header(tmp_path: Path) -> None:
    session = FakeSession()
    download(KEYED, tmp_path, session, env={"K": "secret"})

    assert session.calls == [(KEYED.url, {"x-api-key": "secret"})]


def test_missing_api_key_fails_before_any_request(tmp_path: Path) -> None:
    session = FakeSession()
    with pytest.raises(MissingApiKeyError, match="K"):
        download(KEYED, tmp_path, session, env={"K": "  "})
    assert session.calls == []


def test_http_error_leaves_no_partial_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="HTTP 500"):
        download(CSV, tmp_path, FakeSession(status=500), env={})
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_tar_is_extracted_next_to_archive(tmp_path: Path) -> None:
    body = _tar_bytes({"train_list.mat": b"x", "test_list.mat": b"y"})
    download(TAR, tmp_path, FakeSession(body=body), env={})

    assert (tmp_path / "s" / "c" / "train_list.mat").read_bytes() == b"x"
    assert (tmp_path / "s" / "c" / "test_list.mat").read_bytes() == b"y"


def test_tar_with_path_traversal_is_rejected(tmp_path: Path) -> None:
    body = _tar_bytes({"../escape.txt": b"x"})
    with pytest.raises(tarfile.TarError):
        download(TAR, tmp_path, FakeSession(body=body), env={})
    assert not (tmp_path / "s" / "escape.txt").exists()
    # The failed extraction leaves neither a finished-looking folder nor a temporary one.
    assert not (tmp_path / "s" / "c").exists()
    assert not (tmp_path / "s" / "c.partial").exists()


@pytest.mark.parametrize(
    ("archive", "folder"),
    [("a/lists.tar", "a/lists"), ("a/images.tar.gz", "a/images"), ("a/x.tgz", "a/x")],
)
def test_extract_dir_strips_archive_suffix(archive: str, folder: str) -> None:
    assert extract_dir(Path(archive)) == Path(folder)


def test_extract_dir_rejects_non_archives() -> None:
    with pytest.raises(ValueError, match="not a tar archive"):
        extract_dir(Path("a/b.zip"))


def test_forced_download_replaces_stale_extraction(tmp_path: Path) -> None:
    download(TAR, tmp_path, FakeSession(body=_tar_bytes({"old.txt": b"x"})), env={})
    new = _tar_bytes({"new.txt": b"y"})
    download(TAR, tmp_path, FakeSession(body=new), env={}, force=True)

    assert sorted(p.name for p in (tmp_path / "s" / "c").iterdir()) == ["new.txt"]


def test_manifest_keeps_first_download_time_for_cached_files(tmp_path: Path) -> None:
    first = download(CSV, tmp_path, FakeSession(), env={})
    write_manifest(tmp_path, [first])
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["csv"]["downloaded_at"] = "2020-01-01T00:00:00+00:00"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    write_manifest(tmp_path, [download(CSV, tmp_path, FakeSession(), env={})])

    entry = json.loads((tmp_path / "manifest.json").read_text())["csv"]
    assert entry["downloaded_at"] == "2020-01-01T00:00:00+00:00"
    assert entry == entry | {"path": "akc/a.csv", "url": CSV.url, "sha256": first.sha256}


def test_breed_sources_have_unique_names_and_paths() -> None:
    assert len({s.name for s in BREED_SOURCES}) == len(BREED_SOURCES)
    assert len({s.filename for s in BREED_SOURCES}) == len(BREED_SOURCES)
    assert all(s.url.startswith(("https://", "http://")) for s in BREED_SOURCES)
