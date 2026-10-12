"""Cached, checksummed downloads into data/raw/.

A file that is already on disk is not fetched again unless `force=True`. Every file's
URL, size and SHA-256 go into `data/raw/manifest.json`, which the data card reads.
"""

import hashlib
import json
import tarfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pipeline.sources import Source

MANIFEST_NAME = "manifest.json"
_CHUNK = 1 << 20
_TIMEOUT_S = 60


class MissingApiKeyError(RuntimeError):
    pass


class _Response(Protocol):
    def raise_for_status(self) -> None: ...
    def iter_content(self, chunk_size: int) -> Iterator[bytes]: ...


class HttpSession(Protocol):
    """The slice of requests.Session used here; tests pass a fake."""

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float, stream: bool
    ) -> _Response: ...


@dataclass(frozen=True)
class DownloadResult:
    source: Source
    path: Path
    sha256: str
    size_bytes: int
    cached: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_dir(archive: Path) -> Path:
    """`stanford/lists.tar` unpacks into `stanford/lists/`."""
    return archive.with_suffix("")


def _headers(source: Source, env: Mapping[str, str]) -> dict[str, str]:
    if source.api_key_env is None:
        return {}
    key = env.get(source.api_key_env, "").strip()
    if not key:
        raise MissingApiKeyError(f"{source.name} needs {source.api_key_env} (see .env.example)")
    return {"x-api-key": key}


def _extract(archive: Path) -> None:
    target = extract_dir(archive)
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        # filter="data" rejects absolute paths, links outside the target and device files.
        tar.extractall(target, filter="data")


def download(
    source: Source,
    raw_dir: Path,
    session: HttpSession,
    env: Mapping[str, str],
    *,
    force: bool = False,
) -> DownloadResult:
    dest = raw_dir / source.filename
    cached = dest.exists() and not force

    if not cached:
        headers = _headers(source, env)
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".part")
        try:
            response = session.get(source.url, headers=headers, timeout=_TIMEOUT_S, stream=True)
            response.raise_for_status()
            with partial.open("wb") as f:
                for chunk in response.iter_content(chunk_size=_CHUNK):
                    f.write(chunk)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        partial.replace(dest)

    if source.extract and (not cached or not extract_dir(dest).exists()):
        _extract(dest)

    return DownloadResult(
        source=source,
        path=dest,
        sha256=sha256_file(dest),
        size_bytes=dest.stat().st_size,
        cached=cached,
    )


def write_manifest(raw_dir: Path, results: Iterable[DownloadResult]) -> Path:
    """Merge results into the manifest, keeping the original download time of cached files."""
    path = raw_dir / MANIFEST_NAME
    manifest: dict[str, Any] = {}
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for r in results:
        previous = manifest.get(r.source.name, {})
        manifest[r.source.name] = {
            "url": r.source.url,
            "path": r.path.relative_to(raw_dir).as_posix(),
            "sha256": r.sha256,
            "size_bytes": r.size_bytes,
            "downloaded_at": previous.get("downloaded_at", now) if r.cached else now,
        }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
