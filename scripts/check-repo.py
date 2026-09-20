#!/usr/bin/env python3
"""Validate verible-bin's own contracts. No toolchain, no network, no binaries.

Run from the repo root:

    python3 scripts/check-repo.py

Called by BOTH CI workflows — .github/workflows/ci.yml (so a push to GitHub
gets a real check) and .forgejo/workflows/ci.yml — because the thing worth
checking is the same on both forges and two copies would drift. Forge-specific
checks stay in their own workflow: the tracked-file scan for internal host
names lives in the Forgejo file, which is where publishing to a public mirror
is decided.

Why any of this is checkable without building: this repo is a repack. It
compiles nothing, so almost all of it is declarations — which upstream asset,
which layout, which files get injected into the release — and every one of
those is a file that can be read and cross-checked in seconds. The real build
takes minutes in a container and only runs monthly, so a mistake caught here is
a mistake caught four weeks earlier.

Emits `::error::` / `::warning::` workflow commands, understood by GitHub
Actions and Forgejo Actions alike. Exit 0 clean, 1 on any error.
"""

import json
import pathlib
import re
import sys

import yaml

PACKAGE = "verible-bin"
SHARED_WORKFLOW = "edapack/edapack-common/.github/workflows/build-release.yml@"
EXPECTED_PIN = "v1"

errors = []
warnings = []


def error(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


# --------------------------------------------------------------------------- #
# 1. The shared release pipeline must still resolve
# --------------------------------------------------------------------------- #
# A rename of edapack-common, of the workflow path, or of the `v1` alias breaks
# this repo's entire release pipeline, and GitHub reports it as "workflow was
# not found" HERE while edapack-common looks perfectly healthy. This asserts
# the half that lives in this repository.
#
# Fragment-assembly so this scanner does not trip over its own source.
PUBLISH_MARKERS = tuple(a + b for a, b in (
    ("softprops/action", "-gh-release"), ("actions/create", "-release"),
    ("actions/upload", "-release-asset"), ("gh release", " create"),
    ("peaceiris/actions", "-gh-pages"), ("actions/deploy", "-pages"),
))


def check_release_pipeline():
    pins, local_publishers = [], []
    for wf in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
        doc = yaml.safe_load(wf.read_text()) or {}
        # PyYAML parses a bare `on:` key as the boolean True.
        if doc.get("on", doc.get(True)) is None:
            error("{}: no `on:` block".format(wf))
        for name, job in (doc.get("jobs") or {}).items():
            uses = job.get("uses") or ""
            if uses.startswith(SHARED_WORKFLOW):
                pins.append((str(wf), name, uses))
            for step in job.get("steps") or []:
                text = (step.get("run") or "") + " " + (step.get("uses") or "")
                if any(m in text for m in PUBLISH_MARKERS):
                    cond = "{} {}".format(step.get("if", ""), job.get("if", ""))
                    local_publishers.append(("{}:{}".format(wf, name), cond.strip()))

    if not pins:
        error("no job calls {}<ref>; this repo is supposed to delegate its "
              "release pipeline, and if that changed on purpose it now needs "
              "its own publish gate".format(SHARED_WORKFLOW))
    for wf, name, uses in pins:
        ref = uses.rsplit("@", 1)[1]
        print("OK: {}:{} -> {}".format(wf, name, uses))
        if ref != EXPECTED_PIN:
            # Not an error. A commit SHA would be STRICTER than `v1`, which
            # moves; flag it so a change of pinning strategy is visible.
            warn("{}:{} pins `{}`, not the expected `{}`".format(
                wf, name, ref, EXPECTED_PIN))

    # A caller that has grown its OWN publish step no longer inherits
    # edapack-common's gating, and nothing central would fix it.
    for label, cond in local_publishers:
        if "github.event_name != 'push'" not in cond or "authority" not in cond:
            error("{} publishes locally without the full gate: if={!r}".format(
                label, cond))


# --------------------------------------------------------------------------- #
# 2. A push must actually check something
# --------------------------------------------------------------------------- #
# This repo has no dev track, so its release job is `if: != 'push'` and a push
# would otherwise run nothing at all — a grey "skipped" check, and a broken
# workflow or build script that stays invisible until the monthly cron fires.
def check_push_is_covered():
    for wf in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
        doc = yaml.safe_load(wf.read_text()) or {}
        triggers = doc.get("on", doc.get(True)) or {}
        if isinstance(triggers, str):
            triggers = {triggers: None}
        if "push" not in triggers:
            continue
        runs_on_push = [
            name for name, job in (doc.get("jobs") or {}).items()
            if "github.event_name != 'push'" not in str(job.get("if", ""))
        ]
        if not runs_on_push:
            error("{}: every job opts out of `push`, so a push runs nothing "
                  "and reports a skipped check".format(wf))
        else:
            print("OK: {} runs {} on push".format(wf, runs_on_push))


# --------------------------------------------------------------------------- #
# 3. Repack contracts
# --------------------------------------------------------------------------- #
# The things that make this a package rather than a mirror of an upstream
# tarball. Each is a file, so each is checkable here.
def check_build_inputs():
    bi = yaml.safe_load(pathlib.Path("build-inputs.yaml").read_text())
    if bi.get("schema") != "edapack.build-inputs/1":
        error("build-inputs.yaml: wrong or missing schema")
    core = bi.get("core") or {}
    if "verible" not in (core.get("repo") or ""):
        error("build-inputs.yaml: core.repo is not verible")
    # A repack has no trunk to snapshot: an upstream commit without a release
    # has no assets. Both policies must name a released thing.
    for key in ("policy", "release_policy"):
        val = core.get(key) or ""
        if not val:
            error("build-inputs.yaml: core.{} is required here".format(key))
        elif val.startswith("branch:"):
            error("build-inputs.yaml: core.{}={!r} — a branch has no release "
                  "assets to repack".format(key, val))
    # Verible has no changelog and publishes empty release bodies, so a
    # changelog PATH here would silently produce default notes forever.
    if core.get("release_notes") != "gh-compare":
        error("build-inputs.yaml: core.release_notes must be 'gh-compare' — "
              "verible ships no changelog to slice")
    if bi.get("dependencies"):
        error("build-inputs.yaml: a repack should have no dependencies")


def check_release_ivpm():
    # The consumer contract. Without the PATH entry an installed release puts
    # nothing on PATH and the package is inert.
    rel = pathlib.Path("scripts/release-ivpm.yaml")
    own = pathlib.Path("ivpm.yaml")
    if not rel.is_file():
        error("scripts/release-ivpm.yaml is missing")
        return
    text = rel.read_text()
    if own.is_file() and rel.read_bytes() == own.read_bytes():
        error("release-ivpm.yaml is a copy of the project ivpm.yaml")
    pkg = (yaml.safe_load(text) or {}).get("package") or {}
    if pkg.get("name") != PACKAGE:
        error("release-ivpm.yaml: package.name must be {}".format(PACKAGE))
    env = pkg.get("env") or []
    if not any(e.get("name") == "PATH" and e.get("path-prepend") for e in env):
        error("release-ivpm.yaml: no PATH path-prepend entry")
    if "default-dev" in text:
        error("release-ivpm.yaml: consumers must not fetch build tooling")


def check_skills():
    # Skills are staged with --strict, so a broken manifest fails the real
    # build late. Fail it here instead.
    sm = yaml.safe_load(pathlib.Path("scripts/skill-manifest.yaml").read_text())
    skills = sm.get("skills") or []
    if not skills:
        error("skill-manifest.yaml lists no skills (staged --strict)")
    for s in skills:
        directory = pathlib.Path(s["path"])
        md = directory / "SKILL.md"
        if not md.is_file():
            error("skill {}: missing {}".format(s["name"], md))
            continue
        text = md.read_text()
        if not text.startswith("---"):
            error("skill {}: SKILL.md has no frontmatter".format(s["name"]))
            continue
        fm = yaml.safe_load(text.split("---", 2)[1]) or {}
        for key in ("name", "description", "version"):
            if not fm.get(key):
                error("skill {}: frontmatter missing {}".format(s["name"], key))
        if fm.get("name") != s["name"]:
            error("skill {}: frontmatter name {!r} does not match the "
                  "manifest".format(s["name"], fm.get("name")))
        for ref in sorted((directory / "references").glob("*.md")):
            if ref.name not in text:
                warn("{} is not referenced from {}".format(ref, md))


def check_required_files():
    # The smoke-test fixture the build gates on, and the release-notes hook
    # edapack-common discovers by PATH alone — rename that and the release body
    # silently loses a section, with nothing failing anywhere.
    for p in ("tests/smoke.sv", "tests/run_smoke_test.sh", "scripts/export.envrc",
              "scripts/release-notes-hook.sh", "scripts/verible-behavior-diff.py"):
        if not pathlib.Path(p).is_file():
            error("missing {}".format(p))
    hook = pathlib.Path("scripts/release-notes-hook.sh")
    if hook.is_file() and "verible-behavior-diff.py" not in hook.read_text():
        error("release-notes-hook.sh no longer calls the behavior diff")


# --------------------------------------------------------------------------- #
# 4. Build targets must agree with the repack script
# --------------------------------------------------------------------------- #
# The matrix target names are not labels: scripts/build.sh switches on them to
# pick the upstream asset. A target the script does not know is a build failure
# minutes into a release run; catch it in seconds here.
_CASE_ARM_RE = re.compile(
    r"^\s{4}(linux-[a-z0-9_]+|macos-[a-z0-9]+|win64-[a-z0-9_]+)\)", re.M)


def check_targets():
    script = pathlib.Path("scripts/build.sh").read_text()
    known = set(_CASE_ARM_RE.findall(script))
    if not known:
        error("could not find the target case arms in scripts/build.sh")
        return

    seen = set()
    for wf in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
        doc = yaml.safe_load(wf.read_text()) or {}
        for name, job in (doc.get("jobs") or {}).items():
            raw = ((job.get("with") or {}).get("targets") or "").strip()
            if not raw:
                continue
            for t in json.loads(raw):
                seen.add(t["name"])
                if t["name"] not in known:
                    error("job {}: target {!r} has no arm in scripts/build.sh "
                          "(knows: {})".format(name, t["name"], sorted(known)))
    missing = known - seen
    if missing:
        # Not fatal: an arm can outlive a target on purpose (a platform
        # temporarily dropped from CI). Say so rather than hide it.
        warn("scripts/build.sh handles targets nothing builds: {}".format(
            sorted(missing)))
    if seen:
        print("OK: {} build targets all handled: {}".format(len(seen), sorted(seen)))


def main():
    check_release_pipeline()
    check_push_is_covered()
    check_build_inputs()
    check_release_ivpm()
    check_skills()
    check_required_files()
    check_targets()

    for w in warnings:
        print("::warning::{}".format(w))
    for e in errors:
        print("::error::{}".format(e))
    if errors:
        print("check-repo: {} error(s)".format(len(errors)))
        return 1
    print("check-repo: all contracts intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
