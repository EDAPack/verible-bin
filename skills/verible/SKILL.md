---
name: verible
description: SystemVerilog style linter, formatter, parser and language server from CHIPS Alliance. Use for linting RTL against a configurable 60+ rule style guide, auto-formatting SystemVerilog, checking syntax without elaboration, extracting a parse tree or symbol table as JSON, and serving LSP to an editor. Ships verible-verilog-{lint,format,syntax,project,ls,diff,obfuscate,preprocessor,kythe-extractor,kythe-kzip-writer} and verible-patch-tool.
license: Apache-2.0
version: "1.1.0"
---

# verible — Agent Skill

## When to use this skill
- The user wants their SystemVerilog **formatted** — `verible-verilog-format`
  is the de-facto open-source SV formatter (there is no real competitor).
- The user wants **style linting** — naming conventions, `always_comb` vs
  `always @*`, missing `default:` in a case, parameter casing. 60-odd rules,
  each individually toggleable and parameterizable.
- The user needs to know **"does this parse?"** without building or
  elaborating anything — `verible-verilog-syntax` is fast and needs no
  top module, no include resolution, no macros defined.
- The user wants a **machine-readable parse tree or symbol table** to build
  tooling on — `--export_json` / `verible-verilog-project`.
- The user is setting up **editor integration** — `verible-verilog-ls` speaks
  LSP over stdio.
- The user wants **CI style-gating** of RTL: `--verify` for format,
  `--lint_fatal` for lint.

Do **not** reach for verible when:
- The user wants to **simulate** — that's `verilator` or `iverilog`.
- The user wants **synthesis** or a netlist — that's `yosys`.
- The user wants **semantic/elaboration errors** (width mismatch, unresolved
  hierarchy, unconnected port). Verible is a *syntactic and style* tool; it
  parses per-file and does not elaborate. `verilator --lint-only -Wall` is the
  right tool for semantic lint, and the two are complementary rather than
  overlapping — a mature project runs both.
- The user has **VHDL** — unsupported.

## Core mental model

Every verible tool is a **per-file front end** over one shared SystemVerilog
parser. That single fact explains most of its behavior:

```
   .sv file ──lexer──► tokens ──parser──► concrete syntax tree ──┬──► lint rules
                                                                 ├──► formatter
                                                                 ├──► JSON tree
                                                                 └──► symbol table
```

Consequences worth internalizing before using it:

1. **No elaboration, no project-wide semantics by default.** A file that
   references an undefined module lints clean. Only
   `verible-verilog-project` builds a cross-file symbol table, and it needs an
   explicit ordered file list.
2. **Macros are not expanded** during lint/format. Verible parses
   unexpanded source, which is why it can format code containing `` `ifdef ``
   without needing the defines — and also why a macro that expands to
   syntactically incomplete text will not parse.
3. **The formatter is a fixed point.** Running it on its own output must
   change nothing; `--verify_convergence` (on by default) asserts that. If it
   ever does not converge, that's an upstream bug worth reporting, not
   something to work around.
4. **Exit codes are the interface.** `0`/`1` for clean/violations everywhere,
   with the notable trap in the formatter — see below.

### The one trap that bites everyone

`verible-verilog-format` defaults to `--failsafe_success=true`, meaning **it
exits 0 even when the input failed to parse**, preserving the original text.
Great for an editor-on-save hook; silently useless as a CI gate. A CI check
wants:

```sh
verible-verilog-format --verify rtl/*.sv          # rc 1 == "would reformat"
```

not a diff against `--inplace` output.

## Quick start

```sh
# Does it parse?
verible-verilog-syntax rtl/my_module.sv

# Style lint with the default rule set
verible-verilog-lint rtl/my_module.sv

# Format to stdout / in place
verible-verilog-format rtl/my_module.sv
verible-verilog-format --inplace rtl/*.sv

# CI gates (both exit 1 on failure)
verible-verilog-format --verify rtl/*.sv
verible-verilog-lint rtl/*.sv
```

## The tools

| Binary | What it is for |
|---|---|
| `verible-verilog-lint` | Style lint. `--rules`, `--rules_config`, `--waiver_files`, `--autofix`. |
| `verible-verilog-format` | Formatter. `--inplace`, `--verify`, `--lines N-M`, alignment/indent flags. |
| `verible-verilog-syntax` | Parse check; `--export_json`, `--printtree`, `--printtokens`. |
| `verible-verilog-project` | Cross-file `symbol-table-defs`, `symbol-table-refs`, `file-deps`. |
| `verible-verilog-ls` | Language server (LSP over stdio): diagnostics + format-on-save. |
| `verible-verilog-diff` | Token-level diff. `--mode=format` ignores whitespace; `--mode=obfuscate` compares lengths. |
| `verible-verilog-obfuscate` | Mangles identifiers, preserving whitespace and identifier *lengths* (for shareable bug reports). |
| `verible-verilog-preprocessor` | `preprocess`, `strip-comments`, `generate-variants`. |
| `verible-verilog-kythe-extractor` | Emits Kythe facts for code-search/cross-reference indexing. |
| `verible-verilog-kythe-kzip-writer` | Packages sources + a compilation unit into a Kythe `.kzip`. |
| `verible-patch-tool` | Applies/inspects unified diffs; the partner to `--autofix=patch`. |

## Configuring lint

Three mechanisms, in increasing order of how you should prefer them:

```sh
# 1. ad hoc, on the command line: base set + deltas
verible-verilog-lint --rules=-line-length,+no-tabs,parameter-name-style=localparam_style:ALL_CAPS f.sv

# 2. a checked-in config file
verible-verilog-lint --rules_config .rules.verible_lint f.sv

# 3. the same file, found automatically by walking up from each source file
verible-verilog-lint --rules_config_search f.sv
```

Generate a starting config from the current defaults rather than writing one
by hand — the format is exactly what `--print_rules_file` emits:

```sh
verible-verilog-lint --print_rules_file > .rules.verible_lint
```

In that file (and in `--rules`): a bare name or `+name` enables, `-name`
disables, and `name=key:value;key2:value2` parameterizes. `--ruleset` picks the
base set the deltas apply to: `default`, `all`, or `none`.

To understand a rule you saw in output, ask the binary — do not guess:

```sh
verible-verilog-lint --help_rules=always-comb
verible-verilog-lint --help_rules=all        # all 60+, with parameters
```

**Waivers** are for "this specific line is fine", not "turn the rule off":
`--waiver_files`, or in-source `// verilog_lint: waive <rule>` on the line
before, and `waive-start`/`waive-stop` for a range.

## Autofix

`verible-verilog-lint --autofix=<mode>` can repair a subset of violations:

| Mode | Effect |
|---|---|
| `inplace` | Rewrite the source files directly. |
| `patch` | Write a unified diff to `--autofix_output_file`. |
| `patch-interactive` / `inplace-interactive` | Prompt per fix. |
| `generate-waiver` | Emit a waiver file for everything found — the "adopt verible on a legacy codebase" escape hatch. |

Only rules with a registered fix are fixable; everything else is reported
unchanged. On an existing codebase the sane sequence is: `generate-waiver` to
get to green, then delete waivers as they get fixed.

## Formatting style

There is **no automatic config file** for the formatter; style is flags. Pin
them in a `--flagfile` (an abseil feature every verible tool supports) and
check that in, so the editor, CI and humans cannot disagree:

```sh
# .verible-format.flags
--column_limit=100
--indentation_spaces=2
--wrap_spaces=4
--port_declarations_alignment=align
--named_port_alignment=align
--assignment_statement_alignment=align
```

```sh
verible-verilog-format --flagfile=.verible-format.flags --inplace rtl/*.sv
```

Alignment flags take `align`, `flush-left`, `preserve` or `infer`. `infer`
(the default for several) means "match what the file already does", which is
why a repo can look inconsistent even after formatting — set them explicitly
if you want uniformity.

To format only what changed, `--lines=12-40` (repeatable, cumulative). That is
the right tool for touching a legacy file without a whole-file reformat in the
diff.

## Cross-file work

`verible-verilog-project` is the only tool with a project-wide view, and it
needs to be told what the project is:

```sh
verible-verilog-project symbol-table-defs \
    --file_list_path files.f --file_list_root . \
    --include_dir_paths rtl/include,vendor/include
```

`files.f` is a plain list of paths, **ordered by definition dependency**.
`file-deps` prints the inferred dependency graph, which is the quickest way to
find out why a symbol is not resolving.

## JSON output for tooling

```sh
verible-verilog-syntax --export_json --printtree rtl/f.sv
```

This is the supported way to build on verible without linking it: a stable-ish
CST as JSON. Prefer it over regexing SystemVerilog, always.

## Reference files

- `references/cli-cheatsheet.md` — per-tool flags, exit codes, and the
  copy-paste CI recipes.
- `references/lint-rules.md` — how the rule set is organized, the rules that
  most often need configuring on a real codebase, and waiver syntax.

## Notes on this build

These are upstream's official static binaries, repacked by `verible-bin`. They
are fully static on Linux (no glibc floor, runs on musl/Alpine too). The macOS
build is arm64 only — there is no Intel-Mac binary upstream. Verible versions
look like `v0.0-4294-gc1d8f5e8`; the number is a commit count, not a semantic
version, and upstream releases several times a week.
