---
name: shortcut-dev
description: "Routes Apple Shortcuts work to the right source and tool: the platform protocol, the setting-value lookup in real examples, the wiring audit, and the write-gate that tests and signs a .shortcut file before opening the import dialog. Use when creating or editing a .shortcut file, adding an action or setting the shortcut has not used before, diagnosing a shortcut that signs but fails on the device, or making a shortcut write to Feishu (Lark) Bitable or another web API."
when_to_use: "Requests to create, change or debug a shortcut in Apple Shortcuts (the Shortcuts app on Mac or iPhone). Also on these literal tokens: .shortcut, .wflow, WFWorkflowActions, WFWorkflowMinimumClientVersion, WFTextTokenString, shortcut_io.py, audit_wiring.py, shortcut_action_index.py."
scripts_routing: "NO — the four scripts already live in ${CLAUDE_PLUGIN_ROOT}/scripts/ (shortcut_io / audit_wiring / shortcut_action_index / shortcut_build); this skill only routes and creates no new script"
metadata:
  requires:
    bins: ["python3"]
  cliHelp: "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py --help"
---

# shortcut-dev — routing layer for Apple Shortcuts

**This file answers one question only: where to go for this.** It stores no action identifiers, parameter key names, field schemas or value enumerations.

🚩 Red flag: about to copy a parameter key name or identifier from **this file** into an artifact — this file has none, so whatever you copy was made up in your head.
🚩 Red flag (for whoever edits this file next): about to add a field table or a protocol summary here — nobody will sync it back when the source of truth changes.
First ask: can this be had by running `--help` once or opening the protocol? If yes → write only "where to get it".

## 1. Read the platform protocol first — nothing else will bring it in

**Read `${CLAUDE_PLUGIN_ROOT}/docs/apple_shortcuts_dev_protocol.md`.** Nothing else loads it, so read it here.
It is long. Pick sections by the question in hand; do not read the whole file:

| Question in hand | Which section to read |
|---|---|
| Should this requirement be a Shortcut, or an App | §1 platform capability limits · §2 hard-constraint list |
| Build one from scratch | §3 development flow, Step 0-5 · §4 testing / verification playbook |
| Make a Shortcut write records into a Feishu (Lark) Bitable | Read `${CLAUDE_PLUGIN_ROOT}/docs/feishu-bitable.md` — auth, body shape, what a `datetime` field accepts, time zone |
| Edit an existing `.shortcut` file | all of §7, **read §7.3 (check the corpus before touching anything) first** (the protocol's own top discipline) |
| Signs fine but does nothing on device / a variable is empty | §7.5 wiring bugs (`audit_wiring.py` C1–C6) · §7.6b `setvariable` does not accept a bare string |
| Run probes headless / automated QA | §7.6 probe hygiene · §7.9 headless QA loop (including the write-to-disk order and the idempotency criteria) |
| Can this step be automated, or must the user do it by hand | §7.10 human/machine split; ask item by item using its C triage criteria |
| Can Apple's official user manual answer it | §6a — the manual answers the concept level and **cannot answer identifiers / parameter key names / container structure** |

## 2. Fill in these slots before you start — each tool answers a different question

**QA choice — read it before building.** The project's `.shortcut-dev.json` (the nearest one above the target file,
else above the current directory) says which QA every build runs: `builtin` (the `shortcut-qa` skill's
`specs/ac-matrix.md` + `scripts/*regression*.py`), `own` (`regression_cmd`, the user's own test command) or `none`
(wiring audit and real-sample check only; no spec or regression tests). Follow it without asking again.
No file → ask the user which of the three they want, then run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --setup --qa <choice>` from the project root (add
`--regression-cmd "<command>"` for `own`); the write-gate refuses to build until the file exists.
If the user picks `none`, state this risk to them before running `--setup --qa none`:
"Without tests, nothing checks the spec's acceptance criteria or your regression script, so a change can break a feature and you see it only when it runs on your iPhone."
With `builtin`, the build stops until the product's `specs/PRD.md` exists, so check for it before the first build; if
it is missing, offer the `shortcut-spec` skill (it interviews the user and writes `specs/PRD.md`) or the user's own
spec from any tool, saved as `specs/PRD.md` with stories as `### US-n` and acceptance criteria as `**ACm …**` lines.
Whatever the QA choice, if `specs/PRD.md` starts with `Status: draft`, show it to the user and get their approval
before building; a `specs/PRD.md` with no Status line is the user's own and counts as approved.

For any `.shortcut` change (a new action / a different parameter value / rewiring), fill slots ①②③ **with readings from real runs, and copy the three filled lines into the answer as they are**.
**While ① is empty, no concrete parameter key or value may appear in the answer** — a value written without running this slot can only be made up in your head.
Shortcuts does not validate parameters and `shortcuts sign` signs anyway; the breakage only shows on a real device. Read protocol §7.3 for the cause and the measurements.

**① Setting-value lookup (Required)** — has a real example used this value successfully **in the target file's own generation**

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" --param "<action>:<parameter key>=<value>" --for "<absolute path of the target .shortcut>"
```

→ Fill: samples in this generation = ______
Read the probe-verified defaults table in protocol §7.3: a setting whose default is listed there can be left out to get that default; any other value still needs a sample.
On 0, never copy an unverified value into the product. First run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_action_index.py" --toolkit "<action>"` (Apple's catalog of legal keys and values, not a sample):
- an enum setting → take route (a)'s best guess from the listed values; a value outside them needs route (b);
- a text, number or bool setting → the catalog confirms only that the key exists;
- a key the catalog doesn't list → it decides nothing; use `--dump` and the two routes.
Then offer the user both routes below with your recommendation:
- **(a) build-and-verify** — when the action runs on a Mac and its effect can be read back (a note's text, a file, returned text): build a `probe-*` shortcut with your best-guess value, read protocol §7.6 and deliver the probe as it says, run it with `shortcuts run "<name>" --output-path <file>`, and check the actual effect, not exit 0 (a wrong value usually falls back to a default silently). Use the value in the product only after the effect matches, and keep the probe `.shortcut` in the project directory (not `archive/` or a scratch dir) so it becomes a corpus sample. A probe whose effect you checked counts as a sample even within 24 h of writing it: the "saved in the last 24h = no corpus" rule exists for files nobody has run. After the probe's effect is checked, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/probe_cleanup.py"`: it deletes the installed `probe-` shortcuts from the Shortcuts app (one Delete click, 「削除」 on a Japanese system; the `.shortcut` file stays as the sample).
- **(b) export** — read protocol §7.3, then use the action once in the Shortcuts app and export it as it says. Required when the action cannot run on a Mac (Health writes, camera, iPhone-only) or its effect cannot be read back.
For an action that has never been used: first `--list <keyword>` to find the identifier, then `--toolkit <action>` for its legal keys and values, then `--dump <action>` to see the full parameters of one real sample, and only then the command above.

**② Structure (Required)** — what the target file looks like now and where this step is inserted

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_io.py" --tree "<absolute path of the target .shortcut>"
```

→ Fill: insertion point = after action number ______

**Writing a patch script**: import the helpers (`tok` / `var` / `out` / `setvar` / `locate` …) from `${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_build.py`, and write to disk only through its `write()`. Its write-gate runs four checks on the temp file before `os.replace`: audit_wiring, ac_coverage, the regression script, and the real-sample check on action identifiers the source file does not already use; for the order and the INFO lines run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/shortcut_build.py" --help`. Do not paste another copy of `tok()` into the script: the old copy counts the `￼` offset by code point, which goes out of alignment after an emoji. Read protocol §7.7 before writing any `WFTextTokenString` by hand.

**③ Wiring (Required — run after writing to disk; if nothing was written this time, fill "not written")**

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit_wiring.py" "<absolute path of the target .shortcut>"
```

→ Fill: C1–C6 readings = ______ (all green ≠ it runs on device; its own epilog states the boundary)

Each tool's epilog says which tier to run and what boundary the tool itself admits (which kinds of "all green" do not count as truly green). If unsure about the arguments, run `--help` first.

**④ Split the on-device slot item by item (Required — fill at wrap-up. It does not map to a tool; it is a triage of the items that "can only be done on device")**

After ①②③ are all green, some of the remaining acceptance items will always need a real device. **Do not file a whole item as "🔴 on device"** —
an acceptance item containing ≥2 **separable judgments** → triage sub-item by sub-item, and leave to the user only the cells that really need the device.
Many halves of a "device only" item are **structural facts** (whether a branch contains a write action / whether there is a screen-type action between two steps) that can be read statically on the Mac.

```
→ Fill: acceptance items produced by this change = ______
→ Fill: of those, settled on the Mac = ______ items, readings = ______
→ Fill: really need importing to a device = ______ items, for each say why the Mac cannot settle this cell
→ Fill: "settled on the Mac" count ≥1? = yes / no　　no → probably not split; go back and split
```

🚩 **Red flag: about to file an acceptance item that has several sub-items as a whole "🔴 on device" / "⬜ not run" without having asked the sentence above for each sub-item.**

**⑤ Delivery (Required — after the write-gate passes and the file is written)**

`shortcut_build.write(..., feature="<the sentence the user will see after installing>")` prints the plist md5 itself after the write-gate passes and pops up the import dialog (only in interactive runs; headless or `SHORTCUT_NO_OPEN=1` only prints that `open` command). An update to a name that is already installed first asks the user to click Delete (「削除」 on a Japanese system) on the old copy, then opens the import for Add (「追加」); on Cancel (「キャンセル」) nothing is imported and the retry command is printed. In the same reply write:

```
→ Fill: tap Add (「追加」 on a Japanese system) now; after installing you will see ______ (= the feature sentence) · plist md5 = ______
```

If the user is not at the Mac → read protocol §7.6, then send this file with SendUserFile, with the same two items in the caption.
Before asking the user to import, check that the file exists. After the user presses Add (「追加」 on a Japanese system), confirm with `shortcuts list` (the user's reply is not needed).
If the user asks how to import, or cannot find the dialog, re-run `open -a Shortcuts <file>` yourself — never give the user manual import steps.

## 3. Experience / usage / QA — these three also have sources of truth, in two layers

| Question in hand | Platform layer (which part of the protocol) | Product layer, the physical thing (the protocol will not tell you where it is) |
|---|---|---|
| Has someone already hit this pitfall | §2.1 platform hard constraints | the product's own pitfall log, if it keeps one (for example `specs/problem-log.md`) |
| How is this action usually wired, could its name be misspelled | §3 appendix on commonly mistaken action names · §7.8 key schema cheat sheet · §6a the manual answers the concept level only | the corpus's catalog layer, and Apple's catalog of legal keys and values (`--toolkit`) (tools: see §2, `--help` first) |
| What should this change verify, and how do I know it is verified | §4 testing / verification playbook (C0-C7 in §4.2 · end-to-end dogfood in §4.4) · §7.9 headless QA loop | that product's `specs/ac-matrix.md` + the regression script in `scripts/` |
| Does shipping a package count as delivered | **No** — §7.9 ①, the "install into the library" cell · the red note on the "`shortcuts` CLI has no import" item in §7.6 | §2 ⑤ of this file |

### How to enter the product layer (three things that do not drift)

1. **The entry is the product's own `specs/`; `ls` it first** — which files exist varies by product, and `ls` shows the current state.
2. **The two that are valuable across products**: `specs/ac-matrix.md` = where QA actually lands · the product's own pitfall log, if it keeps one (for example `specs/problem-log.md`).
3. **`scripts/` records naming conventions only**; do not memorize file names: `build_*` generators · `fix_*` patches · `probe_*` probes · `*regression*` / `run_eval*` regression and eval.

### QA: which file answers which question

The protocol does not cover "when a new story is added, how should the cases be designed"; these files do:

| The one question it answers | Which to read |
|---|---|
| Which cases one AC should split into — extracting axes, designing the technique classification, which cells must be run by the user | `${CLAUDE_PLUGIN_ROOT}/skills/shortcut-qa/SKILL.md` §1 → §2 |
| Does the matrix match the ACs (this is a gate; the criterion is the exit code) | `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ac_coverage.py" --help` |

🚩 Red flag: treating the reconciliation gate's printed `uncovered 0` as verified. **This gate has several documented false-green forms, and each product's `ac-matrix.md` header discipline section records only some of them** — before running it, open the file of **the product you are changing**; do not count on another product's file being complete. The correct way to capture the exit code is in that section too (a pipe swallows it).

## Related

- `${CLAUDE_PLUGIN_ROOT}/docs/apple_shortcuts_dev_protocol.md` — the platform protocol, the target this skill routes to; the source of truth for all technical content

## Checklist before you reply

- [ ] ① Setting-value lookup: "samples in this generation" filled with a real `--param … --for` reading (on 0, route (a) or (b) offered, no value copied)?
- [ ] ② Structure: "insertion point" filled with a real `--tree` reading?
- [ ] ③ Wiring: C1–C6 filled with a real `audit_wiring.py` reading, or "not written"?
- [ ] ④ On-device split: each acceptance item split into sub-items, and the Mac-settled count filled with real readings?
- [ ] ⑤ Delivery: feature sentence and plist md5 filled from the real `write()` output, and the file checked to exist?
