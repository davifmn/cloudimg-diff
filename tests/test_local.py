import stat

import pytest

from cloudimg_diff.local import LocalSystemError, local_manifest_lines


@pytest.fixture
def fake_dpkg_query(tmp_path):
    script = tmp_path / "dpkg-query"
    script.write_text(
        "#!/bin/sh\n"
        "printf 'apt\\t2.8.3\\tii \\n'\n"
        "printf 'bind9-libs:amd64\\t1:9.18.39-0ubuntu0.24.04.7\\tii \\n'\n"
        "printf 'oldpkg\\t1.0\\trc \\n'\n"
        "printf 'garbage line\\n'\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_only_installed_packages_are_listed(fake_dpkg_query):
    assert local_manifest_lines(fake_dpkg_query) == [
        "apt\t2.8.3",
        "bind9-libs:amd64\t1:9.18.39-0ubuntu0.24.04.7",
    ]


def test_missing_dpkg_query(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(LocalSystemError, match="dpkg-query not found"):
        local_manifest_lines()
