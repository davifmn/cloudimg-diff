import random
import shutil
import subprocess
from pathlib import Path

import pytest

from cloudimg_diff.debversion import DebVersion, compare, compare_op

FIXTURES = Path(__file__).parent / "fixtures"

# (a, b, expected sign of compare(a, b)) — cases taken from Debian Policy 5.6.12
# and from real version strings found in Ubuntu cloud image manifests.
CASES = [
    ("1.0", "1.0", 0),
    ("1.0", "1.00", 0),
    ("1.0", "1.0-0", 0),
    ("0:1.0", "1.0", 0),
    ("1.0", "1.1", -1),
    ("1.0~rc1", "1.0", -1),
    ("1.0~~", "1.0~", -1),
    ("1.0~", "1.0", -1),
    ("1.0", "1.0+b1", -1),
    ("1.0", "1.0.0", -1),
    ("1.0", "1.0a", -1),
    ("1.0a", "1.0.0", -1),
    ("1:0.1", "2.0", 1),
    ("1.0-1", "1.0-1ubuntu1", -1),
    ("1.0-1ubuntu1", "1.0-2", -1),
    ("2.8.3", "2.7.14build2", 1),
    ("4.0.1really4.0.1-0ubuntu0.24.04.3", "4.0.1really4.0.1-0ubuntu0.24.04.9", -1),
    ("1:9.18.28-0ubuntu0.24.04.1", "1:9.18.39-0ubuntu0.24.04.7", -1),
    ("20260601~24.04.1", "20260601", -1),
    ("2.77.1+ubuntu24.04", "2.77.1~ubuntu24.04", 1),
    ("10", "9", 1),
    ("1.0-10", "1.0-9", 1),
]


@pytest.mark.parametrize(("a", "b", "expected"), CASES)
def test_compare_known_cases(a, b, expected):
    assert compare(a, b) == expected
    assert compare(b, a) == -expected


def test_parse_fields():
    v = DebVersion.parse("1:2.0~rc1-3ubuntu0.1")
    assert (v.epoch, v.upstream, v.revision) == (1, "2.0~rc1", "3ubuntu0.1")
    assert str(v) == "1:2.0~rc1-3ubuntu0.1"


def test_revision_is_split_on_last_hyphen():
    v = DebVersion.parse("1.2-beta-4")
    assert (v.upstream, v.revision) == ("1.2-beta", "4")


@pytest.mark.parametrize("bad", ["", "   ", "a:1.0", "1.0 1", "-1", "1.0-", ":1.0"])
def test_parse_rejects_invalid(bad):
    with pytest.raises(ValueError):
        DebVersion.parse(bad)


def test_equal_versions_hash_alike():
    assert len({DebVersion.parse(v) for v in ["1.0", "1.00", "0:1.0", "1.0-0", "1."]}) == 1


def test_sorting():
    versions = ["1.0", "1.0~rc1", "1:0.5", "1.0-1", "0.9", "1.0+b1"]
    ordered = sorted(versions, key=DebVersion.parse)
    assert ordered == ["0.9", "1.0~rc1", "1.0", "1.0-1", "1.0+b1", "1:0.5"]


@pytest.mark.parametrize(
    ("op", "expected"),
    [("lt", True), ("<<", True), ("le", True), ("eq", False), ("ne", True), ("gt", False)],
)
def test_compare_op(op, expected):
    assert compare_op("1.0~rc1", op, "1.0") is expected


def test_compare_op_rejects_unknown_operator():
    with pytest.raises(ValueError, match="unknown operator"):
        compare_op("1", "lessthan", "2")


def _versions_from_fixtures() -> list[str]:
    versions = set()
    for manifest in FIXTURES.glob("*.manifest"):
        for line in manifest.read_text().splitlines():
            if "\t" in line:
                versions.add(line.split("\t", 1)[1])
    return sorted(versions)


def _random_version(rng: random.Random) -> str:
    alphabet = "0123456789" * 3 + "abz.+~"
    upstream = rng.choice("0123456789") + "".join(
        rng.choice(alphabet) for _ in range(rng.randint(0, 6))
    )
    version = upstream
    if rng.random() < 0.3:
        version = f"{rng.randint(0, 3)}:{version}"
    if rng.random() < 0.5:
        version += "-" + "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 5)))
    return version


@pytest.mark.skipif(shutil.which("dpkg") is None, reason="needs dpkg (runs in CI on Ubuntu)")
def test_matches_dpkg_compare_versions():
    """Cross-check against the real dpkg on hundreds of real and random version pairs."""
    rng = random.Random(1234)
    real = _versions_from_fixtures()
    pairs = [(rng.choice(real), rng.choice(real)) for _ in range(150)]
    pairs += [(_random_version(rng), _random_version(rng)) for _ in range(150)]
    pairs += [(a, b) for a, b, _ in CASES]

    mismatches = []
    for a, b in pairs:
        dpkg_lt = subprocess.run(["dpkg", "--compare-versions", a, "lt", b]).returncode == 0
        dpkg_eq = subprocess.run(["dpkg", "--compare-versions", a, "eq", b]).returncode == 0
        ours = compare(a, b)
        if (ours < 0) != dpkg_lt or (ours == 0) != dpkg_eq:
            mismatches.append((a, b, ours, dpkg_lt, dpkg_eq))
    assert not mismatches, mismatches[:10]
