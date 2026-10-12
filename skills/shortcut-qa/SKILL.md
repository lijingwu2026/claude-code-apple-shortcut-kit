---
name: shortcut-qa
description: "Derives test cases from a shortcut product's acceptance criteria, checks that the case matrix names every criterion, and starts the regression script the write-gate runs. Use when a shortcut product has a PRD with acceptance criteria (US-n / ACm), when choosing which cases need a person on a device, or when the write-gate reports an uncovered criterion."
---

# shortcut-qa — from acceptance criteria to a case matrix the write-gate checks

Used when the project chose `qa = builtin` in `.shortcut-dev.json` (`${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py --setup`).
The write-gate then runs, on every build: `ac_coverage.py` on `<product>/specs/PRD.md` + `<product>/specs/ac-matrix.md`,
then every `<product>/scripts/*regression*.py`. This skill is how those two files get written.
Start the regression script from `${CLAUDE_PLUGIN_ROOT}/templates/regression_template.py`.

## 1. AC → axis → case: ask five questions of every AC

Derive cases forward from each AC in the PRD, not backward from what was built or changed this round: an axis
this round did not touch never enters a matrix derived from the round.

1. **Boundary values?** empty set / 0 / negative / upper limit / first time / last time.
   Example: Shortcuts' Calculate Statistics (Sum) returns an empty value, not 0, for an empty list.
2. **How many states, and were the transitions tested?** Testing each state once cannot catch a lost transition.
3. **Which axes does it combine with, and which combinations are left out?** A left-out combination needs a written reason (a waiver, §3).
4. **Is this number or shape set by the requirement or by the current implementation?** Derive implementation-set values from one source instead of hard-coding them in an invariant.
5. **How are this check's false greens ruled out?** Ask it twice: for everything the AC depends on (variables, upstream outputs, dictionary keys, files), at run time does it resolve to a value or to empty? A reference that is structurally legal but points at an action that runs later is empty on the device.

**Three sources of axes** (read them from the AC text, not the implementation):
parallel enumerations ("A, B or C"; a bracket or slash list; an AC with two or more Given/When/Then segments) ·
state words (empty, none, first time, existing, over the limit, error, fallback) ·
quantifiers and thresholds ("N items", "all 24 hours", "greater than 0").
A slash list can be fields that coexist (one case asserts all) or mutually exclusive options (test each) — ask which.
These cues are hints, not an admission list: if nothing matches but the AC has an axis, use your judgment.

Take the full set of axes from the spec; a batch only decides which cells run now. Cells not run are waived with a reason, not dropped.

Every case has three parts: concrete input or condition + expected behaviour + scenario.
"Test the boundary" is not a case; "open the menu on a day with 0 records → intake shows `0`, not blank" is.
Tag each case with one design technique (equivalence partitioning, boundary values, decision table, state transition, use case, adversarial, composition with earlier stories, …).

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

It checks one property: every AC in the spec is named by a case row or explicitly waived. Exit code = number of
uncovered ACs (capped at 255); 0 ACs parsed → exit 1. Capture the exit code directly, not through a pipe.

- **AC definition**: `**AC<m> …**` lines under a `### US-<n>` or `### Story <n>` heading.
- **Coverage**: `US-<n> AC<m>` or `Story <n> AC<m>` (or the `AC1/AC2` continuation) inside a **table row** of the matrix. Prose mentions do not count; struck-through `~~…~~` text does not count.
- **Waiver**: `<!-- ac-waive: US-<n> AC<m>[, …] — reason -->`; the reason is required.
- `--pairs --matrix <file>`: which 2-way combinations of axis values the selected cells miss (`<!-- pairs-axis: name = v1, v2 -->`, `pairs: name=v` in table rows, `<!-- pairs-waive: … — reason -->`).
- `--selftest` checks the tool itself.

Its boundary: all green means no AC was silently left out. It does not mean the cases test the AC correctly or that the axes were fully extracted (that is §1).

## 4. Regression invariants

Copy `${CLAUDE_PLUGIN_ROOT}/templates/regression_template.py` to `<product>/scripts/<name>_regression.py`.
Each machine row of the matrix becomes one invariant; find actions by what they do, never by index.
Mark an invariant `pending` until its story is built and confirmed on a device, then flip it to `must-pass`.
Exit code = number of failing must-pass invariants, so the write-gate blocks on it.
For each must-pass invariant, break a known-good copy once and see it go red: a check never seen red is not evidence.

## Red flags

- The matrix is organised by which stories were built this round → §1 was skipped.
- A state word is in the AC but no row tests it → an axis was dropped.
- An AC with a bracket list, slash list or several Given/When/Then segments has one row → the enumeration was not extracted.
- "All covered" written without an `ac_coverage.py` exit code → a feeling, not a fact.
- An Apple action's capability is on the person's checklist → §2.
- An earlier batch's AC is missing from this batch's matrix → the next batch can silently break it.
- A waiver whose reason is "later" → that is debt; record it as an open issue.

## Checklist before you hand the matrix over

- [ ] Every AC's axes were taken from the AC text (§1), and every cell not run has a waiver with a reason?
- [ ] `ac_coverage.py` exit code read directly, not through a pipe, and it is 0?
- [ ] Every must-pass invariant was seen red once on a deliberately broken copy (§4)?
