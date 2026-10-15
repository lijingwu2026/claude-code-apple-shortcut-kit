#!/usr/bin/env python3
"""Regression invariants for one shortcut product — copy to <product>/scripts/<name>_regression.py and edit.

The write-gate (shortcut_build.py, qa = builtin) runs every <product>/scripts/*regression*.py as
`python3 <script> <built file>` before the file lands; a non-zero exit blocks the build.

Each invariant is one machine-checkable row of the product's specs/ac-matrix.md, written as a function
(actions) -> (ok, detail). The shared library (lib/shortcut_regress.py) supplies the query helpers, the global
invariants IG-1/3/4/5, the must-pass/pending harness and the destroy-test machinery; this file holds only what is
specific to your product. Find actions by what they do (identifier, variable name, dictionary key), never by index:
inserting one action shifts every index after it.

    python3 my_regression.py <file.shortcut>              # exit code = number of failing must-pass invariants
    python3 my_regression.py --selftest <good.shortcut>   # every must-pass must go red when its destroy test breaks it

Every must-pass invariant needs a destroy test (a function that breaks a known-good file in the way the invariant
guards against). Without one, this script refuses to start unless the id is listed in OWED, and it then prints a
warning naming it: an invariant that has never been seen to fail may be checking nothing.
"""
import os
import pathlib
import sys

# The write-gate sets SHORTCUT_KIT_SCRIPTS (the kit's scripts/ directory); when running by hand, set it yourself.
_SCRIPTS = pathlib.Path(os.environ.get('SHORTCUT_KIT_SCRIPTS', str(pathlib.Path(__file__).resolve().parent)))
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS.parent / 'lib'))
from shortcut_io import open_shortcut  # noqa: E402
from audit_wiring import audit_actions  # noqa: E402
from shortcut_regress import (  # noqa: E402
    act_id as ident, var_writers, ig_wiring_errors, ig_bare_refs, ig_resolvable_refs, ig_uuid_form,
    validate_registry, run_invariants, destroy_ids, assert_destroy_coverage, destroy_suite,
    build_parser, target_of, exit_code)


# ── invariants: replace the examples below with your product's ──────────────────

def no_wiring_errors(actions):
    return ig_wiring_errors(audit_actions(actions))


def has_one_result_screen(actions):
    hits = [i for i, a in enumerate(actions) if ident(a) == 'is.workflow.actions.showresult']
    return len(hits) >= 1, f'showresult at {hits}'


# (story, id, description, 'must-pass' | 'pending', note naming the ac-matrix cell it guards, function).
# 'pending' rows are reported, not counted toward the exit code.
INVARIANTS = [
    ('Global', 'IG-1', 'no wiring errors (C1–C6)', 'must-pass', 'all', no_wiring_errors),
    ('Global', 'IG-3', 'every attachment payload is a bare ref', 'must-pass', 'all', ig_bare_refs),
    ('Global', 'IG-4', 'every reference points at an earlier action', 'must-pass', 'all', ig_resolvable_refs),
    ('Global', 'IG-5', 'every UUID is 8-4-4-4-12', 'must-pass', 'all', ig_uuid_form),
    ('Story 1', 'I1-1', 'the result is shown on screen', 'pending', 'US-1 AC1', has_one_result_screen),
]
validate_registry(INVARIANTS)


# ── destroy tests: (tag, invariant id, what is broken, mutate(actions)) ─────────
# mutate() must first assert that the thing it breaks exists, then break it in place.

def _break_one_uuid(actions):
    hits = [i for i, a in enumerate(actions) if a['WFWorkflowActionParameters'].get('UUID')]
    assert hits, 'premise gone: no action has a UUID'
    actions[hits[0]]['WFWorkflowActionParameters']['UUID'] = 'ABC-12345678-0000-000000000001'


DESTROYS = [
    ('D-IG5', 'IG-5', 'one UUID gets the wrong segment lengths', _break_one_uuid),
]
# IG-1, IG-3 and IG-4 have no destroy test yet: add one per invariant, then delete the id from OWED.
OWED = {'IG-1', 'IG-3', 'IG-4'}
assert_destroy_coverage(INVARIANTS, destroy_ids(DESTROYS), OWED)


def selftest(good_file) -> int:
    acts = open_shortcut(good_file)['WFWorkflowActions']
    ok = destroy_suite(DESTROYS, INVARIANTS, acts, lambda fn, a: fn(a))
    print('\n' + ('✅ selftest passed' if ok else '❌ selftest has failures'))
    return 0 if ok else 1


def main() -> int:
    args = build_parser(__doc__.split('\n')[0]).parse_args()
    if args.selftest:
        return selftest(target_of(args, ''))
    if not (args.shortcut or args.target_opt):
        print(__doc__)
        return 2
    actions = open_shortcut(target_of(args, ''))['WFWorkflowActions']
    failed, results = run_invariants(INVARIANTS, lambda fn: fn(actions))
    for _story, iid, desc, status, note, ok, detail in results:
        print(f'  {"✅" if ok is True else ("❌" if status == "must-pass" else "⬜")} {iid} [{note}] {desc} — {detail}')
    must = [r for r in results if r[3] == 'must-pass']
    print(f'must-pass: {len(must) - failed}/{len(must)} passed')
    return exit_code(failed)


if __name__ == '__main__':
    sys.exit(main())
