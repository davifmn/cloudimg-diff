"""Discover and download manifests from cloud-images.ubuntu.com.

Layout of the "release" stream::

    https://cloud-images.ubuntu.com/releases/<release>/
        release-20261017/
            ubuntu-24.04-server-cloudimg-amd64.manifest
            ...

``<release>`` can be a codename (``noble``) or a version (``24.04``). Builds that
are no longer current redirect to cloud-images-archive.ubuntu.com, which urllib
follows transparently.
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import __version__

BASE_URL = "https://cloud-images.ubuntu.com/releases"
USER_AGENT = f"cloudimg-diff/{__version__} (+https://github.com/davifmn/cloudimg-diff)"
TIMEOUT = 30

_SERIAL_RE = re.compile(r'href="release-([0-9]{8}(?:\.[0-9]+)?)/"')
_RELEASE_RE = re.compile(r"^[a-z]+$|^[0-9]{2}\.[0-9]{2}$")
_ARCH_RE = re.compile(r"^[a-z0-9]+$")

Fetcher = Callable[[str], bytes]


class RemoteError(RuntimeError):
    """Raised when the image server cannot be reached or returns unexpected data."""


def http_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RemoteError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RemoteError(f"{url}: {exc.reason}") from exc


def default_cache_dir() -> Path:
    # Inside a strict snap $HOME is per-revision; SNAP_USER_COMMON survives refreshes.
    if os.environ.get("SNAP_USER_COMMON"):
        return Path(os.environ["SNAP_USER_COMMON"]) / "cache"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "cloudimg-diff"


def _validate(release: str, arch: str) -> None:
    if not _RELEASE_RE.match(release):
        raise RemoteError(f"invalid release {release!r}: use a codename (noble) or version (24.04)")
    if not _ARCH_RE.match(arch):
        raise RemoteError(f"invalid architecture {arch!r}")


class ImageServer:
    """Thin client for the release stream, with an on-disk cache for manifests.

    A published manifest never changes, so cached copies are reused forever.
    Directory listings are always fetched fresh because new serials appear.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        fetch: Fetcher = http_fetch,
        cache_dir: Path | None = None,
        use_cache: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._fetch = fetch
        self.cache_dir = cache_dir or default_cache_dir()
        self.use_cache = use_cache

    def serials(self, release: str) -> list[str]:
        """Return the published release serials, oldest first."""
        _validate(release, "amd64")
        html = self._fetch(f"{self.base_url}/{release}/").decode("utf-8", "replace")
        found = sorted(set(_SERIAL_RE.findall(html)), key=_serial_sort_key)
        if not found:
            raise RemoteError(f"no release serials found for {release!r}")
        return found

    def resolve(self, release: str, serial: str) -> str:
        """Turn ``latest``/``previous``/``latest~N`` into a concrete serial."""
        serial = serial.removeprefix("release-")
        alias = serial.lower()
        if alias not in {"latest", "previous"} and not alias.startswith("latest~"):
            return serial
        available = self.serials(release)
        if alias == "latest":
            offset = 0
        elif alias == "previous":
            offset = 1
        else:
            try:
                offset = int(alias.split("~", 1)[1])
            except ValueError:
                raise RemoteError(f"invalid serial alias {serial!r}") from None
        if offset >= len(available):
            raise RemoteError(f"{release} only has {len(available)} published serials")
        return available[-1 - offset]

    def manifest_url(self, release: str, serial: str, arch: str) -> str:
        _validate(release, arch)
        folder = f"{self.base_url}/{release}/release-{serial}/"
        html = self._fetch(folder).decode("utf-8", "replace")
        pattern = re.compile(
            rf'href="(ubuntu-[0-9.]+-server-cloudimg-{re.escape(arch)}\.manifest)"'
        )
        match = pattern.search(html)
        if not match:
            raise RemoteError(f"no {arch} manifest in {folder}")
        return folder + match.group(1)

    def manifest_text(self, release: str, serial: str, arch: str = "amd64") -> str:
        cache_file = self.cache_dir / release / serial / f"{arch}.manifest"
        if self.use_cache and cache_file.is_file():
            return cache_file.read_text(encoding="utf-8")

        url = self.manifest_url(release, serial, arch)
        body = self._fetch(url)
        text = body.decode("utf-8")
        if "<html" in text[:500].lower():
            raise RemoteError(f"{url}: expected a manifest, got an HTML page")

        if self.use_cache:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(f".tmp-{hashlib.sha256(body).hexdigest()[:8]}")
            tmp.write_bytes(body)
            tmp.replace(cache_file)  # atomic, so a crash never leaves half a file
        return text


def _serial_sort_key(serial: str) -> tuple[int, int]:
    date, _, respin = serial.partition(".")
    return int(date), int(respin or 0)
