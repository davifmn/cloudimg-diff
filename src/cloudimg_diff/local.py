"""Build a manifest from the machine we are running on, for drift detection."""

from __future__ import annotations

import shutil
import subprocess

# Same columns the image build uses, so the result can be diffed directly.
DPKG_QUERY_FORMAT = r"${binary:Package}\t${Version}\t${db:Status-Abbrev}\n"


class LocalSystemError(RuntimeError):
    pass


def local_manifest_lines(dpkg_query: str | None = None) -> list[str]:
    """Return ``package<TAB>version`` lines for every installed package."""
    binary = dpkg_query or shutil.which("dpkg-query")
    if not binary:
        raise LocalSystemError("dpkg-query not found: drift detection needs a Debian/Ubuntu system")
    try:
        proc = subprocess.run(
            [binary, "-W", f"-f={DPKG_QUERY_FORMAT}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise LocalSystemError(f"dpkg-query failed: {exc.stderr.strip()}") from exc

    lines = []
    for row in proc.stdout.splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        name, version, status = parts
        # "ii " = desired install, currently installed. Skip removed-but-configured ("rc").
        if status.startswith("ii") and version:
            lines.append(f"{name}\t{version}")
    return lines
