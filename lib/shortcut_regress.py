#!/usr/bin/env python3
"""Shared regression-test library for `.shortcut` products (import it; do not run it, except `--selftest`).

A product's regression script keeps only the invariants that belong to that product. This library holds the parts
every product needs, so they exist once:

    1. Query helpers   act_id / act_params / writes / var_writers / uuid_index / out_uuid_of / menu_heads /
                       arm_range / direct_indexes / enumerate_paths / walk_refs / walk_attachments.
                       Find an action by what it does (identifier, variable name, dictionary key, menu title),
                       never by index: inserting one action shifts every index after it.
    2. Global invariants   ig_wiring_errors (IG-1) · ig_bare_refs (IG-3) · ig_resolvable_refs (IG-4) ·
                       ig_uuid_form (IG-5). Each is a function `(actions) -> (ok, detail)` that no product-specific
                       fact enters.
    3. Harness         INVARIANTS rows are `(story, id, description, expect, note, fn)`; `expect` is `must-pass`
                       (counts toward the exit code) or `pending` (reported, never counted). validate_registry()
                       rejects any other value, because a third value is silently not counted. run_invariants()
                       turns a raised exception into a failure, never into a silent pass.
    4. Destroy tests   A must-pass invariant whose destroy test has never run is an unverified detector.
                       assert_destroy_coverage() fails at import when a must-pass has none; destroy_suite() runs
                       `(tag, invariant id, what, mutate)` rows: the invariant must be green on the original, the
                       mutation's own precondition must hold, and the invariant must then go red.
    5. Selftests       positive_case() (a known-bad file must fail for the expected reason), negative_case()
                       (a known-good file must raise no false alarm), destroy_suite().
    6. CLI             build_parser() / target_of() / exit_code(): `python3 <script> <file.shortcut>` is the form the
                       write-gate calls; exit code = number of failing must-pass invariants (capped at 255).

Usage in a product script:

    sys.path.insert(0, '<path to this directory>')
    from shortcut_regress import act_id as _id, act_params as _p, run_invariants, validate_registry, ...
"""
import argparse
import copy
import pathlib
import re
import sys

MENU = 'is.workflow.actions.choosefrommenu'
SETVAR = 'is.workflow.actions.setvariable'
DICT = 'is.workflow.actions.dictionary'      # compare exactly: endswith would also match detect.dictionary
GETVAL = 'is.workflow.actions.getvalueforkey'
GETTEXT = 'is.workflow.actions.gettext'
CALC = 'is.workflow.actions.calculateexpression'
FMTNUM = 'is.workflow.actions.format.number'
ASKLLM = 'is.workflow.actions.askllm'

EXPECTS = ('must-pass', 'pending')


# ——————————————————————————— 1. Query helpers ———————————————————————————

def act_params(a):
    return a['WFWorkflowActionParameters']


def act_id(a):
    return a['WFWorkflowActionIdentifier']


_p, _id = act_params, act_id


def ok_fail(cond, good, bad):
    return (True, good) if cond else (False, bad)


def token_string(v):
    """WFTextTokenString / bare str / WFTextTokenAttachment -> (string, {offset: (Type, name)})."""
    if isinstance(v, str):
        return v, {}
    if isinstance(v, dict):
        val = v.get('Value', v)
        if isinstance(val, dict) and 'string' in val:
            atts = {}
            for rng, att in (val.get('attachmentsByRange') or {}).items():
                off = int(rng.strip('{} ').split(',')[0])
                atts[off] = (att.get('Type'),
                             att.get('VariableName') or att.get('OutputUUID'))
            return val['string'], atts
        if isinstance(val, dict) and 'Type' in val:
            return '￼', {0: (val.get('Type'),
                             val.get('VariableName') or val.get('OutputUUID'))}
    return '', {}


def token_text(v):
    return token_string(v)[0]


def token_atts(v):
    """Attachments sorted by offset -> [(Type, name)]."""
    _s, a = token_string(v)
    return [a[k] for k in sorted(a)]


def writes(a):
    """Name of the variable this action writes (setvariable / appendvariable only), else None."""
    if _id(a).endswith(('setvariable', 'appendvariable')):
        return _p(a).get('WFVariableName')
    return None


def uuid_of(a):
    return _p(a).get('UUID')


def uuid_index(acts):
    """{action UUID: [indexes]}."""
    m = {}
    for i, a in enumerate(acts):
        u = _p(a).get('UUID')
        if u:
            m.setdefault(u, []).append(i)
    return m


def var_writers(acts, name):
    """Indexes of every action that writes a variable (setvariable and appendvariable both count)."""
    return [i for i, a in enumerate(acts)
            if _id(a).endswith(('setvariable', 'appendvariable'))
            and _p(a).get('WFVariableName') == name]


def out_uuid_of(param):
    """The OutputUUID of an ActionOutput parameter value (None if absent)."""
    v = param.get('Value') if isinstance(param, dict) else None
    if isinstance(v, dict) and v.get('Type') == 'ActionOutput':
        return v.get('OutputUUID')
    return None


def var_name_of(param):
    """The variable name of a Variable reference parameter value (None if absent)."""
    v = param.get('Value') if isinstance(param, dict) else None
    if isinstance(v, dict) and v.get('Type') == 'Variable':
        return v.get('VariableName')
    return None


def input_uuid(p, key='WFInput'):
    """UUID of the action whose output parameter `key` takes (inline attachment or whole-value reference)."""
    for _t, name in token_atts(p.get(key)):
        if _t == 'ActionOutput':
            return name
    v = p.get(key)
    if isinstance(v, dict):
        val = v.get('Value', {})
        if isinstance(val, dict) and val.get('Type') == 'ActionOutput':
            return val.get('OutputUUID')
    return None


def menu_items(a):
    """Option texts of a choosefrommenu block-start action."""
    return [str(x) for x in _p(a).get('WFMenuItems', [])]


def menu_heads(acts):
    """Every menu head -> [{head, items, prompt, prompt_atts, arms: [(title, idx)], close}]."""
    out = []
    for i, a in enumerate(acts):
        if _id(a) != MENU or _p(a).get('WFControlFlowMode') != 0:
            continue
        g = _p(a)['GroupingIdentifier']
        arms, close = [], None
        for j in range(i + 1, len(acts)):
            q = _p(acts[j])
            if q.get('GroupingIdentifier') != g:
                continue
            if q.get('WFControlFlowMode') == 1:
                arms.append((q.get('WFMenuItemTitle'), j))
            elif q.get('WFControlFlowMode') == 2:
                close = j
                break
        out.append({'head': i, 'items': list(_p(a).get('WFMenuItems') or []),
                    'prompt': token_text(_p(a).get('WFMenuPrompt')),
                    'prompt_atts': token_atts(_p(a).get('WFMenuPrompt')),
                    'arms': arms, 'close': close})
    return out


def arm_range(m, k):
    """[lo, hi) index range of the k-th arm of menu `m` (an element of menu_heads())."""
    lo = m['arms'][k][1] + 1
    hi = m['arms'][k + 1][1] if k + 1 < len(m['arms']) else m['close']
    return lo, hi


def direct_indexes(acts, lo, hi):
    """Indexes in [lo, hi) that belong to this level, leaving out those nested inside a deeper menu.

    Without this, a menu whose arm holds another menu looks as if it wrote everything the inner menu writes.
    """
    inner = [(m['head'], m['close']) for m in menu_heads(acts) if lo <= m['head'] < hi]
    return [i for i in range(lo, hi) if not any(h < i <= c for h, c in inner)]


def enumerate_paths(acts, skip_before=0):
    """Expand nested menus into every walkable path -> [(variables written along the path, path name)]."""
    def walk(lo, hi):
        results = [([], '')]
        i = lo
        while i < hi:
            a, p = acts[i], _p(acts[i])
            if _id(a) == MENU and p.get('WFControlFlowMode') == 0:
                g = p['GroupingIdentifier']
                arms, close = [], None
                for j in range(i + 1, hi):
                    q = _p(acts[j])
                    if q.get('GroupingIdentifier') != g:
                        continue
                    if q.get('WFControlFlowMode') == 1:
                        arms.append((q.get('WFMenuItemTitle'), j))
                    elif q.get('WFControlFlowMode') == 2:
                        close = j
                        break
                assert close is not None, f'menu {g} has no closing action'
                bounds = [j for _, j in arms] + [close]
                sub = []
                for k, (title, start) in enumerate(arms):
                    for vs, name in walk(start + 1, bounds[k + 1]):
                        sub.append((vs, title + (f'>{name}' if name else '')))
                results = [(v0 + v1, (n0 + '>' + n1).strip('>'))
                           for v0, n0 in results for v1, n1 in sub]
                i = close + 1
                continue
            if p.get('WFVariableName') and i >= skip_before:
                results = [(v + [p['WFVariableName']], n) for v, n in results]
            i += 1
        return results
    return walk(0, len(acts))


def walk_refs(o):
    """Yield the OutputUUID of every ActionOutput reference nested in a parameter value."""
    if isinstance(o, dict):
        if o.get('Type') == 'ActionOutput' and isinstance(o.get('OutputUUID'), str):
            yield o['OutputUUID']
        for v in o.values():
            yield from walk_refs(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_refs(v)


def walk_attachments(o):
    """Yield every attachmentsByRange key nested in a parameter value (for counting)."""
    if isinstance(o, dict):
        att = o.get('attachmentsByRange')
        if isinstance(att, dict):
            for k in att:
                yield k
        for v in o.values():
            yield from walk_attachments(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_attachments(v)


# ——————————————————————————— 2. Global invariants ———————————————————————————

def ig_wiring_errors(findings):
    """IG-1: audit_wiring's ERROR level must be 0. `findings` = audit(path) or audit_actions(actions)."""
    errs = [m for lv, m in findings if lv == 'ERROR']
    if errs:
        return False, f'{len(errs)} errors: ' + '; '.join(errs[:2])
    return True, 'C1/C2/C4/C5/C6 have no ERROR'


def ig_bare_refs(acts):
    """IG-3: the payload of every `attachmentsByRange` entry must be a bare ref (with `Type` at the top level).

    Shortcuts serialises "reference the output of another action" in two shapes, and mixing them shows
    「不明な変数」 (unknown variable) on a real device:

    | Position                                                        | Shape                                         |
    |-----------------------------------------------------------------|-----------------------------------------------|
    | Parameter slot (`WFInput` / `WFDictionary` / ...)               | Wrapped `{WFSerializationType, Value:{Type}}` |
    | Inside `attachmentsByRange` (the object placeholder in a text)  | Bare ref `{Type, OutputUUID, OutputName}`     |

    A helper that returns the wrapped shape for parameter slots but is also used inside attachments breaks every
    placeholder it touches. Counting placeholders and checking offsets never looks at the payload structure.
    """
    bad = []

    def scan(o, act_i, ident):
        if isinstance(o, dict):
            att = o.get('attachmentsByRange')
            if isinstance(att, dict):
                for k, v in att.items():
                    if not isinstance(v, dict) or 'Type' not in v:
                        bad.append(f'action {act_i}({ident}) {k}')
            for v in o.values():
                scan(v, act_i, ident)
        elif isinstance(o, list):
            for v in o:
                scan(v, act_i, ident)

    for i, a in enumerate(acts):
        scan(_p(a), i, _id(a).split('.')[-1])

    n_att = sum(1 for a in acts for _ in walk_attachments(_p(a)))
    if bad:
        return False, (f'{len(bad)} attachment payload(s) are not bare refs (a real device would show 「不明な変数」): '
                       + ' · '.join(bad[:4]) + (' …' if len(bad) > 4 else ''))
    return True, f'all {n_att} attachment payloads are bare refs'


def ig_resolvable_refs(acts):
    """IG-4: the target of every ActionOutput reference must exist and come before the referrer.

    IG-3 checks the structure of a reference, not whether it points anywhere. A reference to an action placed after
    the referrer is a reference to an output that has not run yet: it renders empty, and nothing else flags it.

    Honest boundary: it checks position (order) only. Reachability across branches is audit_wiring's job (C4);
    whether the value is right is not checked either.
    """
    pos = {}
    for i, a in enumerate(acts):
        u = _p(a).get('UUID')
        if u:
            pos.setdefault(u, i)

    bad_missing, bad_forward = [], []

    def scan(o, act_i, ident):
        if isinstance(o, dict):
            if o.get('Type') == 'ActionOutput' and isinstance(o.get('OutputUUID'), str):
                tgt = pos.get(o['OutputUUID'])
                if tgt is None:
                    bad_missing.append(f'action {act_i}({ident})→{o["OutputUUID"][:13]}…')
                elif tgt >= act_i:
                    bad_forward.append(f'action {act_i}({ident}) references action {tgt} (which comes after it)')
            for v in o.values():
                scan(v, act_i, ident)
        elif isinstance(o, list):
            for v in o:
                scan(v, act_i, ident)

    n = 0
    for i, a in enumerate(acts):
        scan(_p(a), i, _id(a).split('.')[-1])
    for i, a in enumerate(acts):
        for _ in walk_refs(_p(a)):
            n += 1

    if bad_missing or bad_forward:
        parts = []
        if bad_forward:
            parts.append(f'{len(bad_forward)} reference(s) to an action "placed after itself" (renders empty on a real device): '
                         + ' · '.join(bad_forward[:4]) + (' …' if len(bad_forward) > 4 else ''))
        if bad_missing:
            parts.append(f'{len(bad_missing)} reference(s) to a nonexistent UUID: ' + ' · '.join(bad_missing[:3]))
        return False, '; '.join(parts)
    return True, f'{n} ActionOutput references; all targets exist and all come before the referrer'


_UUID_FORM = re.compile(r'^[0-9A-Za-z]{8}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{12}$')


def ig_uuid_form(acts):
    """IG-5: every UUID has the canonical 8-4-4-4-12 segment structure.

    A generator that emits a UUID with the wrong segment lengths (for example 3-8-4-12) produces a file that still
    runs, but the Shortcuts editor then loads it forever. "The value resolves" and "the string form is canonical" are
    different properties.

    The criterion is the segment structure, not "is it hex": a readable alphanumeric prefix is fine.
    """
    bad = []
    for i, a in enumerate(acts):
        for key, val in _p(a).items():
            if key == 'UUID' and isinstance(val, str) and not _UUID_FORM.match(val):
                bad.append(f'action {i} UUID={val!r}')
    for i, a in enumerate(acts):
        for ou in walk_refs(_p(a)):
            if not _UUID_FORM.match(ou):
                bad.append(f'action {i} OutputUUID={ou!r}')
    if bad:
        return False, (f'{len(bad)} UUID(s) not in canonical 8-4-4-4-12 form: '
                       + ' / '.join(bad[:4]) + (' …' if len(bad) > 4 else ''))
    return True, 'all UUID/OutputUUID are in canonical form'


# ——————————————————————————— 3. Harness ———————————————————————————

def validate_registry(invariants):
    """Reject an `expect` outside EXPECTS and duplicate ids (a third `expect` value is silently not counted)."""
    for _s, i, _d, e, _n, _f in invariants:
        assert e in EXPECTS, f'{i}: expect={e!r} is not in {EXPECTS}'
    assert len({i for _s, i, *_r in invariants}) == len(invariants), 'duplicate invariant id'


def run_invariants(invariants, call):
    """-> (number of failing must-pass, results). `call(fn)` runs one invariant and returns (ok, detail).

    results = [(story, id, description, expect, note, ok, detail)]. `ok` may be True, False or None (None = cannot be
    judged statically); a must-pass counts as failing unless `ok is True`. An invariant that raises is a failure.
    """
    results = []
    for story, iid, desc, expect, note, fn in invariants:
        try:
            ok, detail = call(fn)
        except Exception as e:                    # the assertion itself blowing up = FAIL, never a silent pass
            ok, detail = False, f'invariant raised an exception: {type(e).__name__}: {e}'
        results.append((story, iid, desc, expect, note, ok, detail))
    fails = sum(1 for r in results if r[3] == 'must-pass' and r[5] is not True)
    return fails, results


# ——————————————————————————— 4. Destroy-test registry ———————————————————————————

def destroy_ids(destroys):
    """Invariant ids that have at least one row in a `(tag, invariant id, what, mutate)` list."""
    return {iid for _t, iid, _w, _m in destroys}


def assert_destroy_coverage(invariants, covered, owed=(), stream=None):
    """Every must-pass needs a destroy test: fail (AssertionError) when one has neither a test nor an `owed` entry.

    `owed` = must-pass ids that are let through for now. Each run reports them on `stream` (default stderr): letting
    one through is not an exemption, it puts the debt in the open. The set may only shrink.
    """
    musts = {i for _s, i, _d, e, _n, _f in invariants if e == 'must-pass'}
    uncovered = musts - set(covered) - set(owed)
    assert not uncovered, (
        f'a newly added must-pass has no destroy test, which is the same as adding a check nobody has verified: '
        f'{sorted(uncovered)}. Two ways out: write a destroy test for it, or record it in the owed set for now '
        f'and say why.')
    still_owed = sorted(musts & set(owed))
    if still_owed:
        print(f'⚠️  {len(still_owed)} must-pass invariant(s) still have no destroy test, '
              f'meaning nobody has verified that these checks themselves are alive: {still_owed}',
              file=stream or sys.stderr)


# ——————————————————————————— 5. Selftests ———————————————————————————

def positive_case(results, cases, width=80):
    """A known-bad file: each listed invariant must FAIL. -> ok.

    `cases` = [(invariant id, why it must fail, needle)]. With a needle, the failure detail must also contain it,
    because "red" alone is no evidence the detector is doing its job (it may be red for an unrelated reason).
    """
    ok = True
    got = {i: (o, d) for _s, i, _d, _e, _n, o, d in results}
    for iid, why, needle in cases:
        o, d = got[iid]
        if o is True:
            print(f'  ❌ positive case failed: {iid} should FAIL ({why}) but actually PASSes')
            ok = False
        elif needle is not None and needle not in d:
            print(f'  ❌ positive case failed: {iid} went red but for the wrong reason '
                  f'(expected to contain {needle!r}) — got: {d[:width + 10]}')
            ok = False
        elif needle is None:
            print(f'  ✅ {iid} correctly FAILs — {d[:width]}')
        else:
            print(f'  ✅ {iid} correctly FAILs for the right reason — {d[:width]}')
    return ok


def negative_case(results):
    """A known-good file: no must-pass may fail. -> ok. Prints the false alarms, or the count of green invariants."""
    ok = True
    for _s, iid, _d, expect, _n, o, d in results:
        if expect == 'must-pass' and o is not True:
            print(f'  ❌ negative case failed: {iid} false alarm — {d}')
            ok = False
    if ok:
        print(f'  ✅ {sum(1 for r in results if r[3] == "must-pass")} must-pass invariants all green, zero false alarms')
    return ok


def destroy_suite(destroys, invariants, base_acts, call):
    """Run `(tag, invariant id, what, mutate)` rows against a known-good action list. -> ok.

    For each row, three things are checked, so a destroy test cannot idle green:
      1. the invariant is green on the original actions;
      2. `mutate(actions)` raises no AssertionError (it asserts that the thing it breaks exists);
      3. the invariant is not green on the mutated actions.
    `call(fn, actions)` runs one invariant and returns (ok, detail).
    """
    fn_by_id = {i: f for _s, i, _d, _e, _n, f in invariants}
    ok = True
    print('\n=== destroy tests: artificial regressions, to see whether the assertions really catch them ===')
    print('    (each first checks that the invariant is green on the original and that the premise it breaks exists '
          '— otherwise a destroy test idles green)')
    for tag, iid, what, mut in destroys:
        fn = fn_by_id[iid]
        pre_ok, pre_detail = call(fn, copy.deepcopy(base_acts))
        if pre_ok is not True:
            print(f'  ❌ {tag} idles: {iid} is not green on the **original** ({pre_detail[:60]}) '
                  '— breaking it proves nothing')
            ok = False
            continue
        acts = copy.deepcopy(base_acts)
        try:
            mut(acts)
        except AssertionError as e:
            print(f'  ❌ {tag} idles: {e}')
            ok = False
            continue
        got, detail = call(fn, acts)
        if got is True:
            print(f'  ❌ {tag} failed: {what} → {iid} still PASSes ({detail[:70]})')
            ok = False
        else:
            print(f'  ✅ {tag}: {what} → {iid} correctly goes red')
    return ok


# ——————————————————————————— 6. CLI ———————————————————————————

def build_parser(description):
    """`<script> [file.shortcut] [--target FILE] [--selftest]`; add product-specific options to the result."""
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument('shortcut', nargs='?', help='the .shortcut file to check (the write-gate passes it here)')
    ap.add_argument('--target', dest='target_opt', metavar='FILE', help='same as the positional file')
    ap.add_argument('--selftest', action='store_true', help='verify the detectors themselves')
    return ap


def target_of(args, default):
    """The file to check: positional, else --target, else `default`."""
    return pathlib.Path(args.shortcut or args.target_opt or default)


def exit_code(fails):
    """Exit status for the write-gate: the number of failing must-pass invariants, capped so it cannot wrap to 0."""
    return min(int(fails), 255)


# ——————————————————————————— selftest of this library ———————————————————————————

def _selftest():
    def act(ident, **p):
        return {'WFWorkflowActionIdentifier': 'is.workflow.actions.' + ident, 'WFWorkflowActionParameters': p}

    U1, U2 = 'AAAAAAAA-0000-0000-0000-000000000001', 'AAAAAAAA-0000-0000-0000-000000000002'

    def ref(u):
        return {'Type': 'ActionOutput', 'OutputUUID': u, 'OutputName': 'x'}

    def text_with(u):
        return {'Value': {'string': '￼', 'attachmentsByRange': {'{0, 1}': ref(u)}}}

    good = [act('gettext', UUID=U1, WFTextActionText='a'),
            act('showresult', UUID=U2, Text=text_with(U1))]
    forward = [act('showresult', UUID=U2, Text=text_with(U1)), act('gettext', UUID=U1, WFTextActionText='a')]
    wrapped = [good[0], act('showresult', UUID=U2,
                            Text={'Value': {'string': '￼', 'attachmentsByRange': {
                                '{0, 1}': {'WFSerializationType': 'WFTextTokenAttachment', 'Value': ref(U1)}}}})]
    short_uuid = [act('gettext', UUID='ABC-12345678-0000-000000000001', WFTextActionText='a')]
    checks = [
        ('IG-3 green on a good file', ig_bare_refs(good)[0] is True),
        ('IG-3 red on a wrapped payload', ig_bare_refs(wrapped)[0] is False),
        ('IG-4 green on a good file', ig_resolvable_refs(good)[0] is True),
        ('IG-4 red on a forward reference', ig_resolvable_refs(forward)[0] is False),
        ('IG-5 green on a good file', ig_uuid_form(good)[0] is True),
        ('IG-5 red on a 3-8-4-12 UUID', ig_uuid_form(short_uuid)[0] is False),
        ('IG-1 red on an ERROR finding', ig_wiring_errors([('ERROR', 'x')])[0] is False),
        ('IG-1 green on a WARN finding', ig_wiring_errors([('WARN', 'x')])[0] is True),
        ('registry rejects a third expect value',
         _raises(lambda: validate_registry([('s', 'I-1', 'd', 'must', '', None)]))),
        ('missing destroy test is rejected',
         _raises(lambda: assert_destroy_coverage([('s', 'I-1', 'd', 'must-pass', '', None)], covered=()))),
        ('a raising invariant is a failure',
         run_invariants([('s', 'I-1', 'd', 'must-pass', '', lambda a: 1 / 0)], lambda fn: fn(good))[0] == 1),
        ('exit code is capped', exit_code(300) == 255),
    ]
    ok = True
    for name, passed in checks:
        print(f'  {"✅" if passed else "❌"} {name}')
        ok = ok and passed
    return 0 if ok else 1


def _raises(f):
    try:
        f()
    except AssertionError:
        return True
    return False


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        sys.exit(_selftest())
    print(__doc__)
    sys.exit(2)
