# PRD to QA: the method

Product-independent. The web, agent and Shortcut layers add only what is specific to their product kind.

## Contents

- Step 1: set the test boundary
- Step 2: derive cases from each AC
- Step 3: classify
- Step 4: check coverage (`ac_coverage.py`)
- Step 5: build the regression
- Technique menu
- Test-case template

## Step 1: set the test boundary

Before writing cases, agree where checks can sit and what each can and cannot see. One line per boundary:

```
<boundary> — catches: <…> — cannot catch: <…>
```

Examples: an invariant over the product's source or export (catches wiring, structure; cannot catch rendering or real-world data); a headless run of the real product with a fixed input (catches behaviour; cannot catch device-only layers); a person on a device (catches everything visible; costs a person's time).

Without the "cannot catch" half, a green result reads as more than it proves. Test only externally visible behaviour. A case that depends on how the code is arranged breaks on every refactor and proves nothing about the requirement.

## Step 2: derive cases from each AC

Derive forward from each AC in the PRD, never backward from what was built or changed this round: an axis the round did not touch never enters a matrix derived from the round.

Ask these five questions of every AC:

1. **Boundary values?** Empty set, 0, negative, upper limit, first time, last time. A platform's aggregate over an empty set may return empty, not 0.
2. **How many states, and were the transitions tested?** Testing each state once cannot catch a lost transition.
3. **Which axes does it combine with, and which combinations are left out?** A left-out combination needs a written reason (a waiver, Step 4).
4. **Is this number or shape set by the requirement or by the current implementation?** Values the implementation sets must be derived from one source, not hard-coded into an invariant. An expected value copied from the code's own current output can never fail.
5. **How are this check's false greens ruled out?** Ask it twice. Second pass: for everything the AC depends on (variables, upstream outputs, dictionary keys, files, earlier steps), at run time does it resolve to a value or to empty? Structure right is not the same as having a value: a reference can be legal and point at something that runs later, which is empty at run time. If you cannot name the concrete thing, the PRD is too vague; that is a reason to ask, not to skip the question.

**Three sources of axes**, read from the AC text and not from the implementation:

- parallel enumerations: "A, B or C"; a bracket list; a slash list; an AC with two or more Given/When/Then segments (each segment is a branch);
- state words: empty, none, first time, existing, over the limit, error, fallback;
- quantifiers and thresholds: "N items", "all 24 hours", "greater than 0".

These cues are hints, not an admission list: if nothing matches but the AC has an axis, use judgment. Zero matches means the cue list does not apply to this wording, not that there is no axis.

Two cautions. A slash list can be fields that coexist (one case asserts all) or mutually exclusive options (test each): ask which. A condition joined by "and" is a combination of binary conditions, not N parallel values; recognizing it says there is an axis, not that testing each once is enough, and how far to expand the combinations is a judgment (`ac_coverage.py --pairs` measures which 2-way pairs the selected cases miss).

**Axes take the full set, not this batch's intersection.** Axes belong to the PRD; the batch decides which cells run now. Cells not run are marked waived with a reason, not dropped.

**Every case has three parts together**: concrete input or condition, expected behaviour, scenario. "Test the boundary" is not a case; "open the menu on a day with 0 records, intake shows `0`, not blank" is. A case's oracle is its expected behaviour: a case without one cannot be graded.

Tag each case with one technique from the menu below. Default mix per task of five or more cases: 1 EP, 1 BVA, 1 ADV, 1 UC or ST, and one free slot; at least three distinct techniques.

## Step 3: classify

- **Per AC: deterministic or generative.** Deterministic: the same input gives the same observable result, so a code check can judge it. Generative: a model produces the output, so a model judge or sampled runs are needed (agent layer).
- **Per case: person or machine.** A case goes to a person when it depends on something a machine cannot reach: real device sensors or accounts, camera or photo-library interaction, OS settings, how the UI looks. Merge person cases that can be seen in the same run, and list the checklist by number of runs, not by check item.
- **Everything else goes to a machine**: a fixed-input run with the result read back, plus a variant with a deliberate bug, so the check is shown to go red as well as green.
- **Cheapest layer that catches it.** Put each case at the cheapest layer from Step 1 that can fail on it; a rendered-page case does not need a device, a wiring case does not need a page.
- **A vendor-native capability is not an acceptance item; your use of it is.** If every branch of an axis continues identically and the wiring is machine-checked, do not ask a person to run each branch.

## Step 4: check coverage

```
python3 ac_coverage.py --spec <PRD.md> --cases <matrix.md> [--cases <more>] [--json]
```

(Run from the folder that holds it, or give its path.) The property it checks: every AC in the PRD is named by a case row or explicitly waived.

- **When to run**: after the matrix is written or changed, at each batch start, after the PRD gains an AC.
- **Expected**: last line shows `uncovered 0`, exit code 0. Exit code = number of uncovered ACs, capped at 255. 0 ACs parsed exits 1 with `0 ACs parsed — check the AC ID format`. Capture the exit code directly, not through a pipe.
- `--selftest` checks the tool itself.

**Three parsing conventions:**

1. AC definition: `**AC<m> …**` lines under a `### US-<n>` or `### Story <n>` heading.
2. Coverage: `US-<n> AC<m>` or `Story <n> AC<m>` inside a table row (a line starting with `|`) of the matrix file; `AC1/AC2/AC3` continuation works. Prose mentions do not count: a detector fed by the text it checks is not a detector. A struck-through `~~…~~` row-id cell voids the row.
3. Waiver: `<!-- ac-waive: US-<n> AC<m>[, …] — reason -->`. The reason is required; a bare waiver is listed separately.

**`--pairs`** answers a different question: given cases already cut down, which 2-way pairs of axis values do they miss? It measures only; it generates no cases.

```
python3 ac_coverage.py --pairs --matrix <file> [--matrix <more>] [--json]
```

```
<!-- pairs-axis: entry = A, B, E -->                        axis definition (may span lines and files)
<!-- pairs-axis: state = empty, first, existing -->
| 1 | empty-state record | pairs: entry=A, state=empty |     selected cell, in a table row
<!-- pairs-waive: entry=E, state=existing — unreachable -->   waived pairs, reason required
```

Uncovered pairs = every value pair of every two axes, minus selected, minus waived. Exit code = uncovered pairs plus dangling tokens (a cell naming an undeclared axis or value), capped at 255.

**Boundary of the tool.** It checks that each AC is named, not that the cases test it correctly, and it cannot tell whether the axes were fully extracted (that is Step 2). All green means nothing was silently left out, not that the acceptance is sufficient.

## Step 5: build the regression

- **Machine cases go into a regression suite** that one command runs. Each case becomes one check. Find things by what they are (name, key, identifier), not by position or index.
- **Seen red first.** Before a case enters the suite, run it against a known-good copy and against a deliberately broken copy; it must pass on the first and fail on the second. A check never seen red is not evidence. The expected value comes from the requirement, not from the code's current output.
- **Pending, then must-pass.** Mark a check `pending` until the feature is built and confirmed, then flip it to `must-pass`. The suite's exit code is the number of failing must-pass checks.
- **A real defect gets a case first.** Write a case that reproduces it, see it fail, then fix, then see it pass. The case stays in the suite.
- **Keep it small and stable.** Compare against a stored baseline only where the output is deterministic, and keep the baseline small. Exploratory clicking or a one-off look belongs in acceptance, not in the suite.
- **Regression should sit near 100 percent.** A regression check that fails is either a real break or a stale check; fix whichever it is. Capability tests (can it do this yet) are a separate set.

## Technique menu

Each case carries one label. Other techniques (pairwise, cause-effect, mutation) are allowed if they reduce to one of these.

Deterministic techniques:

- **EP** Equivalence Partitioning: one representative input per class (valid, invalid, edge).
- **BVA** Boundary Value Analysis: min, min+1, max-1, max, off by one.
- **DT** Decision Table: combinations of several conditions.
- **ST** State Transition: state-path coverage, including transitions.
- **UC** Use Case: an end-to-end user journey.
- **ADV** Adversarial: hostile, malformed or anti-pattern input.
- **COMP** Composition: one unit calling another, recursion safety, a new story interacting with earlier ones.
- **HALL** Hallucination Probe: model fabrication detection; required for any case on model-written output.

Techniques for model-driven output:

- **PASSK** Pass@k: k or more sampled runs, report the pass rate.
- **JUDGE** Model-as-judge: a different model grades output that needs a rubric instead of an exact assert.
- **ROBUST** Robustness: reworded or perturbed input, same expected result.
- **SAFE** Safety: injection, contradictory input, claims the product must not accept unverified, hard stops.

Format inside a plan or matrix:

```text
- [ ] T012 [US1] Create user model
  - TC1 [EP] valid email + valid password → user created
  - TC2 [BVA] password length 7 (min is 8) → validation error
  - TC3 [BVA] password length 128 (max) → user created
  - TC4 [ADV] SQL-injection-shaped email → sanitized, nothing executed
  - TC5 [UC] sign up → log in → fetch profile end to end
```

## Test-case template

Use a standalone file per case only when the case needs more than five lines of fixture or is reused across tasks; otherwise write it as one matrix row.

```markdown
# Test Case: TC<n> — <brief title>

**Test Case ID**: TC<n>            (matches the task: T012 → TC1..TC5)
**Linked Task ID**: T<NNN>
**Linked AC**: US-<n> AC<m>        (at least one)
**Created**: <YYYY-MM-DD>
**Status**: Draft | Ready | Passing | Failing | Blocked

## Design technique (pick one)

EP | BVA | DT | ST | UC | ADV | COMP | HALL | PASSK | JUDGE | ROBUST | SAFE

## Pre-conditions

- <state, fixtures or environment that must be true before the run>

## Input

<exact input value, or a fixture reference>

## Expected output / assertion

<observable outcome: output, state change or side effect. A code-level grep does not count.>

## Verification path

- [ ] Machine: runs without a person, fixed input
- [ ] Model-driven: sampled runs graded by a judge from a different model
- [ ] Person: on a device or in a browser (state the hard reason)

## Pass criterion

- Deterministic: output exactly equals expected; or
- Model-driven: pass rate >= <x>, p95 latency <= <s> s, token budget <= <n>, hallucination rate <= <x>

## Notes / known limitations

- <edge cases not covered, flaky conditions, environment dependencies>
```
