#!/usr/bin/env python3
"""Statically audit the wiring of a .shortcut: catches the class of Shortcuts bug that is hardest to spot by eye.

## Why it exists

Shortcuts data flow is **bound by UUID** ("use the output of action N"), yet the UI shows it only as a
colored chip. With many menu/condition branches, you get errors like "bound to the output of another
branch". That branch did not run -> the value is empty -> **it silently writes 0 / writes empty, with no
error**. Tapping through on a real device only tests the one path you took.

This script reads the plist and reconciles every reference, covering all branches at once. **It cannot
replace on-device testing** (it cannot reproduce the real behavior of Apple Health / Apple Intelligence);
it is the cheaper gate in front of it.

## The six checks

- **C1 dangling reference**: an ActionOutput references a UUID that does not exist in the file
- **C2 duplicate UUID**: several actions share one UUID (which one a binding points to is undefined)
- **C3 dead variable**: `変数を設定/追加` writes a variable that nothing in the file reads -> computed and thrown away
- **C4 cross-branch reference**: action X references an output from **another, mutually exclusive branch**
  -> always empty on the main path 🔴
- **C5 Health key chain**: reconciles the sample type + unit of `health.quantity.log`; the key it reads through
  `getvalueforkey` must appear literally as `"<key>"` in the prompt of some askllm before it. If the file has
  no askllm, the key part is skipped and one INFO is printed (the unit part still runs)
- **C6 placeholder offset**: every `{offset, 1}` in a token string's `attachmentsByRange` must point at one
  `￼` (U+FFFC) of that string. The offset unit is the **UTF-16 code unit** (NSRange), not the Python code
  point; the two differ only when non-BMP characters such as emoji come before the `￼`. Evidence: in the
  author's project + iCloud corpus, 28 offsets with "a non-BMP character before the `￼`" (in a bookkeeping, a
  Pomodoro timer and a time-tracker shortcut, e.g. `📊今月の予算進捗…`) all match only under UTF-16;
  counted by code point, 28/28 miss (measured 2026-10-10)

C1–C6 are this script's own numbering; they are a different set from the Cxx entry IDs in `problem-log.md`
and do not correspond to them.

## Usage

    python3 audit_wiring.py <file.shortcut>
    python3 audit_wiring.py --selftest      # check the detector itself against a real-device file with known bugs + C6 synthetic strings
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from shortcut_io import open_shortcut  # noqa: E402

_HERE = pathlib.Path(__file__).resolve().parent
ROOT = _HERE.parents[1] if _HERE.parent.name == 'automation' else _HERE.parent   # source checkout: scripts/ · plugin: scripts/
KNOWN_BUGGY = ROOT / 'tests/fixtures/known-buggy.shortcut'

# HealthKit sample type → expected unit. A type not in the table is reported as unknown, not silently let through.
# ⚠️ The values are **Shortcuts' own names**, not the display names of the Health app. Evidence: 摂取エネルギー is
#    'Dietary Calories' in Shortcuts, while the HealthKit loctable gives 'Dietary Energy' (an invalid value;
#    entered into the 「種類」 field it shows empty). To add a type, get candidate English strings by looking up
#    Japanese -> English in `HealthKit.framework/Resources/Localizable-DataTypes.loctable`, **then verify on a real device display** (2026-08-01).
EXPECTED_UNIT = {'Dietary Calories': 'kcal', 'Carbohydrates': 'g',
                 'Protein': 'g', 'Total Fat': 'g',
                 # 2026-08-01 D-25 extension (verified on device with probe-health-types)
                 'Fiber': 'g', 'Vitamin C': 'mg', 'Potassium': 'mg',
                 # 2026-08-06 D-29 extension (type strings come from HealthKit Localizable-DataTypes.loctable)
                 'Calcium': 'mg', 'Iron': 'mg'}

MENU = 'is.workflow.actions.choosefrommenu'
COND = 'is.workflow.actions.conditional'
OBJ = '\ufffc'   # ￼ placeholder (U+FFFC)


def _walk(obj, hit):
    """Recursively find {Type: ActionOutput|Variable} leaves. hit(kind, payload)."""
    if isinstance(obj, dict):
        t = obj.get('Type')
        if t == 'ActionOutput' and 'OutputUUID' in obj:
            hit('output', obj)
        elif t == 'Variable' and 'VariableName' in obj:
            hit('variable', obj)
        for v in obj.values():
            _walk(v, hit)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, hit)


def branch_of(actions: list) -> list:
    """Tag each action with a branch path, e.g. ('menu@88#1', 'cond@49#0').

    ControlFlowMode: 0 = block start, 1 = next branch (menu item / Otherwise), 2 = block end.

    ⚠️ A block's own **start / end** actions get the **outer** path: they always run once control enters
    the block (the menu start action's output, the selected item, is usable in every branch). Putting them
    in their own branch would cause false C4 reports. Only the **content** actions between mode 0 and
    mode 1, or between two mode 1s, carry `#n`.
    """
    paths, stack = [], []      # stack element: [block_id, current branch number]
    for i, act in enumerate(actions):
        ident = act['WFWorkflowActionIdentifier']
        mode = act['WFWorkflowActionParameters'].get('WFControlFlowMode')
        here = tuple(f'{b}#{n}' for b, n in stack)
        if ident in (MENU, COND) and mode == 0:
            paths.append(here)                      # outer path
            stack.append([f'{"menu" if ident == MENU else "cond"}@{i}', 0])
        elif ident in (MENU, COND) and mode == 1 and stack:
            stack[-1][1] += 1
            paths.append(tuple(f'{b}#{n}' for b, n in stack))
        elif ident in (MENU, COND) and mode == 2:
            if stack:
                stack.pop()
            paths.append(tuple(f'{b}#{n}' for b, n in stack))   # outer path
        else:
            paths.append(here)
    return paths


def unreachable_from(src_path: tuple, ref_path: tuple) -> str | None:
    """Whether the referenced action is **not guaranteed** to have run.

    Criterion: `src_path` must be a prefix of `ref_path`. Only then has every branch layer holding the
    referenced action necessarily been passed when the reference happens. Otherwise the referenced action
    sits in a branch the referencing action is not guaranteed to enter.
    Returns a description of the first mismatch, or None (safe).
    """
    if src_path == ref_path[:len(src_path)]:
        return None
    for depth, comp in enumerate(src_path):
        if depth >= len(ref_path):
            return f'{comp} — the referencing action is outside that control block'
        if ref_path[depth] != comp:
            block = comp.rsplit('#', 1)[0]
            return f'{block}: the referenced action is in branch {comp}, the referencing action is in {ref_path[depth]}'
    return None


def _token_strings(obj, acc: list) -> None:
    """Recursively collect token-string Values: {'string': str, 'attachmentsByRange': {...}}."""
    if isinstance(obj, dict):
        if isinstance(obj.get('string'), str) and isinstance(obj.get('attachmentsByRange'), dict):
            acc.append(obj)
        for v in obj.values():
            _token_strings(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _token_strings(v, acc)


def _obj_offsets_utf16(s: str) -> list[int]:
    """UTF-16 code-unit offset of every ￼ in s (a non-BMP character counts as 2)."""
    out, n = [], 0
    for c in s:
        if c == OBJ:
            out.append(n)
        n += 2 if ord(c) > 0xFFFF else 1
    return out


def audit(path: pathlib.Path) -> list[tuple[str, str]]:
    """Return [(level, message)], level ∈ {ERROR, WARN, INFO}. No ERROR/WARN = all clear."""
    return audit_actions(open_shortcut(path)['WFWorkflowActions'])


def audit_actions(actions: list) -> list[tuple[str, str]]:
    paths = branch_of(actions)
    findings = []

    uuid2idx: dict[str, list[int]] = {}
    for i, act in enumerate(actions):
        u = act['WFWorkflowActionParameters'].get('UUID')
        if u:
            uuid2idx.setdefault(u, []).append(i)

    out_refs, var_reads, var_writes = [], {}, {}
    for i, act in enumerate(actions):
        p = act['WFWorkflowActionParameters']
        ident = act['WFWorkflowActionIdentifier']
        if ident.endswith(('setvariable', 'appendvariable')) and 'WFVariableName' in p:
            var_writes.setdefault(p['WFVariableName'], []).append(i)

        def hit(kind, obj, _i=i):
            if kind == 'output':
                out_refs.append((_i, obj['OutputUUID']))
            else:
                var_reads.setdefault(obj['VariableName'], []).append(_i)
        _walk(p, hit)

    # C1 dangling reference
    for i, u in out_refs:
        if u not in uuid2idx:
            findings.append(('ERROR', f'C1 dangling reference: action {i} references {u[:8]}…, that UUID does not exist'))

    # C2 duplicate UUID
    for u, idxs in uuid2idx.items():
        if len(idxs) > 1:
            findings.append(('ERROR', f'C2 duplicate UUID {u[:8]}…: actions {idxs}'))

    # C3 dead variable
    for name, widx in sorted(var_writes.items()):
        if name not in var_reads:
            findings.append(('WARN', f'C3 dead variable「{name}」: written by action {widx}, never read anywhere in the file'))

    # C4 cross-branch reference (the most important)
    for i, u in out_refs:
        for src in uuid2idx.get(u, []):
            why = unreachable_from(paths[src], paths[i])
            if why:
                findings.append((
                    'ERROR',
                    f'C4 cross-branch reference: action {i} '
                    f'({actions[i]["WFWorkflowActionIdentifier"].split(".")[-1]}) '
                    f'references the output of action {src} '
                    f'({actions[src]["WFWorkflowActionIdentifier"].split(".")[-1]}) '
                    f'[{why}] → it has a value only when that branch ran, otherwise it is empty'))

    # C5 Health key chain
    prompts = []                                   # [(action index, prompt text)]
    for i, act in enumerate(actions):
        if act['WFWorkflowActionIdentifier'] != 'is.workflow.actions.askllm':
            continue
        prompt = act['WFWorkflowActionParameters'].get('WFLLMPrompt')
        if isinstance(prompt, dict):
            prompt = prompt.get('Value', {}).get('string', '')
        prompts.append((i, prompt if isinstance(prompt, str) else ''))
    if not prompts:
        findings.append(('INFO', 'C5 key chain skipped: the file has no askllm action (the unit check still runs)'))
    for i, act in enumerate(actions):
        if act['WFWorkflowActionIdentifier'] != 'is.workflow.actions.health.quantity.log':
            continue
        p = act['WFWorkflowActionParameters']
        stype = p.get('WFQuantitySampleType')
        qty = p.get('WFQuantitySampleQuantity', {}).get('Value', {})
        unit, mag = qty.get('Unit'), qty.get('Magnitude', {})
        want = EXPECTED_UNIT.get(stype)
        if want is None:
            findings.append(('WARN', f'C5 action {i}: sample type「{stype}」is not in the known table, unit not checked'))
        elif unit != want:
            findings.append(('ERROR', f'C5 action {i}: {stype} unit should be {want}, got {unit}'))
        src = mag.get('OutputUUID') if isinstance(mag, dict) else None
        srcs = uuid2idx.get(src, []) if src else []
        key = (actions[srcs[0]]['WFWorkflowActionParameters'].get('WFDictionaryKey')
               if srcs else None)
        if key and prompts and not any(f'"{key}"' in s for j, s in prompts if j < i):
            findings.append(('ERROR', f'C5 action {i}: the key「{key}」it reads does not appear as "{key}" in the '
                                      f'prompt of any earlier askllm → it will always be empty'))

    # C6 placeholder offset (unit = UTF-16 code unit; evidence in the module docstring)
    for i, act in enumerate(actions):
        acc = []
        _token_strings(act['WFWorkflowActionParameters'], acc)
        for tok in acc:
            s = tok['string']
            real = _obj_offsets_utf16(s)
            for k in tok['attachmentsByRange']:
                off = int(k.strip('{}').split(',')[0])
                if off not in real:
                    findings.append(('ERROR', f'C6 placeholder offset: action {i} key {k} does not point at a ￼ '
                                              f'(the ￼ in that string are actually at {real}, UTF-16) → the variable renders misplaced or empty'
                                              f' · string starts {s[:30]!r}'))
    return findings


def report(path: pathlib.Path) -> int:
    findings = audit(path)
    issues = [f for f in findings if f[0] != 'INFO']
    if issues:
        print(f'{path.name}: {len(issues)} issue(s)')
    else:
        print(f'✅ {path.name}: wiring audit: all 6 checks clear')
    for level, msg in findings:
        print(f'  {"🔴" if level == "ERROR" else "🟡" if level == "WARN" else "ℹ️"} {msg}')
    return 1 if any(l == 'ERROR' for l, _ in findings) else 0


def selftest() -> int:
    """Check the detector itself with a positive and a negative case (a newly built detector must first be checked against a known answer)."""
    ok = True
    if not KNOWN_BUGGY.exists():   # the plugin export does not ship this file
        print(f'=== selftest: a real-device file with known bugs — skipped: {KNOWN_BUGGY.name} is not present ===')
    else:
        print('=== selftest: a real-device file with known bugs ===')
        findings = audit(KNOWN_BUGGY)
        c4 = [m for l, m in findings if m.startswith('C4')]
        c3 = [m for l, m in findings if m.startswith('C3')]
        # Positive case: must catch the cross-branch reference in the Health write chain
        if not any('health.quantity.log' in m or 'getvalueforkey' in m for m in c4):
            print('  ❌ positive case failed: did not catch the cross-branch reference on the Health chain'); ok = False
        else:
            print(f'  ✅ positive: C4 caught {len(c4)} cross-branch reference(s)')
        if not any('栄養辞書' in m for m in c3):
            print('  ❌ positive case failed: did not catch dead variable「栄養辞書」'); ok = False
        else:
            print('  ✅ positive: C3 caught dead variable「栄養辞書」')
        # Negative case: this file is measured to have no dangling references / no duplicate UUIDs / all units correct, so no false reports
        for code, label in (('C1', 'dangling reference'), ('C2', 'duplicate UUID'), ('C6', 'placeholder offset')):
            n = len([m for _, m in findings if m.startswith(code)])
            if n:
                print(f'  ❌ negative case failed: {label} false positive, {n} found (measured 0 for this file)'); ok = False
            else:
                print(f'  ✅ negative: {label} zero false positives')
        unit_fp = [m for _, m in findings if m.startswith('C5') and 'unit should be' in m]
        if unit_fp:
            print(f'  ❌ negative case failed: unit false positive {unit_fp}'); ok = False
        else:
            print('  ✅ negative: Health unit/key chain zero false positives')

    print('=== selftest: C6 synthetic string (emoji before ￼, pins the UTF-16 unit) ===')
    def one(key):   # '📊 ￼': the UTF-16 offset of ￼ = 3, its code point offset = 2
        return [{'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext',
                 'WFWorkflowActionParameters': {'WFTextActionText': {'Value': {
                     'string': '📊 ￼', 'attachmentsByRange': {key: {'Type': 'Variable'}}}}}}]
    c6 = lambda key: [m for _, m in audit_actions(one(key)) if m.startswith('C6')]
    if not c6('{2, 1}'):
        print('  ❌ positive case failed: offset {2, 1} (code point position) did not report C6'); ok = False
    else:
        print('  ✅ positive: offset off by one → C6 ERROR')
    if c6('{3, 1}'):
        print(f'  ❌ negative case failed: correct offset {{3, 1}} false positive {c6("{3, 1}")}'); ok = False
    else:
        print('  ✅ negative: correct offset zero false positives')
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Statically audit the wiring of a .shortcut; read the plist and reconcile every reference, covering all branches at once: '
                    'C1 dangling reference / C2 duplicate UUID / C3 dead variable / C4 cross-branch reference / C5 Health key chain / '
                    'C6 placeholder offset.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Where it sits in the whole flow: three jobs, three tools, none replaces another:\n'
               '\n'
               '  Before writing   shortcut_action_index.py --list / --dump / --param\n'
               '                   -> does this action, and this parameter value, have a real sample? (asks "may I write it this way?")\n'
               '  After saving     this script <file.shortcut>\n'
               '                   -> who is each UUID bound to, and is it bound to another mutually exclusive branch? (asks "is it wired correctly?")\n'
               '  Semantic regression  product-side per-story invariants + destroy tests\n'
               '                   -> this script cannot catch these (criteria and precedent -> docs/apple_shortcuts_dev_protocol.md §7.9 ⑤)\n'
               '\n'
               '⚠️ All six green ≠ it runs on a real device: the real behavior of Apple Health / Apple Intelligence\n'
               '   can only be tested on a device; this script is the cheaper gate in front of it.\n'
               '\n'
               'C1–C6 are this script\'s own numbering; they are a different set from the Cxx entry IDs in problem-log.md and do not correspond to them.')
    ap.add_argument('shortcut', nargs='?',
                    help='path of the .shortcut to audit (a signed file; the script unpacks AEA1 itself); '
                         'if omitted, --selftest is required')
    ap.add_argument('--selftest', action='store_true',
                    help='check the detector itself with a real-device file with known bugs + C6 synthetic strings; does not read the positional argument above')
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.shortcut:
        ap.error('give a .shortcut, or use --selftest')
    sys.exit(report(pathlib.Path(args.shortcut)))


if __name__ == '__main__':
    main()
