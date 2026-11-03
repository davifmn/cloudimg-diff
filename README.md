# cloudimg-diff

[![CI](https://github.com/davifmn/cloudimg-diff/actions/workflows/ci.yml/badge.svg)](https://github.com/davifmn/cloudimg-diff/actions/workflows/ci.yml)

Compare the package manifests of Ubuntu cloud image builds.

Every image on [cloud-images.ubuntu.com](https://cloud-images.ubuntu.com/) is published with a
`.manifest` listing the Debian packages inside it. `cloudimg-diff` fetches those manifests
and tells you what changed between two builds: which packages were upgraded, downgraded,
added or removed. It can also compare the machine you are logged into with the image it
was launched from.

```console
$ cloudimg-diff diff noble 20260926 20261017
noble/20260926 -> noble/20261017: 55 upgraded, 0 downgraded, 6 added, 6 removed, 603 unchanged

↑ apparmor                         4.0.1really4.0.1-0ubuntu0.24.04.8  4.0.1really4.0.1-0ubuntu0.24.04.9
↑ bind9-dnsutils                   1:9.18.39-0ubuntu0.24.04.7         1:9.18.39-0ubuntu0.24.04.8
↑ bind9-host                       1:9.18.39-0ubuntu0.24.04.7         1:9.18.39-0ubuntu0.24.04.8
↑ bind9-libs:amd64                 1:9.18.39-0ubuntu0.24.04.7         1:9.18.39-0ubuntu0.24.04.8
↑ curl                             8.5.0-2ubuntu10.15                 8.5.0-2ubuntu10.16
↑ dracut-install                   060+5-1ubuntu3.3                   060+5-1ubuntu3.4
...
```

Typical uses:

- **Before rolling a fleet onto a new image:** see exactly which packages move.
- **Release notes / PRs:** `--format markdown` output can be pasted into a pull request
  that bumps the image serial in your infrastructure code.
- **CI gates:** `--exit-code` returns 1 when the manifests differ, like `diff(1)`.
- **Drift detection:** `cloudimg-diff drift noble` shows what was installed or upgraded on
  a running instance since the image was built.

## Install

From the `.deb` or `.snap` built by CI (see the
[Actions artifacts](https://github.com/davifmn/cloudimg-diff/actions)):

```sh
sudo apt install ./cloudimg-diff_0.1.0_all.deb
# or
sudo snap install --dangerous ./cloudimg-diff_0.1.0_amd64.snap
```

From source (Python 3.10+, no third-party dependencies):

```sh
pip install .
```

## Usage

```sh
cloudimg-diff serials noble                    # newest release serials
cloudimg-diff diff noble                       # previous -> latest
cloudimg-diff diff 24.04 20241004 latest~1     # any two serials or aliases
cloudimg-diff diff noble --only upgraded -f json
cloudimg-diff diff noble -a arm64 -f markdown
cloudimg-diff files old.manifest new.manifest  # two files on disk
cloudimg-diff drift noble --only added         # this machine vs. its image
cloudimg-diff compare-versions 1.0~rc1 lt 1.0  # exit status like dpkg
```

Serial aliases: `latest`, `previous`, `latest~N`. Downloaded manifests are cached in
`$XDG_CACHE_HOME/cloudimg-diff` (published manifests never change); use `--no-cache` to skip it.
`man cloudimg-diff` has the full reference.

## How it works

- **Version ordering:** `cloudimg_diff/debversion.py` is a pure-Python port of dpkg's
  `verrevcmp` (Debian Policy §5.6.12): epochs, `~` sorting before the empty string,
  digit runs compared numerically, and `1.0` == `1.00` == `1.0-0`. CI cross-checks it
  against the real `dpkg --compare-versions` on a few hundred real and randomly generated
  version pairs.
- **Multi-arch:** packages such as `bind9-libs:amd64` keep their architecture qualifier,
  so `foo:amd64` and `foo:i386` are tracked separately.
- **Discovery:** serials and manifest file names are read from the server's directory
  listing, so codenames and version numbers both work. Builds that have moved to
  `cloud-images-archive.ubuntu.com` are followed through the redirect.
- **Drift:** `dpkg-query -W` with the same `${binary:Package}\t${Version}` columns the
  image build uses, so the two lists can be diffed directly.

## Packaging

| Path | What it is |
|---|---|
| `debian/` | Native Debian source package built with `debhelper` 13 + `dh-python`/pybuild, with an autopkgtest smoke test in `debian/tests/`. |
| `snap/snapcraft.yaml` | Strictly confined `core24` snap (`network` + `home` plugs). |
| `man/cloudimg-diff.1` | Man page, installed by the `.deb`. |

Build the `.deb` locally on Ubuntu 24.04:

```sh
sudo apt install build-essential debhelper dh-python pybuild-plugin-pyproject \
    python3-all python3-setuptools python3-pytest lintian
dpkg-buildpackage -us -uc -b
lintian ../cloudimg-diff_*.changes
```

Build the snap: `snapcraft pack`.

The CI workflow (`.github/workflows/ci.yml`) runs the test suite on Python 3.10–3.13,
builds the `.deb`, runs lintian, installs the package and runs the smoke test, then builds,
installs and runs the snap.

## Development

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

The tests never touch the network: the image server is replaced by an in-memory fake
that serves real manifests saved in `tests/fixtures/`.

## License

MIT
