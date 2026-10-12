#!/usr/bin/env python3
"""Delete the `probe-` shortcuts left by on-device probes, with one confirmation click, and verify the result.

    python3 probe_cleanup.py               # list → (build kit-cleanup-probes once) → run it → verify
    python3 probe_cleanup.py --rebuild     # build kit-cleanup-probes even when it is installed
    python3 probe_cleanup.py --selftest    # tempdir only; `shortcuts` and `open` replaced by recording stubs

What it deletes: every shortcut whose name starts with `probe-`, including ones the user named that way by hand.
The `shortcuts` CLI and AppleScript cannot delete a shortcut, so a helper shortcut does it: `kit-cleanup-probes`
(Get My Shortcuts → keep the names starting with `probe-` → Delete Shortcuts → output their names). Apple's
Delete Shortcuts action asks for confirmation in a dialog that lists the shortcuts it will delete first; press 削除
(Delete) once per run. The dialog has no always-allow, so every run asks again.

## Flow

    1 `shortcuts list`; no `probe-` name → "no probe shortcuts", exit 0.
    2 kit-cleanup-probes not in the list (or --rebuild) → build it through shortcut_build.write() to
      ~/Library/Application Support/apple-shortcut-kit/kit-cleanup-probes.shortcut, after writing {"qa": "none"} to
      .shortcut-dev.json in that directory, so the project's own QA choice never applies. Gate 4 takes its samples
      from the bundled action library (examples/action-library/*.wflow). Interactive run → the import dialog opens
      and `shortcuts list` is polled every 5 s for up to 10 min for the Add; otherwise the open command is printed.
    3 `open shortcuts://run-shortcut?name=kit-cleanup-probes`; press 削除 in the dialog. `shortcuts list` is polled
      every 5 s for up to 3 min until no `probe-` name is left. (Started by `shortcuts run`, the dialog often never
      appears and the run waits forever.)
    4 verify from the lists alone: the names removed == the probe names from step 1, no `probe-` name left, the
      other shortcuts unchanged.

## Exit codes

    0  no probe shortcuts, or the deletion was verified
    1  verification failed (including キャンセル or no answer within 3 min), or a write-gate check failed
    2  kit-cleanup-probes is not installed yet: built; add it, then re-run
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
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import shortcut_build as sb  # noqa: E402
import shortcut_action_index  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
# Holds action-library/*.wflow. Source checkout: <root>/automation/shortcut-kit/examples · plugin: <root>/examples.
EXAMPLES = (sb.ROOT / 'automation' / 'shortcut-kit' / 'examples' if HERE.parent.name == 'automation'
            else sb.ROOT / 'examples')
NAME = 'kit-cleanup-probes'
PREFIX = 'probe-'
RUN_URL = 'shortcuts://run-shortcut?name=' + urllib.parse.quote(NAME)
POLL_S, POLL_MAX_S = 5, 600
RUN_MAX_S = 180  # wait for 削除 before reporting キャンセル or no answer
FEATURE = 'deletes every shortcut whose name starts with probe-, then lists them'
HDR = {'WFWorkflowMinimumClientVersion': 900, 'WFWorkflowMinimumClientVersionString': '900',
       'WFWorkflowClientVersion': '3612.0.2.1',
       'WFWorkflowIcon': {'WFWorkflowIconStartColor': 4282601983, 'WFWorkflowIconGlyphNumber': 59511},
       'WFWorkflowImportQuestions': [], 'WFWorkflowTypes': [], 'WFWorkflowInputContentItemClasses': [],
       'WFWorkflowOutputContentItemClasses': [], 'WFWorkflowHasShortcutInputVariables': False,
       'WFWorkflowHasOutputFallback': False, 'WFQuickActionSurfaces': []}


def target(name: str = NAME) -> pathlib.Path:
    return pathlib.Path.home() / 'Library/Application Support/apple-shortcut-kit' / f'{name}.shortcut'


def actions() -> list:
    """The list proven on device 2026-10-11. The If tests Get Text of the Repeat Item: an If directly on the
    shortcut item drops its `probe-` string."""
    u_get, u_name = sb.uid('cleanup-get'), sb.uid('cleanup-name')
    g_rep, g_if = sb.uid('cleanup-rep'), sb.uid('cleanup-if')
    return [
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.getmyworkflows', 'WFWorkflowActionParameters': {'UUID': u_get}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.repeat.each', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_rep, 'WFControlFlowMode': 0, 'WFInput': sb.attach(sb.out(u_get, 'My Shortcuts'))}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext', 'WFWorkflowActionParameters': {
            'UUID': u_name, 'WFTextActionText': sb.tok('{{i}}', {'i': sb.var('Repeat Item')})}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.conditional', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_if, 'WFCondition': 8, 'WFConditionalActionString': PREFIX, 'WFControlFlowMode': 0,
            'WFInput': {'Type': 'Variable', 'Variable': sb.attach(sb.out(u_name, 'Text'))}}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.appendvariable', 'WFWorkflowActionParameters': {
            'WFInput': sb.attach(sb.var('Repeat Item')), 'WFVariableName': 'Targets'}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.conditional', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_if, 'WFControlFlowMode': 2, 'UUID': sb.uid('cleanup-if-end')}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.repeat.each', 'WFWorkflowActionParameters': {
            'GroupingIdentifier': g_rep, 'WFControlFlowMode': 2, 'UUID': sb.uid('cleanup-rep-end')}},
        {'WFWorkflowActionIdentifier': 'com.apple.shortcuts.DeleteWorkflowAction', 'WFWorkflowActionParameters': {
            'AppIntentDescriptor': {'AppIntentIdentifier': 'DeleteWorkflowAction', 'BundleIdentifier': 'com.apple.shortcuts',
                                    'Name': 'Shortcuts', 'TeamIdentifier': '0000000000'},
            'UUID': sb.uid('cleanup-delete'), 'entities': sb.attach(sb.var('Targets'))}},
        {'WFWorkflowActionIdentifier': 'is.workflow.actions.gettext', 'WFWorkflowActionParameters': {
            'UUID': sb.uid('cleanup-out'), 'WFTextActionText': sb.tok('{{t}}', {'t': sb.var('Targets')})}},
    ]


def list_shortcuts() -> list:
    r = subprocess.run(['shortcuts', 'list'], capture_output=True, text=True, check=True)
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def build(name: str = NAME, acts: list | None = None, feature: str = FEATURE, hdr: dict = HDR,
          rerun: str | None = None) -> int | None:
    """Build and deliver a kit helper (default kit-cleanup-probes). None = installed (the Add was seen); 2 = not
    installed yet. `rerun` is the command printed for a non-interactive run (default: this script)."""
    t = target(name)
    t.parent.mkdir(parents=True, exist_ok=True)
    (t.parent / sb.CONFIG).write_text('{"qa": "none"}\n')
    # Gate 4 must find DeleteWorkflowAction in the library. SHORTCUT_CORPUS directories are scanned for *.shortcut
    # only and the library is *.wflow, so point the index's examples root (scanned for *.wflow) at it.
    shortcut_action_index.PLUGIN_EXAMPLES = EXAMPLES
    sb.write(dict(hdr, WFWorkflowActions=actions() if acts is None else acts), t, feature=feature)
    if not sb._interactive():
        print(f'   add it, then re-run: {rerun or "python3 " + shlex.quote(str(pathlib.Path(__file__).resolve()))}')
        return 2
    print(f'   waiting up to {POLL_MAX_S // 60} min for {name} to appear in `shortcuts list` …')
    for _ in range(POLL_MAX_S // POLL_S):
        if name in list_shortcuts():
            return None
        time.sleep(POLL_S)
    print(f'❌ {name} did not appear within {POLL_MAX_S // 60} min — add it, then re-run')
    return 2


def run_and_verify(names: list) -> int:
    probes = sorted(n for n in names if n.startswith(PREFIX))
    others = sorted(n for n in names if not n.startswith(PREFIX))
    print(f'running {NAME}: press 削除 in the dialog ({len(probes)} probe shortcut(s): {", ".join(probes)})')
    subprocess.run(['open', RUN_URL], capture_output=True)
    deadline = time.monotonic() + RUN_MAX_S
    while True:
        after = list_shortcuts()
        if not any(n.startswith(PREFIX) for n in after) or time.monotonic() >= deadline:
            break
        time.sleep(POLL_S)
    removed = sorted(set(names) - set(after))
    left = sorted(n for n in after if n.startswith(PREFIX))
    others_after = sorted(n for n in after if not n.startswith(PREFIX))

    if left and not removed:
        print(f'❌ キャンセル or no answer within {RUN_MAX_S // 60} min: {len(left)} probe shortcut(s) still present: '
              f'{", ".join(left)}')
        return 1
    problems = []
    if removed != probes:
        problems.append(f'removed names differ from the probe list — removed but not a probe: '
                        f'{sorted(set(removed) - set(probes))}; probe not removed: {sorted(set(probes) - set(removed))}')
    if left:
        problems.append(f'{len(left)} probe shortcut(s) still present: {", ".join(left)}')
    if others_after != others:
        problems.append(f'other shortcuts changed {len(others)} → {len(others_after)} — gone: '
                        f'{sorted(set(others) - set(others_after))}; new: {sorted(set(others_after) - set(others))}')
    if problems:
        print('❌ cleanup not verified:' + ''.join(f'\n   - {p}' for p in problems))
        return 1
    print(f'cleanup verified: deleted {len(probes)} probe shortcut(s); others unchanged ({len(others)})')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0],
                                 epilog='exit 0 nothing to delete or verified · 1 not verified / gate failed · '
                                        '2 kit-cleanup-probes built, add it then re-run')
    ap.add_argument('--rebuild', action='store_true', help=f'build {NAME} even when it is installed')
    ap.add_argument('--selftest', action='store_true', help='tempdir-only selftest; never calls the real shortcuts/open')
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    names = list_shortcuts()
    if not args.rebuild and not any(n.startswith(PREFIX) for n in names):
        print('no probe shortcuts')
        return 0
    if args.rebuild or NAME not in names:
        rc = build()
        if rc is not None:
            return rc
        names = list_shortcuts()
    if not any(n.startswith(PREFIX) for n in names):
        print('no probe shortcuts')
        return 0
    return run_and_verify(names)


# ── selftest ─────────────────────────────────────────────────────────────────

def selftest() -> int:
    global EXAMPLES, RUN_MAX_S
    ok = True

    def check(label, cond, detail=''):
        nonlocal ok
        ok &= bool(cond)
        print(f'  {"✅" if cond else "❌"} {label}' + (f'\n{detail}' if detail and not cond else ''))

    tmp = pathlib.Path(tempfile.mkdtemp(prefix='probe_cleanup_selftest_')).resolve()
    saved = dict(os.environ), os.getcwd(), sys.stdin, EXAMPLES, shortcut_action_index.PLUGIN_EXAMPLES, RUN_MAX_S
    RUN_MAX_S = 0  # the stub applies the scenario before the first poll; キャンセル must not wait
    try:
        state, log, open_calls, shim = tmp / 'state.json', tmp / 'shortcuts_calls.txt', tmp / 'open_calls.txt', tmp / 'bin'
        shim.mkdir()
        (shim / 'shortcuts').write_text(
            f'#!{sys.executable}\n'
            'import json, pathlib, sys\n'
            f'st = pathlib.Path({str(state)!r})\n'
            's = json.loads(st.read_text())\n'
            f'with open({str(log)!r}, "a") as f:\n'
            '    f.write(" ".join(sys.argv[1:]) + "\\n")\n'
            'if sys.argv[1:] != ["list"]:\n'
            '    sys.exit(64)\n'
            'print("\\n".join(s["names"]))\n')
        # The run-shortcut URL applies the scenario: ok deletes the probes, extra also one other, cancel nothing.
        (shim / 'open').write_text(
            f'#!{sys.executable}\n'
            'import json, pathlib, sys\n'
            f'with open({str(open_calls)!r}, "a") as f:\n'
            '    f.write(" ".join(sys.argv[1:]) + "\\n")\n'
            f'if sys.argv[1:] != [{RUN_URL!r}]:\n'
            '    sys.exit(0)\n'
            f'st = pathlib.Path({str(state)!r})\n'
            's = json.loads(st.read_text())\n'
            'if s["mode"] != "cancel":\n'
            f'    rest = [n for n in s["names"] if not n.startswith({PREFIX!r})]\n'
            '    s["names"] = rest[1:] if s["mode"] == "extra" else rest\n'
            '    st.write_text(json.dumps(s))\n')
        for f in ('shortcuts', 'open'):
            (shim / f).chmod(0o755)
        os.environ['PATH'] = f'{shim}{os.pathsep}{os.environ["PATH"]}'
        if shutil.which('shortcuts') != str(shim / 'shortcuts') or shutil.which('open') != str(shim / 'open'):
            print('  ❌ stubs not first on PATH — aborting before any call')
            return 1
        os.environ['HOME'] = str(tmp / 'home')
        os.environ.pop('CLAUDE_CODE_ENTRYPOINT', None)
        os.environ['SHORTCUT_NO_OPEN'] = '1'
        sys.stdin = open(os.devnull)
        # Synthetic gate-4 library: one sample per identifier the build uses, so the real library is not needed.
        EXAMPLES = tmp / 'examples'
        (EXAMPLES / 'action-library').mkdir(parents=True)
        (EXAMPLES / 'action-library' / 'selftest-fixture.wflow').write_bytes(plistlib.dumps({'WFWorkflowActions': [
            {'WFWorkflowActionIdentifier': i, 'WFWorkflowActionParameters': {}}
            for i in sorted({a['WFWorkflowActionIdentifier'] for a in actions()})]}))
        empty, proj = tmp / 'empty', tmp / 'proj'
        empty.mkdir()
        proj.mkdir()
        (proj / sb.CONFIG).write_text('{"qa": "own", "regression_cmd": "false"}')
        t = target()

        def lines(p):
            return p.read_text().splitlines() if p.exists() else []

        def case(names, mode, cwd):
            state.write_text(json.dumps({'names': names, 'mode': mode}))
            for p in (log, open_calls):
                p.unlink(missing_ok=True)
            os.chdir(cwd)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    rc = main([])
                except SystemExit as e:          # GateError from a build
                    rc = e.code if isinstance(e.code, int) else 1
                    print(e)
            ran = [c for c in lines(open_calls) if c == RUN_URL]
            return rc, buf.getvalue(), ran, json.loads(state.read_text())['names']

        installed = ['Home', NAME, 'probe-a', 'probe-b']
        print('=== 1 no probes ===')
        rc, out, ran, _ = case(['Home'], 'ok', empty)
        check('exit 0, "no probe shortcuts", no build, open 0×',
              rc == 0 and 'no probe shortcuts' in out and not lines(open_calls) and not t.exists(), out)

        print('=== 2 installed + probes ===')
        rc, out, ran, left = case(installed, 'ok', empty)
        check('exit 0, open called once with the run-shortcut URL and nothing else, `shortcuts` only listed, '
              'counts verified',
              rc == 0 and lines(open_calls) == [RUN_URL] and set(lines(log)) == {'list'} and left == ['Home', NAME]
              and 'cleanup verified: deleted 2 probe shortcut(s); others unchanged (2)' in out, out)

        print('=== 3 stub also deletes a non-probe ===')
        rc, out, ran, left = case(installed, 'extra', empty)
        check('exit 1, names the changed other shortcut', rc == 1 and len(ran) == 1 and "gone: ['Home']" in out, out)

        print('=== 4 キャンセル (nothing deleted) ===')
        t0 = time.monotonic()
        rc, out, ran, left = case(installed, 'cancel', empty)
        check('exit 1 within 5 s, reports キャンセル or no answer and the probes still present',
              time.monotonic() - t0 < 5 and rc == 1 and len(ran) == 1 and 'キャンセル' in out and 'probe-a, probe-b' in out, out)

        for n, label, cwd in (('5', 'not installed, no .shortcut-dev.json anywhere', empty),
                              ('6', 'not installed, project .shortcut-dev.json qa=own with a failing regression_cmd',
                               proj)):
            print(f'=== {n} {label} ===')
            t.unlink(missing_ok=True)
            (t.parent / sb.CONFIG).unlink(missing_ok=True)
            rc, out, ran, _ = case(['Home', 'probe-a'], 'ok', cwd)
            check('builds with qa=none from the kit directory, gates 1 and 4 pass, wiring audit only',
                  f'qa = none from {t.parent / sb.CONFIG}' in out and '✅ 1 audit_wiring' in out
                  and 'wiring audit only' in out and '✅ 4 real-sample' in out, out)
            check(f'file written under {t.parent.relative_to(tmp)}/, exit 2, open command + "add it, then re-run" '
                  'printed, open 0×, no run',
                  t.is_file() and rc == 2 and 'open -a Shortcuts' in out and 'add it, then re-run' in out
                  and not lines(open_calls), out)
    finally:
        os.chdir(saved[1])
        os.environ.clear()
        os.environ.update(saved[0])
        if sys.stdin is not saved[2]:
            sys.stdin.close()
            sys.stdin = saved[2]
        EXAMPLES, shortcut_action_index.PLUGIN_EXAMPLES, RUN_MAX_S = saved[3], saved[4], saved[5]
        shutil.rmtree(tmp, ignore_errors=True)
    print('selftest:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
