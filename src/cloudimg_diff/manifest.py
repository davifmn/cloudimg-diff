"""Parse image manifests and compute the difference between two of them.

Ubuntu cloud images ship a ``.manifest`` file next to every image. Each line is
the output of ``dpkg-query -W``: a package name (optionally qualified with an
architecture, e.g. ``bind9-libs:amd64``) and a version separated by a tab.
Older images also list snaps as ``snap:<name>`` with the revision as version.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .debversion import compare

__all__ = [
    "Change",
    "ChangeKind",
    "Manifest",
    "ManifestDiff",
    "ManifestError",
    "Package",
    "diff_manifests",
    "parse_manifest",
]


class ManifestError(ValueError):
    """Raised when a manifest line cannot be parsed."""


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    arch: str | None = None
    kind: str = "deb"  # "deb" or "snap"

    @property
    def key(self) -> str:
        """Identity used to match the same package across two manifests."""
        prefix = "snap:" if self.kind == "snap" else ""
        suffix = f":{self.arch}" if self.arch else ""
        return f"{prefix}{self.name}{suffix}"


Manifest = Mapping[str, Package]


def parse_manifest(lines: Iterable[str], *, source: str = "<manifest>") -> dict[str, Package]:
    """Parse manifest lines into a mapping of package key -> Package."""
    packages: dict[str, Package] = {}
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ManifestError(f"{source}:{lineno}: expected '<package> <version>', got {raw!r}")
        name, version = parts[0], parts[1].strip()

        kind = "deb"
        arch: str | None = None
        if name.startswith("snap:"):
            kind, name = "snap", name[len("snap:") :]
        elif ":" in name:
            name, arch = name.split(":", 1)
        if not name:
            raise ManifestError(f"{source}:{lineno}: empty package name in {raw!r}")

        pkg = Package(name=name, version=version, arch=arch, kind=kind)
        if pkg.key in packages:
            raise ManifestError(f"{source}:{lineno}: duplicate entry for {pkg.key}")
        packages[pkg.key] = pkg
    return packages


class ChangeKind(str, enum.Enum):
    ADDED = "added"
    REMOVED = "removed"
    UPGRADED = "upgraded"
    DOWNGRADED = "downgraded"


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    key: str
    old: str | None
    new: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {"change": self.kind.value, "package": self.key, "old": self.old, "new": self.new}


@dataclass
class ManifestDiff:
    old_label: str
    new_label: str
    changes: list[Change] = field(default_factory=list)
    unchanged: int = 0
    # Counts of the unfiltered diff, so a filtered view still reports the full picture.
    totals: dict[str, int] | None = None

    def of_kind(self, kind: ChangeKind) -> list[Change]:
        return [c for c in self.changes if c.kind is kind]

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    def summary(self) -> dict[str, int]:
        if self.totals is not None:
            return dict(self.totals)
        counts = {kind.value: 0 for kind in ChangeKind}
        for change in self.changes:
            counts[change.kind.value] += 1
        counts["unchanged"] = self.unchanged
        return counts

    def filtered(self, kinds: Iterable[ChangeKind]) -> ManifestDiff:
        wanted = set(kinds)
        return ManifestDiff(
            old_label=self.old_label,
            new_label=self.new_label,
            changes=[c for c in self.changes if c.kind in wanted],
            unchanged=self.unchanged,
            totals=self.summary(),
        )


def _compare_versions(pkg_old: Package, pkg_new: Package) -> int:
    if pkg_old.kind == "snap":
        # Snap "versions" in manifests are store revisions: plain integers.
        try:
            old_rev, new_rev = int(pkg_old.version), int(pkg_new.version)
        except ValueError:
            old_s, new_s = pkg_old.version, pkg_new.version
            return (old_s > new_s) - (old_s < new_s)
        return (old_rev > new_rev) - (old_rev < new_rev)
    return compare(pkg_old.version, pkg_new.version)


def diff_manifests(
    old: Manifest, new: Manifest, *, old_label: str = "old", new_label: str = "new"
) -> ManifestDiff:
    """Compare two parsed manifests. Changes are sorted by package key."""
    result = ManifestDiff(old_label=old_label, new_label=new_label)
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        if before is None and after is not None:
            result.changes.append(Change(ChangeKind.ADDED, key, None, after.version))
        elif after is None and before is not None:
            result.changes.append(Change(ChangeKind.REMOVED, key, before.version, None))
        elif before is not None and after is not None:
            if before.version == after.version:
                result.unchanged += 1
                continue
            order = _compare_versions(before, after)
            if order == 0:
                # Textually different but equal for dpkg (e.g. "1.0" vs "1.0-0").
                result.unchanged += 1
                continue
            kind = ChangeKind.UPGRADED if order < 0 else ChangeKind.DOWNGRADED
            result.changes.append(Change(kind, key, before.version, after.version))
    return result
