#!/usr/bin/env python3
"""Regression invariants for one shortcut product — copy to <product>/scripts/<name>_regression.py and edit.

The write-gate (shortcut_build.py, qa = builtin) runs every <product>/scripts/*regression*.py as
`python3 <script> <built file>` before the file lands; a non-zero exit blocks the build.

Each invariant is one machine-checkable row of the product's specs/ac-matrix.md, written as a function
(actions) -> (ok, detail). Find actions by what they do (identifier, variable name, dictionary key), never by
index: inserting one action shifts every index after it.

    python3 my_regression.py <file.shortcut>    # exit code = number of failing must-pass invariants
"""
import os
import pathlib
import sys

# The write-gate sets SHORTCUT_KIT_SCRIPTS; when running by hand, set it to the kit's scripts/ directory.
sys.path.insert(0, os.environ.get('SHORTCUT_KIT_SCRIPTS', str(pathlib.Path(__file__).resolve().parent)))
from shortcut_io import open_shortcut  # noqa: E402
from audit_wiring import audit_actions  # noqa: E402


def ident(a):
    return a.get('WFWorkflowActionIdentifier', '')


def params(a):
    return a.get('WFWorkflowActionParameters', {})


def writers(actions, name):
    """Indexes of the setvariable actions that write variable `name`."""
    return [i for i, a in enumerate(actions)
            if ident(a) == 'is.workflow.actions.setvariable' and params(a).get('WFVariableName') == name]


# ── invariants: replace these examples with your product's ───────────────────

def no_wiring_errors(actions):
    errs = [m for lv, m in audit_actions(actions) if lv == 'ERROR']
    return not errs, '; '.join(errs) or 'audit_wiring: 0 ERROR'


def has_one_result_screen(actions):
    hits = [i for i, a in enumerate(actions) if ident(a) == 'is.workflow.actions.showresult']
    return len(hits) >= 1, f'showresult at {hits}'


# (id, AC it guards, description, 'must-pass' | 'pending', function). 'pending' rows are reported, not counted.
INVARIANTS = [
    ('IG-1', 'all', 'no wiring errors (C1–C6)', 'must-pass', no_wiring_errors),
    ('I1-1', 'US-1 AC1', 'the result is shown on screen', 'pending', has_one_result_screen),
]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    actions = open_shortcut(sys.argv[1])['WFWorkflowActions']
    failed = 0
    for iid, ac, desc, status, fn in INVARIANTS:
        ok, detail = fn(actions)
        failed += (not ok) and status == 'must-pass'
        print(f'  {"✅" if ok else ("❌" if status == "must-pass" else "⬜")} {iid} [{ac}] {desc} — {detail}')
    must = [r for r in INVARIANTS if r[3] == 'must-pass']
    print(f'must-pass: {len(must) - failed}/{len(must)} passed')
    return min(failed, 255)


if __name__ == '__main__':
    sys.exit(main())
