# verible CLI cheatsheet

Everything here was checked against the binaries this package ships. Flags are
abseil flags: `--flag=value` and `--flag value` are both accepted, `--helpfull`
lists every flag of a tool, and `--help=<substring>` searches them.

## Exit codes

| Tool | 0 | 1 |
|---|---|---|
| `verible-verilog-syntax` | parsed | syntax/lex error |
| `verible-verilog-lint` | no violations | violations, or syntax error |
| `verible-verilog-format` | **see below** | only with `--verify`, or `--failsafe_success=false` |
| `verible-verilog-diff` | inputs equivalent under `--mode` | differ |

`verible-verilog-format` defaults to `--failsafe_success=true`: a parse failure
still exits 0, with the original text passed through unchanged. That is a
feature for editor-on-save and a bug for CI. Use `--verify` (exit 1 == "would
reformat") to gate, or `--failsafe_success=false` if you want parse failures to
be fatal while still writing output.

`--lint_fatal=false` / `--parse_fatal=false` turn the linter's two failure
classes into reports-without-a-nonzero-exit, for the "collect the report, don't
block the build yet" phase of adoption.

## verible-verilog-lint

```
verible-verilog-lint [options] <file>...
```

| Flag | Notes |
|---|---|
| `--rules=<deltas>` | Comma-separated. `name` / `+name` enable, `-name` disable, `name=k:v;k2:v2` configure. |
| `--ruleset=default\|all\|none` | Base set the `--rules` deltas apply to. |
| `--rules_config=<path>` | Config file. Disables `--rules_config_search`. |
| `--rules_config_search` | Walk up from each source file looking for `.rules.verible_lint`. |
| `--print_rules_file` | Print the current effective rule set in config-file syntax, exit. |
| `--help_rules=all\|<rule>` | Documentation for rules, including their parameters. |
| `--generate_markdown` | The same, as Markdown, for docs generation. |
| `--waiver_files=<paths>` | Comma-separated waiver files. |
| `--autofix=<mode>` | `no`, `patch`, `patch-interactive`, `inplace`, `inplace-interactive`, `generate-waiver`. |
| `--autofix_output_file=<p>` | Destination for `patch` / `generate-waiver`. |
| `--check_syntax=false` | Report style only, ignore lexical/syntax errors. |
| `--show_diagnostic_context` | Print the offending source line plus a position marker. |

## verible-verilog-format

```
verible-verilog-format [options] <file>...      # stdout unless --inplace
verible-verilog-format -                        # stdin; name it with --stdin_name
```

| Flag | Notes |
|---|---|
| `--inplace` | Rewrite the files. |
| `--verify` | Change nothing; exit 1 if any file would change. The CI gate. |
| `--lines=N-M` | Format only these 1-based line ranges. Repeatable, cumulative. |
| `--column_limit` | Target line length. |
| `--indentation_spaces` / `--wrap_spaces` | Indent and continuation-indent widths. |
| `--failsafe_success` | Default true; see the exit-code note above. |
| `--verify_convergence` | Default true. Asserts formatting the output again is a no-op. |
| `--max_search_states` | Line-wrap search budget. Raise it only for a file that visibly gives up. |

Alignment flags — each takes `{align, flush-left, preserve, infer}` and most
default to `infer` ("do what this file already does"), which is why unformatted
repos stay visually inconsistent until you set them explicitly:

```
--port_declarations_alignment      --named_port_alignment
--formal_parameters_alignment      --named_parameter_alignment
--parameter_declaration_alignment  --assignment_statement_alignment
--case_items_alignment             --class_member_variable_alignment
--module_net_variable_alignment    --distribution_items_alignment
--enum_assignment_statement_alignment
--struct_union_members_alignment
```

Indentation flags take `{indent, wrap}`:
`--port_declarations_indentation`, `--named_port_indentation`,
`--formal_parameters_indentation`, `--named_parameter_indentation`.

Keep the whole style in one `--flagfile` and check it in:

```sh
verible-verilog-format --flagfile=.verible-format.flags --inplace rtl/*.sv
```

## verible-verilog-syntax

| Flag | Notes |
|---|---|
| `--export_json` | Machine-readable output. Combine with `--printtree`/`--printtokens`. |
| `--printtree` | Concrete syntax tree. |
| `--printtokens` / `--printrawtokens` | Filtered / unfiltered token stream. |
| `--lang=auto\|sv\|lib` | `lib` parses Verilog library-map files (LRM ch. 33). |
| `--error_limit=N` | Cap reported syntax errors (0 = unlimited). |
| `--verifytree` | Report tokens that did not make it into the tree. |

## verible-verilog-project

```
verible-verilog-project <command> [options]
  symbol-table-defs    symbol-table-refs    file-deps
```

| Flag | Notes |
|---|---|
| `--file_list_path` | File list, **ordered by definition dependency**. |
| `--file_list_root` | Prefix the listed relative paths with this. Default `.`. |
| `--include_dir_paths` | Comma-separated include search path, in order. |

## verible-verilog-diff

```
verible-verilog-diff [--mode=format|obfuscate] file1 file2     # - is stdin
```

`format` compares token text and ignores whitespace (verify a formatter).
`obfuscate` compares token *lengths* and preserves whitespace (verify an
obfuscation).

## verible-verilog-preprocessor

```
verible-verilog-preprocessor <command> args...
  preprocess    strip-comments    generate-variants
```

`generate-variants` enumerates the `` `ifdef `` variants of a file — useful for
proving every configuration of a parameterized block still parses.

## verible-verilog-obfuscate

```
verible-verilog-obfuscate [options] < original > obfuscated
```

stdin to stdout. Mangles identifiers while preserving whitespace *and*
identifier lengths, so the result still reproduces layout-sensitive bugs and
can be attached to a public bug report. Verify the result with
`verible-verilog-diff --mode=obfuscate`.

## verible-verilog-ls

Language server, LSP over stdio, no arguments. Point an editor at the
executable. It provides diagnostics (lint + syntax), formatting and a symbol
outline.

| Flag | Notes |
|---|---|
| `--file_list_path` | Project file list for cross-file symbols. Default `verible.filelist`. |
| `--variables_in_outline` | Default true; drop variables from the outline with `=false`. |
| `--lsp_enable_hover` | Experimental, off by default. |
| `--push_diagnostic_notifications` | Default true. |

It speaks LSP over stdio only — no sockets, no network.

## CI recipes

```sh
# Formatting gate — no diffing, no temp files
verible-verilog-format --flagfile=.verible-format.flags --verify $(git ls-files '*.sv' '*.svh')

# Lint gate with a checked-in config
verible-verilog-lint --rules_config=.rules.verible_lint --show_diagnostic_context \
    $(git ls-files '*.sv' '*.svh')

# Lint only what this PR touched
git diff --name-only --diff-filter=d origin/main... -- '*.sv' '*.svh' \
    | xargs -r verible-verilog-lint --rules_config=.rules.verible_lint

# Adopt on a legacy codebase: freeze today's violations, then chip away
verible-verilog-lint --autofix=generate-waiver \
    --autofix_output_file=verible.waiver $(git ls-files '*.sv')
```
