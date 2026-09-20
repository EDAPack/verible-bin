# verible-bin: research findings and plan

Status: **implemented**, 2026-09-20. Written as a pre-repo draft the same day
and moved here when the repo was built out. The findings below are the
reasoning behind what now exists; they are kept as written rather than
rewritten into past tense, because the *research* is the durable part.

Phases 1 and 2 are done. Phase 3 (macOS x86_64) is deliberately not done.

Three things landed differently from the sketch below. Each is explained where
it comes up, and summarized here:

1. **Versioning** (Finding 4). The published tag is upstream's tag verbatim
   (`v0.0-4294-gc1d8f5e8`), not an edapack-specific scheme. The shared
   release-track gate asks GitHub whether `v<upstream-version>` is already
   published, so the tag is not ours to choose without forking that logic.
   *Cadence* is still ours — a monthly schedule, not upstream's several
   releases per week — which was the substance of the finding.
2. **Release notes.** The plan assumed there was nothing to say, since Verible
   ships no changelog. Checking that turned out to be worth it: upstream's
   release *bodies* are empty too (all 40 of them), so mirroring was never an
   option either — but two other sources exist. `release_notes: gh-compare`, a
   new mode in edapack-common, lists the pull requests merged since our last
   repack; and `scripts/release-notes-hook.sh` diffs the shipped lint rules and
   formatter flags against the previous release, so the notes say what changes
   for a *user* rather than what the project did. See README.md → Release
   notes.
3. **Windows.** `win64` is repacked on an x86_64 Linux runner. The shared
   workflow has no Windows runner, and rearranging a zip does not need one; the
   build still verifies all 11 `.exe` files survived, and logs that it could not
   smoke-test them.

Read alongside `README.md` (what the package is) and `scripts/build.sh` (how
the repack actually works).

Parked in `edapack/` at first, rather than in a tool repo, because it was
cross-cutting: it proposed changes to `ivpm` as well as a new tool repo.

## The question

Verible already publishes prebuilt binaries. Does `verible-bin` need to build
anything, or can it be a thin manifest that points consumers at the right
upstream release asset?

Short answer: **repack, don't build.** Download upstream assets in CI, inject
edapack metadata, republish. No compilers, no bazel. A pure metadata pointer
does not work today for four reasons, detailed below; three of them are cheap
to fix and one (macOS x86_64) is a genuine gap in what upstream ships.

## What upstream ships

Release `v0.0-4294-gc1d8f5e8`, published 2026-09-20 — five assets:

| Asset | Notes |
|---|---|
| `verible-<ver>-linux-static-x86_64.tar.gz` | 17.6 MB |
| `verible-<ver>-linux-static-arm64.tar.gz` | 16.0 MB |
| `verible-<ver>-macOS.tar.gz` | 8.0 MB, **arm64 only** |
| `verible-<ver>-win64.zip` | 6.9 MB |
| `verible-<ver>.tar.gz` | source |

Each binary tarball unpacks to `verible-<version>/bin/` holding 11 executables:
`verible-verilog-{lint,format,syntax,project,ls,diff,obfuscate,preprocessor,
kythe-extractor,kythe-kzip-writer}` and `verible-patch-tool`.

## Finding 1: the Linux static binaries cover every manylinux platform

Verified by downloading and inspecting the x86_64 and arm64 tarballs:

```
verible-verilog-lint: ELF 64-bit LSB executable, x86-64, statically linked,
                      for GNU/Linux 3.2.0, not stripped
ldd: not a dynamic executable
```

arm64 is the same, floor `GNU/Linux 3.7.0`.

- **No glibc dependency at all.** manylinux tags are glibc floors (manylinux1 =
  2.5, 2010 = 2.12, 2014 = 2.17, `_2_28` = 2.28). A fully static binary clears
  all of them vacuously. The only real floor is the kernel version, which is
  below anything in practice. It also runs on Alpine/musl, which manylinux
  wheels do not.
- **The static-glibc NSS trap does not apply.** The classic failure mode for
  statically linked glibc is a runtime `dlopen` of `libnss_*.so`, triggered by
  user/host lookups. `nm` shows no `getaddrinfo`, `getpwuid`, or `gethostby*`
  in the binary — the only `dlopen` symbols present are glibc's own internal
  stubs, unreferenced by Verible code. Verible does file I/O and stdio only
  (`verible-verilog-ls` speaks LSP over stdio, no sockets), so no code path
  reaches NSS.
- Smoke-tested on this machine: `verible-verilog-lint --version` and a lint run
  over a trivial `.sv` file both behave correctly, including exit codes.

**Conclusion: assuming the static Linux binary works on all manylinux platforms
is safe.** No per-distro or per-glibc build matrix is needed for Linux.

One caveat to keep in mind, not a blocker: statically linked glibc means no
loadable locale/iconv support beyond the builtin C locale. Irrelevant for a
linter/formatter operating on ASCII-ish SystemVerilog.

## Finding 2: ivpm's `gh-rls` heuristics mis-parse Verible's Linux asset names

`ivpm/src/ivpm/pkg_types/package_gh_rls.py`, `_parse_linux_generic` (~line 565)
matches:

```python
m = re.search(r"linux[_-]([a-z0-9_]+)", n)
```

Against `verible-v0.0-4294-gc1d8f5e8-linux-static-x86_64.tar.gz` this captures
**`static`**, not `x86_64`. It is not a recognized arch, so
`_select_linux_asset` returns `None`, `_has_binary_assets` reports false, and
ivpm silently falls back to downloading the **source** tarball. Both Linux
assets fail this way. macOS (`macos` token) and Windows (`win64` token) select
correctly.

The `file:` field on a `gh-rls` dep does accept fnmatch globs (it is a
pre-filter over asset names, see ~line 214), but it is a single fixed pattern,
not a per-platform selector — `*linux-static-x86_64*` would hardcode one arch,
and filtering to `*linux-static*` still leaves `_parse_linux_generic` capturing
`static`.

**Fix:** make the generic Linux parser scan for a known arch token anywhere
after `linux`, rather than assuming the arch is the immediately following
token. Roughly:

```python
m = re.search(r"linux[_-]([a-z0-9_.-]+)", n)
if m:
    for tok in re.split(r"[_.-]", m.group(1)):
        arch = _normalize(tok)   # x86_64/amd64/x64, aarch64/arm64, armv7*
        if arch: return arch
```

Worth doing regardless of the outcome here: `linux-<flavor>-<arch>` is a common
upstream naming convention, and today any project using it silently degrades to
a source download.

## Finding 3: the upstream tarball does not satisfy edapack's consumer contract

Per `edapack-common/README.md`, ivpm reads `packages/<name>/ivpm.yaml` for every
installed package; an `ivpm.yaml` *inside* the release tarball is what lets an
installed release prepend its `bin/` to `PATH`. Releases also carry a
`manifest.json` recording resolved inputs and an `inputs_digest` used as the
change-gate.

The upstream tarball has neither, and unpacks under a `verible-<version>/`
prefix rather than at the root.

Verible does need a consumer manifest — unlike `verilator-bin`, which
legitimately ships no `scripts/release-ivpm.yaml` because it needs nothing at
install time. Verible needs exactly one thing, PATH:

```yaml
# scripts/release-ivpm.yaml
package:
  name: verible-bin
  env:
  - name: PATH
    path-prepend: "${IVPM_PACKAGES}/verible-bin/bin"
```

That has to be injected into the tarball by something. Which means a repack
step, which means a repo with a workflow — not a passive pointer.

## Finding 4: versioning and cadence do not map onto edapack's release model

Verible publishes `v0.0-<commit-count>-g<sha>`. Observed cadence: 15 releases
between 2026-09-01 and 2026-09-20, five of them in the last four days. Every
one is flagged as a full release; none are prereleases. There is no semantic
version and no changelog file to slice for release notes.

edapack's release track (see `edapack-common/scripts/`) assumes
`latest-release` or `latest-tag:<regex>`, a stable `latest` pointing at a
tagged upstream release, and `release_notes:` naming an upstream changelog
whose section for the built version becomes the release body.

None of that applies. The sensible move is to **set our own cadence** — snapshot
the newest upstream release on a schedule (monthly, or weekly gated on
`inputs_digest`) rather than mirroring every merge. Version the edapack release
on our own scheme and record the upstream tag in `manifest.json`.

This is another argument against the passive-pointer model: a pointer inherits
upstream's cadence whether we want it or not.

## Finding 5: macOS x86_64 is a real gap

The upstream `macOS.tar.gz` is **arm64 only** — Mach-O `cputype 0x0100000c`, not
a universal binary, and carrying an `LC_CODE_SIGNATURE` load command (so
presumably ad-hoc signed; Gatekeeper quarantine on download is still worth
testing).

There is no Intel-Mac asset. If edapack wants macOS x86_64 coverage, that is the
one platform where building from source is unavoidable.

## Plan

### Phase 1 — ivpm fix (do first, independent of the repo)

- Fix `_parse_linux_generic` per Finding 2.
- Add a regression test covering `linux-static-x86_64` / `linux-static-arm64`
  alongside the existing protobuf-style `linux-x86_64` names.

### Phase 2 — `verible-bin` repo, repack-only

Platforms: **Linux x86_64, Linux arm64, Windows x64, macOS arm64.** All four
come straight from upstream assets.

- `build-inputs.yaml` — `core: {name: verible, repo:
  https://github.com/chipsalliance/verible, policy: latest-release}`. No
  dependencies. The resolver records which upstream release we mirrored;
  `inputs_digest` gates republishing when upstream has not moved.
- `scripts/release-ivpm.yaml` — the PATH-only manifest shown in Finding 3.
- Repack job per platform: download the upstream asset, strip the
  `verible-<version>/` prefix, inject `ivpm.yaml`, let
  `ec_finalize_release` / `gen-manifest.py` produce `manifest.json`, publish.
  No toolchain required, so this need not run in the manylinux images the
  other tool repos use — though staying on the shared
  `edapack-common/.github/workflows/build-release.yml` path is worth trying
  first for consistency, with a build step that is just "download and
  rearrange".
- Cadence: scheduled snapshot, change-gated on `inputs_digest`. Decide the
  interval when setting up CI; monthly is a reasonable starting point given
  upstream's several-per-week churn.
- Tests: run each of the 11 executables' `--version`, plus a lint and a format
  round-trip on a small `.sv` fixture. Cheap and catches a bad repack.

### Phase 3 — macOS x86_64, deferred

Ship without it. Revisit only if someone asks. This is the only piece that
requires an actual bazel build of Verible, and it should not hold up the other
four platforms.

## Alternative considered: no repo at all

Once Phase 1 lands, and *if* ivpm gains a way for a consumer to declare
`env`/`path-prepend` for a foreign package it does not own, consumers could
depend on `chipsalliance/verible` directly via `src: gh-rls` and `verible-bin`
would not need to exist.

That is the cleanest possible outcome and is worth keeping in view. What it
gives up: the `manifest.json` provenance record, control over cadence (you
inherit upstream's several-releases-per-week), and any place to put a macOS
x86_64 build later. Those are the same three things Phase 2 buys, so the
trade-off is explicit rather than incidental.

## Verification notes

Everything above was checked against the live release, not inferred:

- `file` / `ldd` / `nm` on the x86_64 and arm64 Linux binaries.
- Executed `verible-verilog-lint --version` and a lint run on x86_64 Linux.
- Mach-O header parse of the macOS binary for cputype and load commands.
- GitHub releases API for the asset list and the 15-release cadence sample.
- `_parse_linux_generic`'s regex replayed against all four asset names.
