"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .debversion import compare_op
from .local import LocalSystemError, local_manifest_lines
from .manifest import ChangeKind, ManifestError, diff_manifests, parse_manifest
from .remote import ImageServer, RemoteError
from .render import RENDERERS

EXIT_OK, EXIT_DIFF, EXIT_ERROR = 0, 1, 2


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f", "--format", choices=sorted(RENDERERS), default="table", help="output format"
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=[k.value for k in ChangeKind],
        help="show only this kind of change (repeatable)",
    )
    parser.add_argument(
        "--exit-code",
        action="store_true",
        help="exit with status 1 when there are differences (like diff(1))",
    )


def _add_remote_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-a", "--arch", default="amd64", help="image architecture (default: amd64)")
    parser.add_argument("--no-cache", action="store_true", help="always download manifests")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cloudimg-diff",
        description="Compare the package manifests of Ubuntu cloud image builds.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serials = sub.add_parser("serials", help="list published release serials")
    p_serials.add_argument("release", help="codename or version, e.g. noble or 24.04")
    p_serials.add_argument("-n", "--limit", type=int, default=10, help="show the N newest")

    p_diff = sub.add_parser("diff", help="diff two published image builds")
    p_diff.add_argument("release", help="codename or version, e.g. noble or 24.04")
    p_diff.add_argument("old", nargs="?", default="previous", help="serial or alias (previous)")
    p_diff.add_argument("new", nargs="?", default="latest", help="serial or alias (latest)")
    _add_remote_options(p_diff)
    _add_output_options(p_diff)

    p_files = sub.add_parser("files", help="diff two local manifest files")
    p_files.add_argument("old", type=Path)
    p_files.add_argument("new", type=Path)
    _add_output_options(p_files)

    p_drift = sub.add_parser(
        "drift", help="compare this machine's installed packages with the image it came from"
    )
    p_drift.add_argument("release", help="codename or version, e.g. noble or 24.04")
    p_drift.add_argument("serial", nargs="?", default="latest", help="image serial (latest)")
    _add_remote_options(p_drift)
    _add_output_options(p_drift)

    p_cmp = sub.add_parser(
        "compare-versions", help="compare two Debian versions, like dpkg --compare-versions"
    )
    p_cmp.add_argument("a")
    p_cmp.add_argument("op", help="lt le eq ne ge gt << <= = >= >>")
    p_cmp.add_argument("b")
    return parser


def _emit(diff, args: argparse.Namespace) -> int:
    if args.only:
        diff = diff.filtered(ChangeKind(k) for k in args.only)
    sys.stdout.write(RENDERERS[args.format](diff))
    return EXIT_DIFF if (args.exit_code and diff.has_changes) else EXIT_OK


def _server(args: argparse.Namespace) -> ImageServer:
    return ImageServer(use_cache=not getattr(args, "no_cache", False))


def run(args: argparse.Namespace) -> int:
    if args.command == "compare-versions":
        return EXIT_OK if compare_op(args.a, args.op, args.b) else EXIT_DIFF

    if args.command == "files":
        old = parse_manifest(
            args.old.read_text(encoding="utf-8").splitlines(), source=str(args.old)
        )
        new = parse_manifest(
            args.new.read_text(encoding="utf-8").splitlines(), source=str(args.new)
        )
        return _emit(
            diff_manifests(old, new, old_label=args.old.name, new_label=args.new.name), args
        )

    server = _server(args)
    if args.command == "serials":
        for serial in server.serials(args.release)[-args.limit :]:
            print(serial)
        return EXIT_OK

    if args.command == "diff":
        old_serial = server.resolve(args.release, args.old)
        new_serial = server.resolve(args.release, args.new)
        old = parse_manifest(server.manifest_text(args.release, old_serial, args.arch).splitlines())
        new = parse_manifest(server.manifest_text(args.release, new_serial, args.arch).splitlines())
        diff = diff_manifests(
            old,
            new,
            old_label=f"{args.release}/{old_serial}",
            new_label=f"{args.release}/{new_serial}",
        )
        return _emit(diff, args)

    if args.command == "drift":
        serial = server.resolve(args.release, args.serial)
        image = parse_manifest(server.manifest_text(args.release, serial, args.arch).splitlines())
        here = parse_manifest(local_manifest_lines(), source="dpkg-query")
        diff = diff_manifests(
            image, here, old_label=f"image {args.release}/{serial}", new_label="this machine"
        )
        return _emit(diff, args)

    raise AssertionError(f"unhandled command {args.command}")  # pragma: no cover


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (RemoteError, ManifestError, LocalSystemError, ValueError, OSError) as exc:
        print(f"cloudimg-diff: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover
        return 130
