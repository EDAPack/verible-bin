#!/usr/bin/env bash
# verible-bin smoke test.
#
#   tests/run_smoke_test.sh [BIN_DIR] [EXPECTED_VERSION]
#
# BIN_DIR           directory holding the verible executables. Defaults to the
#                   installed package's bin/ if this script lives inside one,
#                   else whatever is on PATH.
# EXPECTED_VERSION  upstream tag (e.g. v0.0-4294-gc1d8f5e8) that every
#                   executable must report. Optional; skipped when absent.
#
# Called by scripts/build.sh during a repack (where it is the only thing
# standing between a mangled archive and a published release), and runnable by
# hand against an installed package:
#
#   tests/run_smoke_test.sh "$(ivpm path verible-bin)/bin"
#
# What it checks, in the order a failure is most likely:
#   1. all 11 executables exist, are executable, and report a version
#   2. that version is the upstream tag we meant to repack
#   3. the front end actually parses (verible-verilog-syntax)
#   4. lint runs, is silent on clean code, and is NOT silently disabled
#      (a broken repack that lost its rule data would pass a clean-file-only
#      test, so a known-bad file must still be flagged)
#   5. format is a fixed point on already-formatted code, and reformats ugly
#      code -- a format that emits nothing would otherwise "pass"
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${1:-}"
expect_version="${2:-}"

if [ -z "$bin_dir" ]; then
    if [ -x "$here/../bin/verible-verilog-lint" ] || [ -x "$here/../bin/verible-verilog-lint.exe" ]; then
        bin_dir="$(cd "$here/.." && pwd)/bin"
    else
        bin_dir=""   # fall back to PATH
    fi
fi

# On Windows the executables carry .exe; everywhere else they do not.
suffix=""
if [ -n "$bin_dir" ] && [ ! -e "$bin_dir/verible-verilog-lint" ] \
   && [ -e "$bin_dir/verible-verilog-lint.exe" ]; then
    suffix=".exe"
fi

tool() {
    if [ -n "$bin_dir" ]; then printf '%s/%s%s' "$bin_dir" "$1" "$suffix";
    else printf '%s' "$1"; fi
}

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
ok()   { echo "  ok: $*"; }

TOOLS="
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

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "verible-bin smoke test (bin_dir=${bin_dir:-<PATH>})"

# --- 1 + 2: every executable runs and reports the expected version ----------
count=0
for t in $TOOLS; do
    exe="$(tool "$t")"
    # No `| head -1` here: with pipefail a tool whose banner outlives head's
    # single line dies of SIGPIPE and the pipeline reports failure for a tool
    # that worked perfectly (verible-verilog-ls prints several lines).
    out="$("$exe" --version 2>&1)" \
        || fail "$t --version exited non-zero"
    out="${out%%$'\n'*}"
    [ -n "$out" ] || fail "$t --version printed nothing"
    if [ -n "$expect_version" ] && ! printf '%s' "$out" | grep -qF "$expect_version"; then
        fail "$t reports '$out', expected it to mention '$expect_version'"
    fi
    count=$((count + 1))
done
ok "$count executables report ${expect_version:-a version}"
[ "$count" = 11 ] || fail "expected 11 executables, checked $count"

# --- 3: the front end parses ------------------------------------------------
"$(tool verible-verilog-syntax)" "$here/smoke.sv" \
    || fail "verible-verilog-syntax rejected tests/smoke.sv"
ok "syntax accepts tests/smoke.sv"

printf 'module broken\nendmodule\n' > "$work/broken.sv"
if "$(tool verible-verilog-syntax)" "$work/broken.sv" >/dev/null 2>&1; then
    fail "verible-verilog-syntax accepted a file with a syntax error"
fi
ok "syntax rejects malformed input"

# --- 4: lint runs, and its rules are really loaded --------------------------
lint_out="$("$(tool verible-verilog-lint)" "$here/smoke.sv" 2>&1)" \
    || fail "verible-verilog-lint flagged tests/smoke.sv: $lint_out"
[ -z "$lint_out" ] || fail "verible-verilog-lint was not silent on clean code: $lint_out"
ok "lint is clean+silent on tests/smoke.sv"

# module name != file name -> module-filename rule. If a repack ever shipped a
# binary whose rules did not load, this is what would catch it.
printf 'module BadName;\nendmodule\n' > "$work/bad.sv"
if "$(tool verible-verilog-lint)" "$work/bad.sv" >/dev/null 2>&1; then
    fail "verible-verilog-lint did not flag a known rule violation"
fi
ok "lint flags a known violation"

# --- 5: format round-trip ---------------------------------------------------
"$(tool verible-verilog-format)" "$here/smoke.sv" > "$work/fmt.sv" \
    || fail "verible-verilog-format exited non-zero"
[ -s "$work/fmt.sv" ] || fail "verible-verilog-format produced an empty file"
diff -u "$here/smoke.sv" "$work/fmt.sv" \
    || fail "verible-verilog-format is not a fixed point on tests/smoke.sv"
ok "format round-trips tests/smoke.sv unchanged"

printf 'module ugly;\nlogic    a;\nendmodule\n' > "$work/ugly.sv"
"$(tool verible-verilog-format)" "$work/ugly.sv" > "$work/ugly.fmt.sv" \
    || fail "verible-verilog-format exited non-zero on unformatted input"
if diff -q "$work/ugly.sv" "$work/ugly.fmt.sv" >/dev/null; then
    fail "verible-verilog-format left badly-formatted input untouched"
fi
ok "format actually reformats unformatted input"

echo "SMOKE PASS"
