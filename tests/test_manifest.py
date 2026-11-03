from pathlib import Path

import pytest

from cloudimg_diff.manifest import ChangeKind, ManifestError, diff_manifests, parse_manifest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return parse_manifest((FIXTURES / name).read_text().splitlines(), source=name)


def test_parse_real_manifest():
    manifest = load("noble-20261017-amd64.manifest")
    assert len(manifest) == 664
    assert manifest["apt"].version == "2.8.3"
    libs = manifest["bind9-libs:amd64"]
    assert (libs.name, libs.arch) == ("bind9-libs", "amd64")


def test_parse_snap_and_comments():
    manifest = parse_manifest(["# comment", "", "snap:lxd\t29351", "vim\t2:9.1.0016-1ubuntu7"])
    assert manifest["snap:lxd"].kind == "snap"
    assert manifest["snap:lxd"].name == "lxd"
    assert manifest["vim"].version == "2:9.1.0016-1ubuntu7"


@pytest.mark.parametrize("line", ["onlyname", ":\t1.0"])
def test_parse_rejects_malformed_lines(line):
    with pytest.raises(ManifestError):
        parse_manifest([line])


def test_parse_rejects_duplicates():
    with pytest.raises(ManifestError, match="duplicate"):
        parse_manifest(["apt\t2.8.3", "apt\t2.8.4"])


def test_diff_classifies_every_kind():
    old = parse_manifest(["a\t1.0", "b\t2.0", "c\t1.0", "d\t1.0", "e\t1.0", "snap:core\t100"])
    new = parse_manifest(["a\t1.0", "b\t2.1", "c\t0.9", "f\t1.0", "e\t1.0-0", "snap:core\t98"])
    diff = diff_manifests(old, new)
    by_key = {c.key: c.kind for c in diff.changes}
    assert by_key == {
        "b": ChangeKind.UPGRADED,
        "c": ChangeKind.DOWNGRADED,
        "d": ChangeKind.REMOVED,
        "f": ChangeKind.ADDED,
        "snap:core": ChangeKind.DOWNGRADED,
    }
    # "1.0" -> "1.0-0" is the same version for dpkg, so it is not a change.
    assert diff.unchanged == 2
    assert diff.summary() == {
        "added": 1,
        "removed": 1,
        "upgraded": 1,
        "downgraded": 2,
        "unchanged": 2,
    }


def test_diff_between_real_builds():
    diff = diff_manifests(
        load("noble-20241004-amd64.manifest"), load("noble-20261017-amd64.manifest")
    )
    upgraded = {c.key: (c.old, c.new) for c in diff.of_kind(ChangeKind.UPGRADED)}
    assert upgraded["apt"] == ("2.7.14build2", "2.8.3")
    assert not diff.of_kind(ChangeKind.DOWNGRADED)
    assert diff.has_changes


def test_identical_manifests_have_no_changes():
    manifest = load("noble-20261017-amd64.manifest")
    diff = diff_manifests(manifest, manifest)
    assert not diff.has_changes
    assert diff.unchanged == 664


def test_filtered_keeps_only_requested_kinds():
    diff = diff_manifests(parse_manifest(["a\t1", "b\t1"]), parse_manifest(["a\t2", "c\t1"]))
    only_added = diff.filtered([ChangeKind.ADDED])
    assert [c.key for c in only_added.changes] == ["c"]
    # The summary still describes the whole diff, not just the filtered rows.
    assert only_added.summary() == diff.summary()
    assert only_added.summary()["upgraded"] == 1
