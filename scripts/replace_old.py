#!/usr/bin/env python3
"""Delete every shortcut named exactly NAME (one 削除 click), so importing an update does not add a second copy.

    python3 replace_old.py NAME          # (build kit-replace-old once) → run it with NAME → wait until NAME is gone
    python3 replace_old.py --selftest    # tempdir only; `shortcuts` and `open` replaced by recording stubs

Importing a .shortcut whose name already exists adds a second shortcut with the same name and a new identifier,
and `shortcuts run <name>` then fails (measured on macOS 27.2, 2026-10-11). So in an interactive run,
shortcut_build.write() calls replace() before it opens the import dialog of a shortcut whose name is listed.

The helper `kit-replace-old` (Shortcut Input as text → Get My Shortcuts → keep the names equal to it → Delete
Shortcuts → output their names) is built and added once through probe_cleanup.build(), in the same kit directory.
It runs through `shortcuts://run-shortcut?name=kit-replace-old&input=text&text=<NAME>`; Apple's dialog lists the
shortcuts it will delete — press 削除. `shortcuts list` is polled every 5 s for up to 3 min until NAME is gone.
キャンセル or no answer → GateError: nothing is imported, because the import would add the second copy.

## Exit codes (CLI)

    0  NAME is not in `shortcuts list` (deleted, or never there)
    1  キャンセル or no answer within 3 min; kit-replace-old not added; or a write-gate check failed
"""
import argparse
import contextlib
import io
import json
import os
import pathlib
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import types
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import shortcut_build as sb  # noqa: E402
import probe_cleanup as pc  # noqa: E402
import shortcut_action_index  # noqa: E402

NAME = 'kit-replace-old'
FEATURE = 'deletes every shortcut whose name equals its text input, then lists them'
# Shortcut Input must be enabled for the run-shortcut URL's text to arrive (as in the Gallery sample
# SummarizePDF.wflow, which reads ExtensionInput with WFWorkflowHasShortcutInputVariables true).
HDR = dict(pc.HDR, WFWorkflowHasShortcutInputVariables=True, WFWorkflowInputContentItemClasses=['WFStringContentItem'])
POLL_S, RUN_MAX_S = pc.POLL_S, pc.RUN_MAX_S
SELF = shlex.quote(str(pathlib.Path(__file__).resolve()))


def run_url(name: str) -> str:
    return (f'shortcuts://run-shortcut?name={urllib.parse.quote(NAME)}&input=text'
            f'&text={urllib.parse.quote(name, safe="")}')


def retry(name: str, target=None) -> str:
    cmd = f'python3 {SELF} {shlex.quote(name)}'
    return cmd + (' && ' + shlex.join(['open', '-a', 'Shortcuts', str(target)]) if target else '')


def actions() -> list:
    """probe_cleanup's proven list with the If changed from `begins with probe-` (WFCondition 8) to `is` the input
    (WFCondition 4: string equality, protocol §7.8a; real sample: an If on a menu's 所选项目 `is` '退出' in
    a time-tracker shortcut, action [158]). The input is read through Get Text first, as the names are."""
    u_in, u_get, u_name = sb.uid('replace-in'), sb.uid('replace-get'), sb.uid('replace-name')
    g_rep, g_if = sb.uid('replace-rep'), sb.uid('replace-if')
    return [
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext', 'WFWorkflowActionParameters': {
            'UUID': u_in, 'WFTextActionText': sb.tok('{{i}}', {'i': {'Type': 'ExtensionInput'}})}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.getmyworkflows', 'WFWorkflowActionParameters': {'UUID': u_get}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.repeat.each', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_rep, 'WFControlFlowMode': 0, 'WFInput': sb.attach(sb.out(u_get, 'My Shortcuts'))}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext', 'WFWorkflowActionParameters': {
            'UUID': u_name, 'WFTextActionText': sb.tok('{{i}}', {'i': sb.var('Repeat Item')})}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.conditional', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_if, 'WFCondition': 4, 'WFControlFlowMode': 0,
            'WFConditionalActionString': sb.tok('{{t}}', {'t': sb.out(u_in, 'Text')}),
            'WFInput': {'Type': 'Variable', 'Variable': sb.attach(sb.out(u_name, 'Text'))}}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.appendvariable', 'WFWorkflowActionParameters': {
            'WFInput': sb.attach(sb.var('Repeat Item')), 'WFVariableName': 'Targets'}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.conditional', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_if, 'WFControlFlowMode': 2, 'UUID': sb.uid('replace-if-end')}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.repeat.each', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_rep, 'WFControlFlowMode': 2, 'UUID': sb.uid('replace-rep-end')}},
        {'WFWorkflowActionIdentifier': 'com.apple.shortcuts.DeleteWorkflowAction', 'WFWorkflowActionParameters': {
            'AppIntentDescriptor': {'AppIntentIdentifier': 'DeleteWorkflowAction', 'BundleIdentifier': 'com.apple.shortcuts',
                                    'Name': 'Shortcuts', 'TeamIdentifier': '0000000000'},
            'UUID': sb.uid('replace-delete'), 'entities': sb.attach(sb.var('Targets'))}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext', 'WFWorkflowActionParameters': {
            'UUID': sb.uid('replace-out'), 'WFTextActionText': sb.tok('{{t}}', {'t': sb.var('Targets')})}},
    ]


def listed(name: str) -> bool:
    """False when the `shortcuts` CLI is absent (not a Mac)."""
    return bool(shutil.which('shortcuts')) and name in pc.list_shortcuts()


def replace(name: str, target=None) -> None:
    """Interactive runs: delete every shortcut named `name` before `target` is imported. Returns once `name` is gone
    (or was never listed); otherwise raises GateError, and the caller must open nothing."""
    names = pc.list_shortcuts()
    if name not in names:
        return
    again = retry(name, target)
    if NAME not in names:
        print(f'{name} already exists; adding {NAME} once to replace it')
        if pc.build(NAME, actions(), FEATURE, HDR, rerun=again) is not None:
            raise sb.GateError(f'❌ {NAME} was not added — nothing imported. Add it, then re-run:\n   {again}')
        names = pc.list_shortcuts()
    print(f'{name} already exists: press 削除 to delete the old copy (importing beside it would add a second one)')
    subprocess.run(['open', run_url(name)], capture_output=True)
    deadline = time.monotonic() + RUN_MAX_S
    while name in (after := pc.list_shortcuts()) and time.monotonic() < deadline:
        time.sleep(POLL_S)
    if name in after:
        raise sb.GateError(f'❌ キャンセル or no answer within {RUN_MAX_S // 60} min: {name} is still there, nothing '
                           f'imported. Press 削除 to replace the old copy, then re-run:\n   {again}')
    gone = sorted(set(names) - set(after) - {name})
    if gone:
        print(f'⚠️ also gone from `shortcuts list` meanwhile: {", ".join(gone)}')
    print(f'   old {name} deleted')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 epilog='exit 0 NAME not listed (deleted or never there) · 1 キャンセル / no answer / '
                                        'helper not added / gate failed')
    ap.add_argument('name', nargs='?', help='shortcut name to delete every copy of')
    ap.add_argument('--selftest', action='store_true', help='tempdir-only selftest; never calls the real shortcuts/open')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.name:
        ap.error('give NAME, or --selftest')
    try:
        replace(args.name)
    except sb.GateError as e:
        print(e)
        return 1
    return 0


# ── selftest ─────────────────────────────────────────────────────────────────

def selftest() -> int:
    import replace_old as ro    # shortcut_build.write() imports this module by name, not as __main__
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok &= bool(cond)
        print(f'  {"✅" if cond else "❌"} {label}' + (f'\n{detail}' if detail and not cond else ''))

    print('=== helper actions (in memory) ===')
    cond = [a['WFWorkflowActionParameters'] for a in actions()
            if a['WFWorkflowActionIdentifier'].endswith('conditional') and a['WFWorkflowActionParameters'].get('WFCondition')]
    check('one If: WFCondition 4 (is), compared with the Get Text of Shortcut Input',
          len(cond) == 1 and cond[0]['WFCondition'] == 4
          and list(cond[0]['WFConditionalActionString']['Value']['attachmentsByRange'].values())
          == [sb.out(sb.uid('replace-in'), 'Text')])
    check('header accepts text input', HDR['WFWorkflowHasShortcutInputVariables'] is True
          and HDR['WFWorkflowInputContentItemClasses'] == ['WFStringContentItem'])

    tmp = pathlib.Path(tempfile.mkdtemp(prefix='replace_old_selftest_')).resolve()
    saved = (dict(os.environ), os.getcwd(), sys.stdin, pc.EXAMPLES, shortcut_action_index.PLUGIN_EXAMPLES, ro.RUN_MAX_S)
    ro.RUN_MAX_S = 0  # the stub applies the scenario before the first poll; キャンセル must not wait
    try:
        state, log, open_calls, shim = tmp / 'state.json', tmp / 'shortcuts_calls.txt', tmp / 'open_calls.txt', tmp / 'bin'
        shim.mkdir()
        (shim / 'shortcuts').write_text(
            f'#!{sys.executable}\n'
            'import json, pathlib, sys\n'
            f'with open({str(log)!r}, "a") as f:\n'
            '    f.write(" ".join(sys.argv[1:]) + "\\n")\n'
            'if sys.argv[1:] != ["list"]:\n'
            '    sys.exit(64)\n'
            f'print("\\n".join(json.loads(pathlib.Path({str(state)!r}).read_text())["names"]))\n')
        # Opening the helper file adds it (the Add click); the run URL deletes the exact name unless mode is cancel.
        (shim / 'open').write_text(
            f'#!{sys.executable}\n'
            'import json, pathlib, sys, urllib.parse\n'
            f'with open({str(open_calls)!r}, "a") as f:\n'
            '    f.write(" ".join(sys.argv[1:]) + "\\n")\n'
            f'st = pathlib.Path({str(state)!r})\n'
            's, a = json.loads(st.read_text()), sys.argv[1:]\n'
            f'if a[:2] == ["-a", "Shortcuts"] and a[2].endswith("/{NAME}.shortcut"):\n'
            f'    s["names"].append({NAME!r})\n'
            f'elif a[0].startswith({run_url("")[:-len("&text=")]!r}) and s["mode"] != "cancel":\n'
            '    text = urllib.parse.parse_qs(urllib.parse.urlsplit(a[0]).query)["text"][0]\n'
            '    s["names"] = [n for n in s["names"] if n != text]\n'
            'st.write_text(json.dumps(s))\n')
        for f in ('shortcuts', 'open'):
            (shim / f).chmod(0o755)
        os.environ['PATH'] = f'{shim}{os.pathsep}{os.environ["PATH"]}'
        if shutil.which('shortcuts') != str(shim / 'shortcuts') or shutil.which('open') != str(shim / 'open'):
            print('  ❌ stubs not first on PATH — aborting before any call')
            return 1
        os.environ['HOME'] = str(tmp / 'home')
        sys.stdin = open(os.devnull)
        # Synthetic gate-4 library: one sample per identifier the builds use, so the real library is not needed.
        pc.EXAMPLES = tmp / 'examples'
        (pc.EXAMPLES / 'action-library').mkdir(parents=True)
        (pc.EXAMPLES / 'action-library' / 'selftest-fixture.wflow').write_bytes(plistlib.dumps({'WFWorkflowActions': [
            {'WFWorkflowActionIdentifier': i, 'WFWorkflowActionParameters': {}}
            for i in sorted({a['WFWorkflowActionIdentifier'] for a in actions()})]}))
        shortcut_action_index.PLUGIN_EXAMPLES = pc.EXAMPLES
        proj = tmp / 'proj'
        proj.mkdir()
        (proj / sb.CONFIG).write_text('{"qa": "none"}')
        old = 'My T & U'                    # space and & must survive the URL
        t, helper = proj / f'{old}.shortcut', pc.target(NAME)
        plist = dict(pc.HDR, WFWorkflowActions=[{'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext',
                                                 'WFWorkflowActionParameters': {'WFTextActionText': sb.tok('x')}}])
        url, imp, imp_helper = run_url(old), f'-a Shortcuts {t}', f'-a Shortcuts {helper}'

        def lines(p):
            return p.read_text().splitlines() if p.exists() else []

        def case(names, mode, env):
            state.write_text(json.dumps({'names': names, 'mode': mode}))
            for p in (log, open_calls):
                p.unlink(missing_ok=True)
            os.chdir(proj)
            for k in ('CLAUDE_CODE_ENTRYPOINT', 'SHORTCUT_NO_OPEN'):
                os.environ.pop(k, None)
            os.environ.update(env)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    sb.write(plist, t, feature='selftest feature line')
                    rc = 0
                except sb.GateError as e:
                    rc = 1
                    print(e)
            return rc, buf.getvalue(), lines(open_calls), json.loads(state.read_text())['names']

        cli = {'CLAUDE_CODE_ENTRYPOINT': 'cli'}
        print('=== a name absent ===')
        rc, out, opened, _ = case(['Home', f'{old} 2'], 'ok', cli)
        check('no helper run, import opened once, `shortcuts` only listed',
              rc == 0 and opened == [imp] and set(lines(log)) == {'list'}, out)

        print('=== b name present, helper added, 削除 ===')
        rc, out, opened, left = case(['Home', NAME, old, f'{old} 2'], 'ok', cli)
        check('helper URL opened (name encoded), then the import; only the exact name deleted',
              rc == 0 and opened == [url, imp] and left == ['Home', NAME, f'{old} 2'] and 'text=My%20T%20%26%20U' in url
              and f'old {old} deleted' in out, out)

        print('=== c name present, キャンセル ===')
        slept, real_time = [], ro.time   # count poll sleeps instead of timing the whole build, which load can slow
        ro.time = types.SimpleNamespace(monotonic=real_time.monotonic,
                                        sleep=lambda s: (slept.append(s), real_time.sleep(s)))
        try:
            rc, out, opened, left = case(['Home', NAME, old], 'cancel', cli)
        finally:
            ro.time = real_time
        check('GateError without a poll wait, import NOT opened, message names キャンセル and the retry',
              not slept and rc == 1 and opened == [url] and old in left and 'キャンセル' in out
              and 'Press 削除 to replace the old copy, then re-run' in out and 'replace_old.py' in out, out)

        print('=== d name present, helper not added yet ===')
        helper.unlink(missing_ok=True)
        rc, out, opened, left = case(['Home', old], 'ok', cli)
        check('helper built with qa=none and its import opened first, then the run URL, then the import',
              rc == 0 and opened == [imp_helper, url, imp] and left == ['Home', NAME]
              and f'qa = none from {helper.parent / sb.CONFIG}' in out and '✅ 1 audit_wiring' in out, out)

        print('=== e name present, non-interactive ===')
        rc, out, opened, left = case(['Home', NAME, old], 'ok', {'SHORTCUT_NO_OPEN': '1'})
        check('open 0×, nothing deleted, prints the replace command then the import command',
              rc == 0 and not opened and old in left and retry(old, t) in out, out)
    finally:
        os.chdir(saved[1])
        os.environ.clear()
        os.environ.update(saved[0])
        if sys.stdin is not saved[2]:
            sys.stdin.close()
            sys.stdin = saved[2]
        pc.EXAMPLES, shortcut_action_index.PLUGIN_EXAMPLES, ro.RUN_MAX_S = saved[3], saved[4], saved[5]
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
