import json
from pathlib import Path

import pytest

from cloudimg_diff import cli
from cloudimg_diff.remote import ImageServer, RemoteError

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://images.test/releases"

INDEX = """
<a href="?C=N;O=D">Name</a>
<a href="release-20241004/">release-20241004/</a>
<a href="release-20260926/">release-20260926/</a>
<a href="release-20240523.1/">release-20240523.1/</a>
<a href="release-20261017/">release-20261017/</a>
"""


def folder(serial: str) -> str:
    return (
        f'<a href="ubuntu-24.04-server-cloudimg-arm64.manifest">x</a>'
        f'<a href="ubuntu-24.04-server-cloudimg-amd64.manifest">x</a>'
        f'<a href="ubuntu-24.04-server-cloudimg-amd64.img">x</a><!-- {serial} -->'
    )


class FakeWeb:
    """In-memory stand-in for cloud-images.ubuntu.com that records requests."""

    def __init__(self):
        self.requests: list[str] = []
        self.pages = {f"{BASE}/noble/": INDEX.encode()}
        for serial in ["20241004", "20260926", "20261017"]:
            prefix = f"{BASE}/noble/release-{serial}/"
            self.pages[prefix] = folder(serial).encode()
            manifest = (FIXTURES / f"noble-{serial}-amd64.manifest").read_bytes()
            self.pages[prefix + "ubuntu-24.04-server-cloudimg-amd64.manifest"] = manifest

    def __call__(self, url: str) -> bytes:
        self.requests.append(url)
        try:
            return self.pages[url]
        except KeyError:
            raise RemoteError(f"{url}: HTTP 404 Not Found") from None


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def server(web, tmp_path):
    return ImageServer(BASE, fetch=web, cache_dir=tmp_path)


def test_serials_are_sorted_including_respins(server):
    assert server.serials("noble") == ["20240523.1", "20241004", "20260926", "20261017"]


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("latest", "20261017"),
        ("previous", "20260926"),
        ("latest~2", "20241004"),
        ("20240101", "20240101"),
    ],
)
def test_resolve_aliases(server, alias, expected):
    assert server.resolve("noble", alias) == expected


def test_resolve_out_of_range(server):
    with pytest.raises(RemoteError, match="only has 4"):
        server.resolve("noble", "latest~9")


def test_manifest_is_cached_after_first_download(server, web, tmp_path):
    first = server.manifest_text("noble", "20261017")
    downloads = len(web.requests)
    second = server.manifest_text("noble", "20261017")
    assert first == second
    assert len(web.requests) == downloads  # served from cache
    assert (tmp_path / "noble" / "20261017" / "amd64.manifest").is_file()


def test_missing_architecture(server):
    with pytest.raises(RemoteError, match="no riscv64 manifest"):
        server.manifest_text("noble", "20261017", arch="riscv64")


@pytest.mark.parametrize("release", ["../etc", "Noble", "24.4", ""])
def test_rejects_suspicious_release_names(server, release):
    with pytest.raises(RemoteError, match="invalid release"):
        server.serials(release)


def test_html_instead_of_manifest_is_an_error(web, tmp_path):
    url = f"{BASE}/noble/release-20261017/ubuntu-24.04-server-cloudimg-amd64.manifest"
    web.pages[url] = b"<html><body>302 Found</body></html>"
    server = ImageServer(BASE, fetch=web, cache_dir=tmp_path)
    with pytest.raises(RemoteError, match="HTML"):
        server.manifest_text("noble", "20261017")


@pytest.fixture
def patched_cli(monkeypatch, web, tmp_path):
    monkeypatch.setattr(
        cli, "_server", lambda args: ImageServer(BASE, fetch=web, cache_dir=tmp_path)
    )


def test_cli_diff_json(patched_cli, capsys):
    code = cli.main(["diff", "noble", "previous", "latest", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["old"] == "noble/20260926"
    assert payload["new"] == "noble/20261017"
    assert sum(payload["summary"].values()) >= 664


def test_cli_exit_code_reports_differences(patched_cli, capsys):
    assert cli.main(["diff", "noble", "20241004", "20261017", "--exit-code"]) == 1
    out = capsys.readouterr().out
    assert "apt" in out and "2.7.14build2" in out


def test_cli_only_filter_and_markdown(patched_cli, capsys):
    cli.main(["diff", "noble", "20241004", "20261017", "--only", "added", "-f", "markdown"])
    out = capsys.readouterr().out
    assert "added (" in out
    assert "upgraded (" not in out


def test_cli_files(capsys):
    old = FIXTURES / "noble-20241004-amd64.manifest"
    new = FIXTURES / "noble-20261017-amd64.manifest"
    assert cli.main(["files", str(old), str(new)]) == 0
    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line.startswith("noble-20241004-amd64.manifest -> noble-20261017-amd64.manifest")


def test_cli_drift_uses_local_packages(patched_cli, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "local_manifest_lines", lambda: ["apt\t2.9.0", "nginx\t1.24.0-2ubuntu7"]
    )
    cli.main(["drift", "noble", "latest", "--only", "added", "--only", "upgraded"])
    out = capsys.readouterr().out
    assert "nginx" in out and "apt" in out


@pytest.mark.parametrize(("args", "code"), [(["1.0", "lt", "1.1"], 0), (["1.0", "gt", "1.1"], 1)])
def test_cli_compare_versions(args, code):
    assert cli.main(["compare-versions", *args]) == code


def test_cli_reports_errors_without_traceback(capsys, tmp_path):
    bad = tmp_path / "bad.manifest"
    bad.write_text("no-version-here\n")
    assert cli.main(["files", str(bad), str(bad)]) == 2
    assert "error" in capsys.readouterr().err
