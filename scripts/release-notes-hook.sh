#!/usr/bin/env bash
# verible-bin release-notes hook.
#
#   scripts/release-notes-hook.sh <artifacts-dir> <upload-dir>   # markdown -> stdout
#
# Called by edapack-common's publish job; its stdout is appended to the release
# body. See edapack-common's README (Release notes -> Adding to the body).
#
# WHY THIS EXISTS. release-notes.py already lists the pull requests merged
# upstream since our last release. That answers "what did the Verible project
# do", which is not quite the question a user of this package has — they want
# "what changes for me if I upgrade". For a linter and a formatter that
# question has a precise, checkable answer: which lint rules exist, which are
# on by default, how they are parameterized, and which command-line flags the
# tools accept. All of it can be read out of the binaries themselves.
#
# So this does not summarize; it DIFFS. It runs the binaries this build just
# produced against the ones the previous release shipped and reports the
# delta. Nothing here is asserted — if the release notes say a lint rule gained
# a parameter, it is because the two binaries disagreed about it.
#
# Verified against the real v0.0-4163-g6cce8f19 -> v0.0-4294-gc1d8f5e8 window
# (three upstream weeks), which produces exactly two lines: the
# `generate-label-prefix` rule became configurable, and the formatter gained
# `--class_parameter_space`. Both trace back to real PRs (#2586, #2595).
#
# Soft-fails throughout. The publish step marks this `continue-on-error`, and
# an incomplete release body is never worth failing a release that is otherwise
# ready to ship.
set -uo pipefail

artifacts_dir="${1:-artifacts}"
upload_dir="${2:-upload}"
repo="${EC_REPO:-}"

log() { printf '[hook] %s\n' "$*" >&2; }

# Explicit template — portable across GNU and BSD mktemp. This runs on the
# publish runner (Linux), but it is documented as runnable by hand.
work="$(mktemp -d "${TMPDIR:-/tmp}/verible-notes.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# The platform we can actually execute on the publish runner (ubuntu-latest).
# Verible's Linux binaries are fully static, so the choice is arbitrary beyond
# that — the lint rules and flags are the same on every platform.
DIFF_PLATFORM="linux-x86_64"

# --- locate this build's binaries ------------------------------------------
new_tarball="$(find "$upload_dir" -name "verible-bin-${DIFF_PLATFORM}-*.tar.gz" \
                    -print 2>/dev/null | head -1)"
new_bin=""
if [ -n "$new_tarball" ]; then
    mkdir -p "$work/new"
    if tar -C "$work/new" -xzf "$new_tarball" 2>/dev/null; then
        new_bin="$(find "$work/new" -type d -name bin | head -1)"
    fi
fi
[ -n "$new_bin" ] || log "no ${DIFF_PLATFORM} tarball in $upload_dir; skipping behavior diff"

# --- locate the previous release's binaries --------------------------------
# The hook runs BEFORE `gh release create`, so the newest published release is
# still the previous one. No need to filter out our own tag.
prev_tag=""
prev_bin=""
if [ -n "$new_bin" ] && [ -n "$repo" ] && command -v gh >/dev/null 2>&1; then
    prev_tag="$(gh release list --repo "$repo" --limit 1 \
                   --json tagName -q '.[0].tagName' 2>/dev/null || true)"
    if [ -n "$prev_tag" ]; then
        mkdir -p "$work/prevdl" "$work/prev"
        if gh release download "$prev_tag" --repo "$repo" \
             --pattern "verible-bin-${DIFF_PLATFORM}-*.tar.gz" \
             --dir "$work/prevdl" >/dev/null 2>&1; then
            prev_archive="$(find "$work/prevdl" -name '*.tar.gz' | head -1)"
            if [ -n "$prev_archive" ] && tar -C "$work/prev" -xzf "$prev_archive" 2>/dev/null; then
                prev_bin="$(find "$work/prev" -type d -name bin | head -1)"
            fi
        fi
        [ -n "$prev_bin" ] || log "could not fetch ${DIFF_PLATFORM} assets for $prev_tag"
    else
        log "no previous release found; this looks like the first one"
    fi
fi

# --- behavior diff ----------------------------------------------------------
if [ -n "$new_bin" ] && [ -n "$prev_bin" ]; then
    chmod -R u+rx "$prev_bin" "$new_bin" 2>/dev/null || true
    python3 "$(dirname "$0")/verible-behavior-diff.py" \
        --old "$prev_bin" --new "$new_bin" --old-tag "$prev_tag" \
        || log "behavior diff failed; omitting that section"
fi

# --- assets -----------------------------------------------------------------
# Checksums exist here and nowhere else in the pipeline, and a release whose
# body carries them is verifiable without downloading anything twice.
python3 - "$upload_dir" "${EC_VERSION:-}" <<'PY'
import os, sys

upload, version = sys.argv[1], sys.argv[2]
PREFIX, SUFFIX = "verible-bin-", ".tar.gz"


def platform_of(name):
    """verible-bin-<platform>-<version>.tar.gz -> <platform>.

    Split on the version rather than on '-': both the platform
    (`linux-x86_64`) and the version (`0.0-4294-gc1d8f5e8`) contain hyphens,
    so counting them from either end gets it wrong.
    """
    stem = name[len(PREFIX):-len(SUFFIX)]
    if version and stem.endswith("-" + version):
        return stem[:-(len(version) + 1)]
    return stem


rows = []
for name in sorted(os.listdir(upload)):
    if not (name.startswith(PREFIX) and name.endswith(SUFFIX)):
        continue
    sha_path = os.path.join(upload, name + ".sha256")
    digest = ""
    if os.path.isfile(sha_path):
        # Both `sha256sum` and `shasum -a 256` write "<digest>  <name>".
        fields = open(sha_path).read().split()
        digest = fields[0] if fields else ""
    size = os.path.getsize(os.path.join(upload, name)) / (1024.0 * 1024.0)
    rows.append((platform_of(name), size, digest))

if rows:
    print()
    print("## Assets")
    print()
    print("| Platform | Size | SHA-256 |")
    print("|---|---|---|")
    for plat, size, digest in rows:
        print("| `{}` | {:.1f} MB | `{}` |".format(plat, size, digest or "n/a"))
PY
