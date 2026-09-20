# verible lint rules — shape, configuration, and the ones that actually matter

61 rules ship in this build: 42 on by default, 19 off. The counts and the
enabled/disabled split move with upstream, so treat the lists below as
orientation and ask the binary for ground truth:

```sh
verible-verilog-lint --help_rules=all         # every rule + its parameters
verible-verilog-lint --help_rules=line-length # one rule
verible-verilog-lint --print_rules_file       # the current effective set, as config
```

## Config file syntax

`--print_rules_file` emits exactly the syntax `--rules_config` reads, which is
the same syntax `--rules` takes on the command line:

```
always-comb                                   # enabled (bare name, or +name)
-signal-name-style                            # disabled
line-length=length:120                        # enabled, one parameter
parameter-name-style=localparam_style:ALL_CAPS;parameter_style:ALL_CAPS
```

`;` separates parameters, `:` separates key from value. `--ruleset` chooses
what the deltas apply *to*: `default` (the 42), `all` (every rule), or `none`
(start from nothing and opt in). `--ruleset=none --rules=line-length,no-tabs`
is the honest way to run a two-rule gate.

Discovery: `--rules_config=<path>` names a file explicitly;
`--rules_config_search` instead walks up from each analyzed file looking for
`.rules.verible_lint`, which is what you want in a monorepo where subtrees have
different conventions. Setting `--rules_config` disables the search.

## Rule families

**Naming conventions** — the group you will actually spend time configuring,
because every organization's house style differs. Most take either a named
style or a raw RE2 regex:

| Rule | Default | Note |
|---|---|---|
| `parameter-name-style` | on | `CamelCase` for localparam, `CamelCase\|ALL_CAPS` for parameter. `*_style_regex` params override with RE2. |
| `signal-name-style` | **off** | `[a-z_0-9]+`. Turn on for lower_snake_case enforcement. |
| `enum-name-style`, `struct-union-name-style`, `interface-name-style`, `macro-name-style`, `constraint-name-style` | on | Each with its own `style_regex`. |
| `port-name-suffix` | off | The `_i` / `_o` / `_io` convention (lowRISC style). |
| `dff-name-style` | off | Flop input/output naming (`next`/`d` → `q`/`r`/`ff`). |
| `module-filename`, `package-filename` | on | Declared name must match the file's first dot-delimited component. `allow-dash-for-underscore` relaxes it. |

**Correctness-adjacent** — these catch real bugs, not just style, and are the
reason to run verible even if you don't care about formatting:

`case-missing-default`, `always-comb-blocking`, `always-ff-non-blocking`,
`truncated-numeric-literal`, `undersized-binary-literal`,
`suggest-parentheses`, `invalid-system-task-function`, `void-cast`,
`packed-dimensions-range-ordering`, `unpacked-dimensions-range-ordering`,
`plusarg-assignment`, `forbid-defparam`.

**Legacy-Verilog hygiene** — `always-comb` (no `always @*`), `v2001-generate-begin`,
`legacy-generate-region`, `legacy-genvar-declaration`, `typedef-enums`,
`typedef-structs-unions`, `explicit-parameter-storage-type`,
`explicit-function-lifetime`, `explicit-task-lifetime`.

**Whitespace and layout** — `line-length` (`length`, default 100), `no-tabs`,
`no-trailing-spaces`, `posix-eof`, `forbid-line-continuations`. If you run the
formatter in CI these are mostly redundant; keep `line-length` in sync with the
formatter's `--column_limit` or the two tools will fight.

**Off by default, worth considering** — `one-module-per-file`,
`explicit-begin`, `mismatched-labels`, `endif-comment`, `suspicious-semicolon`,
`instance-shadowing`, `disable-statement`, `forbid-negative-array-dim`,
`uvm-macro-semicolon` (turn on for UVM testbenches),
`banned-declared-name-patterns`, `proper-parameter-declaration`,
`parameter-type-name-style`, `numeric-format-string-style`,
`macro-string-concatenation`.

## Waivers

A waiver silences one *occurrence*; disabling a rule silences all of them.
Prefer waivers for exceptions and rule-disabling for "this convention is not
ours".

In-source, as comments:

```systemverilog
// verilog_lint: waive module-filename
module NotMatchingTheFilename;
endmodule

// verilog_lint: waive-start line-length
   ... a block of generated code ...
// verilog_lint: waive-stop line-length
```

`waive` applies to the *next* line. `waive-start` / `waive-stop` bracket a
region. Both take a rule name; both are checked against real behavior in this
build.

Out-of-source, via `--waiver_files=<paths>` (comma-separated), which keeps
waivers out of the RTL — the right call for vendor or generated code you do not
want to edit.

## Autofix and adoption

```sh
# See what could be fixed, as a patch you can review
verible-verilog-lint --autofix=patch --autofix_output_file=fix.patch rtl/*.sv
verible-patch-tool ...                 # inspect/apply

# Just fix it
verible-verilog-lint --autofix=inplace rtl/*.sv
```

Only rules with a registered fixer participate; the rest are reported and left
alone, so `--autofix=inplace` is not a guarantee of a clean run afterwards.

Adopting verible on an existing codebase, in order:

1. `--autofix=generate-waiver --autofix_output_file=verible.waiver` over the
   whole tree. This freezes today's violations so CI can go green immediately.
2. Wire `--waiver_files=verible.waiver` into the CI invocation. New code is now
   gated; old code is grandfathered.
3. Delete waivers in batches, using `--autofix=inplace` where it helps.

Doing this in the other order — turning on all rules and fixing everything
first — is how verible adoption stalls.

## Interaction with other tools

Verible lints *syntax and style*; it does not elaborate. It will not tell you
about a width mismatch, an unconnected port, a latch inferred from an
incomplete `always_comb`, or an unresolved module. Those need
`verilator --lint-only -Wall`. Running both is the normal setup, and they
overlap very little.
