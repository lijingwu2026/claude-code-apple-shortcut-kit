#!/usr/bin/env python3
"""AC → case coverage reconciler (the teeth of the test-design skill).

It answers one question, and only this one:
    Is every AC in the spec **named** by the case matrix, or **explicitly waived**?

This is not a judge of "are the cases well written". It catches **silent omission**
(a whole AC / a whole axis disappears from the matrix, while the reconciliation
paragraph still says "⊇ no gaps"). sourceIncident: 2026-08-01, a nutrition-logging shortcut —
the on-device matrix was derived from "which stories were built this round", not from
the 31 ACs, so US-2 AC4 ("with 0 items, 摂取 [intake] shows 0, not blank") was dropped
entirely, and the user hit it on a real device.

## Three parsing conventions (changing a convention = change it here + sync `references/method.md` §Step 4)

1. **AC definition**: the `**AC<m> ...**` lines under a `### US-<n> ...` **or**
   `### Story <n> ...` heading in the spec file. Both heading styles parse to the
   **same internal key** `US-<n>/AC<m>` (not two key sets), so a matrix that mixes
   both styles still reconciles.
2. **Coverage declaration**: in a **table row** (starting with `|`) of the cases file,
   `US-<n> AC<m>` or `Story <n> AC<m>` appears; the `AC1/AC2/AC3` continuation form is
   supported. **Anything struck through with `~~…~~` does not count**: if the row-id
   cell (the first cell) is struck through as a whole = the whole row is void; struck-through
   fragments in other cells also do not count (a voided row cannot keep endorsing an AC).
3. **Waiver**: `<!-- ac-waive: US-<n> AC<m>[, US-<k> AC<j>...] — reason -->`, reason required.

**A mention in prose does not count toward coverage** (this is the whole reason
convention 2 limits itself to "table rows"): the "reconciliation (⊇ no gaps)" prose
paragraph in the original incident **itself listed a string of AC numbers**. If prose
counted, that self-endorsing text would feed the detector directly — a detector fed by
the text it is supposed to check is not a detector. `--selftest` T4 pins this.

Exit code = number of ACs that are uncovered and not waived, capped at 255 (0 = pass,
usable as a gate; POSIX exit status has only 8 bits, 256 would wrap to 0 = false green).
**Exception: if the spec parses to 0 ACs → exit code 1**, reports
`0 ACs parsed — check the AC ID format` and names the recognized formats, and does not
print `covered 0/0 … uncovered 0`. 0 ACs means "nothing was read" (unrecognized ID style /
wrong file passed), not "all covered".

## `--pairs` sub-mode (a different question; do not mix it up with the above)

The above answers "is each AC named?". `--pairs` answers **another question**: given a
batch of already-trimmed cases (= the chosen combinations of axis values), which
**2-way pairs** do they miss (a minimal implementation of NIST combinatorial coverage
measurement; it generates no new cases, it only measures what the chosen ones miss).

For the format and parsing conventions see `references/method.md` §Step 4; not repeated here.
Exit code = number of uncovered pairs (+ number of dangling tokens), the same semantics
as the AC gate above (capped at 255, 0 = pass).

**Dangling-token check (added 2026-09-06)**: any axis name or value that appears in a
selected cell / waived cell but was never declared by `pairs-axis:` counts as "declaration
and usage do not match" and is no longer silently dropped — the exit code counts it, and
the report names each one. This is not "uncovered" (uncovered means "the axes are right,
that combination was just not chosen"); it means **this coverage reading itself cannot be
trusted**: leaving out an axis declaration = a smaller universe = easier false green.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── Parsing ─────────────────────────────────────────────────────────────────
# Two heading styles for a story: `### US-<n> …` (original) and `### Story <n> …` (a bookkeeping shortcut's PRD).
# Both parse to the **same internal key** `US-<n>/AC<m>` — no two key sets; see module docstring, convention 1.
US_HEADING = re.compile(r"^#{2,4}\s*(?:\*\*)?(?:US-\s?|Story\s+)(\d+)\b")
AC_DEF = re.compile(r"^\s*\*\*AC(\d+)\b(.*)$")
# `US-10 AC1/AC2/AC3` / `Story 10 AC1/AC2/AC3` → base 10, ACs 1,2,3
AC_REF = re.compile(r"(?:US-\s?|Story\s+)(\d+)\s*AC\s*(\d+)((?:\s*/\s*AC\s*\d+)*)")
AC_CONT = re.compile(r"AC\s*(\d+)")
WAIVE = re.compile(r"<!--\s*ac-waive:\s*(.+?)\s*-->", re.DOTALL)
STRIKE = re.compile(r"~~.+?~~")  # strikethrough fragment; matches only inside a single table cell, never across cells

NO_AC_MSG = "0 ACs parsed — check the AC ID format"
FOOTER = ("\n  ⚠️  This tool only checks that each AC is named. It does not check that the cases test it correctly."
          "\n     All green = nothing silently missed, ≠ acceptance is sufficient.")
NO_AC_HINT = (
    "Recognized format: a `### US-<n> …` or `### Story <n> …` heading in the spec, with `**AC<m> …**` lines under it "
    "(e.g. `### US-2 …` + `**AC4 …**`).\n"
    "     Styles like `- AC-1:` / `AC-1.`, or passing the wrong --spec file (such as /dev/null), all parse to 0 ACs."
)


def parse_spec(path: Path) -> dict[str, str]:
    """→ {'US-2/AC4': '<AC title>'}, in file order."""
    acs: dict[str, str] = {}
    current_us: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = US_HEADING.match(line)
        if m:
            current_us = m.group(1)
            continue
        m = AC_DEF.match(line)
        if m and current_us:
            title = m.group(2).replace("**", "").strip(" —-—:：")
            acs[f"US-{current_us}/AC{m.group(1)}"] = title[:70]
    return acs


def _refs_in(text: str) -> set[str]:
    out: set[str] = set()
    for m in AC_REF.finditer(text):
        us = m.group(1)
        out.add(f"US-{us}/AC{m.group(2)}")
        for c in AC_CONT.finditer(m.group(3) or ""):
            out.add(f"US-{us}/AC{c.group(1)}")
    return out


def _is_struck(cell: str) -> bool:
    """The whole cell is struck through by `~~…~~` (nothing left after removing the strikethrough fragments and the `*` `` ` `` decoration)."""
    return bool(STRIKE.search(cell)) and not STRIKE.sub("", cell).strip(" *`")


def _live_row(line: str) -> str:
    """Table row → the text still valid after removing strikethrough fragments; if the row-id cell (first cell) is struck through as a whole = the whole row is void → ''."""
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())]
    cells = [c for c in cells if c]
    if not cells or _is_struck(cells[0]):
        return ""
    return " | ".join(STRIKE.sub(" ", c) for c in cells)


def parse_cases(path: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """→ (covered {ac: [evidence lines...]}, waived {ac: reason})."""
    raw = path.read_text(encoding="utf-8")
    covered: dict[str, list[str]] = {}
    for lineno, line in enumerate(raw.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue  # prose does not count — see module docstring
        for ac in _refs_in(_live_row(line)):  # voided rows / struck-through fragments do not count — see module docstring convention 2
            covered.setdefault(ac, []).append(f"{path.name}:{lineno}")

    waived: dict[str, str] = {}
    for m in WAIVE.finditer(raw):
        body = m.group(1)
        parts = re.split(r"\s+[—–-]{1,2}\s+", body, maxsplit=1)
        reason = parts[1].strip() if len(parts) > 1 else ""
        for ac in _refs_in(parts[0]):
            waived[ac] = reason
    return covered, waived


# ── Report ──────────────────────────────────────────────────────────────────
def run(spec: Path, cases: list[Path]) -> dict:
    acs = parse_spec(spec)
    covered: dict[str, list[str]] = {}
    waived: dict[str, str] = {}
    for c in cases:
        cov, wai = parse_cases(c)
        for k, v in cov.items():
            covered.setdefault(k, []).extend(v)
        waived.update(wai)

    rows = []
    for ac, title in acs.items():
        if ac in covered:
            state = "covered"
        elif ac in waived:
            state = "waived" if waived[ac] else "waived-noreason"
        else:
            state = "UNCOVERED"
        rows.append(
            {
                "ac": ac,
                "title": title,
                "state": state,
                "evidence": covered.get(ac, []),
                "reason": waived.get(ac, ""),
            }
        )
    phantom = sorted((set(covered) | set(waived)) - set(acs))
    return {
        "spec": str(spec),
        "cases": [str(c) for c in cases],
        "total": len(acs),
        "rows": rows,
        "phantom": phantom,
        "uncovered": [r["ac"] for r in rows if r["state"] == "UNCOVERED"],
        "waived_noreason": [r["ac"] for r in rows if r["state"] == "waived-noreason"],
        "error": NO_AC_MSG if not acs else "",
    }


def _cap_exit(n: int) -> int:
    """Cap the exit code at 255: POSIX exit status has only 8 bits, n=256 would wrap to 0 = false green."""
    return min(n, 255)


def ac_exit_code(res: dict) -> int:
    """Exit code: 0 ACs parsed = 1 (the reading cannot be trusted; it is not a pass); otherwise = number of uncovered ACs (capped at 255)."""
    return 1 if res["total"] == 0 else _cap_exit(len(res["uncovered"]))


def pairs_exit_code(res: dict) -> int:
    """--pairs exit code: number of uncovered pairs + number of dangling tokens (capped at 255)."""
    return _cap_exit(len(res["uncovered"]) + len(res["dangling"]))


ICON = {"covered": "✅", "waived": "⚪", "waived-noreason": "🟡", "UNCOVERED": "🔴"}


def report(res: dict) -> None:
    print(f"\n  AC coverage reconciliation — spec: {Path(res['spec']).name}")
    print(f"  cases: {', '.join(Path(c).name for c in res['cases'])}")
    print(f"  {'─' * 66}")
    cur = None
    for r in res["rows"]:
        us = r["ac"].split("/")[0]
        if us != cur:
            cur = us
            print(f"  ── {us} ──")
        line = f"  {ICON[r['state']]} {r['ac']:<14} {r['title']}"
        print(line)
        if r["state"] == "UNCOVERED":
            print("       ↳ no case row names it, and there is no ac-waive waiver")
        elif r["state"] == "waived-noreason":
            print("       ↳ waived but no reason given — a waiver must carry a reason")
        elif r["state"] == "waived":
            print(f"       ↳ waived: {r['reason']}")
    if res["phantom"]:
        print(f"\n  ⚠️  References to ACs that do not exist in the spec (phantoms): {', '.join(res['phantom'])}")
    if res["total"] == 0:
        # Don't print "covered 0/0 … uncovered 0" — with 0 ACs that line reads as a pass; the footer is a definition sentence, still printed (constraints.md C2)
        print(f"\n  🔴 {NO_AC_MSG}\n     {NO_AC_HINT}")
        print(FOOTER)
        return
    n_cov = sum(1 for r in res["rows"] if r["state"] == "covered")
    n_wai = sum(1 for r in res["rows"] if r["state"].startswith("waived"))
    print(
        f"\n  covered {n_cov}/{res['total']}  waived {n_wai}  "
        f"**uncovered {len(res['uncovered'])}**"
    )
    if res["uncovered"]:
        print(f"  🔴 {', '.join(res['uncovered'])}")
    print(FOOTER)


# ── --pairs: 2-way pair coverage measurement (NIST combinatorial coverage measurement) ────
# Format: see references/method.md §Step 4. Three syntax elements:
#   1. Axis definition:  <!-- pairs-axis: <axis name> = <value 1>, <value 2>, ... -->
#   2. Selected cell:    anywhere in a table row (starting with `|`), write `pairs: <axis name>=<value>, <axis name>=<value>`
#   3. Waived cell:      <!-- pairs-waive: <axis name>=<value>, <axis name>=<value> — <reason, required> -->
# A selected / waived cell may assign only some of the axes — the pairs it contributes expand only between the axes it assigns.
# Dangling tokens (an axis name / value never declared by pairs-axis) are no longer silently dropped — run_pairs() collects each one into
# `dangling`, report_pairs() names them, and the exit code counts them. See module docstring, "Dangling-token check".
AXIS_DEF = re.compile(r"<!--\s*pairs-axis:\s*(.+?)\s*=\s*(.+?)\s*-->")
PAIRS_CELL = re.compile(r"pairs:\s*([^|]+?)(?:\s*\||\s*$)")
PAIRS_WAIVE = re.compile(r"<!--\s*pairs-waive:\s*(.+?)\s*-->", re.DOTALL)
ASSIGN = re.compile(r"([^,=]+?)\s*=\s*([^,]+)")

Pair = tuple[str, str, str, str]  # (axis A, value A, axis B, value B), axis A < axis B (sorted)


def parse_axes(path: Path) -> dict[str, list[str]]:
    """→ {'axis name': ['value 1', 'value 2', ...]}; repeated definitions across files are merged, values de-duplicated."""
    axes: dict[str, list[str]] = {}
    for m in AXIS_DEF.finditer(path.read_text(encoding="utf-8")):
        name = m.group(1).strip()
        vals = axes.setdefault(name, [])
        for v in m.group(2).split(","):
            v = v.strip()
            if v and v not in vals:
                vals.append(v)
    return axes


def _parse_assignment(text: str) -> dict[str, str]:
    return {m.group(1).strip(): m.group(2).strip() for m in ASSIGN.finditer(text)}


def parse_cells(
    path: Path,
) -> tuple[list[tuple[int, dict[str, str]]], list[tuple[int, dict[str, str], str]]]:
    """→ (selected cells [(line no., assignment)], [(line no., waived cell, reason), ...]).
    The line numbers are used to locate hits in the dangling-token check; a waiver's line number is the start line of its `<!-- pairs-waive: -->` comment."""
    raw = path.read_text(encoding="utf-8")
    selected: list[tuple[int, dict[str, str]]] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue  # prose does not count — the same discipline as parse_cases()
        m = PAIRS_CELL.search(line)
        if m:
            selected.append((lineno, _parse_assignment(m.group(1))))

    waived: list[tuple[int, dict[str, str], str]] = []
    for m in PAIRS_WAIVE.finditer(raw):
        lineno = raw.count("\n", 0, m.start()) + 1
        body = m.group(1)
        parts = re.split(r"\s+[—–-]{1,2}\s+", body, maxsplit=1)
        reason = parts[1].strip() if len(parts) > 1 else ""
        waived.append((lineno, _parse_assignment(parts[0]), reason))
    return selected, waived


def _pairs_of(assignment: dict[str, str], axes: dict[str, list[str]]) -> set[Pair]:
    """One (partial) assignment → the set of pairs it contributes between each two of its axes. Unknown axes / values are silently dropped."""
    names = sorted(a for a in assignment if a in axes and assignment[a] in axes[a])
    out: set[Pair] = set()
    for i, a1 in enumerate(names):
        for a2 in names[i + 1 :]:
            out.add((a1, assignment[a1], a2, assignment[a2]))
    return out


def _dangling_in_assignment(
    assignment: dict[str, str], axes: dict[str, list[str]]
) -> list[tuple[str, str | None]]:
    """One (partial) assignment → the list of "dangling" (axis name, value) inside it.
    Value None = the axis name itself was never declared by pairs-axis;
    value not None = the axis is declared, but this value is not in that axis's declared value list.
    The complement of the filter in `_pairs_of()` — what that one silently drops, this one reports one by one."""
    out: list[tuple[str, str | None]] = []
    for name, val in assignment.items():
        if name not in axes:
            out.append((name, None))
        elif val not in axes[name]:
            out.append((name, val))
    return out


def all_pairs(axes: dict[str, list[str]]) -> set[Pair]:
    """Axis definitions → the full universe of 2-way pairs (every value combination of every two different axes)."""
    names = sorted(axes)
    universe: set[Pair] = set()
    for i, a1 in enumerate(names):
        for a2 in names[i + 1 :]:
            for v1 in axes[a1]:
                for v2 in axes[a2]:
                    universe.add((a1, v1, a2, v2))
    return universe


def run_pairs(matrix_files: list[Path]) -> dict:
    axes: dict[str, list[str]] = {}
    for f in matrix_files:
        for name, vals in parse_axes(f).items():
            bucket = axes.setdefault(name, [])
            for v in vals:
                if v not in bucket:
                    bucket.append(v)

    universe = all_pairs(axes)
    covered: set[Pair] = set()
    waived: dict[Pair, str] = {}
    dangling: list[dict] = []
    for f in matrix_files:
        selected, wv = parse_cells(f)
        for lineno, cell in selected:
            covered |= _pairs_of(cell, axes)
            for name, val in _dangling_in_assignment(cell, axes):
                dangling.append(
                    {"file": f.name, "line": lineno, "kind": "pairs-cell", "axis": name, "value": val}
                )
        for lineno, assignment, reason in wv:
            for p in _pairs_of(assignment, axes):
                waived[p] = reason
            for name, val in _dangling_in_assignment(assignment, axes):
                dangling.append(
                    {"file": f.name, "line": lineno, "kind": "pairs-waive", "axis": name, "value": val}
                )

    uncovered = sorted(universe - covered - set(waived))
    return {
        "matrix_files": [str(f) for f in matrix_files],
        "axes": axes,
        "universe_size": len(universe),
        "covered": len(covered & universe),
        "waived": len(set(waived) & universe),
        "uncovered": [f"{a1}={v1} × {a2}={v2}" for a1, v1, a2, v2 in uncovered],
        "dangling": dangling,
    }


def report_pairs(res: dict) -> None:
    print(f"\n  Pairs coverage measurement — matrix: {', '.join(Path(f).name for f in res['matrix_files'])}")
    print(f"  axes: {', '.join(f'{k}({len(v)})' for k, v in res['axes'].items())}")
    print(f"  {'─' * 66}")
    if res["dangling"]:
        print(
            "\n  🔴 Declarations and usage do not match, so this coverage reading cannot be trusted "
            "(this is not \"uncovered\" — adding cases cannot fix it; fix the declarations or the literal values first):"
        )
        for d in res["dangling"]:
            loc = f"{d['file']}:{d['line']}"
            if d["value"] is None:
                print(f"       {loc} [{d['kind']}] axis name `{d['axis']}` has no matching pairs-axis declaration")
            else:
                print(f"       {loc} [{d['kind']}] `{d['axis']}={d['value']}` is not among the values declared for that axis")
    print(
        f"  universe {res['universe_size']}  covered {res['covered']}  "
        f"waived {res['waived']}  **uncovered {len(res['uncovered'])}**"
    )
    for p in res["uncovered"]:
        print(f"  🔴 {p}")
    print(
        "\n  ⚠️  This tool only checks which 2-way pairs the selected cells miss, not whether the axes are cut the right way,"
        "\n     and it generates no new cases (it is not a PICT replacement). All green = no silent gaps in the selected cells, ≠ the combinations are generated."
    )


# ── selftest (positive / zero false positives / destroy / prose does not count / waiver) ──────
SPEC_FIX = """### US-1 — 甲
**AC1 一**
**AC2 二**
### US-2 — 乙
**AC1 三**
**AC2 四**
"""

# The same AC set in `### Story <n>` style (the bookkeeping PRD shape). The internal keys must be exactly the same as SPEC_FIX's.
SPEC_FIX_STORY = """### Story 1 — 甲
**AC1 一**
**AC2 二**
### Story 2 — 乙
**AC1 三**
**AC2 四**
"""


def _tmp(tmpdir: Path, name: str, body: str) -> Path:
    p = tmpdir / name
    p.write_text(body, encoding="utf-8")
    return p


def _selftest_ac() -> bool:
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        spec = _tmp(d, "spec.md", SPEC_FIX)

        # T1 positive: missing one must turn red
        c = _tmp(d, "c1.md", "| 1 | case | US-1 AC1/AC2 · US-2 AC1 |\n")
        r = run(spec, [c])
        if r["uncovered"] == ["US-2/AC2"]:
            print("  ✅ T1 positive: the missing US-2/AC2 is caught")
        else:
            print(f"  ❌ T1 failed: expected ['US-2/AC2'], got {r['uncovered']}")
            ok = False

        # T2 zero false positives: full coverage must be all green
        c = _tmp(d, "c2.md", "| 1 | case | US-1 AC1/AC2 |\n| 2 | case | US-2 AC1/AC2 |\n")
        r = run(spec, [c])
        if not r["uncovered"] and not r["phantom"]:
            print("  ✅ T2 zero false positives: full coverage → 0 uncovered, 0 phantoms")
        else:
            print(f"  ❌ T2 failed: {r['uncovered']} / {r['phantom']}")
            ok = False

        # T3 destroy: remove one reference from an already-green matrix, it must turn red
        c = _tmp(d, "c3.md", "| 1 | case | US-1 AC1/AC2 |\n| 2 | case | US-2 AC1 |\n")
        r = run(spec, [c])
        if r["uncovered"] == ["US-2/AC2"]:
            print("  ✅ T3 destroy: reference removed → correctly turns red")
        else:
            print(f"  ❌ T3 failed: {r['uncovered']}")
            ok = False

        # T4 prose does not count — the reason this tool exists, and the easiest place to feed it
        c = _tmp(
            d,
            "c4.md",
            "| 1 | case | US-1 AC1/AC2 |\n\n"
            "**Reconciliation (⊇ no gaps)**: the above covers US-2 AC1/AC2 one by one, nothing missed.\n",
        )
        r = run(spec, [c])
        if set(r["uncovered"]) == {"US-2/AC1", "US-2/AC2"}:
            print("  ✅ T4 prose does not count: the self-endorsement in the reconciliation paragraph did not feed the detector")
        else:
            print(f"  ❌ T4 failed: prose counted as coverage → {r['uncovered']}")
            ok = False

        # T5 waiver: with a reason → out; without a reason → listed separately
        c = _tmp(
            d,
            "c5.md",
            "| 1 | case | US-1 AC1/AC2 |\n"
            "<!-- ac-waive: US-2 AC1 — not touched this batch -->\n"
            "<!-- ac-waive: US-2 AC2 -->\n",
        )
        r = run(spec, [c])
        if not r["uncovered"] and r["waived_noreason"] == ["US-2/AC2"]:
            print("  ✅ T5 waiver: a waiver with a reason is out, a bare waiver is listed separately as 🟡")
        else:
            print(f"  ❌ T5 failed: {r['uncovered']} / {r['waived_noreason']}")
            ok = False

        # T6 phantom: references an AC the spec does not have
        c = _tmp(d, "c6.md", "| 1 | case | US-1 AC1/AC2 · US-2 AC1/AC2 · US-9 AC7 |\n")
        r = run(spec, [c])
        if r["phantom"] == ["US-9/AC7"]:
            print("  ✅ T6 phantom: the reference to nonexistent US-9/AC7 is flagged")
        else:
            print(f"  ❌ T6 failed: {r['phantom']}")
            ok = False

        # T7 Story-style positive: `### Story <n>` heading + `Story <n> AC<m>` reference, missing one must turn red.
        #    The key must still be US-2/AC2 — a changed key means two key sets, which would not match existing matrices.
        spec_story = _tmp(d, "spec_story.md", SPEC_FIX_STORY)
        c = _tmp(d, "c7.md", "| 1 | case | Story 1 AC1/AC2 · Story 2 AC1 |\n")
        r = run(spec_story, [c])
        if r["uncovered"] == ["US-2/AC2"] and not r["phantom"]:
            print("  ✅ T7 Story positive: Story heading + Story reference parse to the same key set, the missing one is caught")
        else:
            print(f"  ❌ T7 failed: uncovered={r['uncovered']} phantom={r['phantom']}")
            ok = False

        # T8 Story-style phantom counter-case: full coverage + one Story 9 AC7 that does not exist in the spec → report only the phantom, not uncovered
        c = _tmp(
            d,
            "c8.md",
            "| 1 | case | Story 1 AC1/AC2 · Story 2 AC1/AC2 · Story 9 AC7 |\n",
        )
        r = run(spec_story, [c])
        if r["phantom"] == ["US-9/AC7"] and not r["uncovered"]:
            print("  ✅ T8 Story phantom: in Story style the nonexistent Story 9 AC7 is flagged, with zero false uncovered")
        else:
            print(f"  ❌ T8 failed: phantom={r['phantom']} uncovered={r['uncovered']}")
            ok = False

        # T9 0 ACs ≠ pass: an unrecognized ID style (`- AC-1:`) and /dev/null must both exit non-zero + report NO_AC_MSG.
        #    Uses the real CLI (subprocess), because the gate is the exit code; the same matrix with a recognizable spec as the control must still give 0.
        import os
        import subprocess

        spec_dash = _tmp(d, "spec_dash.md", "### US-1 — 甲\n- AC-1: 一\n- AC-2: 二\n")
        c = _tmp(d, "c9.md", "| 1 | case | US-1 AC1/AC2 |\n")
        for label, sp in (("`- AC-1:` style", spec_dash), ("/dev/null", Path(os.devnull))):
            p = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--spec", str(sp), "--cases", str(c)],
                capture_output=True,
                text=True,
            )
            if p.returncode != 0 and NO_AC_MSG in p.stdout and "covered 0/0" not in p.stdout:
                print(f"  ✅ T9 0 ACs ({label}): exit code {p.returncode}, reports '{NO_AC_MSG}', did not print 'covered 0/0'")
            else:
                print(f"  ❌ T9 failed ({label}): exit={p.returncode} stdout contains NO_AC_MSG={NO_AC_MSG in p.stdout}")
                ok = False
        ok_spec = _tmp(d, "spec_ok.md", "### US-1 — 甲\n**AC1 一**\n**AC2 二**\n")
        p = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--spec", str(ok_spec), "--cases", str(c)],
            capture_output=True,
            text=True,
        )
        if p.returncode == 0 and NO_AC_MSG not in p.stdout:
            print("  ✅ T9 control: recognizable spec + full coverage → exit code 0, no false 0-AC report")
        else:
            print(f"  ❌ T9 control failed: exit={p.returncode}")
            ok = False

        # T10 struck-through rows do not count as coverage: the row-id cell struck through as a whole (`~~R-6~~`) → the whole row is void; the same row without strikethrough → counts as usual (control)
        c = _tmp(
            d,
            "c10.md",
            "| 1 | case | US-1 AC1/AC2 |\n"
            "| ~~2~~ | ~~case~~ | US-2 AC1 · US-2 AC2 | moved to 3 |\n"
            "| ~~**3**~~ | old case | US-2 AC1 |\n",
        )
        r = run(spec, [c])
        c_ctl = _tmp(d, "c10_ctl.md", "| 1 | case | US-1 AC1/AC2 |\n| 2 | case | US-2 AC1 · US-2 AC2 | moved to 3 |\n")
        r_ctl = run(spec, [c_ctl])
        if set(r["uncovered"]) == {"US-2/AC1", "US-2/AC2"} and not r_ctl["uncovered"]:
            print("  ✅ T10 struck-through rows: a row whose id cell is struck through no longer endorses US-2 AC1/AC2; the control without strikethrough covers as usual")
        else:
            print(f"  ❌ T10 failed: uncovered={r['uncovered']} control uncovered={r_ctl['uncovered']}")
            ok = False

        # T11 AC references struck through inline do not count (`~~US-2 AC1~~`, and `/~~AC2~~` in a continuation); references not struck through still count
        c = _tmp(
            d,
            "c11.md",
            "| 1 | case | US-1 AC1/AC2 |\n"
            "| 2 | case | ~~US-2 AC1~~ → reassigned to US-2 AC2 |\n",
        )
        r = run(spec, [c])
        c = _tmp(d, "c11b.md", "| 1 | case | US-1 AC1/AC2 · US-2 AC1/~~AC2~~ |\n")
        r2 = run(spec, [c])
        if r["uncovered"] == ["US-2/AC1"] and r2["uncovered"] == ["US-2/AC2"]:
            print("  ✅ T11 inline strikethrough: the struck-through US-2 AC1 / the ~~AC2~~ in a continuation do not count, the un-struck US-2 AC2 on the same row still counts")
        else:
            print(f"  ❌ T11 failed: uncovered={r['uncovered']} / {r2['uncovered']}")
            ok = False

        # T12 exit-code cap: 256 uncovered must not wrap to 0 (POSIX exit status is 8 bits). Calls the exit-code function directly, without building a spec with 256 ACs.
        def _res(total: int, n_unc: int) -> dict:
            return {"total": total, "uncovered": [f"US-1/AC{i}" for i in range(n_unc)]}

        got = [ac_exit_code(_res(300, n)) for n in (0, 1, 255, 256, 300)]
        if got == [0, 1, 255, 255, 255]:
            print("  ✅ T12 exit-code cap: 0/1/255/256/300 uncovered → exit codes 0/1/255/255/255, 256 does not wrap to 0")
        else:
            print(f"  ❌ T12 failed: expected [0, 1, 255, 255, 255], got {got}")
            ok = False

    print("\n  " + ("✅ AC selftest all passed" if ok else "❌ AC selftest has failures"))
    return ok


# ── selftest for --pairs (positive: known to miss exactly 2 pairs / counter-case: full coverage → 0 / 4 dangling-token cases) ─────
def _selftest_pairs() -> bool:
    import tempfile

    ok = True
    axes_fix = (
        "<!-- pairs-axis: 入口 = A, B -->\n"
        "<!-- pairs-axis: 状态 = 空, 満 -->\n"
    )
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # P1 positive: 2 axes with 2 values each → 4-cell universe; choose only the 2 diagonal cells → exactly the other 2 pairs must be reported missing
        m = _tmp(
            d,
            "m1.md",
            axes_fix
            + "| 1 | case | pairs: 入口=A, 状态=空 |\n"
            + "| 2 | case | pairs: 入口=B, 状态=満 |\n",
        )
        r = run_pairs([m])
        expected = sorted(["入口=A × 状态=満", "入口=B × 状态=空"])
        if sorted(r["uncovered"]) == expected:
            print("  ✅ P1 positive: 4-cell universe with 2 diagonal cells chosen, exactly the 2 missing pairs are caught, no more, no less")
        else:
            print(f"  ❌ P1 failed: expected {expected}, got {r['uncovered']}")
            ok = False

        # P2 counter-case: add the other 2 cells → fully covered, 0 uncovered
        m = _tmp(
            d,
            "m2.md",
            axes_fix
            + "| 1 | case | pairs: 入口=A, 状态=空 |\n"
            + "| 2 | case | pairs: 入口=B, 状态=満 |\n"
            + "| 3 | case | pairs: 入口=A, 状态=満 |\n"
            + "| 4 | case | pairs: 入口=B, 状态=空 |\n",
        )
        r = run_pairs([m])
        if r["universe_size"] == 4 and not r["uncovered"]:
            print("  ✅ P2 counter-case: all 4 cells covered → 0 uncovered")
        else:
            print(f"  ❌ P2 failed: universe={r['universe_size']} uncovered={r['uncovered']}")
            ok = False

        # P3 waiver: explicitly waive the 2 missing cells from P1 → uncovered goes to zero, without actually selecting them
        m = _tmp(
            d,
            "m3.md",
            axes_fix
            + "| 1 | case | pairs: 入口=A, 状态=空 |\n"
            + "| 2 | case | pairs: 入口=B, 状态=満 |\n"
            + "<!-- pairs-waive: 入口=A, 状态=満 — not tested this batch -->\n"
            + "<!-- pairs-waive: 入口=B, 状态=空 — not tested this batch -->\n",
        )
        r = run_pairs([m])
        if not r["uncovered"] and r["waived"] == 2:
            print("  ✅ P3 waiver: a pairs-waive with a reason clears the remaining 2 missing cells")
        else:
            print(f"  ❌ P3 failed: waived={r['waived']} uncovered={r['uncovered']}")
            ok = False

        # P4 dangling ①: a cell references an axis name never declared by pairs-axis → must name that axis + verdict non-zero
        m = _tmp(
            d,
            "m4.md",
            axes_fix
            + "| 1 | case | pairs: 入口=A, 位置=东 |\n"
            + "| 2 | case | pairs: 入口=B, 状态=満 |\n",
        )
        r = run_pairs([m])
        hit = [
            x for x in r["dangling"]
            if x["kind"] == "pairs-cell" and x["axis"] == "位置" and x["value"] is None
        ]
        if hit and (len(r["uncovered"]) + len(r["dangling"])) > 0:
            print("  ✅ P4 dangling ①: the cell's reference to undeclared axis `位置` is named, verdict non-zero")
        else:
            print(f"  ❌ P4 failed: dangling={r['dangling']}")
            ok = False

        # P5 dangling ②: the axis is declared, but the cell's value is not in the declared list → must name `axis=value` + verdict non-zero
        m = _tmp(
            d,
            "m5.md",
            axes_fix
            + "| 1 | case | pairs: 入口=A, 状态=満溢 |\n"
            + "| 2 | case | pairs: 入口=B, 状态=空 |\n",
        )
        r = run_pairs([m])
        hit = [
            x for x in r["dangling"]
            if x["kind"] == "pairs-cell" and x["axis"] == "状态" and x["value"] == "満溢"
        ]
        if hit and (len(r["uncovered"]) + len(r["dangling"])) > 0:
            print("  ✅ P5 dangling ②: the cell's undeclared value `状态=満溢` is named, verdict non-zero")
        else:
            print(f"  ❌ P5 failed: dangling={r['dangling']}")
            ok = False

        # P6 dangling ③: pairs-waive references an axis name never declared by pairs-axis → same semantics as P4, via the waiver syntax
        m = _tmp(
            d,
            "m6.md",
            axes_fix
            + "| 1 | case | pairs: 入口=A, 状态=空 |\n"
            + "| 2 | case | pairs: 入口=B, 状态=満 |\n"
            + "<!-- pairs-waive: 位置=东, 状态=満 — this combination is known to be unreachable -->\n",
        )
        r = run_pairs([m])
        hit = [
            x for x in r["dangling"]
            if x["kind"] == "pairs-waive" and x["axis"] == "位置" and x["value"] is None
        ]
        if hit and (len(r["uncovered"]) + len(r["dangling"])) > 0:
            print("  ✅ P6 dangling ③: the pairs-waive reference to undeclared axis `位置` is named, verdict non-zero")
        else:
            print(f"  ❌ P6 failed: dangling={r['dangling']}")
            ok = False

        # P7 dangling ④ counter-case: everything declared → 0 dangling + the existing coverage logic works as before (guards against the new check becoming a constant error)
        m = _tmp(
            d,
            "m7.md",
            axes_fix
            + "| 1 | case | pairs: 入口=A, 状态=空 |\n"
            + "| 2 | case | pairs: 入口=B, 状态=満 |\n"
            + "| 3 | case | pairs: 入口=A, 状态=満 |\n"
            + "| 4 | case | pairs: 入口=B, 状态=空 |\n",
        )
        r = run_pairs([m])
        if not r["dangling"] and r["universe_size"] == 4 and not r["uncovered"]:
            print("  ✅ P7 dangling ④ counter-case: everything declared → 0 dangling, existing coverage logic unaffected")
        else:
            print(f"  ❌ P7 failed: dangling={r['dangling']} uncovered={r['uncovered']}")
            ok = False

        # P8 exit-code cap: uncovered + dangling totalling 256 must not wrap to 0
        got = [
            pairs_exit_code({"uncovered": ["x"] * u, "dangling": ["y"] * g})
            for u, g in ((0, 0), (1, 1), (200, 56), (200, 100))
        ]
        if got == [0, 2, 255, 255]:
            print("  ✅ P8 exit-code cap: uncovered+dangling 0/2/256/300 → exit codes 0/2/255/255, 256 does not wrap to 0")
        else:
            print(f"  ❌ P8 failed: expected [0, 2, 255, 255], got {got}")
            ok = False

    print("\n  " + ("✅ pairs selftest all passed" if ok else "❌ pairs selftest has failures"))
    return ok


def selftest() -> int:
    ok = _selftest_ac() and _selftest_pairs()
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="AC → case coverage reconciliation / 2-way pair coverage measurement")
    ap.add_argument("--spec", help="spec containing the AC definitions (e.g. PRD.md)")
    ap.add_argument("--cases", action="append", default=[], help="file containing the case matrix; may be given multiple times")
    ap.add_argument("--pairs", action="store_true", help="switch to the --pairs sub-mode (2-way pair coverage measurement)")
    ap.add_argument(
        "--matrix",
        action="append",
        default=[],
        help="for --pairs: file containing the axis definitions + selected/waived cells; may be given multiple times",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    if a.pairs:
        if not a.matrix:
            ap.error("--pairs mode requires at least one --matrix")
        res = run_pairs([Path(m) for m in a.matrix])
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            report_pairs(res)
        return pairs_exit_code(res)

    if not a.spec or not a.cases:
        ap.error("--spec and at least one --cases are required (or use --selftest / --pairs)")

    res = run(Path(a.spec), [Path(c) for c in a.cases])
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        report(res)
    if a.json and res["error"]:
        print(f"{res['error']}\n{NO_AC_HINT}", file=sys.stderr)
    return ac_exit_code(res)


if __name__ == "__main__":
    sys.exit(main())
