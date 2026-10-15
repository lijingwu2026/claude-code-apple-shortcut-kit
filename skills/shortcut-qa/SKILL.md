---
name: shortcut-qa
description: "Derives test cases from a shortcut product's acceptance criteria, checks that the case matrix names every criterion, and starts the regression script the write-gate runs. Use when a shortcut product has a PRD with acceptance criteria (US-n / ACm), when choosing which cases need a person on a device, or when the write-gate reports an uncovered criterion."
---

# shortcut-qa — from acceptance criteria to a case matrix the write-gate checks

Used when the project chose `qa = builtin` in `.shortcut-dev.json` (`${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py --setup`).
The write-gate then runs, on every build: `ac_coverage.py` on `<product>/specs/PRD.md` + `<product>/specs/ac-matrix.md`,
then every `<product>/scripts/*regression*.py`. This skill is how those two files get written.

The method is product-independent. Read `${CLAUDE_PLUGIN_ROOT}/skills/shortcut-qa/references/method.md` before writing the matrix:
the five steps (test boundary, five questions per AC, classify, coverage, regression), the technique menu and the
test-case template. This file adds only what is specific to Shortcuts.

## 1. Shortcut cues for the five questions

- Boundary value: Calculate Statistics (Sum) returns an empty value, not 0, for an empty list.
- False green: a reference that is structurally legal but points at an action that runs later is empty on the device.
  Wiring that looks right is not a value that exists at run time.

## 2. Triage: which cells need a person, which a machine

```
Does the case depend on real Health read/write, the camera, photo-library interaction,
iOS Settings, or how the UI renders?
├─ yes → a person on a device. Merge cells that can be seen in the same run; list the checklist by number of runs.
└─ no  → a machine: an invariant in scripts/*regression*.py, or a headless probe (fixed input file, result read back),
         plus a variant with a deliberate bug so the check is shown to go red as well as green.
```

An Apple action's own capability is not an acceptance item; your wiring is. If every branch of an axis continues
identically and the wiring is machine-checked, do not ask the person to run each branch.
Details: `${CLAUDE_PLUGIN_ROOT}/docs/apple_shortcuts_dev_protocol.md` §7.10.

## 3. The gate: `ac_coverage.py`

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ac_coverage.py" --spec <product>/specs/PRD.md --cases <product>/specs/ac-matrix.md
```

Exit code 0 is the pass condition; capture it directly, not through a pipe. The parsing conventions (AC definition,
coverage row, waiver, `--pairs`) and what green does not prove are in the method's Step 4.

## 4. Regression invariants

Copy `${CLAUDE_PLUGIN_ROOT}/templates/regression_template.py` to `<product>/scripts/<name>_regression.py`.
It imports `${CLAUDE_PLUGIN_ROOT}/lib/shortcut_regress.py`, which already supplies the query helpers, the global
invariants (wiring errors, bare attachment refs, references to earlier actions only, UUID form), the
`must-pass` / `pending` harness and the destroy-test machinery. Write only the invariants of this product.
Each machine row of the matrix becomes one invariant; find actions by what they do, never by index.
The write-gate calls `python3 <script> <built file>` and blocks on a non-zero exit (the number of failing must-pass invariants).
Every must-pass invariant needs a destroy test; the script refuses to start without one unless its id is listed in `OWED`, which prints a warning on every run until the destroy test is added.

## Red flags

- "All covered" written without an `ac_coverage.py` exit code → a feeling, not a fact.
- An Apple action's capability is on the person's checklist → §2.
- A must-pass invariant with no destroy test → it may check nothing.

## Checklist before you hand the matrix over

- [ ] The method's five questions were asked of every AC, and every cell not run has a waiver with a reason?
- [ ] `ac_coverage.py` exit code read directly, not through a pipe, and it is 0?
- [ ] Every must-pass invariant was seen red once on a deliberately broken copy (§4)?
