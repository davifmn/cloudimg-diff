"""Output formats for a ManifestDiff: aligned text table, JSON and Markdown."""

from __future__ import annotations

import json

from .manifest import ChangeKind, ManifestDiff

_SYMBOL = {
    ChangeKind.ADDED: "+",
    ChangeKind.REMOVED: "-",
    ChangeKind.UPGRADED: "↑",
    ChangeKind.DOWNGRADED: "↓",
}


def _summary_line(diff: ManifestDiff) -> str:
    s = diff.summary()
    return (
        f"{s['upgraded']} upgraded, {s['downgraded']} downgraded, "
        f"{s['added']} added, {s['removed']} removed, {s['unchanged']} unchanged"
    )


def render_table(diff: ManifestDiff) -> str:
    lines = [f"{diff.old_label} -> {diff.new_label}: {_summary_line(diff)}"]
    if not diff.changes:
        return lines[0] + "\n"
    width_pkg = max(len(c.key) for c in diff.changes)
    width_old = max(len(c.old or "") for c in diff.changes)
    lines.append("")
    for change in diff.changes:
        lines.append(
            f"{_SYMBOL[change.kind]} {change.key:<{width_pkg}}  "
            f"{change.old or '':<{width_old}}  {change.new or ''}".rstrip()
        )
    return "\n".join(lines) + "\n"


def render_json(diff: ManifestDiff) -> str:
    payload = {
        "old": diff.old_label,
        "new": diff.new_label,
        "summary": diff.summary(),
        "changes": [c.to_dict() for c in diff.changes],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _md_cell(value: str | None) -> str:
    return f"`{value}`" if value else ""


def render_markdown(diff: ManifestDiff) -> str:
    out = [f"### `{diff.old_label}` → `{diff.new_label}`", "", _summary_line(diff), ""]
    for kind in ChangeKind:
        changes = diff.of_kind(kind)
        if not changes:
            continue
        out += [f"<details><summary>{kind.value} ({len(changes)})</summary>", ""]
        out += ["| Package | Old | New |", "|---|---|---|"]
        out += [f"| {c.key} | {_md_cell(c.old)} | {_md_cell(c.new)} |" for c in changes]
        out += ["", "</details>", ""]
    return "\n".join(out).rstrip() + "\n"


RENDERERS = {"table": render_table, "json": render_json, "markdown": render_markdown}
