# verible-bin

[Verible](https://github.com/chipsalliance/verible) — the CHIPS Alliance
SystemVerilog style linter, formatter, parser and language server — packaged
for [edapack](https://edapack.github.io).

Eleven executables per release:

```
verible-verilog-lint        verible-verilog-format      verible-verilog-syntax
verible-verilog-project     verible-verilog-ls          verible-verilog-diff
verible-verilog-obfuscate   verible-verilog-preprocessor
verible-verilog-kythe-extractor   verible-verilog-kythe-kzip-writer
verible-patch-tool
```

## This package repacks; it does not build

Every other `*-bin` repo in edapack compiles its tool from source. This one does
not, and that is deliberate: Verible already publishes prebuilt, **fully static**
binaries for every platform edapack ships. Building them again would produce
strictly worse artifacts at meaningful CI cost.

What CI does instead, per platform: download the upstream release asset, strip
the `verible-<version>/` prefix, move the executables into `bin/` (upstream's
Windows zip has no `bin/` at all), inject the edapack consumer contract, smoke
test, publish. The whole thing is `scripts/build.sh`; there is no compiler, no
bazel and no CMakeLists.txt in this repo.

The injected contract is the reason this repo exists rather than consumers
pointing `ivpm` straight at `chipsalliance/verible`:

| File in the release | Why |
|---|---|
| `ivpm.yaml` | `ivpm` reads `packages/<name>/ivpm.yaml`; without it an installed release puts nothing on `PATH`. Upstream's tarball has none. |
| `manifest.json` | Records the exact upstream release, its commit SHA, and an `inputs_digest`. Provenance, and the change-gate. |
| `skills/` | An Agent Skill for the verible tool family, so an agent that installs the tool also acquires usage guidance. |
| `export.envrc` | `direnv` integration. |

`docs/plan.md` has the full reasoning, including the four findings that ruled
out a passive "just point at upstream" manifest.

## Platforms

| Target | Upstream asset | Smoke-tested in CI |
|---|---|---|
| `linux-x86_64` | `linux-static-x86_64.tar.gz` | yes, natively |
| `linux-aarch64` | `linux-static-arm64.tar.gz` | yes, on an arm runner |
| `macos-arm64` | `macOS.tar.gz` | yes, on macos-14 |
| `win64-x86_64` | `win64.zip` | no — repacked on Linux; contents verified, not executed |

The Linux binaries are statically linked with **no glibc dependency at all**, so
they carry no manylinux floor and run on musl/Alpine as well. There is
deliberately no per-glibc build matrix.

**macOS x86_64 does not exist.** Upstream's macOS asset is arm64-only, not a
universal binary, and this package does not build from source. Intel Macs are
unsupported; see `docs/plan.md` Phase 3 for what adding them would cost.

## Releases

One track, not two. There is no top-of-trunk snapshot track here because a
repack cannot have one: an upstream commit with no release has no assets to
download.

CI runs on the **1st of each month** and repacks the newest Verible release we
have not already published. A month in which upstream has not released is a
no-op. Verible releases several times a week, every one flagged as a full
release, so the cadence is ours by design rather than inherited — mirroring
upstream's would be noise.

Versions and tags are upstream's, verbatim: `v0.0-4294-gc1d8f5e8`. The number
is a commit count, not a semantic version. `latest` always points at the newest
repack.

To pick up a release out of band, run the CI workflow by hand; it takes an
optional `core_ref` (a specific upstream tag to repack) and a `force` flag.

### Release notes

Verible publishes no changelog and its release bodies are empty — every one of
the last 40. So the notes here are assembled from what does exist:

- **Upstream changes** — the pull requests merged between the upstream release
  we last repacked and this one. PR titles, not commit subjects: Verible does
  not squash-merge, so its raw log is mostly `Merge branch 'x' into master` and
  `Fixed formatting`. (edapack-common's `release_notes: gh-compare` mode.)
- **Behavior changes** — what actually changes for *you*, diffed out of the
  binaries: lint rules added, removed, re-defaulted or newly parameterized, and
  command-line flags added, removed or re-defaulted. Nothing in this section is
  asserted; each line is a disagreement between this release's executables and
  the previous release's. See `scripts/verible-behavior-diff.py`.
- **Assets** — every tarball with its size and SHA-256.

A three-week upstream window produces a behavior section like:

```
- lint rule `generate-label-prefix` is now configurable (`style_regex:(g_|gen_).*`)
- `verible-verilog-format`: new flag `--class_parameter_space`
```

"No lint-rule or command-line-flag changes in this release" is a valid and
useful outcome, and is stated explicitly rather than left as an empty section.

## Consuming it

```yaml
# ivpm.yaml
package:
  name: my-project
  dep-sets:
  - name: default
    deps:
    - name: verible-bin
      url: https://github.com/edapack/verible-bin
      src: gh-rls
```

`ivpm update` selects the right asset for the host and puts `bin/` on `PATH`.

## Building locally

```sh
ivpm update -a                            # fetches edapack-common into packages/
EC_IMAGE_NAME=linux-x86_64 scripts/build.sh
```

Targets are `linux-x86_64`, `linux-aarch64`, `macos-arm64`, `win64-x86_64`; with
`EC_IMAGE_NAME` unset the host's own target is inferred. Output lands in
`dist/`, scratch in `.build/`, and nothing is written into the source tree.
Since the repack needs no toolchain, any target can be produced from any host —
only the smoke test is skipped when the host cannot execute what it just packed.

## Testing

`tests/run_smoke_test.sh` runs automatically inside every repack CI can execute,
and is the only thing standing between a mangled archive and a published
release. It checks that all 11 executables run and report the upstream tag, that
the parser accepts a good file and rejects a bad one, that lint is silent on
clean code **and still flags a known violation** (a lint whose rules failed to
load would pass a clean-file-only test), and that the formatter both round-trips
formatted code unchanged and actually reformats ugly code.

Run it against an installed package:

```sh
tests/run_smoke_test.sh /path/to/verible-bin/bin
```
