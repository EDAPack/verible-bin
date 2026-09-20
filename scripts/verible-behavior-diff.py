#!/usr/bin/env python3
"""Diff two Verible builds' user-visible behavior and render it as Markdown.

    verible-behavior-diff.py --old <bin-dir> --new <bin-dir> [--old-tag TAG]

Used by scripts/release-notes-hook.sh to put a "Behavior changes" section in
the release body. It answers the question a *user* of this package has on
seeing a new release — "what changes for me if I upgrade?" — which upstream's
commit log does not.

The trick is that for a linter and a formatter, that question is answerable
from the artifacts. Verible's binaries will describe their own configuration
surface on request:

    verible-verilog-lint --print_rules_file   -> every rule, its default
                                                 enabled state, its parameters
    <any tool> --helpfull                     -> every flag and its default

So this runs both against the old and new binaries and reports the delta.
Nothing is summarized or inferred; every line is a disagreement between two
executables.

Only flags declared in Verible's own sources are considered. `--helpfull`
also lists abseil's flags (`--flagfile`, `--fromenv`, ...), which say nothing
about Verible and would turn a dependency bump into noise in the release notes.

Exit codes: 0 always, unless something truly unexpected happened (1). "No
changes" is a successful outcome with a sentence saying so, because "this
release changes no rules or flags" is itself useful to a reader.
"""

import argparse
import os
import re
import subprocess
import sys

# Every executable Verible ships. Flags are reported per tool.
TOOLS = [
    "verible-verilog-lint",
    "verible-verilog-format",
    "verible-verilog-syntax",
    "verible-verilog-project",
    "verible-verilog-ls",
    "verible-verilog-diff",
    "verible-verilog-obfuscate",
    "verible-verilog-preprocessor",
    "verible-verilog-kythe-extractor",
    "verible-verilog-kythe-kzip-writer",
    "verible-patch-tool",
]

# "  Flags from verible/verilog/tools/lint/verilog-lint.cc:"
_SECTION_RE = re.compile(r"^\s*Flags from (\S+):")
# "    --column_limit (Target line length limit...); default: 100;"
_FLAG_RE = re.compile(r"^\s{2,}--([a-z0-9_]+) \(")
_DEFAULT_RE = re.compile(r"default:\s*(.*?);\s*$")


def _run(exe, args):
    """Run a tool, returning stdout+stderr, or None if it could not run."""
    try:
        proc = subprocess.Popen(
            [exe] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            universal_newlines=True)
        out, _ = proc.communicate(timeout=60)
        return out
    except Exception:
        return None


def parse_rules(text):
    """Parse `--print_rules_file` output into {rule: (enabled, config)}.

    Lines look like:
        always-comb                      -> enabled, no config
        -signal-name-style               -> disabled
        line-length=length:100           -> enabled, configured
    """
    rules = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        enabled = True
        if line.startswith("-"):
            enabled, line = False, line[1:]
        elif line.startswith("+"):
            line = line[1:]
        name, _, config = line.partition("=")
        if name:
            rules[name] = (enabled, config)
    return rules


def parse_flags(text, own_prefix="verible/"):
    """Parse `--helpfull` output into {flag: default}, Verible's flags only."""
    flags, in_own_section = {}, False
    pending = None
    for line in (text or "").splitlines():
        section = _SECTION_RE.match(line)
        if section:
            in_own_section = section.group(1).startswith(own_prefix)
            pending = None
            continue
        if not in_own_section:
            continue
        m = _FLAG_RE.match(line)
        if m:
            pending = m.group(1)
            flags.setdefault(pending, "")
        # The default can land on the flag's own line or on a continuation of
        # its wrapped description, so keep attributing until the next flag.
        if pending:
            d = _DEFAULT_RE.search(line)
            if d:
                flags[pending] = d.group(1).strip()
                pending = None
    return flags


def diff_rules(old, new):
    """Return a list of markdown bullet strings describing rule changes."""
    out = []
    for name in sorted(set(new) - set(old)):
        enabled, config = new[name]
        state = "on by default" if enabled else "off by default"
        out.append("new lint rule `{}` ({})".format(name, state))
    for name in sorted(set(old) - set(new)):
        out.append("lint rule `{}` removed".format(name))
    for name in sorted(set(old) & set(new)):
        (was_on, was_cfg), (now_on, now_cfg) = old[name], new[name]
        if was_on != now_on:
            out.append("lint rule `{}` is now {} by default".format(
                name, "on" if now_on else "off"))
        if was_cfg != now_cfg:
            if not was_cfg:
                out.append("lint rule `{}` is now configurable (`{}`)".format(
                    name, now_cfg))
            elif not now_cfg:
                out.append("lint rule `{}` is no longer configurable".format(name))
            else:
                out.append("lint rule `{}` default config: `{}` → `{}`".format(
                    name, was_cfg, now_cfg))
    return out


def diff_flags(tool, old, new):
    out = []
    for flag in sorted(set(new) - set(old)):
        out.append("`{}`: new flag `--{}`".format(tool, flag))
    for flag in sorted(set(old) - set(new)):
        out.append("`{}`: flag `--{}` removed".format(tool, flag))
    for flag in sorted(set(old) & set(new)):
        if old[flag] != new[flag]:
            out.append("`{}`: `--{}` default `{}` → `{}`".format(
                tool, flag, old[flag] or "(none)", new[flag] or "(none)"))
    return out


def _exe(bin_dir, tool):
    for candidate in (os.path.join(bin_dir, tool),
                      os.path.join(bin_dir, tool + ".exe")):
        if os.path.isfile(candidate):
            return candidate
    return None


def collect(bin_dir):
    """Read the whole configuration surface out of one build."""
    lint = _exe(bin_dir, "verible-verilog-lint")
    rules = parse_rules(_run(lint, ["--print_rules_file"])) if lint else {}
    flags = {}
    for tool in TOOLS:
        exe = _exe(bin_dir, tool)
        if not exe:
            continue
        parsed = parse_flags(_run(exe, ["--helpfull"]))
        if parsed:
            flags[tool] = parsed
    return rules, flags


def render(rule_changes, flag_changes, old_tag):
    since = " against `{}`".format(old_tag) if old_tag else ""
    lines = ["", "## Behavior changes", ""]
    if not rule_changes and not flag_changes:
        lines.append(
            "No lint-rule or command-line-flag changes in this release "
            "(diffed{}).".format(since))
        return "\n".join(lines) + "\n"
    lines.append(
        "Diffed from the shipped binaries{}, not from the commit log.".format(since))
    lines.append("")
    if rule_changes:
        lines.append("**Lint rules**")
        lines.append("")
        lines.extend("- " + c for c in rule_changes)
        lines.append("")
    if flag_changes:
        lines.append("**Command-line flags**")
        lines.append("")
        lines.extend("- " + c for c in flag_changes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--old", required=True, help="bin/ of the previous release")
    p.add_argument("--new", required=True, help="bin/ of this build")
    p.add_argument("--old-tag", default="", help="tag the old build came from")
    args = p.parse_args(argv)

    old_rules, old_flags = collect(args.old)
    new_rules, new_flags = collect(args.new)

    if not new_rules and not new_flags:
        print("verible-behavior-diff: the new build described nothing; "
              "are these the right binaries?", file=sys.stderr)
        return 1

    rule_changes = diff_rules(old_rules, new_rules)
    flag_changes = []
    for tool in TOOLS:
        if tool in old_flags and tool in new_flags:
            flag_changes.extend(diff_flags(tool, old_flags[tool], new_flags[tool]))
        elif tool in new_flags and tool not in old_flags:
            flag_changes.append("`{}`: new executable in this release".format(tool))
        elif tool in old_flags and tool not in new_flags:
            flag_changes.append("`{}`: no longer shipped".format(tool))

    sys.stdout.write(render(rule_changes, flag_changes, args.old_tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
