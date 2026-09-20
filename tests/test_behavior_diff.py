"""Unit tests for scripts/verible-behavior-diff.py.

Pure-function tests over captured `--print_rules_file` / `--helpfull` output;
nothing here runs a binary or touches the network, so they hold on any host.

The fixtures are real output shapes from the shipped binaries, trimmed. The
`generate-label-prefix` and `--class_parameter_space` cases are the actual
delta between Verible v0.0-4163-g6cce8f19 and v0.0-4294-gc1d8f5e8, which is
what this diff was developed against.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verible-behavior-diff.py"


def _load():
    spec = importlib.util.spec_from_file_location("behavior_diff", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["behavior_diff"] = mod
    spec.loader.exec_module(mod)
    return mod


bd = _load()


# --------------------------------------------------------------------------- #
# --print_rules_file
# --------------------------------------------------------------------------- #
RULES_OLD = """\
always-comb
always-ff-non-blocking=catch_modifying_assignments:false;waive_for_locals:false
-banned-declared-name-patterns
generate-label-prefix
line-length=length:100
-signal-name-style=style_regex:[a-z_0-9]+
"""

RULES_NEW = """\
always-comb
always-ff-non-blocking=catch_modifying_assignments:false;waive_for_locals:false
-banned-declared-name-patterns
generate-label-prefix=style_regex:(g_|gen_).*
line-length=length:120
-signal-name-style=style_regex:[a-z_0-9]+
brand-new-rule
"""


def test_parse_rules_enabled_disabled_and_config():
    rules = bd.parse_rules(RULES_OLD)
    assert rules["always-comb"] == (True, "")
    assert rules["banned-declared-name-patterns"][0] is False
    assert rules["line-length"] == (True, "length:100")
    # A disabled rule can still carry a config; both must survive.
    assert rules["signal-name-style"] == (False, "style_regex:[a-z_0-9]+")


def test_parse_rules_ignores_blanks_and_comments():
    assert bd.parse_rules("\n# a comment\n\nalways-comb\n") == {
        "always-comb": (True, "")}


def test_parse_rules_plus_prefix():
    assert bd.parse_rules("+no-tabs\n")["no-tabs"] == (True, "")


def test_diff_rules_detects_new_configurability():
    changes = bd.diff_rules(bd.parse_rules(RULES_OLD), bd.parse_rules(RULES_NEW))
    assert any("`generate-label-prefix` is now configurable" in c for c in changes)


def test_diff_rules_detects_added_and_default_change():
    changes = bd.diff_rules(bd.parse_rules(RULES_OLD), bd.parse_rules(RULES_NEW))
    assert any("new lint rule `brand-new-rule` (on by default)" in c for c in changes)
    assert any("`line-length` default config: `length:100` → `length:120`" in c
               for c in changes)


def test_diff_rules_detects_removal_and_enablement_flip():
    old = bd.parse_rules("gone-rule\n-signal-name-style\n")
    new = bd.parse_rules("signal-name-style\n")
    changes = bd.diff_rules(old, new)
    assert any("`gone-rule` removed" in c for c in changes)
    assert any("`signal-name-style` is now on by default" in c for c in changes)


def test_diff_rules_identical_is_empty():
    parsed = bd.parse_rules(RULES_NEW)
    assert bd.diff_rules(parsed, parsed) == []


# --------------------------------------------------------------------------- #
# --helpfull
# --------------------------------------------------------------------------- #
HELP_OLD = """\
verible-verilog-format: usage: verible-verilog-format [options] <file>...

  Flags from external/abseil-cpp~/absl/flags/parse.cc:
    --flagfile (comma-separated list of files to load flags from); default: ;
    --undefok (comma-separated list of flag names); default: ;

  Flags from verible/common/formatting/basic-format-style-init.cc:
    --column_limit (Target line length limit to stay under when formatting.);
      default: 100;
    --indentation_spaces (Each indentation level adds this many spaces.);
      default: 2;

  Flags from verible/verilog/tools/formatter/verilog-format.cc:
    --failsafe_success (If true, always exit with 0 status, even if there were
      input errors or internal errors. In all error conditions, the original
      text is always preserved.); default: true;
    --inplace (If true, overwrite the input file on successful conditions.);
      default: false;
"""

HELP_NEW = HELP_OLD.replace(
    "    --inplace (If true, overwrite the input file on successful conditions.);\n"
    "      default: false;\n",
    "    --inplace (If true, overwrite the input file on successful conditions.);\n"
    "      default: false;\n"
    "    --class_parameter_space (Space around class parameters.);\n"
    "      default: false;\n",
).replace("default: 100;", "default: 120;")


def test_parse_flags_reads_wrapped_defaults():
    flags = bd.parse_flags(HELP_OLD)
    assert flags["column_limit"] == "100"
    assert flags["indentation_spaces"] == "2"
    # The default is several wrapped lines below the flag name.
    assert flags["failsafe_success"] == "true"
    assert flags["inplace"] == "false"


def test_parse_flags_excludes_third_party_flags():
    """abseil's own flags must not appear: a dependency bump is not news."""
    flags = bd.parse_flags(HELP_OLD)
    assert "flagfile" not in flags
    assert "undefok" not in flags


def test_diff_flags_added_and_default_changed():
    changes = bd.diff_flags("verible-verilog-format",
                            bd.parse_flags(HELP_OLD), bd.parse_flags(HELP_NEW))
    assert any("new flag `--class_parameter_space`" in c for c in changes)
    assert any("`--column_limit` default `100` → `120`" in c for c in changes)


def test_diff_flags_removal():
    changes = bd.diff_flags("t", {"gone": "1", "kept": "2"}, {"kept": "2"})
    assert changes == ["`t`: flag `--gone` removed"]


def test_diff_flags_identical_is_empty():
    parsed = bd.parse_flags(HELP_NEW)
    assert bd.diff_flags("t", parsed, parsed) == []


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def test_render_no_changes_says_so():
    body = bd.render([], [], "v0.0-4163-g6cce8f19")
    assert "No lint-rule or command-line-flag changes" in body
    assert "v0.0-4163-g6cce8f19" in body


def test_render_groups_rules_and_flags():
    body = bd.render(["rule thing"], ["flag thing"], "v1")
    assert "**Lint rules**" in body
    assert "**Command-line flags**" in body
    assert "- rule thing" in body
    assert "- flag thing" in body
    # The claim the section rests on.
    assert "from the shipped binaries" in body


def test_render_omits_empty_group():
    body = bd.render(["rule thing"], [], "v1")
    assert "**Lint rules**" in body
    assert "**Command-line flags**" not in body


@pytest.mark.parametrize("bin_dir", ["", "/nonexistent"])
def test_collect_on_a_missing_dir_is_empty_not_a_crash(bin_dir):
    rules, flags = bd.collect(bin_dir)
    assert rules == {} and flags == {}
