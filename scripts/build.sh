#!/usr/bin/env bash
# verible-bin build driver — a REPACK, not a build.
#
# Verible already publishes prebuilt, fully static binaries for every platform
# edapack ships (docs/plan.md, Finding 1), so there is no compiler, no bazel and
# no toolchain here. What this script does instead:
#
#   1. download the upstream release asset for $EC_IMAGE_NAME, at the exact tag
#      edapack-common's resolve-inputs.py picked,
#   2. rearrange it into edapack's layout (bin/ at the release root — upstream's
#      Windows zip has no bin/ at all, and every archive carries a
#      verible-<version>/ prefix we strip),
#   3. inject the edapack consumer contract (ivpm.yaml, export.envrc, skills/,
#      manifest.json) that the upstream tarball has no reason to carry,
#   4. smoke-test what it can actually execute on this runner,
#   5. emit the tarball + checksum the publish step uploads.
#
# Because a repack needs no toolchain, every target can run on any runner; CI
# nevertheless puts three of the four on native hardware so step 4 is a real
# test rather than a no-op. See .github/workflows/ci.yml.
#
# Runs both in CI (via edapack-common's reusable workflow) and locally:
#   EC_IMAGE_NAME=linux-x86_64 scripts/build.sh
# All transient state goes to WORK_DIR; outputs land in OUT_DIR. Nothing is
# written into the source tree.
set -euo pipefail

# --- locate edapack-common --------------------------------------------------
if [ -z "${EC_COMMON:-}" ]; then
    # sibling checkout fallback for plain local runs
    _repo="$(cd "$(dirname "$0")/.." && pwd)"
    for _c in "$_repo/packages/edapack-common" "$_repo/../edapack-common"; do
        if [ -f "$_c/scripts/build-common.sh" ]; then EC_COMMON="$_c"; break; fi
    done
fi
if [ -z "${EC_COMMON:-}" ] || [ ! -f "$EC_COMMON/scripts/build-common.sh" ]; then
    echo "ERROR: edapack-common not found. Set EC_COMMON or place edapack-common beside verible-bin." >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$EC_COMMON/scripts/build-common.sh"

: "${EC_PACKAGE:=verible-bin}"
export EC_PACKAGE
# A repack has no top-of-trunk story: an upstream commit without a release has
# no assets to download. Default to the release track rather than inheriting
# build-common's dev default, so a local run resolves the same thing CI does.
: "${EC_TRACK:=release}"
export EC_TRACK
ec_init_dirs
ec_prepare_candidate

# --- target -> upstream asset ----------------------------------------------
# EC_IMAGE_NAME is the matrix target name; it is also the platform label in the
# tarball name and the key the publish step merges per-platform manifests on, so
# it must be unique per target.
plat="${EC_IMAGE_NAME:-}"
if [ -z "$plat" ]; then
    case "$(uname -s)" in
        Linux)  plat="linux-$(uname -m | sed 's/^arm64$/aarch64/')" ;;
        Darwin) plat="macos-$(uname -m)" ;;
        *)      ec_die "cannot infer a target from $(uname -s); set EC_IMAGE_NAME" ;;
    esac
    ec_log "EC_IMAGE_NAME unset; inferred target $plat"
fi

upstream_tag="$(ec_core_get ref)"
upstream_repo="$(ec_core_get repo)"
[ -n "$upstream_tag" ] && [ -n "$upstream_repo" ] \
    || ec_die "missing resolved core input (ref/repo) in $CANDIDATE_JSON"

# uname values the built artifact is FOR, which on a cross-repacked target is
# not what `uname` reports here. Recorded in the manifest's platform block.
case "$plat" in
    linux-x86_64)   asset="verible-${upstream_tag}-linux-static-x86_64.tar.gz"
                    p_os=linux;   p_arch=x86_64 ;;
    linux-aarch64)  asset="verible-${upstream_tag}-linux-static-arm64.tar.gz"
                    p_os=linux;   p_arch=aarch64 ;;
    macos-arm64)    asset="verible-${upstream_tag}-macOS.tar.gz"
                    p_os=darwin;  p_arch=arm64 ;;
    win64-x86_64)   asset="verible-${upstream_tag}-win64.zip"
                    p_os=windows; p_arch=x86_64 ;;
    *) ec_die "unknown target '$plat' (expected linux-x86_64|linux-aarch64|macos-arm64|win64-x86_64)" ;;
esac

ec_log "target $plat <- $upstream_repo @ $upstream_tag ($asset)"

# --- download ---------------------------------------------------------------
dl_dir="$WORK_DIR/download"
rm -rf "$dl_dir"; mkdir -p "$dl_dir"
url="${upstream_repo%/}/releases/download/${upstream_tag}/${asset}"
ec_log "downloading $url"
command -v curl >/dev/null 2>&1 || ec_die "curl is required to repack (not found on PATH)"
# --fail so a 404 (upstream dropped a platform, or renamed an asset) is a build
# failure rather than an HTML error page repacked into a tarball.
curl -fsSL --retry 3 --retry-delay 5 -o "$dl_dir/$asset" "$url" \
    || ec_die "download failed: $url"
ec_log "downloaded $(ls -l "$dl_dir/$asset" | awk '{print $5}') bytes"

# --- unpack + rearrange into edapack layout ---------------------------------
# Upstream layout differs per platform:
#   linux/macOS  verible-<tag>[-<plat>]/bin/<exe>
#   win64        verible-<tag>-win64/<exe>.exe     (no bin/ at all)
# Both become <release_root>/bin/<exe>.
unpack_dir="$WORK_DIR/unpack"
release_root="$WORK_DIR/release/verible-bin"
rm -rf "$unpack_dir" "$release_root"
mkdir -p "$unpack_dir" "$release_root/bin"

case "$asset" in
    *.tar.gz) tar -C "$unpack_dir" -xzf "$dl_dir/$asset" ;;
    # python3's zipfile rather than `unzip`: the Windows repack runs in a
    # manylinux container, which has python3 but not necessarily unzip. Mode
    # bits are not preserved either way — the chmod below is what sets them.
    *.zip)    python3 -c 'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
                  "$dl_dir/$asset" "$unpack_dir" ;;
    *)        ec_die "unhandled archive type: $asset" ;;
esac

# Exactly one top-level directory is expected; anything else means upstream
# changed the archive shape and the strip below would silently do the wrong thing.
top_count="$(find "$unpack_dir" -mindepth 1 -maxdepth 1 | wc -l)"
[ "$top_count" = "1" ] || ec_die "expected 1 top-level entry in $asset, found $top_count"
top="$(find "$unpack_dir" -mindepth 1 -maxdepth 1)"
[ -d "$top" ] || ec_die "top-level entry in $asset is not a directory: $top"

if [ -d "$top/bin" ]; then
    cp -R "$top/bin/." "$release_root/bin/"
    # Anything upstream ships beside bin/ (docs, share/, ...) rides along.
    for entry in "$top"/*; do
        [ "$(basename "$entry")" = bin ] && continue
        [ -e "$entry" ] || continue
        cp -R "$entry" "$release_root/"
    done
else
    ec_log "no bin/ in upstream archive; promoting top-level files into bin/"
    cp -R "$top/." "$release_root/bin/"
fi
chmod -R u+w "$release_root"
find "$release_root/bin" -type f -exec chmod a+rx {} +

# --- verify the repack ------------------------------------------------------
# The 11 executables upstream ships. A missing one means the rearrange above
# lost something, which is exactly the failure a repack can introduce.
VERIBLE_TOOLS="
verible-verilog-lint
verible-verilog-format
verible-verilog-syntax
verible-verilog-project
verible-verilog-ls
verible-verilog-diff
verible-verilog-obfuscate
verible-verilog-preprocessor
verible-verilog-kythe-extractor
verible-verilog-kythe-kzip-writer
verible-patch-tool
"
exe_suffix=""
[ "$p_os" = windows ] && exe_suffix=".exe"
missing=""
for t in $VERIBLE_TOOLS; do
    [ -f "$release_root/bin/${t}${exe_suffix}" ] || missing="$missing ${t}${exe_suffix}"
done
[ -z "$missing" ] || ec_die "repack lost executables:$missing"
ec_log "all 11 verible executables present in bin/"

# Guard against an unnoticed extra: if upstream adds a tool, the skill and the
# README should learn about it rather than it shipping unannounced.
shipped="$(find "$release_root/bin" -maxdepth 1 -type f | wc -l)"
[ "$shipped" = "11" ] || ec_log "WARNING: bin/ holds $shipped files, expected 11 — did upstream add a tool?"

# --- smoke test (only where this runner can execute the target) -------------
host_os="$(uname -s | tr '[:upper:]' '[:lower:]')"
host_arch="$(uname -m | sed 's/^arm64$/aarch64/')"
want_arch="$(echo "$p_arch" | sed 's/^arm64$/aarch64/')"
if [ "$host_os" = "$p_os" ] && [ "$host_arch" = "$want_arch" ]; then
    ec_log "smoke-testing $plat natively"
    bash "$SRC_DIR/tests/run_smoke_test.sh" "$release_root/bin" "$upstream_tag" \
        || ec_die "smoke test failed for $plat"
else
    ec_log "skipping smoke test: runner is $host_os/$host_arch, target is $p_os/$want_arch"
fi

# --- shared release tail ----------------------------------------------------
# Not ec_finalize_release: its ec_platform_json derives os/arch from `uname` on
# the machine doing the work, which for a repack is the runner, not the target.
# Everything else it does is reused verbatim.
tarball="verible-bin-${plat}-${EC_VERSION}.tar.gz"
platform_json="$WORK_DIR/platform.json"
python3 - "$platform_json" "$p_os" "$p_arch" "$asset" "$tarball" <<'PY'
import json, sys
out, os_, arch, upstream_asset, artifact = sys.argv[1:6]
json.dump({
    "os": os_,
    "arch": arch,
    # Upstream's Linux builds are fully static (no glibc floor at all, see
    # docs/plan.md Finding 1); macOS/Windows have no libc tag to record.
    "libc": "static" if os_ == "linux" else "",
    # No build image: `image` records where the bits came from instead.
    "image": "upstream:" + upstream_asset,
    "artifact": artifact,
}, open(out, "w"))
PY

ec_stage_skills "$SRC_DIR" "$release_root" --strict
ec_copy_envrc "$SRC_DIR" "$release_root"
ec_stage_release_ivpm "$SRC_DIR" "$release_root"
ec_emit_manifest "$CANDIDATE_JSON" "$release_root" "$platform_json"
ec_require_file "$release_root/skills/index.json" "skills/index.json"
ec_require_file "$release_root/export.envrc" "export.envrc"
ec_require_file "$release_root/ivpm.yaml" "ivpm.yaml"
ec_require_file "$release_root/manifest.json" "manifest.json"
cp "$release_root/manifest.json" "$OUT_DIR/manifest-${plat}.json"

ec_make_tarball "$release_root" "$tarball"
ec_log "repack complete: $tarball"
